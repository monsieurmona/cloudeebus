#!/usr/bin/env python

# Cloudeebus
#
# Copyright 2012 Intel Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Luc Yriarte <luc.yriarte@intel.com>
# Christophe Guiraud <christophe.guiraud@intel.com>
#


import sys, dbus, json

from twisted.internet import glib2reactor
# Configure the twisted mainloop to be run inside the glib mainloop.
# This must be done before importing the other twisted modules
glib2reactor.install()
from twisted.internet import reactor, defer

from autobahn.websocket import listenWS
from autobahn.wamp import exportRpc, WampServerFactory, WampCraServerProtocol

from dbus.mainloop.glib import DBusGMainLoop

import gobject
gobject.threads_init()

from dbus import glib
glib.init_threads()

# enable debug log
from twisted.python import log
log.startLogging(sys.stdout)



###############################################################################
def hashId(list):
	str = list[0]
	for item in list[1:len(list)]:
		str += "#" + item
	return str


###############################################################################
class DbusCache:
	def __init__(self):
		self.reset()


	def reset(self):
		# dbus connexions
		self.dbusConnexions = {}
		# signal handlers
		self.signalHandlers = {}


	def dbusConnexion(self, busName):
		if not self.dbusConnexions.has_key(busName):
			if busName == "session":
				self.dbusConnexions[busName] = dbus.SessionBus()
			elif busName == "system":
				self.dbusConnexions[busName] = dbus.SystemBus()
			else:
				raise Exception("Error: invalid bus: %s" % busName)
		return self.dbusConnexions[busName]



###############################################################################
class DbusSignalHandler:
	def __init__(self, object, senderName, objectName, interfaceName, signalName):
		# publish hash id
		self.id = hashId([senderName, objectName, interfaceName, signalName])
		# connect dbus proxy object to signal
		self.proxyObject = object
		self.proxyObject.connect_to_signal(signalName, self.handleSignal, interfaceName)


	def handleSignal(self, *args):
		# publish dbus args under topic hash id
		factory.dispatch(self.id, json.dumps(args))



###############################################################################
class DbusCallHandler:
	def __init__(self, method, args):
		# deferred reply to return dbus results
		self.pending = False
		self.request = defer.Deferred()
		self.method = method
		self.args = args


	def callMethod(self):
		# dbus method async call
		self.pending = True
		self.method(*self.args, reply_handler=self.dbusSuccess, error_handler=self.dbusError)
		return self.request


	def dbusSuccess(self, *result):
		# return JSON string result array
		self.request.callback(json.dumps(result))
		self.pending = False


	def dbusError(self, error):
		# return dbus error message
		self.request.errback(error.get_dbus_message())
		self.pending = False



###############################################################################
class CloudeebusService:
	def __init__(self):
		# proxy objects
		self.proxyObjects = {}
		# proxy methods
		self.proxyMethods = {}
		# pending dbus calls
		self.pendingCalls = []


	def proxyObject(self, busName, serviceName, objectName):
		id = hashId([serviceName, objectName])
		if not self.proxyObjects.has_key(id):
			bus = cache.dbusConnexion(busName)
			self.proxyObjects[id] = bus.get_object(serviceName, objectName)
		return self.proxyObjects[id]


	def proxyMethod(self, busName, serviceName, objectName, interfaceName, methodName):
		id = hashId([serviceName, objectName, interfaceName, methodName])
		if not self.proxyMethods.has_key(id):
			obj = self.proxyObject(busName, serviceName, objectName)
			self.proxyMethods[id] = obj.get_dbus_method(methodName, interfaceName)
		return self.proxyMethods[id]


	@exportRpc
	def dbusRegister(self, list):
		# read arguments list by position
		if len(list) < 5:
			raise Exception("Error: expected arguments: bus, sender, object, interface, signal)")
		
		# check if a handler exists
		sigId = hashId(list[1:5])
		if cache.signalHandlers.has_key(sigId):
			return sigId
		
		# get dbus proxy object
		object = self.proxyObject(list[0], list[1], list[2])
		
		# create a handler that will publish the signal
		dbusSignalHandler = DbusSignalHandler(object, *list[1:5])
		cache.signalHandlers[sigId] = dbusSignalHandler
		
		return dbusSignalHandler.id


	@exportRpc
	def dbusSend(self, list):
		# clear pending calls
		for call in self.pendingCalls:
			if not call.pending:
				self.pendingCalls.remove(call)
		
		# read arguments list by position
		if len(list) < 5:
			raise Exception("Error: expected arguments: bus, destination, object, interface, message, [args])")
		
		# parse JSON arg list
		args = []
		if len(list) == 6:
			args = json.loads(list[5])
		
		# get dbus proxy method
		method = self.proxyMethod(list[0], *list[1:5])
		
		# use a deferred call handler to manage dbus results
		dbusCallHandler = DbusCallHandler(method, args)
		self.pendingCalls.append(dbusCallHandler)
		return dbusCallHandler.callMethod()



###############################################################################
class CloudeebusServerProtocol(WampCraServerProtocol):
	
	PASSWD = {
		"cloudeebus": "secret"
		}
	
	WHITELIST = [
		"com.intel.media-service-upnp",
		"com.intel.renderer-service-upnp",
		"org.freedesktop.DBus",
		"org.freedesktop.DisplayManager",
		"org.freedesktop.FileManager1",
		"org.freedesktop.ModemManager",
		"org.freedesktop.NetworkManager",
		"org.freedesktop.Notifications",
		"org.freedesktop.Tracker1",
		"org.gnome.Nautilus",
		"org.gnome.Rygel1",
		"org.gnome.ScreenSaver",
		"org.neard",
		"org.ofono"
		]
	

	def onSessionOpen(self):
		# CRA authentication options
		self.clientAuthTimeout = 0
		self.clientAuthAllowAnonymous = True
		# CRA authentication init
		WampCraServerProtocol.onSessionOpen(self)
	
	
	def getAuthPermissions(self, key, extra):
		return json.loads(extra.get("permissions", "[]"))
	
	
	def getAuthSecret(self, key):
		return self.PASSWD.get(key, None)
	

	def onAuthenticated(self, key, permissions):
		# check authentication key
		if key is None:
			raise Exception("Authentication failed")
		# check permissions, array.index throws exception
		for req in permissions:
			self.WHITELIST.index(req)
		# create cloudeebus service instance
		self.cloudeebusService = CloudeebusService()
		# register it for RPC
		self.registerForRpc(self.cloudeebusService)
		# register for Publish / Subscribe
		self.registerForPubSub("", True)
	
	
	def connectionLost(self, reason):
		WampCraServerProtocol.connectionLost(self, reason)
		if factory.getConnectionCount() == 0:
			cache.reset()



###############################################################################
if __name__ == '__main__':
	cache = DbusCache()
	
	port = "9000"
	if len(sys.argv) == 2:
		port = sys.argv[1]
	
	uri = "ws://localhost:" + port
	
	factory = WampServerFactory(uri, debugWamp = True)
	factory.protocol = CloudeebusServerProtocol
	factory.setProtocolOptions(allowHixie76 = True)
	
	listenWS(factory)
	
	DBusGMainLoop(set_as_default=True)
	
	reactor.run()