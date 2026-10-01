"""Two fixed setup capabilities; no ordinary dashboard bridge is loaded."""

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('invalid')
        result[key] = value
    return result


class SetupBridge(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 4

    def __init__(self, ceremony, token):
        self.ceremony, self.token = ceremony, token
        self.slots = threading.BoundedSemaphore(2)
        super().__init__(('127.0.0.1', 0), SetupHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, *_args):
        pass  # Never log callback values or raw request exceptions.


class SetupHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass

    def _reply(self, status, payload):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def send_error(self, _code, message=None, explain=None):
        self._reply(403, {'ok': False})

    def do_POST(self):
        try:
            expected_host = f'127.0.0.1:{self.server.server_port}'
            for header in ('Host', 'X-Mentat-Setup-Token', 'Content-Length', 'Content-Type'):
                if len(self.headers.get_all(header, [])) != 1:
                    raise ValueError('invalid')
            if self.headers['Host'] != expected_host or self.headers['Content-Type'] != 'application/json' or self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Origin'):
                raise ValueError('invalid')
            if not hmac.compare_digest(self.headers['X-Mentat-Setup-Token'], self.server.token):
                raise ValueError('invalid')
            length = self.headers['Content-Length']
            if not length.isascii() or not length.isdecimal() or not 1 <= int(length) <= 8192:
                raise ValueError('invalid')
            if self.path not in {'/setup/begin', '/setup/callback'}:
                raise ValueError('invalid')
            raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                raise ValueError('invalid')
            body = json.loads(raw.decode(), object_pairs_hook=_object)
            if not isinstance(body, dict) or any(not isinstance(value, str) for value in body.values()):
                raise ValueError('invalid')
            if self.path == '/setup/begin' and set(body) == {'grant'}:
                start = self.server.ceremony.begin_browser(body['grant'])
                result = dict(ok=True, authorization_url=start.authorization_url, browser_binding=start.browser_binding)
            elif self.path == '/setup/callback' and set(body) == {'state', 'browser_binding', 'code'}:
                if len(body['code']) > 4096:
                    raise ValueError('invalid')
                self.server.ceremony.verify_browser(**body)
                result = {'ok': True}
            else:
                raise ValueError('invalid')
            self._reply(200, result)
        except Exception:
            self._reply(403, {'ok': False})
