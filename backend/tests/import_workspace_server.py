"""Dedicated local synthetic-transport UI server; never imports runtime secrets."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/v1/businesses/") and self.path.endswith("/imports"):
            self.path = "/import_workspace.html"
        elif self.path.startswith("/static/"):
            self.path = self.path.removeprefix("/static")
        else:
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, private")
        super().end_headers()

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4320)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port),
        lambda *a, **k: Handler(*a, directory=str(ROOT), **k)).serve_forever()
