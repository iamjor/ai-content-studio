"""Integration tests for authentication, authorization, migration, and isolation."""

import http.cookies
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_USERNAME = "owner"
ADMIN_PASSWORD = "owner-password-12345"


class TestClient:
    """Maintain one browser-like cookie and CSRF context for API requests."""

    def __init__(self, base_url):
        """Create a client with no authenticated session."""
        self.base_url = base_url
        self.cookie = ""
        self.csrf_token = ""

    def request(
        self,
        path,
        method="GET",
        payload=None,
        include_csrf=True,
        extra_headers=None,
    ):
        """Send one request and return status, decoded body, and headers."""
        headers = {}
        body = None
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method != "GET":
            headers["Origin"] = self.base_url
            headers["Sec-Fetch-Site"] = "same-origin"
        if include_csrf and self.csrf_token and method != "GET":
            headers["X-CSRF-Token"] = self.csrf_token
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            value = json.loads(raw or b"{}")
        else:
            value = raw.decode("utf-8")
        self._capture_cookie(response.headers)
        if isinstance(value, dict) and value.get("csrfToken"):
            self.csrf_token = value["csrfToken"]
        return response.status, value, response.headers

    def _capture_cookie(self, headers):
        """Store or clear the session cookie returned by the server."""
        for header in headers.get_all("Set-Cookie") or []:
            parsed = http.cookies.SimpleCookie()
            parsed.load(header)
            morsel = parsed.get("AICS_SESSION")
            if morsel:
                self.cookie = (
                    "AICS_SESSION=" + morsel.value if morsel.value else ""
                )
                if not morsel.value:
                    self.csrf_token = ""

    def login(self, username, password):
        """Authenticate and retain the issued session and CSRF values."""
        return self.request(
            "/api/login",
            method="POST",
            payload={"username": username, "password": password},
        )

    def register(self, username, display_name, password, extra=None):
        """Register a regular user and retain the new authenticated session."""
        payload = {
            "username": username,
            "displayName": display_name,
            "password": password,
        }
        payload.update(extra or {})
        return self.request("/api/register", method="POST", payload=payload)


