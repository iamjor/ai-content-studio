"""Multi-user AI Content Studio API and static host using Python's standard library."""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP_NAME = "AI Content Studio"
APP_VERSION = "0.2.0"
ROOT = Path(__file__).parent.resolve()
STATIC = ROOT / "dist"
DB_PATH = Path(os.environ.get("AICS_DB_PATH", "/data/studio.sqlite3"))
MAX_BYTES = 2_000_000
AUTH_MAX_BYTES = 4_096
PASSWORD_ITERATIONS = 600_000
LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_SCOPE_LIMIT = 4_096
REGISTRATION_ATTEMPT_LIMIT = max(
    1, int(os.environ.get("AICS_REGISTRATION_ATTEMPT_LIMIT", "5"))
)
MAX_USERS = max(1, int(os.environ.get("AICS_MAX_USERS", "100")))
SESSION_SECONDS = int(
    os.environ.get(
        "AICS_SESSION_SECONDS",
        str(int(os.environ.get("AICS_SESSION_HOURS", "12")) * 60 * 60),
    )
)
COOKIE_SECURE = os.environ.get("AICS_COOKIE_SECURE", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
REGISTRATION_DEFAULT = os.environ.get(
    "AICS_REGISTRATION_ENABLED", "0"
).strip().lower() in {"1", "true", "yes"}
ADMIN_USERNAME = os.environ.get(
    "AICS_ADMIN_USERNAME", os.environ.get("AICS_USERNAME", "")
).strip()
ADMIN_PASSWORD = os.environ.get(
    "AICS_ADMIN_PASSWORD", os.environ.get("AICS_PASSWORD", "")
)
ADMIN_DISPLAY_NAME = os.environ.get(
    "AICS_ADMIN_DISPLAY_NAME", ADMIN_USERNAME or "Studio owner"
).strip()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def parse_trusted_proxy_networks(value):
    """Parse explicitly trusted proxy CIDRs or fail closed on bad configuration."""
    networks = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as error:
            raise RuntimeError(
                "AICS_TRUSTED_PROXY_NETWORKS contains an invalid network"
            ) from error
    return tuple(networks)


TRUSTED_PROXY_NETWORKS = parse_trusted_proxy_networks(
    os.environ.get("AICS_TRUSTED_PROXY_NETWORKS", "")
)


def connect():
    """Open a SQLite connection with integrity and contention protections enabled."""
    database = sqlite3.connect(DB_PATH, timeout=10)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys=ON")
    database.execute("PRAGMA busy_timeout=10000")
    return database


def hash_password(password):
    """Return a salted PBKDF2-SHA256 password record suitable for database storage."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password, encoded):
    """Compare a supplied password with a stored PBKDF2 record in constant time."""
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


DUMMY_PASSWORD_HASH = hash_password("timing-only-password-value")


def validate_username(username):
    """Accept predictable usernames that are safe to display and query."""
    return isinstance(username, str) and bool(USERNAME_PATTERN.fullmatch(username))


def validate_password(password):
    """Enforce the password policy without logging or retaining plaintext values."""
    return isinstance(password, str) and 12 <= len(password) <= 256


def validate_display_name(display_name):
    """Accept a non-empty human-readable name with a conservative length limit."""
    return (
        isinstance(display_name, str)
        and bool(display_name.strip())
        and len(display_name.strip()) <= 80
    )


def get_setting(database, key, default=None):
    """Read one application setting, returning a supplied default when absent."""
    row = database.execute(
        "SELECT value FROM app_settings WHERE key=?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(database, key, value):
    """Insert or replace one application setting inside the caller's transaction."""
    database.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )


def registration_enabled(database):
    """Return the persisted registration policy, which defaults to disabled."""
    return get_setting(database, "registration_enabled", "0") == "1"


