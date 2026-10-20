"""Loopback-only static fixtures with reusable HTTP connections for Playwright."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FixtureHandler(SimpleHTTPRequestHandler):
    # HTTP/1.0 closes every asset request and can exhaust Windows ephemeral ports
    # during the full browser suite. Standard static responses have Content-Length.
    protocol_version = 'HTTP/1.1'
    timeout = 10

    def log_request(self, code='-', size='-'):
        if isinstance(code, int) and code >= 400:
            super().log_request(code, size)


def main():
    root = Path(__file__).resolve().parents[1] / 'misra-frontend'
    handler = partial(FixtureHandler, directory=str(root))
    with ThreadingHTTPServer(('127.0.0.1', 4173), handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