class ServerIntegrationTests(unittest.TestCase):
    """Exercise public defaults and authenticated behavior against a real server."""

    @classmethod
    def setUpClass(cls):
        """Create a legacy database, start the server, and wait for readiness."""
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="aics-test-")
        cls.database_path = Path(cls.temp_dir.name) / "test.sqlite3"
        cls.legacy_workspace = {
            "projects": [
                {
                    "id": "legacy-series",
                    "title": "Fictional legacy series",
                    "episodes": [],
                    "characters": [],
                }
            ],
            "activeId": "legacy-series",
        }
        with sqlite3.connect(cls.database_path) as database:
            database.execute(
                """
                CREATE TABLE workspace (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    revision INTEGER NOT NULL,
                    data TEXT NOT NULL
                )
                """
            )
            database.execute(
                "INSERT INTO workspace (id, revision, data) VALUES (1, 7, ?)",
                (json.dumps(cls.legacy_workspace),),
            )

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        env = os.environ.copy()
        env.update(
            {
                "AICS_ADMIN_USERNAME": ADMIN_USERNAME,
                "AICS_ADMIN_PASSWORD": ADMIN_PASSWORD,
                "AICS_ADMIN_DISPLAY_NAME": "Studio Owner",
                "AICS_COOKIE_SECURE": "1",
                "AICS_DB_PATH": str(cls.database_path),
                "AICS_REGISTRATION_ENABLED": "0",
                "AICS_MAX_USERS": "8",
                "AICS_SESSION_HOURS": "12",
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
        for _ in range(80):
            try:
                status, _, _ = TestClient(cls.base_url).request("/healthz")
                if status == 200:
                    return
            except OSError:
                time.sleep(0.1)
        cls.stop_server()
        raise RuntimeError("test server did not start")

    @classmethod
    def tearDownClass(cls):
        """Stop the test process and remove every temporary database artifact."""
        cls.stop_server()
        cls.temp_dir.cleanup()

    @classmethod
    def stop_server(cls):
        """Terminate the server, escalating only if graceful shutdown times out."""
        if cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait()

    def admin_client(self):
        """Return a newly authenticated administrator client."""
        client = TestClient(self.base_url)
        status, payload, _ = client.login(ADMIN_USERNAME, ADMIN_PASSWORD)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["role"], "admin")
        return client

    def set_registration(self, enabled):
        """Set registration policy through the administrator API."""
        admin = self.admin_client()
        status, payload, _ = admin.request(
            "/api/admin/settings",
            method="PUT",
            payload={"registrationEnabled": enabled},
        )
        self.assertEqual(status, 200, payload)

    def test_01_public_shell_and_safe_default(self):
        """Serve the login shell without a Basic Auth prompt and keep signup closed."""
        client = TestClient(self.base_url)
        status, health, _ = client.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"ok": True})

        status, html, headers = client.request("/")
        self.assertEqual(status, 200)
        self.assertIn('id="loginUsername"', html)
        self.assertIn('id="loginPassword"', html)
        self.assertIsNone(headers.get("WWW-Authenticate"))

        status, session, _ = client.request("/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(session["authenticated"])
        self.assertFalse(session["registrationEnabled"])
        self.assertEqual(session["version"], "0.2.0")

    def test_02_admin_login_hashing_and_legacy_migration(self):
        """Hash the bootstrap password and assign legacy data to the initial admin."""
        admin = TestClient(self.base_url)
        status, payload, headers = admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["role"], "admin")
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Secure", set_cookie)

        status, workspace, _ = admin.request("/api/workspace")
        self.assertEqual(status, 200)
        self.assertEqual(workspace["revision"], 7)
        self.assertEqual(workspace["data"], self.legacy_workspace)

        with sqlite3.connect(self.database_path) as database:
            stored = database.execute(
                "SELECT password_hash FROM users WHERE username=?",
                (ADMIN_USERNAME,),
            ).fetchone()[0]
            legacy_count = database.execute(
                "SELECT COUNT(*) FROM workspace"
            ).fetchone()[0]
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn(ADMIN_PASSWORD, stored)
        self.assertEqual(legacy_count, 1)

    def test_03_registration_policy_and_roles(self):
        """Keep signup admin-controlled and never accept a requested admin role."""
        self.set_registration(False)
        closed = TestClient(self.base_url)
        status, payload, _ = closed.register(
            "closeduser", "Closed User", "closed-password-123"
        )
        self.assertEqual(status, 403)
        self.assertIn("closed", payload["error"].lower())

        self.set_registration(True)
        elevated = TestClient(self.base_url)
        status, payload, _ = elevated.register(
            "elevated",
            "Elevated Request",
            "elevated-password-123",
            {"role": "admin"},
        )
        self.assertEqual(status, 400)
        self.assertIn("roles", payload["error"].lower())

        regular = TestClient(self.base_url)
        status, payload, _ = regular.register(
            "phoneuser", "Phone User", "phone-user-password"
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["user"]["role"], "user")
        status, _, _ = regular.request("/api/admin/users")
        self.assertEqual(status, 403)

    def test_04_private_workspace_isolation_and_conflicts(self):
        """Keep reads, writes, revisions, and conflicts scoped to each account."""
        self.set_registration(True)
        first = TestClient(self.base_url)
        second = TestClient(self.base_url)
        self.assertEqual(
            first.register("alice", "Alice Example", "alice-password-123")[0],
            201,
        )
        self.assertEqual(
            second.register("bob", "Bob Example", "bob-password-12345")[0],
            201,
        )
        first_data = {
            "projects": [
                {"id": "a", "title": "Alice story", "episodes": [], "characters": []}
            ],
            "activeId": "a",
        }
        second_data = {
            "projects": [
                {"id": "b", "title": "Bob story", "episodes": [], "characters": []}
            ],
            "activeId": "b",
        }
        status, saved, _ = first.request(
            "/api/workspace",
            method="PUT",
            payload={"revision": 0, "data": first_data},
        )
        self.assertEqual((status, saved["revision"]), (200, 1))
        status, saved, _ = second.request(
            "/api/workspace",
            method="PUT",
            payload={"revision": 0, "data": second_data},
        )
        self.assertEqual((status, saved["revision"]), (200, 1))

        self.assertEqual(first.request("/api/workspace")[1]["data"], first_data)
        self.assertEqual(second.request("/api/workspace")[1]["data"], second_data)
        status, _, _ = first.request(
            "/api/workspace",
            method="PUT",
            payload={"revision": 0, "data": first_data},
        )
        self.assertEqual(status, 409)

    def test_05_account_profile_theme_and_password_change(self):
        """Persist account preferences and revoke sessions after a password change."""
        self.set_registration(True)
        client = TestClient(self.base_url)
        self.assertEqual(
            client.register(
                "accountuser", "Account User", "account-password-123"
            )[0],
            201,
        )
        status, payload, _ = client.request(
            "/api/account",
            method="PUT",
            payload={"displayName": "Updated Name", "theme": "light"},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["displayName"], "Updated Name")
        self.assertEqual(payload["user"]["theme"], "light")

        status, _, _ = client.request(
            "/api/account",
            method="PUT",
            payload={
                "currentPassword": "wrong-password-123",
                "newPassword": "new-account-password",
            },
        )
        self.assertEqual(status, 403)
        status, payload, _ = client.request(
            "/api/account",
            method="PUT",
            payload={
                "currentPassword": "account-password-123",
                "newPassword": "new-account-password",
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["reauthenticate"])
        self.assertEqual(client.request("/api/session")[1]["authenticated"], False)

        old_login = TestClient(self.base_url)
        self.assertEqual(
            old_login.login("accountuser", "account-password-123")[0], 401
        )
        new_login = TestClient(self.base_url)
        self.assertEqual(
            new_login.login("accountuser", "new-account-password")[0], 200
        )

    def test_06_admin_user_management(self):
        """Allow explicit admin promotion and disable access without deleting users."""
        self.set_registration(True)
        managed = TestClient(self.base_url)
        self.assertEqual(
            managed.register(
                "manageduser", "Managed User", "managed-password-123"
            )[0],
            201,
        )
        self.assertEqual(managed.request("/api/admin/settings")[0], 403)

        admin = self.admin_client()
        status, payload, _ = admin.request("/api/admin/users")
        self.assertEqual(status, 200, payload)
        target = next(
            user for user in payload["users"] if user["username"] == "manageduser"
        )
        status, payload, _ = admin.request(
            "/api/admin/users/" + str(target["id"]),
            method="PUT",
            payload={"role": "admin", "active": True},
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["role"], "admin")
        self.assertEqual(managed.request("/api/admin/settings")[0], 200)

        status, payload, _ = admin.request(
            "/api/admin/users/" + str(target["id"]),
            method="PUT",
            payload={"role": "user", "active": False},
        )
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["user"]["active"])
        self.assertEqual(managed.request("/api/session")[1]["authenticated"], False)

        status, users, _ = admin.request("/api/admin/users")
        owner = next(
            user for user in users["users"] if user["username"] == ADMIN_USERNAME
        )
        status, _, _ = admin.request(
            "/api/admin/users/" + str(owner["id"]),
            method="PUT",
            payload={"role": "user", "active": False},
        )
        self.assertEqual(status, 409)

    def test_07_csrf_logout_and_expiry(self):
        """Reject missing CSRF tokens, clear logout state, and expire server sessions."""
        self.set_registration(True)
        client = TestClient(self.base_url)
        self.assertEqual(
            client.register(
                "sessionuser", "Session User", "session-password-123"
            )[0],
            201,
        )
        status, _, _ = client.request(
            "/api/account",
            method="PUT",
            payload={"theme": "light"},
            include_csrf=False,
        )
        self.assertEqual(status, 403)

        status, _, _ = client.request(
            "/api/account",
            method="PUT",
            payload={"theme": "light"},
            extra_headers={
                "Origin": "https://untrusted.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertEqual(status, 403)

        status, _, _ = client.request("/api/logout", method="POST", payload={})
        self.assertEqual(status, 200)
        self.assertEqual(client.request("/api/session")[1]["authenticated"], False)

        self.assertEqual(
            client.login("sessionuser", "session-password-123")[0], 200
        )
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                """
                UPDATE sessions SET expires_at=0
                WHERE user_id=(SELECT id FROM users WHERE username='sessionuser')
                """
            )
        self.assertEqual(client.request("/api/session")[1]["authenticated"], False)

    def test_08_malformed_auth_and_account_json(self):
        """Return controlled errors for non-string auth and account fields."""
        self.set_registration(True)
        malformed_registrations = (
            {
                "username": [],
                "displayName": "List User",
                "password": "valid-password-123",
            },
            {
                "username": "dictname",
                "displayName": {},
                "password": "valid-password-123",
            },
            {"username": "dictpass", "displayName": "Dict Pass", "password": {}},
        )
        for payload in malformed_registrations:
            status, _, _ = TestClient(self.base_url).request(
                "/api/register", method="POST", payload=payload
            )
            self.assertEqual(status, 400)

        admin = self.admin_client()
        malformed_updates = (
            {"displayName": {}},
            {"theme": []},
            {"currentPassword": [], "newPassword": "valid-password-123"},
            {"currentPassword": ADMIN_PASSWORD, "newPassword": {}},
        )
        for payload in malformed_updates:
            status, _, _ = admin.request(
                "/api/account", method="PUT", payload=payload
            )
            self.assertEqual(status, 400)

        status, users, _ = admin.request("/api/admin/users")
        self.assertEqual(status, 200)
        owner = next(user for user in users["users"] if user["role"] == "admin")
        status, _, _ = admin.request(
            "/api/admin/users/" + str(owner["id"]),
            method="PUT",
            payload={"role": [], "active": True},
        )
        self.assertEqual(status, 400)

    def test_09_registration_account_limit(self):
        """Stop public registration at the configured total account limit."""
        self.set_registration(True)
        allowed = TestClient(self.base_url)
        status, _, _ = allowed.register(
            "limituser", "Limit User", "limit-user-password"
        )
        self.assertEqual(status, 201)

        rejected = TestClient(self.base_url)
        status, payload, _ = rejected.register(
            "overflowuser", "Overflow User", "overflow-user-password"
        )
        self.assertEqual(status, 403)
        self.assertIn("limit", payload["error"].lower())

    def test_10_https_proxy_origin_and_secure_cookie_contract(self):
        """Simulate preserved public Host and HTTPS Origin headers locally."""
        proxy_headers = {
            "Host": "studio.example.test",
            "Origin": "https://studio.example.test",
            "Sec-Fetch-Site": "same-origin",
        }
        proxy_client = TestClient(self.base_url)
        status, _, headers = proxy_client.request(
            "/api/login",
            method="POST",
            payload={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            extra_headers=proxy_headers,
        )
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

        rejected = TestClient(self.base_url)
        status, _, _ = rejected.request(
            "/api/login",
            method="POST",
            payload={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            extra_headers={
                "Host": "studio.example.test",
                "Origin": "https://different.example.test",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(status, 403)

    def test_11_login_throttling(self):
        """Throttle username cycling without letting failures lock out the owner."""
        with sqlite3.connect(self.database_path) as database:
            database.execute("DELETE FROM login_attempts")

        client = TestClient(self.base_url)
        statuses = []
        for attempt in range(5):
            status, _, _ = client.request(
                "/api/login",
                method="POST",
                payload={
                    "username": "changing-" + str(attempt),
                    "password": "incorrect-password",
                },
                extra_headers={
                    "CF-Connecting-IP": "198.51.100." + str(attempt + 1)
                },
            )
            statuses.append(status)
        self.assertEqual(statuses[-1], 429)

        status, payload, headers = client.request(
            "/api/login",
            method="POST",
            payload={"username": "another-name", "password": "incorrect-password"},
            extra_headers={"CF-Connecting-IP": "203.0.113.99"},
        )
        self.assertEqual(status, 429)
        self.assertIn("later", payload["error"].lower())
        self.assertIsNotNone(headers.get("Retry-After"))

        for _ in range(5):
            client.login(ADMIN_USERNAME, "incorrect-password")
        status, payload, _ = client.login(ADMIN_USERNAME, ADMIN_PASSWORD)
        self.assertEqual(status, 200, payload)

        self.assertEqual(
            TestClient(self.base_url).login("x" * 41, "incorrect-password")[0],
            400,
        )
        self.assertEqual(
            TestClient(self.base_url).login("bounded", "x" * 257)[0],
            400,
        )
        self.assertEqual(
            TestClient(self.base_url).login("bounded", "x" * 5_000)[0],
            400,
        )

    def test_12_frontend_contract(self):
        """Keep responsive, themed, versioned, and attributed shell requirements."""
        client = TestClient(self.base_url)
        html = client.request("/")[1]
        css = client.request("/style.css")[1]
        favicon = client.request("/favicon.svg")[1]
        script = client.request("/app.js")[1]

        self.assertIn("width=device-width", html)
        self.assertIn('rel="icon"', html)
        self.assertIn('id="loginThemeToggle"', html)
        self.assertIn('id="themeToggle"', html)
        self.assertIn("https://www.jomaroliverreyes.com/", html)
        self.assertIn(">Developed by JOR</a>", html)
        self.assertNotIn("Jomar Oliver Reyes</a>", html)
        self.assertIn('id="footerVersion"', html)
        self.assertNotIn("0.2.0", html)
        self.assertNotIn("0.2.0", script)
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("@media (max-width: 520px)", css)
        self.assertIn("<svg", favicon)
        self.assertIn("creative spark", favicon)

if __name__ == "__main__":
    unittest.main()
