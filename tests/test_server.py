"""Integration tests for authentication, authorization, migration, and isolation."""

import base64
import concurrent.futures
import http.cookies
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import mcp_service
import server


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
        raw_body=None,
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
        if raw_body is not None:
            body = raw_body
        elif payload is not None:
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
        elif content_type.startswith("image/"):
            value = raw
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

    def login(self, username, password, extra_headers=None):
        """Authenticate and retain the issued session and CSRF values."""
        return self.request(
            "/api/login",
            method="POST",
            payload={"username": username, "password": password},
            extra_headers=extra_headers,
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


class LoginThrottleUnitTests(unittest.TestCase):
    """Test throttle decisions that must happen before credential verification."""

    def test_blocked_source_skips_password_verification(self):
        """Return 429 without querying users or verifying a supplied password."""
        handler = object.__new__(server.Handler)
        handler.read_json = unittest.mock.Mock(
            return_value={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        handler.attempt_scope = unittest.mock.Mock(return_value="blocked-source")
        handler.reserve_attempt = unittest.mock.Mock(
            return_value=(False, 60, 0)
        )
        handler.json_reply = unittest.mock.Mock(return_value="blocked")

        database = unittest.mock.MagicMock()
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value = database
        with unittest.mock.patch.object(server, "connect", return_value=connection):
            with unittest.mock.patch.object(server, "verify_password") as verify:
                result = handler.login()

        self.assertEqual(result, "blocked")
        verify.assert_not_called()
        database.execute.assert_not_called()
        handler.json_reply.assert_called_once_with(
            429,
            {"error": "Too many attempts. Try again later."},
            {"Retry-After": "60"},
        )

    def test_concurrent_burst_reserves_limit_before_verification(self):
        """Allow only the atomic limit to verify or create server sessions."""
        burst_size = server.LOGIN_LIMIT + 3
        release_verifiers = threading.Event()
        verification_lock = threading.Lock()
        verification_count = 0

        def controlled_verify(password, encoded):
            """Pause accepted verifications so excess requests hit the reservation."""
            nonlocal verification_count
            with verification_lock:
                verification_count += 1
            if not release_verifiers.wait(timeout=20):
                raise RuntimeError("concurrency test verifier timed out")
            return True

        class QuietHandler(server.Handler):
            """Run the burst without emitting one production log line per request."""

            def log_message(self, message_format, *args):
                """Suppress expected status logs inside this focused test."""
                return None

        with tempfile.TemporaryDirectory(prefix="aics-concurrency-") as temp_dir:
            database_path = Path(temp_dir) / "concurrency.sqlite3"
            patches = (
                unittest.mock.patch.object(server, "DB_PATH", database_path),
                unittest.mock.patch.object(server, "ADMIN_USERNAME", ADMIN_USERNAME),
                unittest.mock.patch.object(server, "ADMIN_PASSWORD", ADMIN_PASSWORD),
                unittest.mock.patch.object(
                    server, "ADMIN_DISPLAY_NAME", "Concurrency Owner"
                ),
                unittest.mock.patch.object(server, "PASSWORD_ITERATIONS", 1_000),
                unittest.mock.patch.object(
                    server, "verify_password", side_effect=controlled_verify
                ),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                server.setup()
                httpd = server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), QuietHandler
                )
                httpd.daemon_threads = True
                serving = threading.Thread(
                    target=httpd.serve_forever, daemon=True
                )
                serving.start()
                base_url = "http://127.0.0.1:" + str(httpd.server_port)
                executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=burst_size
                )
                futures = [
                    executor.submit(
                        TestClient(base_url).login,
                        ADMIN_USERNAME,
                        ADMIN_PASSWORD,
                    )
                    for _ in range(burst_size)
                ]
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        with verification_lock:
                            started = verification_count
                        if started == server.LOGIN_LIMIT:
                            break
                        time.sleep(0.01)
                    self.assertEqual(started, server.LOGIN_LIMIT)

                    excess = burst_size - server.LOGIN_LIMIT
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        completed = [future for future in futures if future.done()]
                        if len(completed) == excess:
                            break
                        time.sleep(0.01)
                    self.assertEqual(len(completed), excess)
                    early_statuses = [future.result()[0] for future in completed]
                    self.assertEqual(early_statuses, [429] * excess)
                    self.assertNotIn(500, early_statuses)
                    with sqlite3.connect(database_path) as database:
                        session_count = database.execute(
                            "SELECT COUNT(*) FROM sessions"
                        ).fetchone()[0]
                    self.assertEqual(session_count, 0)
                finally:
                    release_verifiers.set()
                    try:
                        results = [
                            future.result(timeout=10) for future in futures
                        ]
                    finally:
                        executor.shutdown(wait=True)
                        httpd.shutdown()
                        httpd.server_close()
                        serving.join(timeout=5)

                statuses = [status for status, _, _ in results]
                self.assertEqual(statuses.count(200), server.LOGIN_LIMIT)
                self.assertEqual(statuses.count(429), excess)
                self.assertNotIn(500, statuses)
                with verification_lock:
                    self.assertEqual(verification_count, server.LOGIN_LIMIT)
                with sqlite3.connect(database_path) as database:
                    session_count = database.execute(
                        "SELECT COUNT(*) FROM sessions"
                    ).fetchone()[0]
                self.assertEqual(session_count, server.LOGIN_LIMIT)

    def test_forwarded_address_requires_a_trusted_direct_peer(self):
        """Use Cloudflare's address only when the immediate peer is trusted."""
        handler = object.__new__(server.Handler)
        handler.headers = {"CF-Connecting-IP": "203.0.113.25"}
        trusted = (server.ipaddress.ip_network("127.0.0.1/32"),)
        with unittest.mock.patch.object(
            server, "TRUSTED_PROXY_NETWORKS", trusted
        ):
            handler.client_address = ("192.0.2.10", 1234)
            self.assertEqual(handler.login_client_address(), "192.0.2.10")
            handler.client_address = ("127.0.0.1", 1234)
            self.assertEqual(handler.login_client_address(), "203.0.113.25")


class McpReadinessUnitTests(unittest.TestCase):
    """Verify container health can detect a stopped private MCP worker."""

    def test_readiness_fails_when_mcp_worker_is_unreachable(self):
        """Return 503 when the loopback MCP child process cannot be contacted."""
        handler = object.__new__(server.Handler)
        handler.json_reply = unittest.mock.Mock(return_value="unhealthy")
        with unittest.mock.patch.object(
            server.http.client,
            "HTTPConnection",
            side_effect=ConnectionRefusedError,
        ):
            result = handler.mcp_readiness()
        self.assertEqual(result, "unhealthy")
        handler.json_reply.assert_called_once_with(503, {"ready": False})

    def test_compose_health_checks_web_and_mcp_readiness(self):
        """Keep both public web and private worker readiness in Compose health."""
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:8787/healthz", compose)
        self.assertIn("http://127.0.0.1:8787/mcp/ready", compose)


class WorkspacePlanningMigrationTests(unittest.TestCase):
    """Verify v0.2 defaults preserve owner-entered legacy planning records."""

    def test_normalization_preserves_legacy_text_ids_and_adds_planning_fields(self):
        """Migrate old JSON without rewriting descriptions, hooks, or scripts."""
        legacy = {
            "projects": [{
                "id": "existing-project",
                "title": "Existing project",
                "description": "Owner description",
                "episodes": [{
                    "id": "EP06",
                    "title": "Existing episode",
                    "hook": "Owner hook",
                    "script": "Owner full script",
                }],
                "characters": [{
                    "id": "existing-character",
                    "name": "Existing character",
                    "look": "Fixed appearance",
                }],
            }],
            "activeId": "existing-project",
        }

        migrated, changed = server.normalize_workspace_data(legacy)

        self.assertTrue(changed)
        project = migrated["projects"][0]
        episode = project["episodes"][0]
        character = project["characters"][0]
        self.assertEqual(project["id"], "existing-project")
        self.assertEqual(project["description"], "Owner description")
        self.assertEqual(episode["id"], "EP06")
        self.assertEqual(episode["hook"], "Owner hook")
        self.assertEqual(episode["script"], "Owner full script")
        self.assertEqual(episode["synopsis"], "")
        self.assertEqual(episode["beats"], "")
        self.assertEqual(episode["shots"], [])
        self.assertEqual(project["prompts"], [])
        self.assertEqual(project["bible"]["seasonArc"], "")
        self.assertEqual(character["referenceRequirements"], "")
        self.assertEqual(character["continuity"]["mustKeep"], "")

        _, changed_again = server.normalize_workspace_data(migrated)
        self.assertFalse(changed_again)

    def test_oauth_token_scope_column_migrates_without_losing_rows(self):
        """Add per-token scopes to an existing schema while retaining token records."""
        with tempfile.TemporaryDirectory(prefix="aics-scope-migration-") as directory:
            database_path = Path(directory) / "migration.sqlite3"
            raw_token = "migration-access-" + secrets.token_urlsafe(40)
            with unittest.mock.patch.multiple(
                server,
                DB_PATH=database_path,
                ADMIN_USERNAME=ADMIN_USERNAME,
                ADMIN_PASSWORD=ADMIN_PASSWORD,
                ADMIN_DISPLAY_NAME="Studio Owner",
            ):
                server.setup()
                with sqlite3.connect(database_path) as database:
                    user_id = database.execute(
                        "SELECT id FROM users WHERE role='admin'"
                    ).fetchone()[0]
                    now = int(time.time())
                    database.execute(
                        """
                        INSERT INTO oauth_clients
                            (client_id, client_name, redirect_uris, created_at)
                        VALUES ('migration-client', 'Migration test', '[]', ?)
                        """,
                        (now,),
                    )
                    grant_id = database.execute(
                        """
                        INSERT INTO oauth_grants
                            (user_id, client_id, scopes, created_at)
                        VALUES (?, 'migration-client',
                                'aics.read aics.write', ?)
                        """,
                        (user_id, now),
                    ).lastrowid
                    database.execute(
                        """
                        INSERT INTO oauth_tokens
                            (token_hash, grant_id, token_type, family_id,
                             created_at, expires_at, scopes)
                        VALUES (?, ?, 'access', 'migration-family', ?, ?,
                                'aics.read aics.write')
                        """,
                        (
                            server.token_hash(raw_token), grant_id,
                            now, now + 3600,
                        ),
                    )
                    database.execute("ALTER TABLE oauth_tokens DROP COLUMN scopes")
                server.setup()
                with sqlite3.connect(database_path) as database:
                    columns = {
                        row[1]
                        for row in database.execute(
                            "PRAGMA table_info(oauth_tokens)"
                        )
                    }
                    token_count = database.execute(
                        "SELECT COUNT(*) FROM oauth_tokens"
                    ).fetchone()[0]
                self.assertIn("scopes", columns)
                self.assertEqual(token_count, 1)
                self.assertIsNotNone(
                    server.resolve_access_token(raw_token, "aics.write")
                )


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
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.mcp_port = sock.getsockname()[1]
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
                "AICS_REGISTRATION_ATTEMPT_LIMIT": "5",
                "AICS_OAUTH_CLIENT_LIMIT": "12",
                "AICS_OAUTH_FLOW_LIMIT": "4",
                "AICS_TRUSTED_PROXY_NETWORKS": "127.0.0.1/32",
                "AICS_SESSION_HOURS": "12",
                "AICS_PUBLIC_BASE_URL": cls.base_url,
                "AICS_MCP_INTERNAL_PORT": str(cls.mcp_port),
                "PORT": str(cls.port),
            }
        )
        cls.process = subprocess.Popen(
            [sys.executable, "launcher.py"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(80):
            try:
                web_status, _, _ = TestClient(cls.base_url).request("/healthz")
                mcp_status, _, _ = TestClient(cls.base_url).request("/mcp/ready")
                if web_status == 200 and mcp_status == 200:
                    return
            except OSError:
                pass
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

    def setUp(self):
        """Clear request throttles so every integration test is independent."""
        with sqlite3.connect(self.database_path) as database:
            database.execute("DELETE FROM login_attempts")

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
        status, ready, _ = client.request("/mcp/ready")
        self.assertEqual(status, 200)
        self.assertEqual(ready, {"ready": True})

        status, html, headers = client.request("/")
        self.assertEqual(status, 200)
        self.assertIn('id="loginUsername"', html)
        self.assertIn('id="loginPassword"', html)
        self.assertIsNone(headers.get("WWW-Authenticate"))

        status, session, _ = client.request("/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(session["authenticated"])
        self.assertFalse(session["registrationEnabled"])
        self.assertEqual(session["version"], "0.3.0")

    def test_02_admin_login_hashing_and_legacy_migration(self):
        """Hash the bootstrap password and assign legacy data to the initial admin."""
        admin = TestClient(self.base_url)
        status, payload, headers = admin.login(ADMIN_USERNAME, ADMIN_PASSWORD)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["role"], "admin")
        self.assertEqual(payload["version"], "0.3.0")
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Secure", set_cookie)

        status, workspace, _ = admin.request("/api/workspace")
        self.assertEqual(status, 200)
        self.assertEqual(workspace["revision"], 7)
        self.assertFalse(workspace["data"]["projects"][0]["archived"])
        self.assertEqual(
            workspace["data"]["projects"][0]["title"],
            self.legacy_workspace["projects"][0]["title"],
        )
        self.assertEqual(workspace["data"]["projects"][0]["prompts"], [])
        self.assertEqual(workspace["data"]["projects"][0]["bible"]["logline"], "")
        self.assertEqual(workspace["data"]["projects"][0]["gates"], [])

        with sqlite3.connect(self.database_path) as database:
            stored = database.execute(
                "SELECT password_hash FROM users WHERE username=?",
                (ADMIN_USERNAME,),
            ).fetchone()[0]
            legacy_count = database.execute(
                "SELECT COUNT(*) FROM workspace"
            ).fetchone()[0]
            schema_version = database.execute(
                "SELECT value FROM app_settings WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn(ADMIN_PASSWORD, stored)
        self.assertEqual(legacy_count, 1)
        self.assertEqual(schema_version, "5")

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
                {
                    "id": "a", "title": "Alice story",
                    "bible": {"logline": "Alice private logline"},
                    "prompts": [{"id": "prompt-a", "name": "Alice prompt", "body": "Private prompt"}],
                    "episodes": [{
                        "id": "EP01", "title": "Alice episode",
                        "hook": "Unchanged hook", "script": "Unchanged script",
                        "synopsis": "Private synopsis", "beats": "Beat one",
                        "shots": [{"id": "shot-a", "imagePrompt": "Private image prompt"}],
                    }],
                    "characters": [{
                        "id": "alice-character", "name": "Alice character",
                        "referenceRequirements": "Private image plan",
                        "continuity": {"mustKeep": "Blue coat"},
                    }],
                }
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

        first_loaded = first.request("/api/workspace")[1]["data"]["projects"][0]
        self.assertEqual(first_loaded["title"], "Alice story")
        self.assertEqual(first_loaded["episodes"][0]["hook"], "Unchanged hook")
        self.assertEqual(first_loaded["episodes"][0]["script"], "Unchanged script")
        self.assertEqual(first_loaded["episodes"][0]["synopsis"], "Private synopsis")
        self.assertEqual(first_loaded["episodes"][0]["shots"][0]["imagePrompt"], "Private image prompt")
        self.assertEqual(first_loaded["prompts"][0]["body"], "Private prompt")
        self.assertEqual(
            second.request("/api/workspace")[1]["data"]["projects"][0]["title"],
            "Bob story",
        )
        self.assertNotIn("Alice private logline", json.dumps(second.request("/api/workspace")[1]))
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

    def test_09_registration_attempt_limit(self):
        """Limit repeated registration attempts from one trusted client source."""
        self.set_registration(True)
        client = TestClient(self.base_url)
        headers = {"CF-Connecting-IP": "198.51.100.30"}
        statuses = []
        for _ in range(5):
            status, _, _ = client.request(
                "/api/register",
                method="POST",
                payload={
                    "username": ADMIN_USERNAME,
                    "displayName": "Duplicate Owner",
                    "password": "duplicate-password-123",
                },
                extra_headers=headers,
            )
            statuses.append(status)
        self.assertEqual(statuses, [409, 409, 409, 409, 409])

        status, payload, response_headers = client.request(
            "/api/register",
            method="POST",
            payload={
                "username": "sixth-attempt",
                "displayName": "Sixth Attempt",
                "password": "sixth-attempt-password",
            },
            extra_headers=headers,
        )
        self.assertEqual(status, 429)
        self.assertIn("later", payload["error"].lower())
        self.assertIsNotNone(response_headers.get("Retry-After"))

    def test_10_registration_account_limit(self):
        """Test the total account cap without depending on earlier test data."""
        self.set_registration(True)
        maximum_users = 8
        now = int(time.time())
        with sqlite3.connect(self.database_path) as database:
            database.execute("PRAGMA foreign_keys=ON")
            database.execute(
                "DELETE FROM users WHERE username<>?", (ADMIN_USERNAME,)
            )
            owner_hash = database.execute(
                "SELECT password_hash FROM users WHERE username=?",
                (ADMIN_USERNAME,),
            ).fetchone()[0]
            current_users = database.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
            fillers_needed = max(0, maximum_users - current_users - 1)
            for index in range(fillers_needed):
                database.execute(
                    """
                    INSERT INTO users
                        (username, display_name, password_hash, role, created_at, updated_at)
                    VALUES (?, ?, ?, 'user', ?, ?)
                    """,
                    (
                        "capfill" + str(index),
                        "Capacity Filler " + str(index),
                        owner_hash,
                        now,
                        now,
                    ),
                )

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

    def test_11_https_proxy_origin_and_secure_cookie_contract(self):
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

    def test_12_login_throttling(self):
        """Block one trusted source before allowing a separate source to sign in."""
        client = TestClient(self.base_url)
        blocked_headers = {"CF-Connecting-IP": "198.51.100.40"}
        statuses = []
        for attempt in range(5):
            status, _, _ = client.login(
                "changing-" + str(attempt),
                "incorrect-password",
                extra_headers=blocked_headers,
            )
            statuses.append(status)
        self.assertEqual(statuses[-1], 429)

        status, payload, headers = client.login(
            "another-name",
            "incorrect-password",
            extra_headers=blocked_headers,
        )
        self.assertEqual(status, 429)
        self.assertIn("later", payload["error"].lower())
        self.assertIsNotNone(headers.get("Retry-After"))

        trusted_client = TestClient(self.base_url)
        status, payload, _ = trusted_client.login(
            ADMIN_USERNAME,
            ADMIN_PASSWORD,
            extra_headers={"CF-Connecting-IP": "198.51.100.41"},
        )
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

    def test_13_frontend_contract(self):
        """Keep responsive, themed, versioned, and attributed shell requirements."""
        client = TestClient(self.base_url)
        html = client.request("/")[1]
        css = client.request("/style.css")[1]
        favicon = client.request("/favicon.svg")[1]
        script = client.request("/app.js")[1]

        self.assertIn("width=device-width", html)
        self.assertIn('rel="icon"', html)
        self.assertIn('class="bootstrap-view" id="bootstrapView" role="status"', html)
        self.assertIn('aria-live="polite" aria-busy="true"', html)
        self.assertIn('id="bootstrapTitle">Loading studio</h1>', html)
        self.assertIn('<section class="auth-view hidden" id="authView"', html)
        self.assertIn('<div class="app-view hidden" id="appView">', html)
        self.assertIn("JavaScript is required to sign in", html)
        self.assertIn('id="loginThemeToggle"', html)
        self.assertIn('id="themeToggle"', html)
        self.assertIn("https://www.jomaroliverreyes.com/", html)
        self.assertIn(">Developed by JOR</a>", html)
        self.assertNotIn("Jomar Oliver Reyes</a>", html)
        self.assertIn('id="footerVersion"', html)
        self.assertNotIn("0.1.0", html)
        self.assertNotIn("0.1.0", script)
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("@media (max-width: 520px)", css)
        favicon_text = favicon.decode("utf-8")
        self.assertIn("<svg", favicon_text)
        self.assertIn("film and story mark", favicon_text)
        self.assertNotIn("creative spark", favicon_text)
        self.assertIn('id="navToggle"', html)
        self.assertIn(
            '<small class="sidebar-tagline"><span>CREATIVE</span>'
            '<span>WORKSPACE</span></small>',
            html,
        )
        self.assertIn(".brand .sidebar-tagline", css)
        self.assertIn(".sidebar-tagline span", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn(".shell.sidebar-closed .sidebar-tagline", css)
        self.assertIn("function goTo(tab, focusDestination)", script)
        self.assertIn("function focusSectionHeading(tab)", script)
        self.assertIn("section.getAttribute(\"aria-labelledby\")", script)
        self.assertIn("focusSectionHeading(tab)", script)
        self.assertNotIn('byId("mainContent").focus', script)
        self.assertIn("showAuthenticated(payload, false)", script)
        self.assertIn('byId("bootstrapView").classList.add("hidden")', script)
        self.assertLess(
            script.index("applyTheme(session.user.theme, false)"),
            script.index('byId("appView").classList.remove("hidden")'),
        )
        self.assertEqual(script.count("await showAuthenticated(payload, true);"), 2)
        self.assertIn("goTo(button.dataset.tab, true);", script)
        self.assertIn("goTo(goButton.dataset.go, true);", script)
        self.assertIn("window.requestAnimationFrame", script)
        self.assertIn(":focus-visible", css)
        self.assertIn("#mainContent:focus-visible", css)
        self.assertIn(".side {\n  position: fixed", css)
        self.assertIn(".main {\n  grid-column: 2", css)
        self.assertIn("position: sticky;\n    left: auto;\n    width: 100%", css)
        self.assertNotIn("var(--surface) 0 259px", css)
        self.assertNotIn("var(--surface) 0 77px", css)
        self.assertIn("flex: 1 1 auto", css)
        self.assertIn(".shell:not(.sidebar-closed) .sidefoot", css)
        self.assertEqual(html.count('class="nav-icon"'), 9)
        self.assertNotIn('<span class="n">01</span>', html)
        self.assertIn('class="footer-line"', html)
        self.assertIn('id="toolDialog"', html)
        self.assertIn('id="addTool"', html)
        self.assertNotIn('<div class="stack" id="toolGrid"></div><form', html)
        self.assertIn("openToolDialog", script)
        self.assertIn('id="projectFilter"', html)
        self.assertIn('id="cImage"', html)
        self.assertIn("Uploaded images are not included", script)
        self.assertIn('id="pLogline"', html)
        self.assertIn('id="episodeSynopsis"', html)
        self.assertIn('id="episodeBeats"', html)
        self.assertIn('id="shotList"', html)
        self.assertIn('id="promptGrid"', html)
        self.assertIn('id="gateList"', html)
        self.assertIn("one approved PNG", html)
        self.assertIn("navigator.clipboard.writeText", script)
        self.assertIn("structuredClone(editingShots)", script)
    def reset_regular_users(self):
        """Remove prior test accounts while retaining the initial administrator."""
        with sqlite3.connect(self.database_path) as database:
            database.execute("PRAGMA foreign_keys=ON")
            database.execute("DELETE FROM users WHERE username<>?", (ADMIN_USERNAME,))

    def test_14_user_lifecycle_and_scoped_deletion(self):
        """Retain archived data, revoke access, and delete only the selected user."""
        self.reset_regular_users()
        self.set_registration(True)
        managed = TestClient(self.base_url)
        self.assertEqual(managed.register("lifecycle", "Lifecycle User", "lifecycle-password-123")[0], 201)
        workspace = {"projects": [{"id": "kept", "title": "Kept", "episodes": [], "characters": [{"id": "kept-cast", "name": "Fictional cast"}]}], "activeId": "kept"}
        self.assertEqual(managed.request("/api/workspace", method="PUT", payload={"revision": 0, "data": workspace})[0], 200)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        self.assertEqual(managed.request("/api/characters/kept-cast/image", method="PUT", raw_body=png, extra_headers={"Content-Type": "image/png"})[0], 200)
        admin = self.admin_client()
        users = admin.request("/api/admin/users")[1]["users"]
        target = next(user for user in users if user["username"] == "lifecycle")
        endpoint = "/api/admin/users/" + str(target["id"])

        self.assertEqual(admin.request(endpoint, method="PUT", payload={"action": "archive"})[0], 200)
        self.assertFalse(managed.request("/api/session")[1]["authenticated"])
        self.assertEqual(TestClient(self.base_url).login("lifecycle", "lifecycle-password-123")[0], 401)
        archived = next(user for user in admin.request("/api/admin/users")[1]["users"] if user["id"] == target["id"])
        self.assertTrue(archived["archived"])

        self.assertEqual(admin.request(endpoint, method="PUT", payload={"action": "restore"})[0], 200)
        restored = TestClient(self.base_url)
        self.assertEqual(restored.login("lifecycle", "lifecycle-password-123")[0], 200)
        self.assertEqual(restored.request("/api/workspace")[1]["data"]["projects"][0]["id"], "kept")
        self.assertEqual(admin.request(endpoint, method="PUT", payload={"action": "disable"})[0], 200)
        self.assertFalse(restored.request("/api/session")[1]["authenticated"])
        self.assertEqual(admin.request(endpoint, method="PUT", payload={"action": "restore"})[0], 200)
        self.assertEqual(admin.request(endpoint, method="DELETE")[0], 200)
        self.assertEqual(TestClient(self.base_url).login("lifecycle", "lifecycle-password-123")[0], 401)
        with sqlite3.connect(self.database_path) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM workspaces WHERE user_id=?", (target["id"],)).fetchone()[0], 0)
        self.assertFalse((self.database_path.parent / "images" / str(target["id"])).exists())
        self.assertEqual(admin.request("/api/workspace")[1]["data"]["projects"][0]["id"], "legacy-series")
        owner = next(user for user in admin.request("/api/admin/users")[1]["users"] if user["username"] == ADMIN_USERNAME)
        owner_endpoint = "/api/admin/users/" + str(owner["id"])
        self.assertEqual(admin.request(owner_endpoint, method="PUT", payload={"action": "archive"})[0], 409)
        self.assertEqual(admin.request(owner_endpoint, method="DELETE")[0], 409)

    def test_15_workspace_lifecycle_empty_and_legacy_compatibility(self):
        """Round-trip lifecycle fields, legacy IDs, and an intentionally empty workspace."""
        admin = self.admin_client()
        current = admin.request("/api/workspace")[1]
        data = {
            "projects": [{
                "id": "legacy-id", "title": "Lifecycle project", "archived": True,
                "episodes": [{"id": "EP01", "title": "Archived episode", "archived": True}],
                "characters": [{"id": "cast-id", "name": "Archived cast", "archived": True}],
            }],
            "activeId": "legacy-id",
        }
        status, saved, _ = admin.request("/api/workspace", method="PUT", payload={"revision": current["revision"], "data": data})
        self.assertEqual(status, 200, saved)
        loaded = admin.request("/api/workspace")[1]
        self.assertEqual(loaded["data"]["projects"][0]["id"], "legacy-id")
        self.assertTrue(loaded["data"]["projects"][0]["episodes"][0]["archived"])
        status, saved, _ = admin.request("/api/workspace", method="PUT", payload={"revision": loaded["revision"], "data": {"projects": [], "activeId": ""}})
        self.assertEqual(status, 200, saved)
        self.assertEqual(admin.request("/api/workspace")[1]["data"], {"projects": [], "activeId": ""})

    def test_16_private_character_images(self):
        """Isolate, validate, replace, remove, and persist private image bytes."""
        self.reset_regular_users()
        self.set_registration(True)
        first = TestClient(self.base_url)
        second = TestClient(self.base_url)
        self.assertEqual(first.register("imageone", "Image One", "image-one-password")[0], 201)
        self.assertEqual(second.register("imagetwo", "Image Two", "image-two-password")[0], 201)
        for client, project_id in ((first, "one"), (second, "two")):
            data = {"projects": [{"id": project_id, "title": project_id, "episodes": [], "characters": [{"id": "shared-character", "name": "Cast"}]}], "activeId": project_id}
            self.assertEqual(client.request("/api/workspace", method="PUT", payload={"revision": 0, "data": data})[0], 200)
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        path = "/api/characters/shared-character/image"
        self.assertEqual(first.request(path, method="PUT", raw_body=png, extra_headers={"Content-Type": "image/png"})[0], 200)
        self.assertEqual(first.request(path)[1], png)
        self.assertEqual(second.request(path)[0], 404)
        self.assertEqual(first.request("/api/workspace")[1]["imageCharacterIds"], ["shared-character"])
        self.assertEqual(first.request(path, method="PUT", raw_body=b"not-an-image", extra_headers={"Content-Type": "image/png"})[0], 400)
        oversized_handler = object.__new__(server.Handler)
        oversized_handler.headers = {"Content-Length": str(server.MAX_IMAGE_BYTES + 1)}
        with self.assertRaises(ValueError):
            oversized_handler.read_body(server.MAX_IMAGE_BYTES)
        webp_payload = b"\x00" * 10
        webp = (
            b"RIFF"
            + (4 + 8 + len(webp_payload)).to_bytes(4, "little")
            + b"WEBPVP8X"
            + len(webp_payload).to_bytes(4, "little")
            + webp_payload
        )
        self.assertEqual(first.request(path, method="PUT", raw_body=webp, extra_headers={"Content-Type": "image/webp"})[0], 200)
        self.assertEqual(first.request(path)[1], webp)
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            server.setup()
        self.assertEqual(first.request(path)[1], webp)
        with sqlite3.connect(self.database_path) as database:
            user_id = database.execute("SELECT id FROM users WHERE username='imageone'").fetchone()[0]
            image_count = database.execute("SELECT COUNT(*) FROM character_images WHERE user_id=?", (user_id,)).fetchone()[0]
        self.assertEqual(image_count, 1)
        self.assertEqual(first.request(path, method="DELETE")[0], 200)
        self.assertEqual(first.request(path)[0], 404)
        self.assertEqual(first.request(path, method="PUT", raw_body=png, extra_headers={"Content-Type": "image/png"})[0], 200)
        current = first.request("/api/workspace")[1]
        current["data"]["projects"][0]["characters"] = []
        self.assertEqual(first.request("/api/workspace", method="PUT", payload={"revision": current["revision"], "data": current["data"]})[0], 200)
        self.assertEqual(first.request(path)[0], 404)

    def test_17_tool_catalog_permissions_and_validation(self):
        """Persist categorized tool CRUD and restrict management to administrators."""
        self.reset_regular_users()
        self.set_registration(True)
        regular = TestClient(self.base_url)
        self.assertEqual(regular.register("toolviewer", "Tool Viewer", "tool-viewer-password")[0], 201)
        self.assertEqual(regular.request("/api/tools")[0], 200)
        valid = {"name": "Fictional Editor", "category": "Editing", "url": "https://example.com/editor", "purpose": "Edit fictional scenes.", "notes": "Sample only."}
        self.assertEqual(regular.request("/api/admin/tools", method="POST", payload=valid)[0], 403)
        admin = self.admin_client()
        self.assertEqual(admin.request("/api/admin/tools", method="POST", payload=dict(valid, url="http://example.com"))[0], 400)
        status, created, _ = admin.request("/api/admin/tools", method="POST", payload=valid)
        self.assertEqual(status, 201, created)
        tool_id = created["tool"]["id"]
        self.assertEqual(created["tool"]["category"], "Editing")
        self.assertEqual(admin.request("/api/admin/tools/" + str(tool_id), method="PUT", payload={"action": "archive"})[0], 200)
        self.assertNotIn(tool_id, [tool["id"] for tool in regular.request("/api/tools")[1]["tools"]])
        admin_tools = admin.request("/api/tools")[1]["tools"]
        self.assertTrue(next(tool for tool in admin_tools if tool["id"] == tool_id)["archived"])
        self.assertEqual(admin.request("/api/admin/tools/" + str(tool_id), method="PUT", payload={"action": "restore"})[0], 200)
        edited = dict(valid, action="edit", name="Updated Editor")
        self.assertEqual(admin.request("/api/admin/tools/" + str(tool_id), method="PUT", payload=edited)[1]["tool"]["name"], "Updated Editor")
        self.assertEqual(admin.request("/api/admin/tools/" + str(tool_id), method="DELETE")[0], 200)
        with sqlite3.connect(self.database_path) as database:
            database.execute("DELETE FROM tools")
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            server.setup()
        self.assertEqual(admin.request("/api/tools")[1]["tools"], [])

    def test_17a_oauth_authorization_ui_locales_compatibility(self):
        """Accept ChatGPT locale hints without weakening OAuth request validation."""
        client = TestClient(self.base_url)
        redirect_uri = self.base_url + "/locale-test-callback"
        status, registered, _ = client.request(
            "/oauth/register",
            method="POST",
            payload={
                "client_name": "Locale compatibility test",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual(status, 201, registered)
        admin = self.admin_client()
        valid = {
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": redirect_uri,
            "scope": "aics.read aics.write",
            "state": "locale-state",
            "code_challenge": server.pkce_challenge("l" * 48),
            "code_challenge_method": "S256",
            "resource": self.base_url + "/mcp",
        }

        def authorize(changes=None):
            """Send one authorization request built from the valid baseline."""
            parameters = dict(valid)
            parameters.update(changes or {})
            return admin.request(
                "/oauth/authorize?" + urllib.parse.urlencode(parameters)
            )

        status, page, _ = authorize()
        self.assertEqual(status, 200, page)
        status, page, _ = authorize({"ui_locales": "en-US"})
        self.assertEqual(status, 200, page)
        status, page, _ = authorize({"ui_locales": "en-US fr-FR"})
        self.assertEqual(status, 200, page)

        with sqlite3.connect(self.database_path) as database:
            saved_requests = [
                json.loads(row[0])
                for row in database.execute(
                    "SELECT request_data FROM oauth_flows"
                ).fetchall()
            ]
        self.assertTrue(saved_requests)
        self.assertTrue(
            all("ui_locales" not in request for request in saved_requests)
        )

        rejected = (
            {"ui_locales": "en_US"},
            {"ui_locales": "en-US  fr-FR"},
            {"ui_locales": "a" * 129},
            {"unknown_parameter": "value"},
            {"redirect_uri": self.base_url + "/wrong-callback"},
            {"resource": self.base_url + "/wrong-resource"},
            {"code_challenge": "short"},
            {"code_challenge_method": "plain"},
            {"scope": "aics.admin"},
            {"client_id": "unknown-client"},
        )
        for changes in rejected:
            status, payload, _ = authorize(changes)
            self.assertEqual(status, 400, (changes, payload))
            self.assertEqual(payload["error"], "invalid_request")

        handler = object.__new__(server.Handler)
        with self.assertRaises(ValueError):
            handler.validated_authorization_request(
                dict(valid, ui_locales=["en-US"])
            )

        with sqlite3.connect(self.database_path) as database:
            database.execute("DELETE FROM oauth_flows")
            database.execute(
                "DELETE FROM oauth_source_limits WHERE purpose='authorization'"
            )
            database.execute(
                "DELETE FROM oauth_source_limits WHERE purpose='registration'"
            )

    def test_18_oauth_discovery_pkce_rotation_revocation_and_redirects(self):
        """Exercise OAuth discovery, consent, PKCE, rotation, and revocation."""
        client = TestClient(self.base_url)
        protected = client.request("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(protected[0], 200)
        self.assertEqual(protected[1]["resource"], self.base_url + "/mcp")
        metadata = client.request("/.well-known/oauth-authorization-server")
        self.assertEqual(metadata[0], 200)
        self.assertEqual(metadata[1]["code_challenge_methods_supported"], ["S256"])

        invalid = {
            "client_name": "Bad redirect",
            "redirect_uris": ["https://example.test/callback#fragment"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        self.assertEqual(
            client.request("/oauth/register", method="POST", payload=invalid)[0],
            400,
        )
        redirect_uri = self.base_url + "/oauth-test-callback"
        registration = dict(invalid, client_name="MCP test", redirect_uris=[redirect_uri])
        now = int(time.time())
        registration_scope = server.hashlib.sha256(
            b"oauth-registration\x00127.0.0.1"
        ).hexdigest()
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                """
                INSERT INTO oauth_source_limits
                    (scope_hash, purpose, window_started, request_count)
                VALUES (?, 'registration', ?, ?)
                """,
                (registration_scope, now, server.OAUTH_REGISTRATION_LIMIT),
            )
            clients_before = database.execute(
                "SELECT COUNT(*) FROM oauth_clients"
            ).fetchone()[0]
        status, _, headers = client.request(
            "/oauth/register", method="POST", payload=registration
        )
        self.assertEqual(status, 429)
        self.assertIsNotNone(headers.get("Retry-After"))
        with sqlite3.connect(self.database_path) as database:
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0],
                clients_before,
            )
            database.execute(
                "DELETE FROM oauth_source_limits WHERE purpose='registration'"
            )
            database.execute(
                """
                INSERT INTO oauth_clients
                    (client_id, client_name, redirect_uris, created_at)
                VALUES ('expired-client', 'Expired', '[]', ?)
                """,
                (now - server.OAUTH_CLIENT_TTL_SECONDS - 1,),
            )
            database.execute(
                """
                INSERT INTO oauth_flows
                    (flow_hash, request_data, created_at, expires_at)
                VALUES ('expired-flow', '{}', ?, ?)
                """,
                (now - 10, now - 1),
            )
        status, registered, _ = client.request(
            "/oauth/register", method="POST", payload=registration
        )
        self.assertEqual(status, 201, registered)
        with sqlite3.connect(self.database_path) as database:
            self.assertIsNone(
                database.execute(
                    "SELECT 1 FROM oauth_clients WHERE client_id='expired-client'"
                ).fetchone()
            )
            self.assertIsNone(
                database.execute(
                    "SELECT 1 FROM oauth_flows WHERE flow_hash='expired-flow'"
                ).fetchone()
            )

        admin = self.admin_client()
        verifier = "v" * 48
        challenge = server.pkce_challenge(verifier)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": registered["client_id"],
                "redirect_uri": redirect_uri,
                "scope": "aics.read aics.write",
                "state": "state-value",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": self.base_url + "/mcp",
            }
        )
        authorization_scope = server.hashlib.sha256(
            b"oauth-authorization\x00127.0.0.1"
        ).hexdigest()
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                """
                INSERT INTO oauth_source_limits
                    (scope_hash, purpose, window_started, request_count)
                VALUES (?, 'authorization', ?, ?)
                """,
                (authorization_scope, now, server.OAUTH_AUTHORIZATION_LIMIT),
            )
            flows_before = database.execute(
                "SELECT COUNT(*) FROM oauth_flows"
            ).fetchone()[0]
        status, _, headers = admin.request("/oauth/authorize?" + query)
        self.assertEqual(status, 429)
        self.assertIsNotNone(headers.get("Retry-After"))
        with sqlite3.connect(self.database_path) as database:
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM oauth_flows").fetchone()[0],
                flows_before,
            )
            database.execute(
                "DELETE FROM oauth_source_limits WHERE purpose='authorization'"
            )
        status, page, headers = admin.request("/oauth/authorize?" + query)
        self.assertEqual(status, 200, page)
        flow = page.split('name="flow" value="', 1)[1].split('"', 1)[0]
        flow_cookie = headers.get("Set-Cookie", "").split(";", 1)[0]

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            """Keep the authorization response available for exact inspection."""

            def redirect_request(self, request, file_pointer, code, message, headers, new_url):
                """Decline automatic callback navigation."""
                return None

        body = urllib.parse.urlencode(
            {"flow": flow, "decision": "approve"}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/oauth/authorize",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": admin.cookie + "; " + flow_cookie,
            },
        )
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=5)
            self.fail("Authorization redirect was expected.")
        except urllib.error.HTTPError as response:
            self.assertEqual(response.code, 302)
            callback = urllib.parse.urlsplit(response.headers["Location"])
        parameters = urllib.parse.parse_qs(callback.query)
        self.assertEqual(parameters["state"], ["state-value"])
        code = parameters["code"][0]

        def form_post(path, values):
            """Post an OAuth form and decode its JSON response."""
            request = urllib.request.Request(
                self.base_url + path,
                data=urllib.parse.urlencode(values).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            return response.status, json.loads(response.read() or b"{}")

        status, tokens = form_post(
            "/oauth/token",
            {
                "grant_type": "authorization_code",
                "client_id": registered["client_id"],
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": verifier,
                "resource": self.base_url + "/mcp",
            },
        )
        self.assertEqual(status, 200, tokens)
        with sqlite3.connect(self.database_path) as database:
            stored_hashes = {
                row[0] for row in database.execute(
                    "SELECT token_hash FROM oauth_tokens"
                ).fetchall()
            }
        self.assertNotIn(tokens["access_token"], stored_hashes)
        self.assertIn(server.token_hash(tokens["access_token"]), stored_hashes)
        self.assertIn(server.token_hash(tokens["refresh_token"]), stored_hashes)
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            self.assertIsNotNone(
                server.resolve_access_token(tokens["access_token"], "aics.read")
            )
            self.assertIsNone(
                server.resolve_access_token(tokens["access_token"], "aics.admin")
            )
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                "UPDATE oauth_tokens SET expires_at=? WHERE token_hash=?",
                (int(time.time()) - 1, server.token_hash(tokens["access_token"])),
            )
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            self.assertIsNone(server.resolve_access_token(tokens["access_token"]))
        integrations = admin.request("/api/account/integrations")[1]["integrations"]
        self.assertEqual(integrations[0]["clientName"], "MCP test")
        self.assertEqual(
            integrations[0]["scopes"], ["aics.read", "aics.write"]
        )

        status, rotated = form_post(
            "/oauth/token",
            {
                "grant_type": "refresh_token",
                "client_id": registered["client_id"],
                "refresh_token": tokens["refresh_token"],
                "scope": "aics.read",
            },
        )
        self.assertEqual(status, 200, rotated)
        self.assertEqual(rotated["scope"], "aics.read")
        self.assertNotEqual(rotated["refresh_token"], tokens["refresh_token"])
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            self.assertIsNotNone(
                server.resolve_access_token(rotated["access_token"], "aics.read")
            )
            self.assertIsNone(
                server.resolve_access_token(rotated["access_token"], "aics.write")
            )
        self.assertEqual(
            form_post(
                "/oauth/token",
                {
                    "grant_type": "refresh_token",
                    "client_id": registered["client_id"],
                    "refresh_token": tokens["refresh_token"],
                },
            )[0],
            400,
        )
        grant_id = integrations[0]["id"]
        self.assertEqual(
            admin.request(
                "/api/account/integrations/" + str(grant_id), method="DELETE"
            )[0],
            200,
        )
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            self.assertIsNone(
                server.resolve_access_token(rotated["access_token"])
            )
        with sqlite3.connect(self.database_path) as database:
            for index in range(4):
                database.execute(
                    """
                    INSERT INTO oauth_flows
                        (flow_hash, request_data, created_at, expires_at)
                    VALUES (?, '{}', ?, ?)
                    """,
                    ("capacity-flow-" + str(index), now, now + 300),
                )
            flows_before = database.execute(
                "SELECT COUNT(*) FROM oauth_flows"
            ).fetchone()[0]
        status, payload, _ = admin.request("/oauth/authorize?" + query)
        self.assertEqual(status, 503, payload)
        with sqlite3.connect(self.database_path) as database:
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM oauth_flows").fetchone()[0],
                flows_before,
            )
        with sqlite3.connect(self.database_path) as database:
            client_count = database.execute(
                "SELECT COUNT(*) FROM oauth_clients"
            ).fetchone()[0]
            for index in range(12 - client_count):
                database.execute(
                    """
                    INSERT INTO oauth_clients
                        (client_id, client_name, redirect_uris, created_at)
                    VALUES (?, 'Capacity test', '[]', ?)
                    """,
                    ("capacity-client-" + str(index), int(time.time())),
                )
            clients_before = database.execute(
                "SELECT COUNT(*) FROM oauth_clients"
            ).fetchone()[0]
        status, payload, _ = client.request(
            "/oauth/register", method="POST", payload=registration
        )
        self.assertEqual(status, 503, payload)
        with sqlite3.connect(self.database_path) as database:
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0],
                clients_before,
            )

    def test_19a_read_only_refresh_token_rejects_every_mcp_mutation(self):
        """Keep a narrowed refresh token read-only through the actual MCP transport."""
        admin = self.admin_client()
        revision_before = admin.request("/api/workspace")[1]["revision"]
        now = int(time.time())
        client_id = "read-only-refresh-client"
        raw_refresh = "test-refresh-" + secrets.token_urlsafe(40)
        with sqlite3.connect(self.database_path) as database:
            user_id = database.execute(
                "SELECT id FROM users WHERE username=?", (ADMIN_USERNAME,)
            ).fetchone()[0]
            database.execute(
                """
                INSERT OR REPLACE INTO oauth_clients
                    (client_id, client_name, redirect_uris, created_at)
                VALUES (?, 'Read-only refresh test', '[]', ?)
                """,
                (client_id, now),
            )
            database.execute(
                """
                INSERT OR REPLACE INTO oauth_grants
                    (id, user_id, client_id, scopes, created_at, revoked_at)
                VALUES (9002, ?, ?, 'aics.read aics.write', ?, NULL)
                """,
                (user_id, client_id, now),
            )
            database.execute(
                """
                INSERT INTO oauth_tokens
                    (token_hash, grant_id, token_type, family_id, created_at,
                     expires_at, scopes)
                VALUES (?, 9002, 'refresh', 'read-only-family', ?, ?,
                        'aics.read aics.write')
                """,
                (server.token_hash(raw_refresh), now, now + 3600),
            )

        request = urllib.request.Request(
            self.base_url + "/oauth/token",
            data=urllib.parse.urlencode(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": raw_refresh,
                    "scope": "aics.read",
                }
            ).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            narrowed = json.loads(response.read())
        self.assertEqual(narrowed["scope"], "aics.read")

        def mcp_request(payload, session_id=None):
            """Send an authenticated JSON-RPC request with the narrowed token."""
            headers = {
                "Authorization": "Bearer " + narrowed["access_token"],
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            rpc = urllib.request.Request(
                self.base_url + "/mcp",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            with urllib.request.urlopen(rpc, timeout=10) as response:
                body = response.read()
                return json.loads(body) if body else {}, response.headers.get(
                    "Mcp-Session-Id"
                )

        initialized, session_id = mcp_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "Read-only test", "version": "1"},
                },
            }
        )
        self.assertIn("result", initialized)
        mcp_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id,
        )
        read_result, _ = mcp_request(
            {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "get_workspace_summary",
                    "arguments": {},
                },
            },
            session_id,
        )
        self.assertIn("result", read_result)

        mutation_calls = {
            "update_project_bible": {
                "project_id": "blocked", "expected_revision": 0,
                "changes": {"logline": "Blocked"},
            },
            "update_episode_planning": {
                "project_id": "blocked", "episode_id": "blocked",
                "expected_revision": 0, "synopsis": "Blocked",
            },
            "replace_episode_shots": {
                "project_id": "blocked", "episode_id": "blocked",
                "expected_revision": 0, "shots": [],
            },
            "update_character_planning": {
                "project_id": "blocked", "character_id": "blocked",
                "expected_revision": 0, "reference_requirements": "Blocked",
            },
            "upsert_project_prompt": {
                "project_id": "blocked", "expected_revision": 0,
                "name": "Blocked", "category": "style", "body": "Blocked",
            },
            "update_production_gates": {
                "project_id": "blocked", "expected_revision": 0,
                "gates": [{"id": "blocked", "name": "Blocked"}],
            },
            "archive_content_record": {
                "project_id": "blocked", "record_type": "project",
                "record_id": "blocked", "expected_revision": 0,
            },
            "restore_content_record": {
                "project_id": "blocked", "record_type": "project",
                "record_id": "blocked", "expected_revision": 0,
            },
            "delete_project": {
                "project_id": "blocked", "expected_revision": 0,
                "confirmation": "Blocked",
            },
            "delete_episode": {
                "project_id": "blocked", "episode_id": "blocked",
                "expected_revision": 0, "confirmation": "Blocked",
            },
            "delete_character": {
                "project_id": "blocked", "character_id": "blocked",
                "expected_revision": 0, "confirmation": "Blocked",
            },
            "delete_project_prompt": {
                "project_id": "blocked", "prompt_id": "blocked",
                "expected_revision": 0, "confirmation": "Blocked",
            },
            "delete_episode_shot": {
                "project_id": "blocked", "episode_id": "blocked",
                "shot_id": "blocked", "expected_revision": 0,
                "confirmation": "Blocked",
            },
            "delete_production_gate": {
                "project_id": "blocked", "gate_id": "blocked",
                "expected_revision": 0, "confirmation": "Blocked",
            },
        }
        for request_id, (name, arguments) in enumerate(
            mutation_calls.items(), start=3
        ):
            denied, _ = mcp_request(
                {
                    "jsonrpc": "2.0", "id": request_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
                session_id,
            )
            self.assertIn("insufficient_scope", json.dumps(denied), name)
        self.assertEqual(
            admin.request("/api/workspace")[1]["revision"], revision_before
        )

    def test_19_mcp_actual_http_transport_and_bounded_tool_catalog(self):
        """Initialize over Streamable HTTP and call representative read and write tools."""
        self.assertEqual(
            TestClient(self.base_url).request("/mcp", method="POST", payload={})[0],
            401,
        )
        admin = self.admin_client()
        current = admin.request("/api/workspace")[1]
        transport_data = {
            "projects": [{
                "id": "transport-project", "title": "Transport project",
                "bible": {"logline": "Before transport write"},
                "episodes": [], "characters": [], "prompts": [], "gates": [],
            }],
            "activeId": "transport-project",
        }
        status, saved, _ = admin.request(
            "/api/workspace", method="PUT",
            payload={"revision": current["revision"], "data": transport_data},
        )
        self.assertEqual(status, 200, saved)
        transport_revision = saved["revision"]
        with sqlite3.connect(self.database_path) as database:
            database.row_factory = sqlite3.Row
            user_id = database.execute(
                "SELECT id FROM users WHERE username=?", (ADMIN_USERNAME,)
            ).fetchone()["id"]
            client_id = "transport-test-client"
            now = int(time.time())
            database.execute(
                "INSERT OR REPLACE INTO oauth_clients VALUES (?, ?, ?, ?)",
                (client_id, "Transport test", json.dumps([self.base_url + "/callback"]), now),
            )
            database.execute(
                """
                INSERT OR REPLACE INTO oauth_grants
                    (id, user_id, client_id, scopes, created_at, revoked_at)
                VALUES (9001, ?, ?, 'aics.read aics.write', ?, NULL)
                """,
                (user_id, client_id, now),
            )
            raw_token = "test-access-" + secrets.token_urlsafe(40)
            database.execute(
                """
                INSERT INTO oauth_tokens
                    (token_hash, grant_id, token_type, family_id, created_at, expires_at)
                VALUES (?, 9001, 'access', 'test-family', ?, ?)
                """,
                (server.token_hash(raw_token), now, now + 3600),
            )

        def mcp_request(payload, session_id=None):
            """Send one JSON-RPC request through the public MCP transport."""
            headers = {
                "Authorization": "Bearer " + raw_token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            request = urllib.request.Request(
                self.base_url + "/mcp",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            response = urllib.request.urlopen(request, timeout=10)
            raw = response.read()
            return (
                json.loads(raw) if raw else {},
                response.headers.get("Mcp-Session-Id"),
            )

        initialized, session_id = mcp_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "AICS tests", "version": "1"},
                },
            }
        )
        self.assertIn("result", initialized)
        mcp_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_id,
        )
        listed, _ = mcp_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id,
        )
        names = {item["name"] for item in listed["result"]["tools"]}
        self.assertIn("get_workspace_summary", names)
        expected_tools = {
            "get_workspace_summary", "list_projects", "get_project",
            "get_project_bible", "list_episodes", "get_episode",
            "list_characters", "get_character", "list_prompts",
            "list_production_gates", "update_project_bible",
            "update_episode_planning", "replace_episode_shots",
            "update_character_planning", "upsert_project_prompt",
            "update_production_gates", "archive_content_record",
            "restore_content_record", "delete_project", "delete_episode",
            "delete_character", "delete_project_prompt",
            "delete_episode_shot", "delete_production_gate",
        }
        self.assertTrue(expected_tools.issubset(names))
        delete_tool = next(
            item for item in listed["result"]["tools"]
            if item["name"] == "delete_project"
        )
        self.assertTrue(delete_tool["annotations"]["destructiveHint"])
        self.assertNotIn("delete_user", names)
        self.assertFalse(any("admin" in name or "deployment" in name for name in names))
        called, _ = mcp_request(
            {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "get_workspace_summary", "arguments": {}},
            },
            session_id,
        )
        self.assertIn("result", called)
        written, _ = mcp_request(
            {
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {
                    "name": "update_project_bible",
                    "arguments": {
                        "project_id": "transport-project",
                        "expected_revision": transport_revision,
                        "changes": {"logline": "Written through MCP transport"},
                    },
                },
            },
            session_id,
        )
        self.assertIn("result", written)
        project = admin.request("/api/workspace")[1]["data"]["projects"][0]
        self.assertEqual(
            project["bible"]["logline"], "Written through MCP transport"
        )

    def test_20_mcp_service_isolation_conflicts_preservation_and_limits(self):
        """Keep direct MCP operations scoped, revisioned, partial, and bounded."""
        self.reset_regular_users()
        self.set_registration(True)
        first = TestClient(self.base_url)
        second = TestClient(self.base_url)
        self.assertEqual(
            first.register("mcpalice", "MCP Alice", "mcp-alice-password")[0],
            201,
        )
        self.assertEqual(
            second.register("mcpbob", "MCP Bob", "mcp-bob-password")[0],
            201,
        )
        first_data = {
            "projects": [{
                "id": "alice-project", "title": "Alice project",
                "description": "Keep this description",
                "bible": {"logline": "Old logline"},
                "episodes": [{
                    "id": "EP01", "title": "Pilot", "hook": "Keep hook",
                    "script": "Keep script", "synopsis": "", "beats": "",
                    "shots": [{
                        "id": "shot-a", "promptId": "prompt-a",
                        "imagePrompt": "Frozen prompt snapshot",
                    }],
                }],
                "characters": [{
                    "id": "alice-cast", "name": "Alice cast",
                    "look": "Keep appearance",
                }],
                "prompts": [{
                    "id": "prompt-a", "name": "Alice style",
                    "category": "style", "body": "Reusable prompt",
                }],
                "gates": [{"id": "gate-a", "name": "Manual review", "done": False}],
            }, {
                "id": "cascade-project", "title": "Cascade project",
                "episodes": [{
                    "id": "cascade-episode", "title": "Cascade episode",
                    "shots": [{"id": "cascade-shot", "imagePrompt": "Snapshot"}],
                }],
                "characters": [{"id": "cascade-cast", "name": "Cascade cast"}],
                "prompts": [{"id": "cascade-prompt", "name": "Cascade prompt"}],
                "gates": [{"id": "cascade-gate", "name": "Cascade gate"}],
            }],
            "activeId": "alice-project",
        }
        second_data = {
            "projects": [{
                "id": "bob-project", "title": "Bob private project",
                "episodes": [], "characters": [], "prompts": [], "gates": [],
            }],
            "activeId": "bob-project",
        }
        self.assertEqual(
            first.request(
                "/api/workspace", method="PUT",
                payload={"revision": 0, "data": first_data},
            )[0],
            200,
        )
        self.assertEqual(
            second.request(
                "/api/workspace", method="PUT",
                payload={"revision": 0, "data": second_data},
            )[0],
            200,
        )
        with sqlite3.connect(self.database_path) as database:
            alice_id = database.execute(
                "SELECT id FROM users WHERE username='mcpalice'"
            ).fetchone()[0]
            bob_id = database.execute(
                "SELECT id FROM users WHERE username='mcpbob'"
            ).fetchone()[0]
            database.executemany(
                """
                INSERT INTO character_images
                    (storage_id, user_id, character_id, mime_type, byte_size, created_at)
                VALUES (?, ?, ?, 'image/png', 3, ?)
                """,
                (
                    ("alice-image", alice_id, "alice-cast", int(time.time())),
                    ("cascade-image", alice_id, "cascade-cast", int(time.time())),
                ),
            )
        image_directory = self.database_path.parent / "images" / str(alice_id)
        image_directory.mkdir(parents=True, exist_ok=True)
        (image_directory / "alice-image").write_bytes(b"png")
        (image_directory / "cascade-image").write_bytes(b"png")
        with unittest.mock.patch.object(server, "DB_PATH", self.database_path):
            alice_projects = mcp_service.list_projects(alice_id)["projects"]
            self.assertEqual(
                [item["id"] for item in alice_projects],
                ["alice-project", "cascade-project"],
            )
            self.assertNotIn("Alice", json.dumps(mcp_service.list_projects(bob_id)))
            saved = mcp_service.update_project_bible(
                alice_id, "alice-project", 1, {"logline": "New logline"}
            )
            self.assertEqual(saved["revision"], 2)
            episode = mcp_service.get_episode(
                alice_id, "alice-project", "EP01"
            )["episode"]
            self.assertEqual(episode["hook"], "Keep hook")
            self.assertEqual(episode["script"], "Keep script")
            with self.assertRaises(mcp_service.ServiceError) as conflict:
                mcp_service.update_episode_planning(
                    alice_id, "alice-project", "EP01", 1, synopsis="Stale"
                )
            self.assertEqual(conflict.exception.code, "revision_conflict")
            with self.assertRaises(mcp_service.ServiceError) as oversized:
                mcp_service.update_episode_planning(
                    alice_id, "alice-project", "EP01", 2,
                    synopsis="x" * (mcp_service.MAX_TEXT + 1),
                )
            self.assertEqual(oversized.exception.code, "invalid_input")
            archived = mcp_service.set_archive_state(
                alice_id, "alice-project", "episode", "EP01", 2, True
            )
            restored = mcp_service.set_archive_state(
                alice_id, "alice-project", "episode", "EP01",
                archived["revision"], False,
            )
            self.assertGreater(restored["revision"], archived["revision"])
            revision = restored["revision"]
            with self.assertRaises(mcp_service.ServiceError) as mismatch:
                mcp_service.delete_episode(
                    alice_id, "alice-project", "EP01", revision, "pilot"
                )
            self.assertEqual(mismatch.exception.code, "confirmation_mismatch")
            with self.assertRaises(mcp_service.ServiceError) as isolated:
                mcp_service.delete_project(
                    bob_id, "alice-project", 1, "Alice project"
                )
            self.assertEqual(isolated.exception.code, "not_found")

            deleted_prompt = mcp_service.delete_project_prompt(
                alice_id, "alice-project", "prompt-a", revision, "Alice style"
            )
            revision = deleted_prompt["revision"]
            preserved = mcp_service.get_episode(
                alice_id, "alice-project", "EP01"
            )["episode"]["shots"][0]
            self.assertEqual(preserved["imagePrompt"], "Frozen prompt snapshot")
            self.assertEqual(deleted_prompt["receipt"]["shotSnapshotsPreserved"], True)

            deleted_shot = mcp_service.delete_episode_shot(
                alice_id, "alice-project", "EP01", "shot-a",
                revision, "shot-a",
            )
            revision = deleted_shot["revision"]
            deleted_gate = mcp_service.delete_production_gate(
                alice_id, "alice-project", "gate-a", revision, "Manual review"
            )
            revision = deleted_gate["revision"]
            deleted_character = mcp_service.delete_character(
                alice_id, "alice-project", "alice-cast", revision, "Alice cast"
            )
            revision = deleted_character["revision"]
            self.assertEqual(deleted_character["receipt"]["privateImagesDeleted"], 1)
            self.assertFalse((image_directory / "alice-image").exists())
            deleted_episode = mcp_service.delete_episode(
                alice_id, "alice-project", "EP01", revision, "Pilot"
            )
            revision = deleted_episode["revision"]
            self.assertEqual(deleted_episode["receipt"]["shotsDeleted"], 0)

            cascade = mcp_service.delete_project(
                alice_id, "cascade-project", revision, "Cascade project"
            )
            self.assertEqual(cascade["receipt"]["episodesDeleted"], 1)
            self.assertEqual(cascade["receipt"]["charactersDeleted"], 1)
            self.assertEqual(cascade["receipt"]["promptsDeleted"], 1)
            self.assertEqual(cascade["receipt"]["shotsDeleted"], 1)
            self.assertEqual(cascade["receipt"]["gatesDeleted"], 1)
            self.assertEqual(cascade["receipt"]["privateImagesDeleted"], 1)
            self.assertFalse((image_directory / "cascade-image").exists())
            self.assertEqual(
                [item["id"] for item in mcp_service.list_projects(alice_id)["projects"]],
                ["alice-project"],
            )
            self.assertEqual(
                [item["id"] for item in mcp_service.list_projects(bob_id)["projects"]],
                ["bob-project"],
            )
            with sqlite3.connect(self.database_path) as database:
                self.assertEqual(
                    database.execute(
                        "SELECT COUNT(*) FROM character_images WHERE user_id=?",
                        (alice_id,),
                    ).fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
