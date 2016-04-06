# -*- coding: utf-8 -*-
import marshal

import zmq

from . import config
from . import core

_logger = core.get_logger(__name__)

def _serialise(message):
    return marshal.dumps(message)

def _unserialise(message_bytes):
    return marshal.loads(message_bytes)

PUBSUB_DELIMETER = b"\x00"

def _serialise_for_pubsub(topic, data):
    topic_bytes = topic.encode(config.ENCODING)
    data_bytes = _serialise(data)
    return topic_bytes + PUBSUB_DELIMETER + data_bytes

def _unserialise_for_pubsub(message_bytes):
    topic_bytes, data_bytes = message_bytes.split(PUBSUB_DELIMETER, maxsplit=1)
    return topic_bytes.decode(config.ENCODING), _unserialise(data_bytes)

class Socket(zmq.Socket):

    def __repr__(self):
        return "<Socket %x on %s>" % (id(self), getattr(self, "address", "<No address>"))

    def _get_address(self):
        return self._address
    def _set_address(self, address):
        self.__dict__['_address'] = address
        tcp_address = "tcp://%s" % address
        if self.type in (zmq.REQ, zmq.SUB):
            self.connect(tcp_address)
        elif self.type in (zmq.REP, zmq.PUB):
            self.bind(tcp_address)
    address = property(_get_address, _set_address)

class Context(zmq.Context):
    
    _socket_class = Socket

context = Context()

#
# Global mapping from address to socket. When a socket
# is needed, its address (ip:port) is looked up here. If
# a mapping exists, that socket is returned. If not, a new
# one is created of the right type (REQ / SUB etc.) and
# returned
#
class Sockets:

    try_length_ms = 500 # wait for .5 second at a time
    
    def __init__(self):
        self._sockets = {}
        self._poller = zmq.Poller()
    
    def get_socket(self, address, type):
        """Create or retrieve a socket of the right type, already connected
        to the address. Address (ip:port) must be fully specified at this
        point. core.address can be used to generate an address.
        """
        caddress = core.address(address)
        if (caddress, type) not in self._sockets:
            socket = context.socket(type)
            socket.address = caddress
            self._poller.register(socket)
            #
            # Do this last so that an exception earlier will result
            # in the socket not being cached
            #
            self._sockets[(caddress, type)] = socket
        return self._sockets[(caddress, type)]
    
    def intervals_ms(self, timeout_ms):
        """Generate a series of interval lengths, in ms, which
        will add up to the number of ms in timeout_ms. If timeout_ms
        is None, keep returning intervals forever.
        """
        if timeout_ms is config.FOREVER:
            while True:
                yield self.try_length_ms
        else:
            whole_intervals, part_interval = divmod(timeout_ms, self.try_length_ms)
            for _ in range(whole_intervals):
                yield self.try_length_ms
            yield part_interval

    def _receive_with_timeout(self, socket, timeout_secs):
        """Check for socket activity and either return what's
        received on the socket or time out if timeout_secs expires
        without anything on the socket.
        
        This is implemented in loops of self.try_length_ms ms to
        allow Ctrl-C handling to take place.
        """
        if timeout_secs is config.FOREVER:
            timeout_ms = config.FOREVER
        else:
            timeout_ms = int(1000 * timeout_secs)
        
        for interval_ms in self.intervals_ms(timeout_ms):
            sockets = dict(self._poller.poll(interval_ms))
            if socket in sockets:
                return socket.recv()
        else:
            raise core.SocketTimedOutError(timeout_secs)

    def wait_for_message(self, address, wait_for_s):
        socket = self.get_socket(address, zmq.REP)
        _logger.debug("socket %s waiting for request", socket)
        try:
            return _unserialise(self._receive_with_timeout(socket, wait_for_s))
        except core.SocketTimedOutError:
            return None
        
    def send_message(self, address, request, wait_for_reply_secs):
        socket = self.get_socket(address, zmq.REQ)
        socket.send(_serialise(request))
        return _unserialise(self._receive_with_timeout(socket, wait_for_reply_secs))

    def send_reply(self, address, reply):
        socket = self.get_socket(address, zmq.REP)
        return socket.send(_serialise(reply))
    
    def send_notification(self, address, topic, data):
        socket = self.get_socket(address, zmq.PUB)
        return socket.send(_serialise_for_pubsub(topic, data))
    
    def wait_for_notification(self, address, topic, wait_for_s):
        socket = self.get_socket(address, zmq.SUB)
        socket.set(zmq.SUBSCRIBE, topic.encode(config.ENCODING))
        try:
            result = self._receive_with_timeout(socket, wait_for_s)
            unserialised_result = _unserialise_for_pubsub(result)
            return unserialised_result
        except core.SocketTimedOutError:
            return None, None

_sockets = Sockets()

def get_socket(address, type):
    return _sockets.get_socket(address, type)
