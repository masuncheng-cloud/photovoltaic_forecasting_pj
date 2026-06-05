#!/usr/bin/env python3
"""
No-cache HTTP server for the photovoltaic dashboard.
Forces Cache-Control: no-store on ALL responses, including HTML,
CSS, JS, and JSON.  This eliminates any possibility of browser
cache interference during debugging.

Usage:
    python scripts/serve_dashboard_no_cache.py --port 8070 --directory .
    python scripts/serve_dashboard_no_cache.py  # defaults: port=8070, dir=.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Vary", "Accept-Encoding")
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[serve] {self.address_string()} - {format % args}")


def main():
    parser = argparse.ArgumentParser(description="No-cache HTTP server for dashboard debugging")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8070)
    parser.add_argument("--directory", default=".", type=Path)
    args = parser.parse_args()

    directory = args.directory.resolve()
    handler = partial(NoCacheHandler, directory=str(directory))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"[serve] no-cache server at http://{args.host}:{args.port}/")
    print(f"[serve] directory={directory}")
    print(f"[serve] Cache-Control: no-store on ALL responses")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
