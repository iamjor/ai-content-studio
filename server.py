"""Multi-user AI Content Studio API and static host using Python's standard library."""

import base64
import hashlib
import hmac
import html
import http.client
import ipaddress
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import time
import zipfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

APP_NAME = "AI Content Studio"
APP_VERSION = "0.4.0"
ROOT = Path(__file__).parent.resolve()
STATIC = ROOT / "dist"
DB_PATH = Path(os.environ.get("AICS_DB_PATH", "/data/studio.sqlite3"))
IMAGE_ROOT_OVERRIDE = os.environ.get("AICS_IMAGE_ROOT", "").strip()
MAX_BYTES = 2_000_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PROMPT_BODY = 120_000
MAX_PROMPT_NOTES = 20_000
MAX_PROMPT_ATTACHMENTS = 20
MAX_PROMPT_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_PROMPT_ATTACHMENT_TOTAL = 100 * 1024 * 1024
AUTH_MAX_BYTES = 4_096
OAUTH_MAX_BYTES = 32_768
OAUTH_CODE_SECONDS = 5 * 60
OAUTH_ACCESS_SECONDS = 60 * 60
OAUTH_REFRESH_SECONDS = 30 * 24 * 60 * 60
OAUTH_SCOPES = {
    "aics.read", "aics.write", "aics.archive", "aics.delete",
}
OAUTH_PUBLIC_WINDOW_SECONDS = 60
OAUTH_REGISTRATION_LIMIT = 10
OAUTH_AUTHORIZATION_LIMIT = 30
OAUTH_SOURCE_LIMIT = 4_096
OAUTH_CLIENT_LIMIT = max(1, int(os.environ.get("AICS_OAUTH_CLIENT_LIMIT", "1000")))
OAUTH_FLOW_LIMIT = max(1, int(os.environ.get("AICS_OAUTH_FLOW_LIMIT", "5000")))
OAUTH_CLIENT_TTL_SECONDS = 30 * 24 * 60 * 60
OAUTH_UI_LOCALES_PATTERN = re.compile(
    r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*"
    r"(?: [A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*)*"
)
DEFAULT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; style-src 'self'; script-src 'self'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
MCP_INTERNAL_PORT = int(os.environ.get("AICS_MCP_INTERNAL_PORT", "8788"))
MCP_DIAGNOSTICS = os.environ.get("AICS_MCP_DIAGNOSTICS", "") == "1"
MCP_FORWARDED_HEADERS = (
    "Authorization",
    "Accept",
    "Content-Type",
    "MCP-Protocol-Version",
    "Mcp-Session-Id",
    "Last-Event-ID",
    "Mcp-Method",
    "Mcp-Name",
)
MCP_FORWARDED_HEADER_NAMES = frozenset(
    name.lower() for name in MCP_FORWARDED_HEADERS
)
MCP_PARAM_HEADER_PREFIX = "mcp-param-"
MCP_HOP_BY_HOP_HEADERS = frozenset({
    "host", "connection", "content-length", "transfer-encoding", "upgrade",
})
MCP_SAFE_METHOD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{0,127}")
MCP_SAFE_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MCP_DIAGNOSTIC_ERROR_LIMIT = 1_024
PUBLIC_BASE_URL = os.environ.get(
    "AICS_PUBLIC_BASE_URL", "http://127.0.0.1:8787"
).rstrip("/")
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
RECOVERY_CODE_COUNT = 8
RECOVERY_LIMIT = 5
RECOVERY_SETUP_SECONDS = 15 * 60
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
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
TOOL_SEEDS = (
    ("ChatGPT", "Writing", "https://chatgpt.com/", "Story bible, scripts, prompts, and optional image references.", ""),
    ("Google Flow", "Video", "https://labs.google/fx/tools/flow/", "Image-to-video experiments. Check current credit and export terms.", ""),
    ("Google AI Studio", "Audio", "https://aistudio.google.com/", "Text-to-speech tests. Verify pronunciation, timing, and current limits.", ""),
    ("CapCut", "Editing", "https://www.capcut.com/", "Assemble clips, effects, music, and captions. Check export licensing.", ""),
    ("Kdenlive", "Editing", "https://kdenlive.org/", "Open-source editing fallback and clean master exports.", ""),
)


def image_root():
    """Return the configured image directory or one beside the active database."""
    return Path(IMAGE_ROOT_OVERRIDE) if IMAGE_ROOT_OVERRIDE else DB_PATH.parent / "images"


def attachment_root():
    """Return the private prompt-attachment directory in persistent storage."""
    return DB_PATH.parent / "prompt-attachments"


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


def is_forwarded_mcp_header(name):
    """Return whether a client header is safe MCP end-to-end metadata."""
    lowered = name.lower()
    if lowered in MCP_HOP_BY_HOP_HEADERS:
        return False
    return (
        lowered in MCP_FORWARDED_HEADER_NAMES
        or lowered.startswith(MCP_PARAM_HEADER_PREFIX)
    )


def forwarded_mcp_headers(headers):
    """Copy client-provided MCP headers without deriving values from the body."""
    return {
        name: value
        for name, value in headers.items()
        if is_forwarded_mcp_header(name)
    }



def filter_mcp_tools_response(request_body, response_body, scopes):
    """Remove tools the current token cannot invoke from tools/list output."""
    try:
        request = json.loads(request_body)
        response = json.loads(response_body)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        return response_body
    if not isinstance(request, dict) or request.get("method") != "tools/list" or not isinstance(response, dict):
        return response_body
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        return response_body
    archive_tools = {"archive_content_record", "restore_content_record"}
    delete_tools = {
        "delete_project", "delete_episode", "delete_character",
        "delete_project_prompt", "delete_episode_shot", "delete_production_gate",
    }
    read_tools = {
        "get_workspace_summary", "list_projects", "get_project", "get_project_bible",
        "list_episodes", "get_episode", "list_characters", "get_character",
        "list_prompts", "list_production_gates",
    }
    allowed = []
    for tool in result["tools"]:
        name = tool.get("name") if isinstance(tool, dict) else ""
        required = (
            "aics.read" if name in read_tools else
            "aics.archive" if name in archive_tools else
            "aics.delete" if name in delete_tools else "aics.write"
        )
        if required in scopes:
            allowed.append(tool)
    result["tools"] = allowed
    return json.dumps(response, separators=(",", ":")).encode("utf-8")
def parse_mcp_diagnostic_request(body):
    """Return safe protocol metadata and values that error text must redact."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        return None, None, ()
    if not isinstance(payload, dict):
        return None, None, ()

    raw_method = payload.get("method")
    method = (
        raw_method
        if isinstance(raw_method, str)
        and MCP_SAFE_METHOD_PATTERN.fullmatch(raw_method)
        else None
    )
    raw_version = None
    params = payload.get("params")
    if method == "initialize" and isinstance(params, dict):
        raw_version = params.get("protocolVersion")
    protocol_version = (
        raw_version
        if isinstance(raw_version, str)
        and MCP_SAFE_VERSION_PATTERN.fullmatch(raw_version)
        else None
    )

    sensitive = []
    pending = [(payload, ())]
    while pending:
        value, path = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                pending.append((item, path + (str(key),)))
        elif isinstance(value, list):
            for item in value:
                pending.append((item, path))
        elif isinstance(value, str) and value:
            approved = path == ("method",) or (
                method == "initialize" and path == ("params", "protocolVersion")
            )
            if not approved:
                sensitive.append(value)
        elif path and path[0] == "params" and isinstance(value, (int, float)):
            sensitive.append(str(value))
    return method, protocol_version, tuple(sensitive)


def sanitize_mcp_diagnostic_text(value, sensitive_values, limit):
    """Bound one internal error field and remove request-derived secrets."""
    if not isinstance(value, str):
        return None
    text = "".join(
        character if 32 <= ord(character) <= 126 else " "
        for character in value
    )
    text = " ".join(text.split())
    for sensitive in sorted(set(sensitive_values), key=len, reverse=True):
        if sensitive:
            text = text.replace(sensitive, "[redacted]")
    text = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [redacted]",
        text,
    )
    text = re.sub(
        r"(?i)\b(authorization|cookie|access[_ -]?token|refresh[_ -]?token|"
        r"oauth[_ -]?code|state|code[_ -]?verifier|code[_ -]?challenge|pkce)"
        r"\b\s*[:=]\s*(?:\"[^\"]*\"|[^\s,;}]+)",
        r"\1=[redacted]",
        text,
    )
    return text[:limit]


def log_mcp_internal_error(headers, body, status, response_body):
    """Emit opt-in MCP failure metadata without request or workspace content."""
    if not MCP_DIAGNOSTICS or status < 400:
        return
    method, protocol_version, sensitive_values = parse_mcp_diagnostic_request(body)
    # Header values are never approved diagnostic fields. Retain them only long
    # enough to redact any value reflected by the internal transport error.
    for name, value in headers.items():
        lowered = name.lower()
        if value and (lowered == "cookie" or is_forwarded_mcp_header(name)):
            sensitive_values += (value,)
            if lowered == "authorization" and value.startswith("Bearer "):
                sensitive_values += (value[7:],)

    error_code = None
    error_message = None
    try:
        payload = json.loads(response_body)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            raw_code = error.get("code")
            if isinstance(raw_code, int) and not isinstance(raw_code, bool):
                error_code = str(raw_code)
            elif isinstance(raw_code, str):
                error_code = sanitize_mcp_diagnostic_text(
                    raw_code, sensitive_values, 64
                )
            remaining = MCP_DIAGNOSTIC_ERROR_LIMIT - len(error_code or "")
            error_message = sanitize_mcp_diagnostic_text(
                error.get("message"), sensitive_values, max(0, remaining)
            )
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        pass

    diagnostic = {
        "correlation_id": secrets.token_hex(16),
        "status": status,
        "accept_present": bool(headers.get("Accept")),
        "content_type_present": bool(headers.get("Content-Type")),
        "mcp_protocol_version_present": bool(
            headers.get("MCP-Protocol-Version")
        ),
        "mcp_session_id_present": bool(headers.get("Mcp-Session-Id")),
        "request_body_bytes": len(body),
    }
    if method is not None:
        diagnostic["jsonrpc_method"] = method
    if protocol_version is not None:
        diagnostic["initialize_protocol_version"] = protocol_version
    if error_code is not None:
        diagnostic["error_code"] = error_code
    if error_message is not None:
        diagnostic["error_message"] = error_message
    print("MCP diagnostic " + json.dumps(diagnostic, sort_keys=True), file=sys.stderr)


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


def validate_https_url(value):
    """Accept only absolute HTTPS URLs with a network host."""
    if not isinstance(value, str) or len(value) > 500:
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def validate_public_base_url(value):
    """Accept HTTPS origins, plus loopback HTTP for local development only."""
    if not isinstance(value, str) or len(value) > 500:
        return False
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    return (
        bool(parsed.netloc)
        and not parsed.username
        and not parsed.path.rstrip("/")
        and not parsed.query
        and not parsed.fragment
        and (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
    )


def validate_redirect_uri(value):
    """Validate an exact OAuth redirect URI without permitting open redirects."""
    if not isinstance(value, str) or len(value) > 1000:
        return False
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc or parsed.fragment or parsed.username:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in {
        "localhost", "127.0.0.1", "::1"
    }


def oauth_redirect_origin(value):
    """Return a CSP-safe origin from an already validated OAuth redirect URI."""
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("Invalid redirect origin")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid redirect origin") from error
    if ":" in hostname:
        if not re.fullmatch(r"[0-9A-Fa-f:.]+", hostname):
            raise ValueError("Invalid redirect origin")
        authority = "[" + hostname + "]"
    else:
        try:
            authority = hostname.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("Invalid redirect origin") from error
        if not re.fullmatch(r"[A-Za-z0-9.-]+", authority):
            raise ValueError("Invalid redirect origin")
    if port is not None:
        authority += ":" + str(port)
    return parsed.scheme.lower() + "://" + authority


def token_hash(token):
    """Hash a high-entropy OAuth secret before database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pkce_challenge(verifier):
    """Return the RFC 7636 S256 challenge for a code verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def parse_scopes(value):
    """Return a validated, normalized OAuth scope string or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("Invalid scope")
    scopes = set(value.split())
    if not scopes or not scopes.issubset(OAUTH_SCOPES):
        raise ValueError("Invalid scope")
    return " ".join(sorted(scopes))