def setup():
    """Create the multi-user schema and safely adopt the legacy owner workspace."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as database:
        database.execute("PRAGMA journal_mode=WAL").fetchone()
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                theme TEXT NOT NULL DEFAULT 'dark' CHECK(theme IN ('dark', 'light')),
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                scope_hash TEXT PRIMARY KEY,
                failures INTEGER NOT NULL,
                window_started INTEGER NOT NULL,
                blocked_until INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        if get_setting(database, "registration_enabled") is None:
            set_setting(
                database,
                "registration_enabled",
                "1" if REGISTRATION_DEFAULT else "0",
            )
        set_setting(database, "schema_version", "2")

        admin = database.execute(
            "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"
        ).fetchone()
        if not admin:
            if not validate_username(ADMIN_USERNAME) or not validate_password(
                ADMIN_PASSWORD
            ):
                raise RuntimeError(
                    "Set AICS_ADMIN_USERNAME and a 12+ character "
                    "AICS_ADMIN_PASSWORD for the initial admin"
                )
            if not validate_display_name(ADMIN_DISPLAY_NAME):
                raise RuntimeError("Set a valid AICS_ADMIN_DISPLAY_NAME")
            now = int(time.time())
            cursor = database.execute(
                """
                INSERT INTO users
                    (username, display_name, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', ?, ?)
                """,
                (
                    ADMIN_USERNAME,
                    ADMIN_DISPLAY_NAME,
                    hash_password(ADMIN_PASSWORD),
                    now,
                    now,
                ),
            )
            admin_id = cursor.lastrowid
        else:
            admin_id = admin["id"]

        legacy_table = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace'"
        ).fetchone()
        if legacy_table:
            legacy = database.execute(
                "SELECT revision, data FROM workspace WHERE id=1"
            ).fetchone()
            if legacy:
                database.execute(
                    """
                    INSERT OR IGNORE INTO workspaces (user_id, revision, data)
                    VALUES (?, ?, ?)
                    """,
                    (admin_id, legacy["revision"], legacy["data"]),
                )
                set_setting(database, "legacy_workspace_migrated", str(admin_id))


def session_token_hash(token):
    """Hash a raw session token so a database disclosure cannot replay it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(database, user_id):
    """Create a fixed-lifetime server-side session and return its browser values."""
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = int(time.time())
    expires_at = now + SESSION_SECONDS
    database.execute(
        """
        INSERT INTO sessions
            (token_hash, user_id, csrf_token, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_token_hash(raw_token), user_id, csrf_token, now, expires_at),
    )
    return raw_token, csrf_token, expires_at


def public_user(row):
    """Serialize account fields that are safe to return to an authenticated client."""
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
        "active": bool(row["is_active"]),
        "theme": row["theme"],
    }


class Handler(BaseHTTPRequestHandler):
    """Serve static assets and the authenticated JSON API."""

    server_version = "AIContentStudio"
    sys_version = ""

    def log_message(self, message_format, *args):
        """Log method and status without headers, cookies, request bodies, or secrets."""
        safe_path = urlsplit(self.path).path
        print(
            f'"{self.command} {safe_path}" '
            f"{args[1] if len(args) > 1 else '-'}"
        )

    def reply(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        """Send a response with common browser security headers."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        if COOKIE_SECURE:
            self.send_header(
                "Strict-Transport-Security", "max-age=31536000"
            )
        items = extra.items() if isinstance(extra, dict) else (extra or [])
        for key, value in items:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status, value, extra=None):
        """Encode and send one JSON response."""
        self.reply(status, json.dumps(value).encode("utf-8"), extra=extra)

    def read_json(self, max_bytes=MAX_BYTES):
        """Read a size-limited JSON object or raise ValueError for invalid input."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid content length") from error
        if length <= 0 or length > max_bytes:
            raise ValueError("Invalid request size")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def same_origin_request(self):
        """Reject browser state changes that explicitly originate off-site."""
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        host = self.headers.get("Host", "").lower()
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host

    def cookie_token(self):
        """Extract the raw session cookie from the request."""
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("AICS_SESSION")
        return morsel.value if morsel else ""

    def current_session(self):
        """Load the active user and session, deleting expired session records."""
        if hasattr(self, "_session_cache"):
            return self._session_cache
        token = self.cookie_token()
        if not token:
            self._session_cache = None
            return None
        now = int(time.time())
        with connect() as database:
            row = database.execute(
                """
                SELECT
                    s.token_hash, s.csrf_token, s.expires_at,
                    u.id, u.username, u.display_name, u.role, u.is_active, u.theme
                FROM sessions s
                JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=?
                """,
                (session_token_hash(token),),
            ).fetchone()
            if not row or not row["is_active"] or row["expires_at"] <= now:
                if row:
                    database.execute(
                        "DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],)
                    )
                self._session_cache = None
                return None
        self._session_cache = row
        return row

    def session_cookie(self, token, max_age):
        """Build the hardened browser cookie used for session transport."""
        parts = [
            f"AICS_SESSION={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={max_age}",
        ]
        if COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def require_session(self, admin=False, csrf=False):
        """Require an active session, optional admin role, and optional CSRF token."""
        session = self.current_session()
        if not session:
            self.json_reply(401, {"error": "Your session has expired. Sign in again."})
            return None
        if admin and session["role"] != "admin":
            self.json_reply(403, {"error": "Administrator access is required."})
            return None
        if csrf:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not supplied or not hmac.compare_digest(
                supplied, session["csrf_token"]
            ):
                self.json_reply(403, {"error": "The request could not be verified."})
                return None
        return session

    def session_payload(self, session):
        """Build the authenticated bootstrap response for the current browser."""
        with connect() as database:
            allow_registration = registration_enabled(database)
        return {
            "authenticated": True,
            "user": public_user(session),
            "csrfToken": session["csrf_token"],
            "expiresAt": session["expires_at"],
            "registrationEnabled": allow_registration,
            "appName": APP_NAME,
            "version": APP_VERSION,
        }

    def static_response(self, path):
        """Serve a known public frontend asset and reject arbitrary file paths."""
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/seed.js": ("seed.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        }
        asset = files.get(path)
        if not asset:
            return False
        filename, content_type = asset
        self.reply(200, (STATIC / filename).read_bytes(), content_type)
        return True

    def do_GET(self):
        """Route public assets, session bootstrap, and authenticated reads."""
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self.json_reply(200, {"ok": True})
        if self.static_response(path):
            return None
        if path == "/api/session":
            session = self.current_session()
            if session:
                return self.json_reply(200, self.session_payload(session))
            with connect() as database:
                allow_registration = registration_enabled(database)
            return self.json_reply(
                200,
                {
                    "authenticated": False,
                    "registrationEnabled": allow_registration,
                    "appName": APP_NAME,
                    "version": APP_VERSION,
                },
            )

        session = self.require_session(
            admin=path.startswith("/api/admin/")
        )
        if not session:
            return None
        if path == "/api/workspace":
            return self.get_workspace(session)
        if path == "/api/account":
            return self.json_reply(200, {"user": public_user(session)})
        if path == "/api/admin/users":
            return self.get_users()
        if path == "/api/admin/settings":
            with connect() as database:
                enabled = registration_enabled(database)
            return self.json_reply(200, {"registrationEnabled": enabled})
        return self.json_reply(404, {"error": "Not found"})

    def do_POST(self):
        """Route login, registration, and logout requests."""
        if not self.same_origin_request():
            return self.json_reply(403, {"error": "Cross-site request rejected."})
        path = urlsplit(self.path).path
        if path == "/api/login":
            return self.login()
        if path == "/api/register":
            return self.register()
        if path == "/api/logout":
            session = self.require_session(csrf=True)
            if not session:
                return None
            with connect() as database:
                database.execute(
                    "DELETE FROM sessions WHERE token_hash=?",
                    (session["token_hash"],),
                )
            return self.json_reply(
                200,
                {"ok": True},
                [("Set-Cookie", self.session_cookie("", 0))],
            )
        return self.json_reply(404, {"error": "Not found"})

    def do_PUT(self):
        """Route authenticated state changes protected by a CSRF token."""
        if not self.same_origin_request():
            return self.json_reply(403, {"error": "Cross-site request rejected."})
        path = urlsplit(self.path).path
        session = self.require_session(
            admin=path.startswith("/api/admin/"), csrf=True
        )
        if not session:
            return None
        if path == "/api/workspace":
            return self.put_workspace(session)
        if path == "/api/account":
            return self.update_account(session)
        if path == "/api/admin/settings":
            return self.update_admin_settings()
        if path.startswith("/api/admin/users/"):
            return self.update_user(path)
        return self.json_reply(404, {"error": "Not found"})

    def login_client_address(self):
        """Return a safe login source, honoring Cloudflare only from trusted peers."""
        peer_text = self.client_address[0]
        try:
            peer = ipaddress.ip_address(peer_text)
        except ValueError:
            return peer_text
        if any(peer in network for network in TRUSTED_PROXY_NETWORKS):
            forwarded_text = self.headers.get("CF-Connecting-IP", "").strip()
            try:
                return ipaddress.ip_address(forwarded_text).compressed
            except ValueError:
                pass
        return peer.compressed

    def attempt_scope(self, purpose):
        """Hash a request purpose and safe client address for bounded throttling."""
        value = purpose + "\0" + self.login_client_address()
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def attempt_blocked(self, database, scope, now):
        """Return remaining block seconds, clearing an expired attempt window."""
        row = database.execute(
            "SELECT * FROM login_attempts WHERE scope_hash=?", (scope,)
        ).fetchone()
        if not row:
            return 0
        if row["blocked_until"] > now:
            return row["blocked_until"] - now
        if now - row["window_started"] >= LOGIN_WINDOW_SECONDS:
            database.execute(
                "DELETE FROM login_attempts WHERE scope_hash=?", (scope,)
            )
        return 0

    def record_attempt(self, database, scope, now, limit):
        """Record an attempt and return block seconds when its limit is reached."""
        row = database.execute(
            "SELECT * FROM login_attempts WHERE scope_hash=?", (scope,)
        ).fetchone()
        if not row or now - row["window_started"] >= LOGIN_WINDOW_SECONDS:
            failures = 1
            window_started = now
        else:
            failures = row["failures"] + 1
            window_started = row["window_started"]
        blocked_until = now + LOGIN_LOCK_SECONDS if failures >= limit else 0
        database.execute(
            """
            INSERT INTO login_attempts
                (scope_hash, failures, window_started, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(scope_hash) DO UPDATE SET
                failures=excluded.failures,
                window_started=excluded.window_started,
                blocked_until=excluded.blocked_until
            """,
            (scope, failures, window_started, blocked_until),
        )
        return max(0, blocked_until - now)

    def prune_attempts(self, database, now):
        """Expire stale throttle scopes and cap storage created by changing inputs."""
        database.execute(
            """
            DELETE FROM login_attempts
            WHERE blocked_until<=? AND window_started<?
            """,
            (now, now - LOGIN_WINDOW_SECONDS),
        )
        database.execute(
            """
            DELETE FROM login_attempts
            WHERE scope_hash IN (
                SELECT scope_hash FROM login_attempts
                ORDER BY
                    blocked_until DESC, failures DESC,
                    window_started DESC, scope_hash
                LIMIT -1 OFFSET ?
            )
            """,
            (LOGIN_SCOPE_LIMIT,),
        )

    def reserve_attempt(self, database, scope, now, limit):
        """Atomically reserve one attempt before expensive or sensitive work."""
        database.execute("BEGIN IMMEDIATE")
        self.prune_attempts(database, now)
        remaining = self.attempt_blocked(database, scope, now)
        if remaining:
            return False, remaining, 0
        block_after_failure = self.record_attempt(
            database, scope, now, limit
        )
        return True, 0, block_after_failure

    def release_login_attempt(self, database, scope):
        """Release a successful reservation without erasing concurrent failures."""
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT failures FROM login_attempts WHERE scope_hash=?", (scope,)
        ).fetchone()
        if not row:
            return
        failures = max(0, row["failures"] - 1)
        if failures == 0:
            database.execute(
                "DELETE FROM login_attempts WHERE scope_hash=?", (scope,)
            )
            return
        blocked_until = (
            0
            if failures < LOGIN_LIMIT
            else int(time.time()) + LOGIN_LOCK_SECONDS
        )
        database.execute(
            """
            UPDATE login_attempts
            SET failures=?, blocked_until=?
            WHERE scope_hash=?
            """,
            (failures, blocked_until, scope),
        )

    def login(self):
        """Authenticate credentials, enforce throttling, and issue a session cookie."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Enter a username and password."})
        username = value.get("username", "")
        password = value.get("password", "")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or not username
            or len(username) > 40
            or not password
            or len(password) > 256
        ):
            return self.json_reply(400, {"error": "Enter a username and password."})
        scope = self.attempt_scope("login")
        now = int(time.time())
        with connect() as database:
            accepted, remaining, block_after_failure = self.reserve_attempt(
                database, scope, now, LOGIN_LIMIT
            )
            if not accepted:
                return self.json_reply(
                    429,
                    {"error": "Too many attempts. Try again later."},
                    {"Retry-After": str(remaining)},
                )
            user = database.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone()

        encoded = user["password_hash"] if user else DUMMY_PASSWORD_HASH
        password_matches = verify_password(password, encoded)
        valid = bool(user and user["is_active"] and password_matches)
        if not valid:
            status = 429 if block_after_failure else 401
            message = (
                "Too many attempts. Try again later."
                if block_after_failure
                else "Invalid username or password."
            )
            headers = (
                {"Retry-After": str(block_after_failure)}
                if block_after_failure
                else None
            )
            return self.json_reply(status, {"error": message}, headers)

        with connect() as database:
            self.release_login_attempt(database, scope)
            database.execute(
                "DELETE FROM sessions WHERE expires_at<=?", (now,)
            )
            raw_token, csrf_token, expires_at = new_session(
                database, user["id"]
            )
        session = dict(user)
        session.update(
            {
                "token_hash": session_token_hash(raw_token),
                "csrf_token": csrf_token,
                "expires_at": expires_at,
            }
        )
        return self.json_reply(
            200,
            self.session_payload(session),
            [("Set-Cookie", self.session_cookie(raw_token, SESSION_SECONDS))],
        )

    def register(self):
        """Create a regular user only when an administrator enabled registration."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Complete all registration fields."})
        if "role" in value:
            return self.json_reply(400, {"error": "Account roles cannot be requested."})
        username = value.get("username", "")
        display_name = value.get("displayName", "")
        password = value.get("password", "")
        registration_fields = (username, display_name, password)
        if not all(isinstance(item, str) for item in registration_fields):
            return self.json_reply(400, {"error": "Complete all registration fields."})
        username = username.strip()
        display_name = display_name.strip()
        if not validate_username(username):
            return self.json_reply(
                400,
                {"error": "Use 3 to 40 letters, numbers, dots, dashes, or underscores."},
            )
        if not validate_display_name(display_name):
            return self.json_reply(400, {"error": "Enter a display name."})
        if not validate_password(password):
            return self.json_reply(
                400, {"error": "Use a password between 12 and 256 characters."}
            )
        now = int(time.time())
        scope = self.attempt_scope("registration")
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            if not registration_enabled(database):
                return self.json_reply(
                    403, {"error": "Registration is currently closed."}
                )
            user_count = database.execute(
                "SELECT COUNT(*) AS total FROM users"
            ).fetchone()["total"]
            if user_count >= MAX_USERS:
                return self.json_reply(
                    403, {"error": "Account registration has reached its limit."}
                )
            self.prune_attempts(database, now)
            remaining = self.attempt_blocked(database, scope, now)
            if remaining:
                return self.json_reply(
                    429,
                    {"error": "Too many registration attempts. Try again later."},
                    {"Retry-After": str(remaining)},
                )
            self.record_attempt(
                database, scope, now, REGISTRATION_ATTEMPT_LIMIT
            )
        password_hash = hash_password(password)
        try:
            with connect() as database:
                database.execute("BEGIN IMMEDIATE")
                if not registration_enabled(database):
                    return self.json_reply(
                        403, {"error": "Registration is currently closed."}
                    )
                user_count = database.execute(
                    "SELECT COUNT(*) AS total FROM users"
                ).fetchone()["total"]
                if user_count >= MAX_USERS:
                    return self.json_reply(
                        403, {"error": "Account registration has reached its limit."}
                    )
                cursor = database.execute(
                    """
                    INSERT INTO users
                        (username, display_name, password_hash, role, created_at, updated_at)
                    VALUES (?, ?, ?, 'user', ?, ?)
                    """,
                    (
                        username,
                        display_name,
                        password_hash,
                        now,
                        now,
                    ),
                )
                user_id = cursor.lastrowid
                raw_token, csrf_token, expires_at = new_session(
                    database, user_id
                )
                user = database.execute(
                    "SELECT * FROM users WHERE id=?", (user_id,)
                ).fetchone()
        except sqlite3.IntegrityError:
            return self.json_reply(409, {"error": "That username is unavailable."})
        session = dict(user)
        session.update(
            {
                "token_hash": session_token_hash(raw_token),
                "csrf_token": csrf_token,
                "expires_at": expires_at,
            }
        )
        return self.json_reply(
            201,
            self.session_payload(session),
            [("Set-Cookie", self.session_cookie(raw_token, SESSION_SECONDS))],
        )

    def get_workspace(self, session):
        """Return only the workspace belonging to the authenticated user."""
        with connect() as database:
            row = database.execute(
                "SELECT revision, data FROM workspaces WHERE user_id=?",
                (session["id"],),
            ).fetchone()
        value = (
            {"revision": row["revision"], "data": json.loads(row["data"])}
            if row
            else {"revision": 0, "data": None}
        )
        return self.json_reply(200, value)

    def put_workspace(self, session):
        """Save one user's validated workspace with optimistic conflict detection."""
        try:
            value = self.read_json()
            revision, data = value["revision"], value["data"]
            if (
                type(revision) is not int
                or revision < 0
                or not isinstance(data, dict)
                or not isinstance(data.get("projects"), list)
                or not data["projects"]
            ):
                raise ValueError("Invalid workspace")
            if not all(
                isinstance(project, dict)
                and isinstance(project.get("episodes"), list)
                and isinstance(project.get("characters"), list)
                for project in data["projects"]
            ):
                raise ValueError("Invalid projects")
        except (ValueError, KeyError, TypeError):
            return self.json_reply(400, {"error": "Invalid workspace."})
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            if revision == 0:
                result = database.execute(
                    """
                    INSERT OR IGNORE INTO workspaces
                        (user_id, revision, data)
                    VALUES (?, 1, ?)
                    """,
                    (session["id"], json.dumps(data)),
                )
            else:
                result = database.execute(
                    """
                    UPDATE workspaces
                    SET revision=revision+1, data=?
                    WHERE user_id=? AND revision=?
                    """,
                    (json.dumps(data), session["id"], revision),
                )
            if result.rowcount != 1:
                return self.json_reply(
                    409,
                    {
                        "error": (
                            "Workspace changed in another tab or device. "
                            "Reload before editing."
                        )
                    },
                )
        return self.json_reply(200, {"revision": revision + 1})

    def update_account(self, session):
        """Change display name, theme, or password for the current account."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Invalid account update."})
        updates = []
        parameters = []
        if "displayName" in value:
            display_name = value["displayName"]
            if not validate_display_name(display_name):
                return self.json_reply(400, {"error": "Enter a display name."})
            updates.append("display_name=?")
            parameters.append(display_name.strip())
        if "theme" in value:
            if not isinstance(value["theme"], str) or value["theme"] not in {
                "dark",
                "light",
            }:
                return self.json_reply(400, {"error": "Invalid theme."})
            updates.append("theme=?")
            parameters.append(value["theme"])

        new_password = value.get("newPassword")
        if new_password is not None:
            current_password = value.get("currentPassword", "")
            if not isinstance(current_password, str):
                return self.json_reply(
                    400, {"error": "Enter your current password."}
                )
            if not validate_password(new_password):
                return self.json_reply(
                    400,
                    {"error": "Use a password between 12 and 256 characters."},
                )
            with connect() as database:
                user = database.execute(
                    "SELECT password_hash FROM users WHERE id=?",
                    (session["id"],),
                ).fetchone()
            if not verify_password(current_password, user["password_hash"]):
                return self.json_reply(
                    403, {"error": "Current password is incorrect."}
                )
            updates.append("password_hash=?")
            parameters.append(hash_password(new_password))

        if not updates:
            return self.json_reply(400, {"error": "No account changes supplied."})
        updates.append("updated_at=?")
        parameters.append(int(time.time()))
        parameters.append(session["id"])
        with connect() as database:
            database.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id=?",
                parameters,
            )
            user = database.execute(
                "SELECT * FROM users WHERE id=?", (session["id"],)
            ).fetchone()
            if new_password is not None:
                database.execute(
                    "DELETE FROM sessions WHERE user_id=?", (session["id"],)
                )
        if new_password is not None:
            return self.json_reply(
                200,
                {
                    "ok": True,
                    "reauthenticate": True,
                    "message": "Password changed. Sign in again.",
                },
                [("Set-Cookie", self.session_cookie("", 0))],
            )
        return self.json_reply(200, {"ok": True, "user": public_user(user)})

    def get_users(self):
        """List public account metadata for basic administrator management."""
        with connect() as database:
            rows = database.execute(
                """
                SELECT id, username, display_name, role, is_active, theme, created_at
                FROM users
                ORDER BY created_at, id
                """
            ).fetchall()
        users = []
        for row in rows:
            item = public_user(row)
            item["createdAt"] = row["created_at"]
            users.append(item)
        return self.json_reply(200, {"users": users})

    def update_admin_settings(self):
        """Allow administrators to open or close regular-user registration."""
        try:
            value = self.read_json()
        except ValueError:
            return self.json_reply(400, {"error": "Invalid settings update."})
        enabled = value.get("registrationEnabled")
        if type(enabled) is not bool:
            return self.json_reply(
                400, {"error": "Registration setting must be true or false."}
            )
        with connect() as database:
            set_setting(
                database, "registration_enabled", "1" if enabled else "0"
            )
        return self.json_reply(200, {"registrationEnabled": enabled})

    def update_user(self, path):
        """Change a user's role or active state without removing the last admin."""
        try:
            user_id = int(path.rsplit("/", 1)[1])
            value = self.read_json()
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid user update."})
        role = value.get("role")
        active = value.get("active")
        if (
            not isinstance(role, str)
            or role not in {"admin", "user"}
            or type(active) is not bool
        ):
            return self.json_reply(400, {"error": "Invalid user update."})
        with connect() as database:
            target = database.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return self.json_reply(404, {"error": "User not found."})
            removes_active_admin = (
                target["role"] == "admin"
                and target["is_active"]
                and (role != "admin" or not active)
            )
            if removes_active_admin:
                admin_count = database.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM users
                    WHERE role='admin' AND is_active=1
                    """
                ).fetchone()["total"]
                if admin_count <= 1:
                    return self.json_reply(
                        409, {"error": "At least one active admin is required."}
                    )
            database.execute(
                """
                UPDATE users
                SET role=?, is_active=?, updated_at=?
                WHERE id=?
                """,
                (role, 1 if active else 0, int(time.time()), user_id),
            )
            if not active:
                database.execute(
                    "DELETE FROM sessions WHERE user_id=?", (user_id,)
                )
            updated = database.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return self.json_reply(200, {"user": public_user(updated)})


if __name__ == "__main__":
    setup()
    ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("PORT", "8787"))), Handler
    ).serve_forever()
