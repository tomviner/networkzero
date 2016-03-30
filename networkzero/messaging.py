# -*- coding: utf-8 -*-
"""
* send_command(address, command)

* command = wait_for_command([wait_for_secs=FOREVER])

* send_request(address, question[, wait_for_response_secs=FOREVER])

* question, address = wait_for_request([wait_for_secs=FOREVER])

* send_response(address, response)

* publish(address, news)

* wait_for_news(address[, pattern=EVERYTHING, wait_for_secs=FOREVER])
"""
import zmq

from . import config
from . import core
from . import exc
from .logging import logger

class BaseSocket:
    
    def __init__(self, address):
        self.address = address
    
class RequestSocket(BaseSocket):
    
    def __init__(self, address, type):
        super().__init__(address)
        self.type = type

class ReplySocket(BaseSocket):
    
    def __init__(self, address, type):
        super().__init__(address)
        self.type = type

#
# Global mapping from address to socket. When a socket
# is needed, its address (ip:port) is looked up here. If
# a mapping exists, that socket is returned. If not, a new
# one is created of the right type (REQ / SUB etc.) and
# returned
#
class Sockets:

    def __init__(self):
        self._sockets = {}
        self._poller = zmq.Poller()
    
    def get_socket(self, address, type):
        """Create or retrieve a socket of the right type, already connected
        to the address
        """
        socket = self._sockets.get(address)
        if socket is not None:
            if socket.type != type:
                raise exc.SocketAlreadyExistsError(address, type, socket.type)
        else:
            socket = self._sockets[address] = core.context.socket(type)
            if type in (zmq.REQ,):
                socket.connect("tcp://%s" % address)
            elif type in (zmq.REP,):
                socket.bind("tcp://%s" % address)
            if type in (zmq.REQ, zmq.REP):
                self._poller.register(socket)
        return socket
    
    def _receive_with_timeout(self, socket, timeout_secs):
        if timeout_secs is config.FOREVER:
            return socket.recv()
        
        sockets = dict(self._poller.poll(1000 * timeout_secs))
        if socket in sockets:
            return socket.recv()
        else:
            raise SocketTimedOutError

    def wait_for_request(self, address, wait_for_secs=config.FOREVER):
        socket = self.get_socket(address, zmq.REP)
        return self._receive_with_timeout(socket, wait_for_secs)
        
    def send_request(self, address, request, wait_for_reply_secs=config.FOREVER):
        socket = self.get_socket(address, zmq.REQ)
        socket.send(request)
        return self._receive_with_timeout(socket, wait_for_reply_secs)

    def send_reply(self, address, reply):
        socket = self.get_socket(address, zmq.REP)
        return socket.send(reply)

def send_request(address, request, wait_for_reply_secs=config.FOREVER):
    return _sockets.send_request(address, request, wait_for_reply_secs)

def wait_for_request(address, wait_for_secs=config.FOREVER):
    return _sockets.wait_for_request(address, wait_for_secs)

def send_reply(address, reply):
    return _sockets.send_reply(address, reply)

def send_command(address, command, wait_for_reply_secs=config.FOREVER):
    try:
        reply = send_request(address, command, wait_for_reply_secs)
    except exc.SocketTimedOutError:
        logger.warn("No reply received for command %s to address %s", command, address)

def wait_for_command(address, callback, wait_for_secs=config.FOREVER):
    command = wait_for_request(address, wait_for_secs)
    reply = callback(command)
    return send_reply(address, reply)

def publish_news(address, news):
    raise NotImplementedError

def wait_for_news(address, pattern=config.EVERYTHING, wait_for_secs=config.FOREVER):
    raise NotImplementedError

_sockets = Sockets()
