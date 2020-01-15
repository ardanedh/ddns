#!/usr/bin/python3
###############################################################################
#                                                                             #
# ddns - A dynamic DNS client for IPFire                                      #
# Copyright (C) 2012 IPFire development team                                  #
#                                                                             #
# This program is free software: you can redistribute it and/or modify        #
# it under the terms of the GNU General Public License as published by        #
# the Free Software Foundation, either version 3 of the License, or           #
# (at your option) any later version.                                         #
#                                                                             #
# This program is distributed in the hope that it will be useful,             #
# but WITHOUT ANY WARRANTY; without even the implied warranty of              #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the               #
# GNU General Public License for more details.                                #
#                                                                             #
# You should have received a copy of the GNU General Public License           #
# along with this program.  If not, see <http://www.gnu.org/licenses/>.       #
#                                                                             #
###############################################################################

import logging
import logging.handlers
import configparser

from .i18n import _

logger = logging.getLogger("ddns.core")
logger.propagate = 1

from . import database
from . import providers

from .errors import *
from .system import DDNSSystem

# Setup the logger.
def setup_logging():
	rootlogger = logging.getLogger("ddns")
	rootlogger.setLevel(logging.INFO)

	# Setup a logger that logs to syslog.
	handler = logging.handlers.SysLogHandler(address="/dev/log",
		facility=logging.handlers.SysLogHandler.LOG_DAEMON
	)
	formatter = logging.Formatter("ddns[%(process)d]: %(message)s")
	handler.setFormatter(formatter)
	handler.setLevel(logging.INFO)
	rootlogger.addHandler(handler)

	handler = logging.StreamHandler()
	rootlogger.addHandler(handler)

setup_logging()

class DDNSCore(object):
	def __init__(self, debug=False):
		# In debug mode, enable debug logging.
		if debug:
			rootlogger = logging.getLogger("ddns")
			rootlogger.setLevel(logging.DEBUG)

			logger.debug(_("Debugging mode enabled"))

		# Initialize the settings array.
		self.settings = {}

		# Dict with all providers, that are supported.
		self.providers = providers.get()

		for handle, provider in sorted(self.providers.items()):
			logger.debug("Registered new provider: %s (%s)" % (provider.name, provider.handle))

		# List of configuration entries.
		self.entries = []

		# Add the system class.
		self.system = DDNSSystem(self)

		# Open the database.
		self.db = database.DDNSDatabase(self, "/var/lib/ddns.db")

	def get_provider_names(self):
		"""
			Returns a list of names of all registered providers.
		"""
		return sorted(self.providers.keys())

	def load_configuration(self, filename):
		logger.debug(_("Loading configuration file %s") % filename)

		configs = configparser.RawConfigParser()
		configs.read([filename,])

		# First apply all global configuration settings.
		try:
			for k, v in configs.items("config"):
				self.settings[k] = v

		# Allow missing config section
		except configparser.NoSectionError:
			pass

		for entry in configs.sections():
			# Skip the special config section.
			if entry == "config":
				continue

			settings = {}
			for k, v in configs.items(entry):
				settings[k] = v
			settings["hostname"] = entry

			# Get the name of the provider.
			provider = settings.get("provider", None)
			if not provider:
				logger.warning("Entry '%s' lacks a provider setting. Skipping." % entry)
				continue

			# Try to find the provider with the wanted name.
			try:
				provider = self.providers[provider]
			except KeyError:
				logger.warning("Could not find provider '%s' for entry '%s'." % (provider, entry))
				continue

			# Check if the provider is actually supported and if there are
			# some dependencies missing on this system.
			if not provider.supported():
				logger.warning("Provider '%s' is known, but not supported on this machine" % provider.name)
				continue

			# Create an instance of the provider object with settings from the
			# configuration file.
			entry = provider(self, **settings)

			# Add new entry to list (if not already exists).
			if not entry in self.entries:
				self.entries.append(entry)

	def updateone(self, hostname, **kwargs):
		for entry in self.entries:
			if not entry.hostname == hostname:
				continue

			return self._update(entry, **kwargs)

		raise DDNSHostNotFoundError(hostname)

	def updateall(self, **kwargs):
		"""
			Update all configured entries.
		"""
		# If there are no entries, there is nothing to do.
		if not self.entries:
			logger.debug(_("Found no entries in the configuration file. Exiting."))
			return

		for entry in self.entries:
			self._update(entry, **kwargs)

	def _update(self, entry, force=False):
		try:
			entry(force=force)

		except DDNSError as e:
			logger.error(_("Dynamic DNS update for %(hostname)s (%(provider)s) failed:") %
				{"hostname": entry.hostname, "provider": entry.name})
			logger.error("  %s: %s" % (e.__class__.__name__, e.reason))
			if e.message:
				logger.error("  %s" % e.message)

		except Exception:
			logger.error(_("Dynamic DNS update for %(hostname)s (%(provider)s) threw an unhandled exception:") %
						 {"hostname": entry.hostname, "provider": entry.name}, exc_info=True)
