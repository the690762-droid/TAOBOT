"""API JSON + giao diện tĩnh cho desktop. Chỉ bind 127.0.0.1."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "desktop" / "index.html"


def make_handler(o, db):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                return self._send(200, UI.read_bytes(), "text/html")
            if self.path == "/api/state":
                return self._send(200, {
                    "agents": [{"name": a.name, "label": a.label, "status": a.status()} for a in o.ad.values()],
                    "projects": db.projects(), "jobs": db.list_jobs(20)})
            if self.path.startswith("/api/job/"):
                jid = self.path.rsplit("/", 1)[1]
                return self._send(200, {"job": db.get_job(jid), "events": db.events(jid)})
            self._send(404, {"error": "not_found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            act, jid = self.path.rsplit("/", 1)[-1], body.get("job_id")
            if self.path == "/api/new":
                return self._send(200, {"job_id": o.new_job(body["request"], body.get("project"), "desktop")})
            if self.path == "/api/project":
                db.add_project(body["name"], body["path"])
                return self._send(200, {"ok": True})
            if self.path == "/api/plan":
                return self._send(200, {"ok": o.plan(jid)})
            if self.path == "/api/approve":
                return self._send(200, {"ok": o.approve(jid)})
            if self.path == "/api/run":
                return self._send(200, {"result": o.run(jid)})
            if self.path == "/api/cancel":
                o.cancel(jid); return self._send(200, {"ok": True})
            if self.path == "/api/rollback":
                return self._send(200, o.rollback(jid))
            self._send(404, {"error": "not_found"})

    return H


def serve(o, db, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(o, db))
    srv.serve_forever()
