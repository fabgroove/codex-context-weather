#!/usr/bin/env python3
"""Optional read-only local dashboard; runs only while this command is open."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from context_weather import codex_home, measure, read_settings, valid_session


def serve(session, transcript, port, label=None, historical=False):
    home = codex_home()
    html = (Path(__file__).parent / "dashboard.html").read_bytes()
    # Validate the source before binding; read only this explicitly selected chat.
    measure(transcript, session, home)
    state = {"marker": 0, "identity": None, "size": 0, "generation": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            if self.path == "/":
                body, mime = html, "text/html; charset=utf-8"
            elif self.path == "/api/status":
                try:
                    with lock:
                        m = measure(transcript, session, home)
                        changed = state["identity"] is not None and (m["identity"] != state["identity"] or m["size"] < state["size"])
                        if changed or m["marker"] > state["marker"]:
                            state["generation"] += 1
                        state.update(identity=m["identity"], size=m["size"], marker=max(m["marker"], state["marker"]))
                        d = {"status": "measured" if m["sample"] else "unavailable", "measurement": m["sample"],
                             "settings": read_settings(home), "generation": state["generation"],
                             "source_label": label, "historical": historical}
                    body = json.dumps(d, ensure_ascii=False).encode()
                except Exception:
                    body = b'{"status":"unavailable"}'
                mime = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", required=True)
    p.add_argument("--transcript", required=True)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--label", help="Short source label shown in the panel")
    p.add_argument("--historical", action="store_true", help="Label a read-only historical inspection and hide the handoff button")
    a = p.parse_args()
    if not valid_session(a.session):
        p.error("Invalid session id")
    if a.historical and not a.label:
        p.error("Historical inspection requires an explicit source label")
    if a.label and len(a.label) > 120:
        p.error("Source label is limited to 120 characters")
    serve(a.session, a.transcript, a.port, a.label, a.historical)