def detect_image_type(data):
    """Return a MIME type only for structurally plausible supported images."""
    if (
        len(data) >= 45
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and int.from_bytes(data[8:12], "big") == 13
        and data[12:16] == b"IHDR"
        and int.from_bytes(data[16:20], "big") > 0
        and int.from_bytes(data[20:24], "big") > 0
        and data[-12:-8] == b"\x00\x00\x00\x00"
        and data[-8:-4] == b"IEND"
    ):
        return "image/png"
    if data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        for marker in (b"\xff\xc0", b"\xff\xc1", b"\xff\xc2"):
            offset = data.find(marker)
            if offset >= 0 and offset + 9 <= len(data):
                height = int.from_bytes(data[offset + 5 : offset + 7], "big")
                width = int.from_bytes(data[offset + 7 : offset + 9], "big")
                if width and height:
                    return "image/jpeg"
    if (
        len(data) >= 20
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
        and int.from_bytes(data[4:8], "little") + 8 == len(data)
        and data[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
        and int.from_bytes(data[16:20], "little") <= len(data) - 20
    ):
        return "image/webp"
    return ""


def generate_recovery_codes():
    """Create eight high-entropy human-readable codes for one-time display."""
    return [secrets.token_hex(12).upper() for _ in range(RECOVERY_CODE_COUNT)]


def hash_recovery_code(code, salt=None):
    """Hash one recovery code with a unique salt for offline resistance."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_recovery_code(code, salt_hex, digest_hex):
    """Compare a supplied recovery code with a stored salted hash."""
    try:
        actual = hashlib.pbkdf2_hmac(
            "sha256", code.strip().upper().encode("utf-8"),
            bytes.fromhex(salt_hex), PASSWORD_ITERATIONS,
        ).hex()
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(actual, digest_hex)


def detect_prompt_attachment(data, filename, claimed_type):
    """Validate supported attachment signatures and return a trusted MIME type."""
    image_type = detect_image_type(data)
    if image_type:
        return image_type if claimed_type in {image_type, "application/octet-stream"} else ""
    lowered = filename.lower()
    if data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]:
        return "application/pdf" if lowered.endswith(".pdf") else ""
    if data.startswith(b"PK\x03\x04") and lowered.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" in names and "word/document.xml" in names:
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except (ValueError, zipfile.BadZipFile):
            return ""
    if lowered.endswith((".md", ".markdown", ".txt")):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return ""
        return "text/markdown" if lowered.endswith((".md", ".markdown")) else "text/plain"
    return ""


def normalize_workspace_data(data):
    """Add compatible planning defaults without replacing existing records or IDs."""
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        return data, False
    changed = False
    for project in data["projects"]:
        if not isinstance(project, dict):
            continue
        if "archived" not in project:
            project["archived"] = False
            changed = True
        if not isinstance(project.get("bible"), dict):
            project["bible"] = {}
            changed = True
        for field in (
            "logline",
            "premise",
            "seasonArc",
            "worldRules",
            "toneStyle",
            "audience",
            "language",
            "aspectRatio",
            "productionConstraints",
        ):
            if field not in project["bible"]:
                project["bible"][field] = ""
                changed = True
        if not isinstance(project.get("prompts"), list):
            project["prompts"] = []
            changed = True
        if not isinstance(project.get("gates"), list):
            project["gates"] = []
            changed = True
        for prompt in project["prompts"]:
            if not isinstance(prompt, dict):
                continue
            if not prompt.get("id"):
                prompt["id"] = "prompt-" + secrets.token_hex(12)
                changed = True
            if "archived" not in prompt:
                prompt["archived"] = False
                changed = True
        for gate in project["gates"]:
            if not isinstance(gate, dict):
                continue
            if not gate.get("id"):
                gate["id"] = "gate-" + secrets.token_hex(12)
                changed = True
        for episode in project.get("episodes", []):
            if not isinstance(episode, dict):
                continue
            for field, default in (
                ("archived", False),
                ("synopsis", ""),
                ("beats", ""),
                ("shots", []),
            ):
                if field not in episode or (
                    field == "shots" and not isinstance(episode[field], list)
                ):
                    episode[field] = default
                    changed = True
            for shot in episode["shots"]:
                if not isinstance(shot, dict):
                    continue
                if not shot.get("id"):
                    shot["id"] = "shot-" + secrets.token_hex(12)
                    changed = True
        for character in project.get("characters", []):
            if not isinstance(character, dict):
                continue
            if not character.get("id"):
                character["id"] = "c-" + secrets.token_hex(12)
                changed = True
            if "archived" not in character:
                character["archived"] = False
                changed = True
            if "referenceRequirements" not in character:
                character["referenceRequirements"] = ""
                changed = True
            if not isinstance(character.get("continuity"), dict):
                character["continuity"] = {}
                changed = True
            for field in ("mustKeep", "mustAvoid", "wardrobeVariants", "voice"):
                if field not in character["continuity"]:
                    character["continuity"][field] = ""
                    changed = True
    if data["projects"] and not any(
        project.get("id") == data.get("activeId")
        for project in data["projects"]
        if isinstance(project, dict)
    ):
        data["activeId"] = data["projects"][0].get("id", "")
        changed = True
    if not data["projects"] and data.get("activeId"):
        data["activeId"] = ""
        changed = True
    return data, changed


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
    if not validate_public_base_url(PUBLIC_BASE_URL):
        raise RuntimeError(
            "AICS_PUBLIC_BASE_URL must be an HTTPS origin or a loopback HTTP origin"
        )
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
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                url TEXT NOT NULL,
                purpose TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                archived_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS character_images (
                storage_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                character_id TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, character_id)
            );
            CREATE INDEX IF NOT EXISTS character_images_user
                ON character_images(user_id);
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id TEXT PRIMARY KEY,
                client_name TEXT NOT NULL,
                redirect_uris TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_flows (
                flow_hash TEXT PRIMARY KEY,
                request_data TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_codes (
                code_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_id TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
                redirect_uri TEXT NOT NULL,
                scopes TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                resource TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_grants (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                client_id TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
                scopes TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                revoked_at INTEGER,
                UNIQUE(user_id, client_id)
            );
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                token_hash TEXT PRIMARY KEY,
                grant_id INTEGER NOT NULL REFERENCES oauth_grants(id) ON DELETE CASCADE,
                token_type TEXT NOT NULL CHECK(token_type IN ('access', 'refresh')),
                family_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                scopes TEXT NOT NULL DEFAULT '',
                used_at INTEGER,
                revoked_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS oauth_tokens_grant ON oauth_tokens(grant_id);
            CREATE INDEX IF NOT EXISTS oauth_tokens_expiry ON oauth_tokens(expires_at);
            CREATE TABLE IF NOT EXISTS mcp_rate_limits (
                token_hash TEXT PRIMARY KEY,
                window_started INTEGER NOT NULL,
                request_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_source_limits (
                scope_hash TEXT NOT NULL,
                purpose TEXT NOT NULL,
                window_started INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                PRIMARY KEY(scope_hash, purpose)
            );
            CREATE TABLE IF NOT EXISTS recovery_codes (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                set_id TEXT NOT NULL,
                salt TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                confirmed_at INTEGER,
                used_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS recovery_codes_user
                ON recovery_codes(user_id, set_id);
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                subject_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prompt_attachments (
                id INTEGER PRIMARY KEY,
                storage_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS prompt_attachments_scope
                ON prompt_attachments(user_id, project_id, prompt_id);
            CREATE TABLE IF NOT EXISTS tool_assignments (
                tool_id INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(tool_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS mcp_permissions (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                can_read INTEGER NOT NULL DEFAULT 0 CHECK(can_read IN (0, 1)),
                can_write INTEGER NOT NULL DEFAULT 0 CHECK(can_write IN (0, 1)),
                can_archive INTEGER NOT NULL DEFAULT 0 CHECK(can_archive IN (0, 1)),
                can_delete INTEGER NOT NULL DEFAULT 0 CHECK(can_delete IN (0, 1)),
                updated_at INTEGER NOT NULL
            );
            """
        )
        user_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(users)")
        }
        if "archived_at" not in user_columns:
            database.execute("ALTER TABLE users ADD COLUMN archived_at INTEGER")
        if "must_change_password" not in user_columns:
            database.execute(
                "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
            )
        if "recovery_setup_required" not in user_columns:
            database.execute(
                "ALTER TABLE users ADD COLUMN recovery_setup_required INTEGER NOT NULL DEFAULT 1"
            )
        tool_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(tools)")
        }
        if "owner_user_id" not in tool_columns:
            database.execute(
                "ALTER TABLE tools ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"
            )
        token_columns = {
            row["name"] for row in database.execute("PRAGMA table_info(oauth_tokens)")
        }
        if "scopes" not in token_columns:
            database.execute(
                "ALTER TABLE oauth_tokens ADD COLUMN scopes TEXT NOT NULL DEFAULT ''"
            )
        try:
            previous_schema = int(get_setting(database, "schema_version", "0"))
        except ValueError:
            previous_schema = 0
        if (
            previous_schema < 3
            and database.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
        ):
            now = int(time.time())
            database.executemany(
                """
                INSERT INTO tools
                    (name, category, url, purpose, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ((*tool, now, now) for tool in TOOL_SEEDS),
            )
        if get_setting(database, "registration_enabled") is None:
            set_setting(
                database,
                "registration_enabled",
                "1" if REGISTRATION_DEFAULT else "0",
            )
        set_setting(database, "schema_version", "6")

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

        for row in database.execute(
            "SELECT user_id, data FROM workspaces"
        ).fetchall():
            try:
                data = json.loads(row["data"])
            except json.JSONDecodeError:
                continue
            data, changed = normalize_workspace_data(data)
            if changed:
                database.execute(
                    "UPDATE workspaces SET data=? WHERE user_id=?",
                    (json.dumps(data), row["user_id"]),
                )
    image_root().mkdir(parents=True, exist_ok=True)
    attachment_root().mkdir(parents=True, exist_ok=True)


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
        "archived": bool(row["archived_at"]),
        "theme": row["theme"],
        "mustChangePassword": bool(row["must_change_password"]),
        "recoverySetupRequired": bool(row["recovery_setup_required"]),
    }


def mcp_permissions(database, user_id, role=None):
    """Return current granular MCP entitlements, with full admin compatibility."""
    if role is None:
        user = database.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        role = user["role"] if user else ""
    if role == "admin":
        return {"enabled": True, "read": True, "write": True, "archive": True, "delete": True}
    row = database.execute("SELECT * FROM mcp_permissions WHERE user_id=?", (user_id,)).fetchone()
    return {
        "enabled": bool(row and row["enabled"]),
        "read": bool(row and row["can_read"]),
        "write": bool(row and row["can_write"]),
        "archive": bool(row and row["can_archive"]),
        "delete": bool(row and row["can_delete"]),
    }


def permitted_oauth_scopes(database, user_id, requested):
    """Intersect requested OAuth scopes with the account current entitlements."""
    permissions = mcp_permissions(database, user_id)
    if not permissions["enabled"]:
        return ""
    mapping = {
        "aics.read": "read", "aics.write": "write",
        "aics.archive": "archive", "aics.delete": "delete",
    }
    return " ".join(sorted(
        scope for scope in requested.split() if permissions[mapping[scope]]
    ))


def resolve_access_token(raw_token, required_scope=None, touch=False):
    """Resolve an active bearer token to its owner without exposing stored secrets."""
    if not isinstance(raw_token, str) or len(raw_token) < 32:
        return None
    now = int(time.time())
    digest = token_hash(raw_token)
    with connect() as database:
        row = database.execute(
            """
            SELECT t.token_hash, t.expires_at, g.id AS grant_id,
                   COALESCE(NULLIF(t.scopes, ''), g.scopes) AS scopes,
                   g.user_id, c.client_id, c.client_name, u.role
            FROM oauth_tokens t
            JOIN oauth_grants g ON g.id=t.grant_id
            JOIN oauth_clients c ON c.client_id=g.client_id
            JOIN users u ON u.id=g.user_id
            WHERE t.token_hash=? AND t.token_type='access'
              AND t.revoked_at IS NULL AND g.revoked_at IS NULL
              AND t.expires_at>? AND u.is_active=1 AND u.archived_at IS NULL
            """,
            (digest, now),
        ).fetchone()
        if not row:
            return None
        effective = permitted_oauth_scopes(database, row["user_id"], row["scopes"])
        if not effective or (required_scope and required_scope not in effective.split()):
            return None
        row = dict(row)
        row["scopes"] = effective
        if touch:
            database.execute(
                "UPDATE oauth_tokens SET used_at=? WHERE token_hash=?",
                (now, digest),
            )
            database.execute(
                "UPDATE oauth_grants SET last_used_at=? WHERE id=?",
                (now, row["grant_id"]),
            )
        return dict(row)


def revoke_user_oauth(database, user_id, now):
    """Revoke every integration grant and token for one account."""
    database.execute(
        "UPDATE oauth_grants SET revoked_at=? WHERE user_id=?",
        (now, user_id),
    )
    database.execute(
        """
        UPDATE oauth_tokens SET revoked_at=?
        WHERE grant_id IN (SELECT id FROM oauth_grants WHERE user_id=?)
        """,
        (now, user_id),
    )


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

    def reply(
        self,
        status,
        body,
        content_type="application/json; charset=utf-8",
        extra=None,
        content_security_policy=DEFAULT_CONTENT_SECURITY_POLICY,
    ):
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
        self.send_header("Content-Security-Policy", content_security_policy)
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

    def read_body(self, max_bytes):
        """Read a bounded raw request body for authenticated image uploads."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid content length") from error
        if length <= 0 or length > max_bytes:
            raise ValueError("Invalid request size")
        return self.rfile.read(length)

    def read_form(self, max_bytes=OAUTH_MAX_BYTES):
        """Read a bounded URL-encoded form and reject repeated fields."""
        raw = self.read_body(max_bytes)
        try:
            parsed = parse_qs(
                raw.decode("utf-8"), keep_blank_values=True, strict_parsing=True
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Invalid form") from error
        if any(len(values) != 1 for values in parsed.values()):
            raise ValueError("Repeated form field")
        return {key: values[0] for key, values in parsed.items()}

    def redirect(self, location, extra=None):
        """Redirect a completed form submission to an already validated URL."""
        headers = [("Location", location)]
        headers.extend(extra or [])
        return self.reply(303, b"", "text/plain; charset=utf-8", headers)

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
                    u.id, u.username, u.display_name, u.role, u.is_active,
                    u.archived_at, u.theme, u.must_change_password,
                    u.recovery_setup_required
                FROM sessions s
                JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=?
                """,
                (session_token_hash(token),),
            ).fetchone()
            if (
                not row
                or not row["is_active"]
                or row["archived_at"]
                or row["expires_at"] <= now
            ):
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
            contact_url = get_setting(database, "contact_page_url", "")
            permissions = mcp_permissions(database, session["id"], session["role"])
        return {
            "authenticated": True,
            "user": public_user(session),
            "csrfToken": session["csrf_token"],
            "expiresAt": session["expires_at"],
            "registrationEnabled": allow_registration,
            "contactPageUrl": contact_url,
            "mcpPermissions": permissions,
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
        if path == "/mcp/ready":
            return self.mcp_readiness()
        if path in {
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        }:
            return self.oauth_protected_resource_metadata()
        if path == "/.well-known/oauth-authorization-server":
            return self.oauth_authorization_metadata()
        if path == "/oauth/authorize":
            return self.oauth_authorize_page()
        if path == "/mcp":
            return self.proxy_mcp()
        if self.static_response(path):
            return None
        if path == "/api/session":
            session = self.current_session()
            if session:
                return self.json_reply(200, self.session_payload(session))
            with connect() as database:
                allow_registration = registration_enabled(database)
                contact_url = get_setting(database, "contact_page_url", "")
            return self.json_reply(
                200,
                {
                    "authenticated": False,
                    "registrationEnabled": allow_registration,
                    "contactPageUrl": contact_url,
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
        if path == "/api/account/integrations":
            return self.get_integrations(session)
        if path == "/api/tools":
            return self.get_tools(session)
        if path.startswith("/api/projects/") and "/prompts/" in path and "/attachments" in path:
            return self.list_prompt_attachments(path, session)
        if path.startswith("/api/characters/") and path.endswith("/image"):
            return self.get_character_image(path, session)
        if path == "/api/admin/users":
            return self.get_users()
        if path == "/api/admin/settings":
            with connect() as database:
                enabled = registration_enabled(database)
                contact_url = get_setting(database, "contact_page_url", "")
            return self.json_reply(200, {"registrationEnabled": enabled, "contactPageUrl": contact_url})
        return self.json_reply(404, {"error": "Not found"})

    def do_POST(self):
        """Route login, registration, and logout requests."""
        path = urlsplit(self.path).path
        if path == "/mcp":
            return self.proxy_mcp()
        if path == "/oauth/register":
            return self.oauth_register()
        if path == "/oauth/token":
            return self.oauth_token()
        if path == "/oauth/revoke":
            return self.oauth_revoke()
        if path == "/oauth/authorize":
            return self.oauth_authorize_submit()
        if not self.same_origin_request():
            return self.json_reply(403, {"error": "Cross-site request rejected."})
        if path == "/api/login":
            return self.login()
        if path == "/api/register":
            return self.register()
        if path == "/api/recover":
            return self.recover_password()
        if path == "/api/admin/tools" or path == "/api/tools":
            session = self.require_session(admin=path.startswith("/api/admin/"), csrf=True)
            if not session:
                return None
            return self.create_tool(session)
        if path == "/api/account/recovery-codes/generate":
            session = self.require_session(csrf=True)
            if not session:
                return None
            return self.generate_account_recovery_codes(session)
        if path == "/api/account/recovery-codes/confirm":
            session = self.require_session(csrf=True)
            if not session:
                return None
            return self.confirm_account_recovery_codes(session)
        if path.startswith("/api/admin/users/") and path.endswith("/reset-password"):
            session = self.require_session(admin=True, csrf=True)
            if not session:
                return None
            return self.admin_reset_password(path, session)
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
        if path.startswith("/api/projects/") and "/prompts/" in path and path.endswith("/attachments"):
            return self.put_prompt_attachment(path, session)
        if path == "/api/account":
            return self.update_account(session)
        if path == "/api/admin/settings":
            return self.update_admin_settings()
        if path.startswith("/api/admin/users/") and path.endswith("/mcp"):
            return self.update_user_mcp_permissions(path)
        if path.startswith("/api/admin/users/"):
            return self.update_user(path, session)
        if path.startswith("/api/admin/tools/"):
            return self.update_tool(path, session)
        if path.startswith("/api/tools/"):
            return self.update_tool(path, session)
        if path.startswith("/api/characters/") and path.endswith("/image"):
            return self.put_character_image(path, session)
        return self.json_reply(404, {"error": "Not found"})

    def do_DELETE(self):
        """Route destructive actions with role and CSRF enforcement."""
        path = urlsplit(self.path).path
        if path == "/mcp":
            return self.proxy_mcp()
        if not self.same_origin_request():
            return self.json_reply(403, {"error": "Cross-site request rejected."})
        session = self.require_session(
            admin=path.startswith("/api/admin/"), csrf=True
        )
        if not session:
            return None
        if path.startswith("/api/admin/users/"):
            return self.delete_user(path, session)
        if path.startswith("/api/admin/tools/"):
            return self.delete_tool(path, session)
        if path.startswith("/api/tools/"):
            return self.delete_tool(path, session)
        if path.startswith("/api/characters/") and path.endswith("/image"):
            return self.delete_character_image(path, session)
        if path.startswith("/api/projects/") and "/prompts/" in path and "/attachments/" in path:
            return self.delete_prompt_attachment(path, session)
        if path.startswith("/api/account/integrations/"):
            return self.revoke_integration(path, session)
        return self.json_reply(404, {"error": "Not found"})

    def oauth_authorization_metadata(self):
        """Publish OAuth server discovery metadata for remote MCP clients."""
        return self.json_reply(
            200,
            {
                "issuer": PUBLIC_BASE_URL,
                "authorization_endpoint": PUBLIC_BASE_URL + "/oauth/authorize",
                "token_endpoint": PUBLIC_BASE_URL + "/oauth/token",
                "registration_endpoint": PUBLIC_BASE_URL + "/oauth/register",
                "revocation_endpoint": PUBLIC_BASE_URL + "/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": sorted(OAUTH_SCOPES),
            },
        )

    def oauth_protected_resource_metadata(self):
        """Publish RFC 9728 metadata for the account-scoped MCP resource."""
        return self.json_reply(
            200,
            {
                "resource": PUBLIC_BASE_URL + "/mcp",
                "authorization_servers": [PUBLIC_BASE_URL],
                "scopes_supported": sorted(OAUTH_SCOPES),
                "bearer_methods_supported": ["header"],
            },
        )

    def oauth_error(self, status, error, description, headers=None):
        """Return a structured OAuth error without reflecting credentials."""
        response_headers = {"Pragma": "no-cache", **(headers or {})}
        return self.json_reply(
            status,
            {"error": error, "error_description": description},
            response_headers,
        )

    def oauth_register(self):
        """Register a bounded public OAuth client with exact redirect URIs."""
        try:
            value = self.read_json(OAUTH_MAX_BYTES)
            allowed = {
                "client_name", "redirect_uris", "grant_types",
                "response_types", "token_endpoint_auth_method",
            }
            if set(value) - allowed:
                raise ValueError("Unknown field")
            raw_name = value["client_name"]
            if not isinstance(raw_name, str):
                raise ValueError("Invalid client name")
            name = raw_name.strip()
            redirect_uris = value["redirect_uris"]
            if (
                not name
                or len(name) > 120
                or not isinstance(redirect_uris, list)
                or not 1 <= len(redirect_uris) <= 10
                or len(set(redirect_uris)) != len(redirect_uris)
                or not all(validate_redirect_uri(item) for item in redirect_uris)
                or value.get("grant_types", ["authorization_code", "refresh_token"])
                != ["authorization_code", "refresh_token"]
                or value.get("response_types", ["code"]) != ["code"]
                or value.get("token_endpoint_auth_method", "none") != "none"
            ):
                raise ValueError("Invalid client metadata")
        except (KeyError, TypeError, ValueError):
            return self.oauth_error(
                400, "invalid_client_metadata", "Provide valid public client metadata."
            )
        client_id = "aics-client-" + secrets.token_urlsafe(24)
        now = int(time.time())
        with connect() as database:
            accepted, retry_after = self.reserve_oauth_source(
                database, "registration", now, OAUTH_REGISTRATION_LIMIT
            )
            if not accepted:
                return self.oauth_error(
                    429,
                    "slow_down",
                    "Too many client registration requests.",
                    {"Retry-After": str(retry_after)},
                )
            self.cleanup_expired_oauth_records(database, now)
            client_count = database.execute(
                "SELECT COUNT(*) FROM oauth_clients"
            ).fetchone()[0]
            if client_count >= OAUTH_CLIENT_LIMIT:
                return self.oauth_error(
                    503,
                    "temporarily_unavailable",
                    "The public client registration limit has been reached.",
                )
            database.execute(
                """
                INSERT INTO oauth_clients
                    (client_id, client_name, redirect_uris, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (client_id, name, json.dumps(redirect_uris), now),
            )
        return self.json_reply(
            201,
            {
                "client_id": client_id,
                "client_name": name,
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )

    def validated_authorization_request(self, values):
        """Validate an authorization request and return normalized saved fields."""
        allowed = {
            "response_type", "client_id", "redirect_uri", "scope", "state",
            "code_challenge", "code_challenge_method", "resource", "ui_locales",
        }
        if set(values) - allowed or values.get("response_type") != "code":
            raise ValueError("Invalid authorization request")
        client_id = values.get("client_id", "")
        redirect_uri = values.get("redirect_uri", "")
        state = values.get("state", "")
        challenge = values.get("code_challenge", "")
        resource = values.get("resource", PUBLIC_BASE_URL + "/mcp")
        ui_locales = values.get("ui_locales")
        if (
            not isinstance(state, str)
            or len(state) > 512
            or (
                ui_locales is not None
                and (
                    not isinstance(ui_locales, str)
                    or len(ui_locales) > 128
                    or not OAUTH_UI_LOCALES_PATTERN.fullmatch(ui_locales)
                )
            )
            or values.get("code_challenge_method") != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", challenge)
            or resource != PUBLIC_BASE_URL + "/mcp"
        ):
            raise ValueError("Invalid authorization request")
        scopes = parse_scopes(values.get("scope", "aics.read"))
        with connect() as database:
            client = database.execute(
                "SELECT client_name, redirect_uris FROM oauth_clients WHERE client_id=?",
                (client_id,),
            ).fetchone()
        if not client or redirect_uri not in json.loads(client["redirect_uris"]):
            raise ValueError("Invalid client or redirect URI")
        # ChatGPT sends ui_locales only as a display hint. Validate it above,
        # then omit it here so it never enters flow, code, grant, or token data.
        return {
            "client_id": client_id,
            "client_name": client["client_name"],
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge": challenge,
            "resource": resource,
        }

    def oauth_flow_cookie(self, raw_flow, max_age):
        """Build the short-lived cookie that binds consent POST to its browser."""
        parts = [
            "AICS_OAUTH_FLOW=" + raw_flow,
            "Path=/oauth/authorize",
            "HttpOnly",
            "SameSite=Lax",
            "Max-Age=" + str(max_age),
        ]
        if COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def oauth_flow_token(self):
        """Read the short-lived OAuth consent binding cookie."""
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return ""
        morsel = cookie.get("AICS_OAUTH_FLOW")
        return morsel.value if morsel else ""

    def oauth_authorize_page(self):
        """Validate an OAuth request and render account login plus explicit consent."""
        now = int(time.time())
        with connect() as database:
            self.cleanup_expired_oauth_records(database, now)
        try:
            query = parse_qs(
                urlsplit(self.path).query,
                keep_blank_values=True,
                strict_parsing=True,
            )
            if any(len(values) != 1 for values in query.values()):
                raise ValueError("Repeated parameter")
            request_data = self.validated_authorization_request(
                {key: values[0] for key, values in query.items()}
            )
            callback_origin = oauth_redirect_origin(request_data["redirect_uri"])
        except ValueError:
            return self.oauth_error(
                400, "invalid_request", "The authorization request is invalid."
            )
        raw_flow = secrets.token_urlsafe(32)
        with connect() as database:
            accepted, retry_after = self.reserve_oauth_source(
                database, "authorization", now, OAUTH_AUTHORIZATION_LIMIT
            )
            if not accepted:
                return self.oauth_error(
                    429,
                    "slow_down",
                    "Too many authorization requests.",
                    {"Retry-After": str(retry_after)},
                )
            self.cleanup_expired_oauth_records(database, now)
            flow_count = database.execute(
                "SELECT COUNT(*) FROM oauth_flows"
            ).fetchone()[0]
            if flow_count >= OAUTH_FLOW_LIMIT:
                return self.oauth_error(
                    503,
                    "temporarily_unavailable",
                    "The active authorization request limit has been reached.",
                )
            database.execute(
                """
                INSERT INTO oauth_flows
                    (flow_hash, request_data, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    token_hash(raw_flow),
                    json.dumps(request_data),
                    now,
                    now + OAUTH_CODE_SECONDS,
                ),
            )
        session = self.current_session()
        display_scopes = request_data["scope"]
        if session:
            with connect() as database:
                display_scopes = permitted_oauth_scopes(database, session["id"], display_scopes)
        identity = (
            "<p>Signed in as <strong>"
            + html.escape(session["display_name"])
            + "</strong>.</p>"
            if session
            else (
                '<label>Username<input name="username" autocomplete="username" '
                'required maxlength="40"></label>'
                '<label>Password<input name="password" type="password" '
                'autocomplete="current-password" required maxlength="256"></label>'
            )
        )
        scope_items = "".join(
            "<li>"
            + (
                "Read your project planning records"
                if scope == "aics.read"
                else "Create and update your project planning records"
            )
            + "</li>"
            for scope in display_scopes.split()
        )
        page = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Authorize integration</title><link rel=\"stylesheet\" href=\"/style.css\">"
            "</head><body><main class=\"oauth-page\"><section class=\"panel\">"
            "<p class=\"eyebrow\">Connected integration</p><h1>Authorize "
            + html.escape(request_data["client_name"])
            + "</h1><p>This client is requesting permission to:</p><ul>"
            + scope_items
            + '</ul><form method="post" action="/oauth/authorize">'
            + identity
            + '<input type="hidden" name="flow" value="'
            + html.escape(raw_flow)
            + '"><div class="action-row"><button class="btn" name="decision" '
            'value="deny" type="submit">Deny</button><button class="btn primary" '
            'name="decision" value="approve" type="submit">Authorize</button>'
            "</div></form></section></main></body></html>"
        ).encode("utf-8")
        # Browsers apply form-action across redirects. Permit only the origin
        # derived from the registered, validated callback for this consent page.
        consent_csp = DEFAULT_CONTENT_SECURITY_POLICY.replace(
            "form-action 'self'",
            "form-action 'self' " + callback_origin,
        )
        return self.reply(
            200,
            page,
            "text/html; charset=utf-8",
            [("Set-Cookie", self.oauth_flow_cookie(raw_flow, OAUTH_CODE_SECONDS))],
            content_security_policy=consent_csp,
        )

    def oauth_authorize_submit(self):
        """Authenticate if needed, consume consent, and issue a one-time code."""
        try:
            form = self.read_form()
            raw_flow = form.get("flow", "")
            cookie_flow = self.oauth_flow_token()
            if (
                not raw_flow
                or not cookie_flow
                or not hmac.compare_digest(raw_flow, cookie_flow)
            ):
                raise ValueError("Flow mismatch")
            now = int(time.time())
            with connect() as database:
                database.execute("BEGIN IMMEDIATE")
                row = database.execute(
                    """
                    SELECT request_data FROM oauth_flows
                    WHERE flow_hash=? AND expires_at>?
                    """,
                    (token_hash(raw_flow), now),
                ).fetchone()
                database.execute(
                    "DELETE FROM oauth_flows WHERE flow_hash=?",
                    (token_hash(raw_flow),),
                )
            if not row:
                raise ValueError("Expired flow")
            request_data = json.loads(row["request_data"])
        except (ValueError, json.JSONDecodeError):
            return self.oauth_error(
                400, "invalid_request", "The authorization request expired."
            )
        redirect_uri = request_data["redirect_uri"]
        state = request_data["state"]
        if form.get("decision") != "approve":
            query = {"error": "access_denied"}
            if state:
                query["state"] = state
            separator = "&" if urlsplit(redirect_uri).query else "?"
            return self.redirect(redirect_uri + separator + urlencode(query))
        session = self.current_session()
        user_id = session["id"] if session else None
        if not user_id:
            username = form.get("username", "")
            password = form.get("password", "")
            if (
                not isinstance(username, str)
                or not isinstance(password, str)
                or not username.strip()
                or len(username) > 40
                or not password
                or len(password) > 256
            ):
                return self.oauth_error(401, "access_denied", "Sign-in failed.")
            attempt_scope = self.attempt_scope("oauth-consent-login")
            now = int(time.time())
            with connect() as database:
                accepted, remaining, block_after_failure = self.reserve_attempt(
                    database, attempt_scope, now, LOGIN_LIMIT
                )
                if not accepted:
                    return self.oauth_error(
                        429, "temporarily_unavailable",
                        "Too many sign-in attempts. Try again later.",
                        {"Retry-After": str(remaining)},
                    )
                user = database.execute(
                    """
                    SELECT * FROM users
                    WHERE username=? COLLATE NOCASE AND is_active=1
                      AND archived_at IS NULL
                    """,
                    (username.strip(),),
                ).fetchone()
            encoded = user["password_hash"] if user else DUMMY_PASSWORD_HASH
            if not verify_password(password, encoded) or not user:
                if block_after_failure:
                    return self.oauth_error(
                        429, "temporarily_unavailable",
                        "Too many sign-in attempts. Try again later.",
                        {"Retry-After": str(block_after_failure)},
                    )
                return self.oauth_error(401, "access_denied", "Sign-in failed.")
            with connect() as database:
                self.release_login_attempt(database, attempt_scope)
            user_id = user["id"]
        with connect() as database:
            account = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            effective_scopes = permitted_oauth_scopes(database, user_id, request_data["scope"])
        if (not account or (account["role"] != "admin" and (
                account["must_change_password"] or account["recovery_setup_required"]
            )) or not effective_scopes):
            return self.oauth_error(403, "access_denied", "MCP access is not available for this account.")
        raw_code = secrets.token_urlsafe(32)
        with connect() as database:
            database.execute(
                """
                INSERT INTO oauth_codes
                    (code_hash, user_id, client_id, redirect_uri, scopes,
                     code_challenge, resource, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash(raw_code), user_id, request_data["client_id"],
                    redirect_uri, effective_scopes,
                    request_data["code_challenge"], request_data["resource"],
                    int(time.time()) + OAUTH_CODE_SECONDS,
                ),
            )
        query = {"code": raw_code, "iss": PUBLIC_BASE_URL}
        if state:
            query["state"] = state
        separator = "&" if urlsplit(redirect_uri).query else "?"
        return self.redirect(
            redirect_uri + separator + urlencode(query),
            [("Set-Cookie", self.oauth_flow_cookie("", 0))],
        )

    def issue_oauth_pair(self, database, grant_id, scopes, family_id=None):
        """Create one short access token and one rotating refresh token."""
        now = int(time.time())
        family_id = family_id or secrets.token_hex(24)
        access = secrets.token_urlsafe(48)
        refresh = secrets.token_urlsafe(48)
        database.executemany(
            """
            INSERT INTO oauth_tokens
                (token_hash, grant_id, token_type, family_id, created_at, expires_at, scopes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    token_hash(access), grant_id, "access", family_id,
                    now, now + OAUTH_ACCESS_SECONDS, scopes,
                ),
                (
                    token_hash(refresh), grant_id, "refresh", family_id,
                    now, now + OAUTH_REFRESH_SECONDS, scopes,
                ),
            ),
        )
        return access, refresh

    def oauth_token(self):
        """Exchange a PKCE code or rotate a refresh token."""
        try:
            form = self.read_form()
        except ValueError:
            return self.oauth_error(400, "invalid_request", "Invalid token request.")
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return self.oauth_authorization_code_token(form)
        if grant_type == "refresh_token":
            return self.oauth_refresh_token(form)
        return self.oauth_error(
            400, "unsupported_grant_type", "Use authorization_code or refresh_token."
        )

    def oauth_authorization_code_token(self, form):
        """Consume one authorization code after exact redirect and PKCE checks."""
        code = form.get("code", "")
        verifier = form.get("code_verifier", "")
        client_id = form.get("client_id", "")
        redirect_uri = form.get("redirect_uri", "")
        if (
            not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
            or form.get("resource", PUBLIC_BASE_URL + "/mcp")
            != PUBLIC_BASE_URL + "/mcp"
        ):
            return self.oauth_error(400, "invalid_grant", "PKCE verification failed.")
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM oauth_codes WHERE code_hash=?",
                (token_hash(code),),
            ).fetchone()
            if row:
                database.execute(
                    "DELETE FROM oauth_codes WHERE code_hash=?",
                    (token_hash(code),),
                )
            if (
                not row
                or row["expires_at"] <= now
                or row["client_id"] != client_id
                or row["redirect_uri"] != redirect_uri
                or row["resource"] != PUBLIC_BASE_URL + "/mcp"
                or not hmac.compare_digest(
                    row["code_challenge"], pkce_challenge(verifier)
                )
            ):
                return self.oauth_error(
                    400, "invalid_grant", "The authorization code is invalid."
                )
            effective_scopes = permitted_oauth_scopes(database, row["user_id"], row["scopes"])
            if not effective_scopes:
                return self.oauth_error(400, "invalid_grant", "MCP access was revoked.")
            database.execute(
                """
                INSERT INTO oauth_grants
                    (user_id, client_id, scopes, created_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, client_id) DO UPDATE SET
                    scopes=excluded.scopes, created_at=excluded.created_at,
                    revoked_at=NULL
                """,
                (row["user_id"], client_id, effective_scopes, now),
            )
            grant = database.execute(
                "SELECT id FROM oauth_grants WHERE user_id=? AND client_id=?",
                (row["user_id"], client_id),
            ).fetchone()
            database.execute(
                "UPDATE oauth_tokens SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL",
                (now, grant["id"]),
            )
            access, refresh = self.issue_oauth_pair(
                database, grant["id"], effective_scopes
            )
        return self.oauth_token_response(access, refresh, effective_scopes)

    def oauth_refresh_token(self, form):
        """Rotate a refresh token and revoke its family on replay."""
        raw_refresh = form.get("refresh_token", "")
        client_id = form.get("client_id", "")
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                """
                SELECT t.*,
                       COALESCE(NULLIF(t.scopes, ''), g.scopes) AS effective_scopes,
                       g.client_id, g.user_id, g.revoked_at AS grant_revoked
                FROM oauth_tokens t
                JOIN oauth_grants g ON g.id=t.grant_id
                WHERE t.token_hash=? AND t.token_type='refresh'
                """,
                (token_hash(raw_refresh),),
            ).fetchone()
            if not row or row["client_id"] != client_id:
                return self.oauth_error(400, "invalid_grant", "Invalid refresh token.")
            if row["used_at"] or row["revoked_at"]:
                database.execute(
                    """
                    UPDATE oauth_tokens SET revoked_at=?
                    WHERE family_id=? AND revoked_at IS NULL
                    """,
                    (now, row["family_id"]),
                )
                return self.oauth_error(
                    400, "invalid_grant", "Refresh token reuse was rejected."
                )
            if row["grant_revoked"] or row["expires_at"] <= now:
                return self.oauth_error(400, "invalid_grant", "Refresh token expired.")
            try:
                scopes = (
                    parse_scopes(form["scope"])
                    if form.get("scope")
                    else row["effective_scopes"]
                )
            except ValueError:
                return self.oauth_error(400, "invalid_scope", "Invalid scope.")
            if not set(scopes.split()).issubset(set(row["effective_scopes"].split())):
                return self.oauth_error(400, "invalid_scope", "Scope cannot expand.")
            scopes = permitted_oauth_scopes(database, row["user_id"], scopes)
            if not scopes:
                revoke_user_oauth(database, row["user_id"], now)
                return self.oauth_error(400, "invalid_grant", "MCP access was revoked.")
            database.execute(
                "UPDATE oauth_tokens SET used_at=? WHERE token_hash=?",
                (now, row["token_hash"]),
            )
            access, refresh = self.issue_oauth_pair(
                database, row["grant_id"], scopes, row["family_id"]
            )
        return self.oauth_token_response(access, refresh, scopes)

    def oauth_token_response(self, access, refresh, scopes):
        """Return a no-store bearer token response."""
        return self.json_reply(
            200,
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": OAUTH_ACCESS_SECONDS,
                "refresh_token": refresh,
                "scope": scopes,
            },
            {"Pragma": "no-cache"},
        )

    def oauth_revoke(self):
        """Revoke the grant associated with a supplied access or refresh token."""
        try:
            form = self.read_form()
        except ValueError:
            return self.oauth_error(400, "invalid_request", "Invalid revocation request.")
        raw_token = form.get("token", "")
        client_id = form.get("client_id", "")
        with connect() as database:
            row = database.execute(
                """
                SELECT t.grant_id, g.client_id FROM oauth_tokens t
                JOIN oauth_grants g ON g.id=t.grant_id
                WHERE t.token_hash=?
                """,
                (token_hash(raw_token),),
            ).fetchone()
            if row and row["client_id"] == client_id:
                now = int(time.time())
                database.execute(
                    "UPDATE oauth_grants SET revoked_at=? WHERE id=?", (now, row["grant_id"])
                )
                database.execute(
                    "UPDATE oauth_tokens SET revoked_at=? WHERE grant_id=?", (now, row["grant_id"])
                )
        return self.reply(200, b"", "application/json; charset=utf-8")

    def get_integrations(self, session):
        """List connected OAuth grants for only the signed-in account."""
        with connect() as database:
            rows = database.execute(
                """
                SELECT g.id, c.client_name, g.scopes, g.created_at,
                       g.last_used_at
                FROM oauth_grants g
                JOIN oauth_clients c ON c.client_id=g.client_id
                WHERE g.user_id=? AND g.revoked_at IS NULL
                ORDER BY g.created_at DESC, g.id DESC
                """,
                (session["id"],),
            ).fetchall()
        return self.json_reply(
            200,
            {
                "integrations": [
                    {
                        "id": row["id"],
                        "clientName": row["client_name"],
                        "scopes": row["scopes"].split(),
                        "createdAt": row["created_at"],
                        "lastUsedAt": row["last_used_at"],
                    }
                    for row in rows
                ]
            },
        )

    def revoke_integration(self, path, session):
        """Revoke one connected client and all its tokens for the owner."""
        try:
            grant_id = int(path.rsplit("/", 1)[1])
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid integration."})
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            result = database.execute(
                """
                UPDATE oauth_grants SET revoked_at=?
                WHERE id=? AND user_id=? AND revoked_at IS NULL
                """,
                (now, grant_id, session["id"]),
            )
            if result.rowcount == 1:
                database.execute(
                    "UPDATE oauth_tokens SET revoked_at=? WHERE grant_id=?",
                    (now, grant_id),
                )
        if result.rowcount != 1:
            return self.json_reply(404, {"error": "Integration not found."})
        return self.json_reply(200, {"ok": True, "integrationId": grant_id})

    def mcp_readiness(self):
        """Report only whether the internal MCP process is accepting HTTP."""
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", MCP_INTERNAL_PORT, timeout=1
            )
            connection.request("GET", "/healthz")
            ready = connection.getresponse().status in {200, 400, 401, 404, 405}
            connection.close()
        except OSError:
            ready = False
        return self.json_reply(200 if ready else 503, {"ready": ready})

    def proxy_mcp(self):
        """Authenticate, rate-limit, and relay MCP without forwarding cookies."""
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return self.json_reply(
                401,
                {"error": "Bearer authentication is required."},
                {
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="'
                        + PUBLIC_BASE_URL
                        + '/.well-known/oauth-protected-resource/mcp"'
                    )
                },
            )
        raw_token = authorization[7:]
        identity = resolve_access_token(raw_token, touch=True)
        if not identity:
            return self.json_reply(401, {"error": "Invalid or expired bearer token."})
        now = int(time.time())
        digest = token_hash(raw_token)
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM mcp_rate_limits WHERE token_hash=?", (digest,)
            ).fetchone()
            count = row["request_count"] + 1 if row and row["window_started"] > now - 60 else 1
            started = row["window_started"] if row and row["window_started"] > now - 60 else now
            database.execute(
                """
                INSERT INTO mcp_rate_limits
                    (token_hash, window_started, request_count)
                VALUES (?, ?, ?)
                ON CONFLICT(token_hash) DO UPDATE SET
                    window_started=excluded.window_started,
                    request_count=excluded.request_count
                """,
                (digest, started, count),
            )
        if count > 120:
            return self.json_reply(
                429, {"error": "MCP request limit exceeded."}, {"Retry-After": "60"}
            )
        body = b""
        if self.command in {"POST", "PUT", "PATCH"}:
            try:
                body = self.read_body(MAX_BYTES)
            except ValueError:
                return self.json_reply(413, {"error": "MCP request is too large."})
        # Preserve modern routing metadata exactly as the client supplied it.
        # The MCP SDK, not the proxy, validates it against the JSON-RPC body.
        forwarded = forwarded_mcp_headers(self.headers)
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", MCP_INTERNAL_PORT, timeout=310
            )
            connection.request(self.command, "/mcp", body=body, headers=forwarded)
            response = connection.getresponse()
            response_body = response.read(MAX_BYTES + 1)
            response_body = filter_mcp_tools_response(body, response_body, set(identity["scopes"].split()))
            if len(response_body) > MAX_BYTES:
                connection.close()
                return self.json_reply(502, {"error": "MCP response is too large."})
            response_headers = []
            for name in (
                "Mcp-Session-Id", "MCP-Protocol-Version",
                "WWW-Authenticate",
            ):
                value = response.getheader(name)
                if value:
                    response_headers.append((name, value))
            status = response.status
            content_type = response.getheader(
                "Content-Type", "application/json; charset=utf-8"
            )
            connection.close()
            log_mcp_internal_error(
                self.headers, body, status, response_body
            )
            return self.reply(
                status, response_body, content_type, response_headers
            )
        except OSError:
            return self.json_reply(503, {"error": "MCP service is not ready."})

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

    def cleanup_expired_oauth_records(self, database, now):
        """Remove expired transient records and unclaimed public clients safely."""
        database.execute("DELETE FROM oauth_flows WHERE expires_at<=?", (now,))
        database.execute("DELETE FROM oauth_codes WHERE expires_at<=?", (now,))
        database.execute(
            """
            DELETE FROM oauth_clients
            WHERE created_at<=?
              AND NOT EXISTS (
                  SELECT 1 FROM oauth_grants
                  WHERE oauth_grants.client_id=oauth_clients.client_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM oauth_codes
                  WHERE oauth_codes.client_id=oauth_clients.client_id
              )
            """,
            (now - OAUTH_CLIENT_TTL_SECONDS,),
        )

    def reserve_oauth_source(self, database, purpose, now, limit):
        """Atomically reserve one public OAuth write without unbounded source rows."""
        database.execute("BEGIN IMMEDIATE")
        database.execute(
            "DELETE FROM oauth_source_limits WHERE window_started<=?",
            (now - OAUTH_PUBLIC_WINDOW_SECONDS,),
        )
        scope = self.attempt_scope("oauth-" + purpose)
        row = database.execute(
            """
            SELECT window_started, request_count FROM oauth_source_limits
            WHERE scope_hash=? AND purpose=?
            """,
            (scope, purpose),
        ).fetchone()
        if row and row["request_count"] >= limit:
            retry_after = row["window_started"] + OAUTH_PUBLIC_WINDOW_SECONDS - now
            return False, max(1, retry_after)
        if not row:
            stored = database.execute(
                "SELECT COUNT(*) FROM oauth_source_limits"
            ).fetchone()[0]
            if stored >= OAUTH_SOURCE_LIMIT:
                return False, OAUTH_PUBLIC_WINDOW_SECONDS
        database.execute(
            """
            INSERT INTO oauth_source_limits
                (scope_hash, purpose, window_started, request_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(scope_hash, purpose) DO UPDATE SET
                request_count=oauth_source_limits.request_count+1
            """,
            (scope, purpose, now),
        )
        return True, 0

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
        if set(value) != {"username", "password"}:
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
        if set(value) - {"username", "displayName", "password"}:
            return self.json_reply(400, {"error": "Account roles or unsupported fields cannot be requested."})
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

    def generic_recovery_reply(self):
        """Return one non-enumerating response for every recovery outcome."""
        with connect() as database:
            contact_url = get_setting(database, "contact_page_url", "")
        return self.json_reply(200, {
            "ok": True,
            "message": "If the account and unused recovery code were valid, the password was changed. Sign in with the new password.",
            "contactPageUrl": contact_url,
        }, [("Set-Cookie", self.session_cookie("", 0))])

    def recover_password(self):
        """Consume one recovery code atomically and revoke every connected session."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.generic_recovery_reply()
        if set(value) != {"username", "recoveryCode", "newPassword"}:
            return self.generic_recovery_reply()
        username = value.get("username")
        code = value.get("recoveryCode")
        password = value.get("newPassword")
        if not all(isinstance(item, str) for item in (username, code, password)):
            return self.generic_recovery_reply()
        if len(username) > 40 or len(code) > 80 or not validate_password(password):
            return self.generic_recovery_reply()
        now = int(time.time())
        source_scope = self.attempt_scope("recovery-source")
        account_scope = hashlib.sha256(
            ("recovery-account\0" + username.casefold()).encode("utf-8")
        ).hexdigest()
        with connect() as database:
            accepted, remaining, _ = self.reserve_attempt(
                database, source_scope, now, RECOVERY_LIMIT
            )
        if not accepted:
            return self.json_reply(429, {"error": "Too many attempts. Try again later."}, {"Retry-After": str(remaining)})
        with connect() as database:
            accepted, remaining, _ = self.reserve_attempt(
                database, account_scope, now, RECOVERY_LIMIT
            )
        if not accepted:
            return self.json_reply(429, {"error": "Too many attempts. Try again later."}, {"Retry-After": str(remaining)})
        password_hash = hash_password(password)
        success = False
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            user = database.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone()
            rows = database.execute(
                """
                SELECT * FROM recovery_codes
                WHERE user_id=? AND confirmed_at IS NOT NULL AND used_at IS NULL
                """, (user["id"] if user else -1,)
            ).fetchall()
            matched = next((row for row in rows if verify_recovery_code(
                code, row["salt"], row["code_hash"]
            )), None)
            if user and user["is_active"] and not user["archived_at"] and matched:
                changed = database.execute(
                    "UPDATE recovery_codes SET used_at=? WHERE id=? AND used_at IS NULL",
                    (now, matched["id"]),
                )
                if changed.rowcount == 1:
                    database.execute(
                        """
                        UPDATE users SET password_hash=?, must_change_password=0,
                            recovery_setup_required=0, updated_at=? WHERE id=?
                        """, (password_hash, now, user["id"]),
                    )
                    database.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
                    revoke_user_oauth(database, user["id"], now)
                    database.execute(
                        "INSERT INTO security_events (event_type, subject_user_id, created_at) VALUES ('password_recovered', ?, ?)",
                        (user["id"], now),
                    )
                    success = True
        if success:
            with connect() as database:
                self.release_login_attempt(database, source_scope)
            with connect() as database:
                self.release_login_attempt(database, account_scope)
        return self.generic_recovery_reply()

    def generate_account_recovery_codes(self, session):
        """Create a replacement recovery set and return plaintext exactly once."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Invalid recovery setup."})
        if set(value) - {"currentPassword"}:
            return self.json_reply(400, {"error": "Invalid recovery setup."})
        with connect() as database:
            user = database.execute("SELECT * FROM users WHERE id=?", (session["id"],)).fetchone()
        existing_setup = not bool(user["recovery_setup_required"])
        if existing_setup:
            current = value.get("currentPassword", "")
            if not isinstance(current, str) or not verify_password(current, user["password_hash"]):
                return self.json_reply(403, {"error": "Current password is incorrect."})
        codes = generate_recovery_codes()
        set_id = secrets.token_hex(16)
        now = int(time.time())
        hashed = [(set_id, *hash_recovery_code(code), now) for code in codes]
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute("DELETE FROM recovery_codes WHERE user_id=?", (session["id"],))
            database.executemany(
                """
                INSERT INTO recovery_codes
                    (user_id, set_id, salt, code_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """, ((session["id"], *item) for item in hashed),
            )
            database.execute(
                "INSERT INTO security_events (event_type, actor_user_id, subject_user_id, created_at) VALUES ('recovery_codes_generated', ?, ?, ?)",
                (session["id"], session["id"], now),
            )
        return self.json_reply(201, {"codes": codes, "setId": set_id})

    def confirm_account_recovery_codes(self, session):
        """Confirm possession of one freshly generated code without consuming it."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Enter one recovery code."})
        if set(value) != {"setId", "recoveryCode"}:
            return self.json_reply(400, {"error": "Enter one recovery code."})
        set_id, code = value["setId"], value["recoveryCode"]
        if not isinstance(set_id, str) or len(set_id) != 32 or not isinstance(code, str) or len(code) > 80:
            return self.json_reply(400, {"error": "Enter one recovery code."})
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            rows = database.execute(
                "SELECT * FROM recovery_codes WHERE user_id=? AND set_id=? AND confirmed_at IS NULL AND created_at>?",
                (session["id"], set_id, now - RECOVERY_SETUP_SECONDS),
            ).fetchall()
            if not any(verify_recovery_code(code, row["salt"], row["code_hash"]) for row in rows):
                return self.json_reply(400, {"error": "That code did not match the new set."})
            database.execute(
                "UPDATE recovery_codes SET confirmed_at=? WHERE user_id=? AND set_id=?",
                (now, session["id"], set_id),
            )
            database.execute(
                "UPDATE users SET recovery_setup_required=0, updated_at=? WHERE id=?",
                (now, session["id"]),
            )
        return self.json_reply(200, {"ok": True})

    def admin_reset_password(self, path, session):
        """Replace one password, invalidate credentials, and return the temporary value once."""
        try:
            user_id = int(path.split("/")[4])
            value = self.read_json(AUTH_MAX_BYTES)
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid password reset."})
        if set(value) - {"temporaryPassword", "requireChange"}:
            return self.json_reply(400, {"error": "Invalid password reset."})
        require_change = value.get("requireChange", True)
        if type(require_change) is not bool:
            return self.json_reply(400, {"error": "Require change must be true or false."})
        temporary = value.get("temporaryPassword") or secrets.token_urlsafe(18)
        if not validate_password(temporary):
            return self.json_reply(400, {"error": "Use a temporary password between 12 and 256 characters."})
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            target = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                return self.json_reply(404, {"error": "User not found."})
            database.execute(
                """
                UPDATE users SET password_hash=?, must_change_password=?,
                    recovery_setup_required=1, updated_at=? WHERE id=?
                """, (hash_password(temporary), 1 if require_change else 0, now, user_id),
            )
            database.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            database.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
            database.execute("DELETE FROM oauth_codes WHERE user_id=?", (user_id,))
            revoke_user_oauth(database, user_id, now)
            database.execute(
                "INSERT INTO security_events (event_type, actor_user_id, subject_user_id, created_at) VALUES ('admin_password_reset', ?, ?, ?)",
                (session["id"], user_id, now),
            )
        headers = [("Set-Cookie", self.session_cookie("", 0))] if user_id == session["id"] else None
        return self.json_reply(200, {
            "ok": True, "temporaryPassword": temporary,
            "requireChange": require_change,
            "message": "Copy the temporary password now. It will not be shown again.",
        }, headers)

    def prompt_scope(self, database, user_id, project_id, prompt_id):
        """Confirm a project and prompt ID belong to the authenticated workspace."""
        row = database.execute("SELECT data FROM workspaces WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return False
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            return False
        return any(
            prompt.get("id") == prompt_id
            for project in data.get("projects", []) if isinstance(project, dict) and project.get("id") == project_id
            for prompt in project.get("prompts", []) if isinstance(prompt, dict)
        )

    def attachment_path_parts(self, path):
        """Parse a project-scoped prompt attachment route conservatively."""
        parts = path.strip("/").split("/")
        if len(parts) not in {6, 7} or parts[:2] != ["api", "projects"] or parts[3] != "prompts" or parts[5] != "attachments":
            raise ValueError("Invalid attachment path")
        project_id, prompt_id = parts[2], parts[4]
        if not IDENTIFIER_PATTERN.fullmatch(project_id) or not IDENTIFIER_PATTERN.fullmatch(prompt_id):
            raise ValueError("Invalid attachment scope")
        attachment_id = int(parts[6]) if len(parts) == 7 else None
        return project_id, prompt_id, attachment_id

    @staticmethod
    def serialize_attachment(row):
        """Return private attachment metadata without its random storage name."""
        return {
            "id": row["id"], "filename": row["filename"],
            "mimeType": row["mime_type"], "byteSize": row["byte_size"],
            "createdAt": row["created_at"],
        }

    def list_prompt_attachments(self, path, session):
        """List files attached to one caller-owned project prompt."""
        try:
            project_id, prompt_id, attachment_id = self.attachment_path_parts(path)
        except ValueError:
            return self.json_reply(404, {"error": "Prompt not found."})
        if attachment_id is not None:
            return self.get_prompt_attachment(path, session)
        with connect() as database:
            if not self.prompt_scope(database, session["id"], project_id, prompt_id):
                return self.json_reply(404, {"error": "Prompt not found."})
            rows = database.execute(
                "SELECT * FROM prompt_attachments WHERE user_id=? AND project_id=? AND prompt_id=? ORDER BY id",
                (session["id"], project_id, prompt_id),
            ).fetchall()
        return self.json_reply(200, {"attachments": [self.serialize_attachment(row) for row in rows]})

    def get_prompt_attachment(self, path, session):
        """Download or safely preview one authenticated private attachment."""
        try:
            project_id, prompt_id, attachment_id = self.attachment_path_parts(path)
        except ValueError:
            return self.json_reply(404, {"error": "Attachment not found."})
        with connect() as database:
            row = database.execute(
                "SELECT * FROM prompt_attachments WHERE id=? AND user_id=? AND project_id=? AND prompt_id=?",
                (attachment_id, session["id"], project_id, prompt_id),
            ).fetchone()
        if not row:
            return self.json_reply(404, {"error": "Attachment not found."})
        try:
            data = (attachment_root() / str(session["id"]) / row["storage_id"]).read_bytes()
        except FileNotFoundError:
            return self.json_reply(404, {"error": "Attachment not found."})
        disposition = "inline" if row["mime_type"].startswith("image/") else "attachment"
        safe_name = row["filename"].replace('"', "")
        return self.reply(200, data, row["mime_type"], {
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        })

    def put_prompt_attachment(self, path, session):
        """Validate and persist one private prompt attachment with bounded totals."""
        try:
            project_id, prompt_id, attachment_id = self.attachment_path_parts(path)
            if attachment_id is not None:
                raise ValueError("Replace is not supported")
            filename = unquote(self.headers.get("X-File-Name", ""))
            claimed = self.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
            if not filename or len(filename) > 200 or any(character in filename for character in "/\\\0"):
                raise ValueError("Invalid filename")
            data = self.read_body(MAX_PROMPT_ATTACHMENT_BYTES)
            mime_type = detect_prompt_attachment(data, filename, claimed)
            if not mime_type:
                raise ValueError("Invalid file")
        except ValueError:
            return self.json_reply(400, {"error": "Use a valid PDF, DOCX, Markdown, text, PNG, JPEG, or WebP file up to 20 MB."})
        storage_id = secrets.token_hex(24)
        directory = attachment_root() / str(session["id"])
        directory.mkdir(parents=True, exist_ok=True)
        location = directory / storage_id
        location.write_bytes(data)
        try:
            with connect() as database:
                database.execute("BEGIN IMMEDIATE")
                if not self.prompt_scope(database, session["id"], project_id, prompt_id):
                    location.unlink(missing_ok=True)
                    return self.json_reply(404, {"error": "Prompt not found."})
                count, total = database.execute(
                    "SELECT COUNT(*), COALESCE(SUM(byte_size), 0) FROM prompt_attachments WHERE user_id=? AND project_id=? AND prompt_id=?",
                    (session["id"], project_id, prompt_id),
                ).fetchone()
                if count >= MAX_PROMPT_ATTACHMENTS or total + len(data) > MAX_PROMPT_ATTACHMENT_TOTAL:
                    location.unlink(missing_ok=True)
                    return self.json_reply(413, {"error": "This prompt reached its 20-file or 100 MB attachment limit."})
                cursor = database.execute(
                    """
                    INSERT INTO prompt_attachments
                        (storage_id, user_id, project_id, prompt_id, filename, mime_type, byte_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (storage_id, session["id"], project_id, prompt_id, filename, mime_type, len(data), int(time.time())),
                )
                row = database.execute("SELECT * FROM prompt_attachments WHERE id=?", (cursor.lastrowid,)).fetchone()
        except Exception:
            location.unlink(missing_ok=True)
            raise
        return self.json_reply(201, {"attachment": self.serialize_attachment(row)})

    def delete_prompt_attachment(self, path, session):
        """Delete one caller-owned attachment record before removing its bytes."""
        try:
            project_id, prompt_id, attachment_id = self.attachment_path_parts(path)
            if attachment_id is None:
                raise ValueError("Missing attachment")
        except ValueError:
            return self.json_reply(400, {"error": "Invalid attachment."})
        with connect() as database:
            row = database.execute(
                "SELECT * FROM prompt_attachments WHERE id=? AND user_id=? AND project_id=? AND prompt_id=?",
                (attachment_id, session["id"], project_id, prompt_id),
            ).fetchone()
            if not row:
                return self.json_reply(404, {"error": "Attachment not found."})
            database.execute("DELETE FROM prompt_attachments WHERE id=?", (attachment_id,))
        (attachment_root() / str(session["id"]) / row["storage_id"]).unlink(missing_ok=True)
        return self.json_reply(200, {"ok": True})

    def get_workspace(self, session):
        """Return only the workspace belonging to the authenticated user."""
        with connect() as database:
            row = database.execute(
                "SELECT revision, data FROM workspaces WHERE user_id=?",
                (session["id"],),
            ).fetchone()
        if not row:
            return self.json_reply(200, {"revision": 0, "data": None})
        data, changed = normalize_workspace_data(json.loads(row["data"]))
        if changed:
            with connect() as database:
                database.execute(
                    "UPDATE workspaces SET data=? WHERE user_id=?",
                    (json.dumps(data), session["id"]),
                )
        with connect() as database:
            image_ids = [
                item["character_id"]
                for item in database.execute(
                    "SELECT character_id FROM character_images WHERE user_id=?",
                    (session["id"],),
                ).fetchall()
            ]
        return self.json_reply(
            200,
            {
                "revision": row["revision"],
                "data": data,
                "imageCharacterIds": image_ids,
            },
        )

    def put_workspace(self, session):
        """Save one user's validated workspace with optimistic conflict detection."""
        try:
            value = self.read_json()
            if set(value) != {"revision", "data"}:
                raise ValueError("Unknown workspace field")
            revision, data = value["revision"], value["data"]
            if (
                type(revision) is not int
                or revision < 0
                or not isinstance(data, dict)
                or not isinstance(data.get("projects"), list)
            ):
                raise ValueError("Invalid workspace")
            if not all(
                isinstance(project, dict)
                and isinstance(project.get("episodes"), list)
                and isinstance(project.get("characters"), list)
                for project in data["projects"]
            ):
                raise ValueError("Invalid projects")
            if len(data["projects"]) > 100:
                raise ValueError("Too many projects")
            prompt_fields = {
                "id", "name", "category", "purpose", "body", "modelSettings",
                "updatedAt", "archived", "sourceUrl", "sourceNotes",
            }
            for project in data["projects"]:
                prompts = project.get("prompts", [])
                if not isinstance(prompts, list) or len(prompts) > 100:
                    raise ValueError("Invalid prompts")
                for prompt in prompts:
                    if not isinstance(prompt, dict) or set(prompt) - prompt_fields:
                        raise ValueError("Invalid prompt fields")
                    if (not isinstance(prompt.get("body", ""), str)
                            or len(prompt.get("body", "")) > MAX_PROMPT_BODY
                            or not isinstance(prompt.get("sourceNotes", ""), str)
                            or len(prompt.get("sourceNotes", "")) > MAX_PROMPT_NOTES):
                        raise ValueError("Prompt text is too long")
                    source_url = prompt.get("sourceUrl", "")
                    if source_url and not validate_https_url(source_url):
                        raise ValueError("Invalid prompt source URL")
        except (ValueError, KeyError, TypeError):
            return self.json_reply(400, {"error": "Invalid workspace."})
        data, _ = normalize_workspace_data(data)
        character_ids = {
            character.get("id")
            for project in data["projects"]
            for character in project.get("characters", [])
            if isinstance(character, dict) and character.get("id")
        }
        prompt_scopes = {
            (project.get("id"), prompt.get("id"))
            for project in data["projects"] if isinstance(project, dict)
            for prompt in project.get("prompts", []) if isinstance(prompt, dict)
        }
        removed_files = []
        removed_attachments = []
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            image_rows = database.execute(
                "SELECT storage_id, character_id FROM character_images WHERE user_id=?",
                (session["id"],),
            ).fetchall()
            removed_files = [
                row["storage_id"]
                for row in image_rows
                if row["character_id"] not in character_ids
            ]
            attachment_rows = database.execute(
                "SELECT storage_id, project_id, prompt_id FROM prompt_attachments WHERE user_id=?",
                (session["id"],),
            ).fetchall()
            removed_attachments = [row["storage_id"] for row in attachment_rows if (row["project_id"], row["prompt_id"]) not in prompt_scopes]
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
            if removed_files:
                database.executemany(
                    "DELETE FROM character_images WHERE storage_id=?",
                    ((storage_id,) for storage_id in removed_files),
                )
            if removed_attachments:
                database.executemany(
                    "DELETE FROM prompt_attachments WHERE storage_id=?",
                    ((storage_id,) for storage_id in removed_attachments),
                )
        for storage_id in removed_files:
            (image_root() / str(session["id"]) / storage_id).unlink(missing_ok=True)
        for storage_id in removed_attachments:
            (attachment_root() / str(session["id"]) / storage_id).unlink(missing_ok=True)
        return self.json_reply(200, {"revision": revision + 1})

    def update_account(self, session):
        """Change display name, theme, or password for the current account."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Invalid account update."})
        if set(value) - {"displayName", "theme", "currentPassword", "newPassword"}:
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
            updates.append("must_change_password=0")

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
                now = int(time.time())
                database.execute(
                    "UPDATE oauth_grants SET revoked_at=? WHERE user_id=?",
                    (now, session["id"]),
                )
                database.execute(
                    """
                    UPDATE oauth_tokens SET revoked_at=?
                    WHERE grant_id IN (
                        SELECT id FROM oauth_grants WHERE user_id=?
                    )
                    """,
                    (now, session["id"]),
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
                SELECT * FROM users
                ORDER BY created_at, id
                """
            ).fetchall()
        users = []
        for row in rows:
            item = public_user(row)
            item["createdAt"] = row["created_at"]
            with connect() as permission_database:
                item["mcpPermissions"] = mcp_permissions(permission_database, row["id"], row["role"])
            users.append(item)
        return self.json_reply(200, {"users": users})

    def update_admin_settings(self):
        """Update bounded public registration and support-link settings."""
        try:
            value = self.read_json(AUTH_MAX_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Invalid settings update."})
        if not value or set(value) - {"registrationEnabled", "contactPageUrl"}:
            return self.json_reply(400, {"error": "Invalid settings update."})
        if "registrationEnabled" in value and type(value["registrationEnabled"]) is not bool:
            return self.json_reply(400, {"error": "Registration setting must be true or false."})
        contact_url = value.get("contactPageUrl")
        if contact_url is not None:
            if not isinstance(contact_url, str):
                return self.json_reply(400, {"error": "Contact page URL must be HTTPS."})
            contact_url = contact_url.strip()
            if contact_url and not validate_https_url(contact_url):
                return self.json_reply(400, {"error": "Contact page URL must be HTTPS."})
        with connect() as database:
            if "registrationEnabled" in value:
                set_setting(database, "registration_enabled", "1" if value["registrationEnabled"] else "0")
            if contact_url is not None:
                set_setting(database, "contact_page_url", contact_url)
            enabled = registration_enabled(database)
            saved_contact = get_setting(database, "contact_page_url", "")
        return self.json_reply(200, {"registrationEnabled": enabled, "contactPageUrl": saved_contact})
    def active_admin_count(self, database):
        """Count administrators who are active and not archived."""
        return database.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role='admin' AND is_active=1 AND archived_at IS NULL
            """
        ).fetchone()[0]

    def update_user_mcp_permissions(self, path):
        """Set independent MCP entitlements and revoke tokens on every reduction."""
        try:
            user_id = int(path.split("/")[4])
            value = self.read_json(AUTH_MAX_BYTES)
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid MCP permissions."})
        expected = {"enabled", "read", "write", "archive", "delete"}
        if set(value) != expected or any(type(value[key]) is not bool for key in expected):
            return self.json_reply(400, {"error": "Supply every MCP permission as true or false."})
        if value["enabled"] and not any(value[key] for key in expected - {"enabled"}):
            value["read"] = True
        if not value["enabled"] and any(value[key] for key in expected - {"enabled"}):
            return self.json_reply(400, {"error": "Disabled MCP access cannot include permissions."})
        now = int(time.time())
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            user = database.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                return self.json_reply(404, {"error": "User not found."})
            if user["role"] == "admin":
                return self.json_reply(409, {"error": "Administrators retain full MCP access."})
            old = mcp_permissions(database, user_id, user["role"])
            database.execute(
                """
                INSERT INTO mcp_permissions
                    (user_id, enabled, can_read, can_write, can_archive, can_delete, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    enabled=excluded.enabled, can_read=excluded.can_read,
                    can_write=excluded.can_write, can_archive=excluded.can_archive,
                    can_delete=excluded.can_delete, updated_at=excluded.updated_at
                """, (user_id, int(value["enabled"]), int(value["read"]), int(value["write"]), int(value["archive"]), int(value["delete"]), now),
            )
            reduced = any(old[key] and not value[key] for key in expected)
            if reduced:
                revoke_user_oauth(database, user_id, now)
            database.execute(
                "INSERT INTO security_events (event_type, subject_user_id, created_at) VALUES ('mcp_permissions_changed', ?, ?)",
                (user_id, now),
            )
        return self.json_reply(200, {"mcpPermissions": value})

    def update_user(self, path, session):
        """Apply one explicit account lifecycle or role action."""
        try:
            user_id = int(path.rsplit("/", 1)[1])
            value = self.read_json(AUTH_MAX_BYTES)
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid user update."})
        if set(value) - {"action", "role", "active"}:
            return self.json_reply(400, {"error": "Invalid user update."})
        action = value.get("action")
        role = value.get("role")
        legacy_active = value.get("active")
        if (
            action is None
            and isinstance(role, str)
            and role in {"admin", "user"}
            and type(legacy_active) is bool
        ):
            action = "legacy"
        if action not in {"disable", "archive", "restore", "role", "legacy"}:
            return self.json_reply(400, {"error": "Choose a valid account action."})
        if action in {"role", "legacy"} and (
            not isinstance(role, str) or role not in {"admin", "user"}
        ):
            return self.json_reply(400, {"error": "Choose a valid role."})
        if user_id == session["id"] and action in {"disable", "archive"}:
            return self.json_reply(409, {"error": "You cannot disable or archive yourself."})
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            target = database.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return self.json_reply(404, {"error": "User not found."})
            removes_admin = target["role"] == "admin" and (
                action in {"disable", "archive"}
                or (action in {"role", "legacy"} and role != "admin")
                or (action == "legacy" and not legacy_active)
            )
            if removes_admin and target["is_active"] and not target["archived_at"]:
                if self.active_admin_count(database) <= 1:
                    return self.json_reply(
                        409, {"error": "At least one active admin is required."}
                    )
            now = int(time.time())
            if action == "disable":
                database.execute(
                    "UPDATE users SET is_active=0, updated_at=? WHERE id=?",
                    (now, user_id),
                )
                database.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            elif action == "archive":
                database.execute(
                    """
                    UPDATE users SET is_active=0, archived_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (now, now, user_id),
                )
                database.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            elif action == "restore":
                database.execute(
                    """
                    UPDATE users SET is_active=1, archived_at=NULL, updated_at=?
                    WHERE id=?
                    """,
                    (now, user_id),
                )
            elif action == "role":
                database.execute(
                    "UPDATE users SET role=?, updated_at=? WHERE id=?",
                    (role, now, user_id),
                )
            else:
                database.execute(
                    """
                    UPDATE users SET role=?, is_active=?, updated_at=?
                    WHERE id=?
                    """,
                    (role, 1 if legacy_active else 0, now, user_id),
                )
                if not legacy_active:
                    database.execute(
                        "DELETE FROM sessions WHERE user_id=?", (user_id,)
                    )
            if action in {"disable", "archive"} or (action == "legacy" and not legacy_active):
                revoke_user_oauth(database, user_id, now)
            updated = database.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
        return self.json_reply(200, {"user": public_user(updated)})

    def delete_user(self, path, session):
        """Permanently remove one account and its cascaded private records."""
        try:
            user_id = int(path.rsplit("/", 1)[1])
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid user."})
        if user_id == session["id"]:
            return self.json_reply(409, {"error": "You cannot delete yourself."})
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            target = database.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return self.json_reply(404, {"error": "User not found."})
            if (
                target["role"] == "admin"
                and target["is_active"]
                and not target["archived_at"]
                and self.active_admin_count(database) <= 1
            ):
                return self.json_reply(
                    409, {"error": "At least one active admin is required."}
                )
            database.execute("DELETE FROM users WHERE id=?", (user_id,))
        shutil.rmtree(image_root() / str(user_id), ignore_errors=True)
        shutil.rmtree(attachment_root() / str(user_id), ignore_errors=True)
        return self.json_reply(200, {"ok": True})

    def tool_payload_from_value(self, value):
        """Validate a decoded tool payload and reject unsupported fields."""
        allowed = {"action", "name", "category", "url", "purpose", "notes", "userIds"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("Invalid tool fields")
        fields = {key: value.get(key, "") for key in ("name", "category", "url", "purpose", "notes")}
        if not all(isinstance(item, str) for item in fields.values()):
            raise ValueError("Invalid tool fields")
        fields = {key: item.strip() for key, item in fields.items()}
        if (not fields["name"] or len(fields["name"]) > 100 or not fields["category"]
                or len(fields["category"]) > 60 or not fields["purpose"]
                or len(fields["purpose"]) > 300 or len(fields["notes"]) > 500
                or not validate_https_url(fields["url"])):
            raise ValueError("Invalid tool fields")
        return fields

    def tool_payload(self):
        """Read and validate a bounded tool catalog record."""
        return self.tool_payload_from_value(self.read_json(AUTH_MAX_BYTES))

    @staticmethod
    def serialize_tool(row, session):
        """Serialize ownership and capabilities without exposing assignments."""
        owner_id = row["owner_user_id"]
        admin = session["role"] == "admin"
        own = owner_id == session["id"]
        return {
            "id": row["id"], "name": row["name"], "category": row["category"],
            "url": row["url"], "purpose": row["purpose"], "notes": row["notes"],
            "archived": bool(row["archived_at"]), "ownerUserId": owner_id,
            "adminCreated": owner_id is None, "canManage": admin or own,
            "assigned": bool(row["assigned"]) if "assigned" in row.keys() else False,
            "assignedUserIds": ([int(item) for item in row["assigned_user_ids"].split(",") if item] if "assigned_user_ids" in row.keys() and row["assigned_user_ids"] else []),
        }

    def get_tools(self, session):
        """List only owned or explicitly assigned tools for regular users."""
        with connect() as database:
            if session["role"] == "admin":
                rows = database.execute(
                    """SELECT tools.*, 0 AS assigned, COALESCE((
                        SELECT GROUP_CONCAT(a.user_id) FROM tool_assignments a WHERE a.tool_id=tools.id
                    ), '') AS assigned_user_ids FROM tools ORDER BY category, name, id"""
                ).fetchall()
            else:
                rows = database.execute(
                    """
                    SELECT tools.*, EXISTS(
                        SELECT 1 FROM tool_assignments a
                        WHERE a.tool_id=tools.id AND a.user_id=?
                    ) AS assigned
                    FROM tools
                    WHERE tools.archived_at IS NULL AND (
                        tools.owner_user_id=? OR (
                            tools.owner_user_id IS NULL AND EXISTS(
                                SELECT 1 FROM tool_assignments a
                                WHERE a.tool_id=tools.id AND a.user_id=?
                            )
                        )
                    )
                    ORDER BY category, name, id
                    """, (session["id"], session["id"], session["id"]),
                ).fetchall()
        return self.json_reply(200, {"tools": [self.serialize_tool(row, session) for row in rows]})

    def create_tool(self, session):
        """Create an admin catalog tool or a private user-owned tool."""
        try:
            value = self.tool_payload()
        except ValueError:
            return self.json_reply(400, {"error": "Enter valid tool details and an HTTPS URL."})
        now = int(time.time())
        owner_id = None if session["role"] == "admin" else session["id"]
        with connect() as database:
            cursor = database.execute(
                """
                INSERT INTO tools
                    (name, category, url, purpose, notes, owner_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (*value.values(), owner_id, now, now),
            )
            row = database.execute("SELECT tools.*, 0 AS assigned FROM tools WHERE id=?", (cursor.lastrowid,)).fetchone()
        return self.json_reply(201, {"tool": self.serialize_tool(row, session)})

    def update_tool(self, path, session):
        """Edit a manageable tool or apply admin-only lifecycle and assignments."""
        try:
            tool_id = int(path.rstrip("/").rsplit("/", 1)[1])
            value = self.read_json(AUTH_MAX_BYTES)
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid tool update."})
        action = value.get("action", "edit")
        with connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if not row:
                return self.json_reply(404, {"error": "Tool not found."})
            admin = session["role"] == "admin"
            own = row["owner_user_id"] == session["id"]
            if not admin and not own:
                return self.json_reply(403, {"error": "This assigned tool is view and use only."})
            now = int(time.time())
            if action in {"archive", "restore"}:
                database.execute("UPDATE tools SET archived_at=?, updated_at=? WHERE id=?", (now if action == "archive" else None, now, tool_id))
            elif action == "assign" and admin and row["owner_user_id"] is None:
                user_ids = value.get("userIds")
                if not isinstance(user_ids, list) or len(user_ids) > MAX_USERS or any(type(item) is not int for item in user_ids):
                    return self.json_reply(400, {"error": "Choose valid users."})
                valid = {item["id"] for item in database.execute(
                    "SELECT id FROM users WHERE role='user' AND is_active=1 AND archived_at IS NULL"
                ).fetchall()}
                if set(user_ids) - valid:
                    return self.json_reply(400, {"error": "Choose valid users."})
                database.execute("DELETE FROM tool_assignments WHERE tool_id=?", (tool_id,))
                database.executemany(
                    "INSERT INTO tool_assignments (tool_id, user_id, created_at) VALUES (?, ?, ?)",
                    ((tool_id, user_id, now) for user_id in sorted(set(user_ids))),
                )
            elif action == "edit":
                try:
                    fields = self.tool_payload_from_value(value)
                except ValueError:
                    return self.json_reply(400, {"error": "Enter valid tool details and an HTTPS URL."})
                database.execute(
                    "UPDATE tools SET name=?, category=?, url=?, purpose=?, notes=?, updated_at=? WHERE id=?",
                    (*fields.values(), now, tool_id),
                )
            else:
                return self.json_reply(400, {"error": "Choose a valid tool action."})
            updated = database.execute("SELECT tools.*, 0 AS assigned FROM tools WHERE id=?", (tool_id,)).fetchone()
        return self.json_reply(200, {"tool": self.serialize_tool(updated, session)})

    def delete_tool(self, path, session):
        """Delete a user-owned tool, or any tool when requested by an admin."""
        try:
            tool_id = int(path.rsplit("/", 1)[1])
        except (ValueError, IndexError):
            return self.json_reply(400, {"error": "Invalid tool."})
        with connect() as database:
            row = database.execute("SELECT owner_user_id FROM tools WHERE id=?", (tool_id,)).fetchone()
            if not row:
                return self.json_reply(404, {"error": "Tool not found."})
            if session["role"] != "admin" and row["owner_user_id"] != session["id"]:
                return self.json_reply(403, {"error": "This assigned tool is view and use only."})
            database.execute("DELETE FROM tools WHERE id=?", (tool_id,))
        return self.json_reply(200, {"ok": True})

    def character_id_from_path(self, path):
        """Extract a conservative character identifier from an image route."""
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "characters"] or parts[3] != "image":
            raise ValueError("Invalid image path")
        character_id = parts[2]
        if not IDENTIFIER_PATTERN.fullmatch(character_id):
            raise ValueError("Invalid character id")
        return character_id

    def user_has_character(self, database, user_id, character_id):
        """Confirm that a character identifier belongs to one user's workspace."""
        row = database.execute(
            "SELECT data FROM workspaces WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return False
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            return False
        return any(
            character.get("id") == character_id
            for project in data.get("projects", []) if isinstance(project, dict)
            for character in project.get("characters", []) if isinstance(character, dict)
        )

    def get_character_image(self, path, session):
        """Return a private character image only to its owning account."""
        try:
            character_id = self.character_id_from_path(path)
        except ValueError:
            return self.json_reply(404, {"error": "Image not found."})
        with connect() as database:
            row = database.execute(
                """
                SELECT storage_id, mime_type FROM character_images
                WHERE user_id=? AND character_id=?
                """,
                (session["id"], character_id),
            ).fetchone()
        if not row:
            return self.json_reply(404, {"error": "Image not found."})
        location = image_root() / str(session["id"]) / row["storage_id"]
        try:
            data = location.read_bytes()
        except FileNotFoundError:
            return self.json_reply(404, {"error": "Image not found."})
        return self.reply(200, data, row["mime_type"], {"Cache-Control": "private, no-store"})

    def put_character_image(self, path, session):
        """Validate and replace one private character reference image."""
        try:
            character_id = self.character_id_from_path(path)
            data = self.read_body(MAX_IMAGE_BYTES)
        except ValueError:
            return self.json_reply(400, {"error": "Choose an image up to 5 MB."})
        mime_type = detect_image_type(data)
        if not mime_type:
            return self.json_reply(400, {"error": "Use an actual PNG, JPEG, or WebP image."})
        storage_id = secrets.token_hex(24)
        directory = image_root() / str(session["id"])
        directory.mkdir(parents=True, exist_ok=True)
        location = directory / storage_id
        location.write_bytes(data)
        old_storage_id = None
        try:
            with connect() as database:
                database.execute("BEGIN IMMEDIATE")
                if not self.user_has_character(database, session["id"], character_id):
                    location.unlink(missing_ok=True)
                    return self.json_reply(404, {"error": "Character not found."})
                old = database.execute(
                    """
                    SELECT storage_id FROM character_images
                    WHERE user_id=? AND character_id=?
                    """,
                    (session["id"], character_id),
                ).fetchone()
                old_storage_id = old["storage_id"] if old else None
                database.execute(
                    """
                    INSERT INTO character_images
                        (storage_id, user_id, character_id, mime_type, byte_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, character_id) DO UPDATE SET
                        storage_id=excluded.storage_id,
                        mime_type=excluded.mime_type,
                        byte_size=excluded.byte_size,
                        created_at=excluded.created_at
                    """,
                    (storage_id, session["id"], character_id, mime_type, len(data), int(time.time())),
                )
        except Exception:
            location.unlink(missing_ok=True)
            raise
        if old_storage_id:
            (directory / old_storage_id).unlink(missing_ok=True)
        return self.json_reply(200, {"ok": True, "imageUrl": path})

    def delete_character_image(self, path, session):
        """Remove one private image record and its stored bytes."""
        try:
            character_id = self.character_id_from_path(path)
        except ValueError:
            return self.json_reply(400, {"error": "Invalid character image."})
        with connect() as database:
            row = database.execute(
                """
                SELECT storage_id FROM character_images
                WHERE user_id=? AND character_id=?
                """,
                (session["id"], character_id),
            ).fetchone()
            if not row:
                return self.json_reply(404, {"error": "Image not found."})
            database.execute(
                "DELETE FROM character_images WHERE user_id=? AND character_id=?",
                (session["id"], character_id),
            )
        (image_root() / str(session["id"]) / row["storage_id"]).unlink(missing_ok=True)
        return self.json_reply(200, {"ok": True})


if __name__ == "__main__":
    setup()
    ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("PORT", "8787"))), Handler
    ).serve_forever()
