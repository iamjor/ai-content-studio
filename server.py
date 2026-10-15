"""Single-user AI Content Studio API and static host (Python standard library)."""
import base64
import binascii
import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent.resolve()
STATIC = ROOT / "dist"
DB_PATH = Path(os.environ.get("AICS_DB_PATH", "/data/studio.sqlite3"))
USERNAME = os.environ.get("AICS_USERNAME", "")
PASSWORD = os.environ.get("AICS_PASSWORD", "")
MAX_BYTES = 2_000_000


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    return db


def setup():
    if not USERNAME or not PASSWORD:
        raise RuntimeError("Set AICS_USERNAME and AICS_PASSWORD before starting")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)")


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status, value, extra=None):
        self.reply(status, json.dumps(value).encode("utf-8"), extra=extra)

    def authorized(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
            user, password = raw.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return False
        return hmac.compare_digest(user, USERNAME) and hmac.compare_digest(password, PASSWORD)

    def route(self, writing=False):
        path = urlsplit(self.path).path
        if path == "/healthz" and not writing:
            return self.json_reply(200, {"ok": True})
        if not self.authorized():
            return self.json_reply(401, {"error": "Authentication required"}, {"WWW-Authenticate": 'Basic realm="AI Content Studio", charset="UTF-8"'})
        if path == "/api/workspace":
            return self.put_workspace() if writing else self.get_workspace()
        if writing:
            return self.json_reply(404, {"error": "Not found"})
        files = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/seed.js": "seed.js", "/style.css": "style.css"}
        filename = files.get(path)
        if not filename:
            return self.json_reply(404, {"error": "Not found"})
        mime = "text/html; charset=utf-8" if filename.endswith(".html") else "text/javascript; charset=utf-8" if filename.endswith(".js") else "text/css; charset=utf-8"
        return self.reply(200, (STATIC / filename).read_bytes(), mime)

    def do_GET(self):
        self.route()

    def do_PUT(self):
        self.route(writing=True)

    def get_workspace(self):
        with connect() as db:
            row = db.execute("SELECT revision, data FROM workspace WHERE id=1").fetchone()
        return self.json_reply(200, {"revision": row[0], "data": json.loads(row[1])} if row else {"revision": 0, "data": None})

    def put_workspace(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BYTES:
                return self.json_reply(413, {"error": "Workspace exceeds the 2 MB limit"})
            value = json.loads(self.rfile.read(length))
            rev, data = value["revision"], value["data"]
            if type(rev) is not int or rev < 0 or not isinstance(data, dict) or not isinstance(data.get("projects"), list) or not data["projects"]:
                raise ValueError("Invalid workspace")
            if not all(isinstance(p, dict) and isinstance(p.get("episodes"), list) and isinstance(p.get("characters"), list) for p in data["projects"]):
                raise ValueError("Invalid projects")
        except (ValueError, KeyError, TypeError):
            return self.json_reply(400, {"error": "Invalid workspace"})
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if rev == 0:
                result = db.execute("INSERT OR IGNORE INTO workspace (id, revision, data) VALUES (1, 1, ?)", (json.dumps(data),))
            else:
                result = db.execute("UPDATE workspace SET revision=revision+1, data=? WHERE id=1 AND revision=?", (json.dumps(data), rev))
            if result.rowcount != 1:
                return self.json_reply(409, {"error": "Workspace changed in another tab or device. Reload before editing."})
        return self.json_reply(200, {"revision": rev + 1})


if __name__ == "__main__":
    setup()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8787"))), Handler).serve_forever()
