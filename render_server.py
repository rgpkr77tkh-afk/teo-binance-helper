#!/usr/bin/env python3
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "10000"))

class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/health"):
            self.send_json(200, {
                "status": "ok",
                "service": "teo-binance-helper",
                "mode": "PAPER_SIGNAL_ONLY"
            })
            return

        if self.path.startswith("/scan"):
            try:
                p = subprocess.run(
                    ["python", "teo_helper.py"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if p.returncode != 0:
                    self.send_json(500, {
                        "status": "scan_error",
                        "stderr": p.stderr[-4000:]
                    })
                    return
                data = json.loads(p.stdout)
                self.send_json(200, data)
            except Exception as e:
                self.send_json(500, {"status": "server_error", "error": str(e)})
            return

        self.send_json(404, {"status": "not_found"})

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

if __name__ == "__main__":
    print(f"Teo helper listening on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
