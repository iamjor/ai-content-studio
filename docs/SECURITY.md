# Security

Do not post credentials, backups, private assets, session cookies, personal logs, or vulnerability details in public issues. Use GitHub private vulnerability reporting or a private owner contact listed on the verified public portfolio.

## Deployment requirements

Run behind HTTPS. Compose binds to `127.0.0.1`. Secure cookies are enabled by default and must remain enabled publicly.

Registration is disabled by default and creates regular users only. Open it only intentionally.

Passwords use salted PBKDF2-SHA256 records. Sessions are random, fixed-lifetime, stored server-side, and transported in HttpOnly, SameSite Strict cookies. State changes require a CSRF token. Login attempts are reserved atomically and throttled by source before password verification, and enabled registration has a separate per-source attempt limit. Forwarded client addresses are accepted only from explicitly configured trusted proxy networks.

Remote MCP access uses OAuth authorization code with S256 PKCE. Redirect URIs are registered and compared exactly. Access tokens are short-lived, refresh tokens rotate, replay revokes the token family, and only hashes are stored. Each request resolves one active account and checks aics.read or aics.write. Administrator role never grants access to another user workspace. The MCP proxy does not forward browser cookies, and browser CSRF and same-origin controls remain unchanged.

Set AICS_PUBLIC_BASE_URL to the exact external HTTPS origin. Never put bearer tokens or client credentials in URLs, source files, logs, browser exports, or plugin packages. Review connected client names, scopes, and last-use times in Account, and revoke access there when it is no longer needed. Ordinary browser logout does not revoke a separately consented integration.

MCP does not expose private image bytes, direct image upload or image-only deletion, user-account deletion, administrator functions, registration controls, deployment, publishing, shell access, arbitrary file or database access, AI generation, or paid APIs. Confirmed character and project deletion remove only their associated private images as part of the content deletion receipt.

Rotate exposed passwords immediately. Password changes revoke all user sessions and connected integration grants. Disable or archive accounts from Admin when access must stop. Both actions revoke sessions and preserve private data. Permanent deletion is separately confirmed and scoped to one selected account.

SQLite, private images, `.env`, exports, and backups are excluded from Git. Protect off-server backups and review proxy, access, and logging settings.

## Unsupported controls

This personal project has no email verification, password-reset email, MFA, external identity provider, audit-log retention, or an audit log. Add an external access layer or keep registration closed when those controls are required.
