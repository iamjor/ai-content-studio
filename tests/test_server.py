"""Local integration tests for the standard-library HTTP server."""

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ServerIntegrationTests(unittest.TestCase):
    """Exercise authentication, persistence, health, and conflict behavior."""

    @classmethod
    def setUpClass(cls):
        """Start one isolated server and wait until its health route responds."""
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="aics-test-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]

        env = os.environ.copy()
        env.update(
            {
                "AICS_USERNAME": "test-user",
                "AICS_PASSWORD": "test-password-not-a-secret",
                "AICS_DB_PATH": str(Path(cls.temp_dir.name) / "test.sqlite3"),
                "PORT": str(cls.port),
            }
        )
        cls.process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        token = base64.b64encode(b"test-user:test-password-not-a-secret").decode()
        cls.authorization = f"Basic {token}"

        for _ in range(50):
            try:
                with cls.request("/healthz", authenticated=False) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.1)

        cls.stop_server()
        raise RuntimeError("test server did not start")

    @classmethod
    def tearDownClass(cls):
        """Stop the server process and remove its temporary database directory."""
        cls.stop_server()
        cls.temp_dir.cleanup()

    @classmethod
    def stop_server(cls):
        """Stop the server process, escalating to a kill only after timeout."""
        if cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait()

    @classmethod
    def request(cls, path, method="GET", payload=None, authenticated=True):
        """Send a request with optional JSON data and test authentication."""
        headers = {"Authorization": cls.authorization} if authenticated else {}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            cls.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        return urllib.request.urlopen(request, timeout=3)

    def test_health_check_is_public_and_minimal(self):
        """Expose a minimal public health response without workspace data."""
        with self.request("/healthz", authenticated=False) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"ok": True})

    def test_workspace_requires_authentication(self):
        """Reject workspace reads that do not provide Basic authentication."""
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/workspace", authenticated=False)
        self.assertEqual(context.exception.code, 401)
        self.assertIn("Basic", context.exception.headers["WWW-Authenticate"])

    def test_read_write_and_revision_conflict(self):
        """Persist data and reject a second write with a stale revision."""
        with self.request("/api/workspace") as response:
            initial = json.load(response)
        self.assertEqual(initial, {"revision": 0, "data": None})

        workspace = {
            "projects": [{"episodes": [], "characters": []}],
            "activeId": "sample",
        }
        with self.request(
            "/api/workspace",
            method="PUT",
            payload={"revision": 0, "data": workspace},
        ) as response:
            self.assertEqual(json.load(response), {"revision": 1})

        with self.request("/api/workspace") as response:
            saved = json.load(response)
        self.assertEqual(saved, {"revision": 1, "data": workspace})

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(
                "/api/workspace",
                method="PUT",
                payload={"revision": 0, "data": workspace},
            )
        self.assertEqual(context.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
