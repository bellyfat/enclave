"""
The backend for Stream420, a thread safe two-way communication protocol for
web-based applications and their servers.

This module requires Bottle (bottlepy.org), and includes:
 - A listener that receives data from a client via AJAX, triggering a callback
   method
 - A sender that pushes data from a thread safe queue (Queue.Queue or other)
   to the client using HTML5 SSE
 - A launcher for launching WSGI compatible servers on separate threads

NOTE: Data is sent and received as a dictionary


#################################EXAMPLE USAGE#################################


import stream420
import bottle
import Queue

def printer(data):
    assert type(data) == dict  # Deserialized from JSON

    print data  # May not actually work, because the stream420 sender will
                # suppress stdin when sending data. Nevertheless, the function
                # will still be called whenever the client sends data

q = Queue.Queue()

sio = stream420.stream('/stream', printer, q)

stream420.launch(bottle.run, bottle.default_app(),
                 host='localhost', port=8080)       # (server, app, ..., ***)

q.put({'hello_message': 'Hello, World!'})  # Will be sent once and only once:
                                           # when the first client begins
                                           # listnening to the output stream
"""


from bottle import get, post, request, response, default_app
import json
import contextlib
import sys
import threading

from wsgiref.simple_server import WSGIServer, make_server
from SocketServer import ThreadingMixIn


@contextlib.contextmanager
def _silence():
    savestderr = sys.stderr
    savestdout = sys.stdout

    class Devnull(object):
        def write(self, _):
            pass
    sys.stderr = Devnull()
    sys.stdout = Devnull()
    yield
    sys.stderr = savestderr
    sys.stdout = savestdout


class Streamer(object):

    def __init__(self, queue):
        self.queue = queue

    def start(self):
        self.running = True
        while self.running:
            if not self.queue.empty():
                yield '\n'
                yield 'data: %s\n\n' % json.dumps(self.queue.get())

    def stop(self):
        self.running = False


class _istream(object):

    def __init__(self, callback):
        self.callback = callback

    def __call__(self):
        response.set_header('Content-Type', 'text/plain')
        data = request.forms.get('data')
        if data is None:
            return '!'
        try:
            self.callback(json.loads(data))
        except Exception:
            return '?'
        return '.'


class _ostream(object):

    def __init__(self, queue):
        self.queue = queue
        self.old = None

    def __call__(self):
        response.set_header('Content-Type', 'text/event-stream')
        response.set_header('Cache-Control', 'no-cache')
        if self.old is not None:
            self.old.stop()
        self.old = Streamer(self.queue)
        return self.old.start()


def istream(path, callback):
    """A listener that receives data from a client via AJAX"""
    return post(path)(_istream(callback))


def ostream(path, queue):
    """A sender that pushes data from a thread safe queue to the client"""
    return get(path)(_ostream(queue))


def stream(path, callback, queue):
    """Sender and receiver at the same address, no conflicts"""
    return get(path)(_ostream(queue)), post(path)(_istream(callback))


class ThreadingWSGIServer(WSGIServer, ThreadingMixIn):
    """Because threading"""


class launch(threading.Thread):
    """A launcher for launching WSGI compatible servers on separate threads"""

    def __init__(self, server=ThreadingWSGIServer, app=default_app(), host='localhost', port=8080):
        threading.Thread.__init__(self)
        self.server = make_server(host, port, app, server)
        self.start()

    def run(self):
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()