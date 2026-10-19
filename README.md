<p align="center">
  <img src="dist/favicon.svg" width="96" height="96" alt="AI Content Studio film and story mark">
</p>

<h1 align="center">AI Content Studio</h1>

<p align="center">A private, self-hosted workspace for planning stories and AI-assisted media production.</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-60a5fa.svg"></a>
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB.svg">
</p>

AI Content Studio organizes project Bibles, episodes, shot plans, characters, reusable prompts, production gates, private reference images, and a shared tools catalog. Each account has a private workspace. Administrators control registration, account lifecycle, and the catalog.

## Features

- Private per-user projects, episodes, characters, workflow notes, and reference images
- Editable project Bibles, episode synopses and beats, and reorderable shot plans
- Project-scoped prompt libraries with stable shot prompt snapshots
- Character reference requirements, continuity locks, and manual production gates
- Archive, restore, and confirmed deletion flows
- Remote Streamable HTTP MCP access with OAuth 2.1, PKCE, narrow scopes, and revision-safe writes
- Account-visible connected integrations with explicit token revocation
- Administrator-managed users, registration policy, and shared tools
- Password hashing, server-side sessions, CSRF checks, and bounded authentication attempts
- Responsive dark and light themes with accessible navigation
- Text-only JSON workspace transfer and volume-level complete backup
- Non-destructive migration from the legacy single-owner workspace

## Supported runtime

The packaged runtime uses Python 3.13, SQLite, dependency-free HTML, CSS, and JavaScript, the official MCP Python SDK pinned through `requirements.in` and the hash-locked `requirements.txt`, and Docker Compose v2. Native development requires a compatible Python 3 runtime with the pinned requirements installed. Node.js is used only for optional JavaScript syntax checks.

## Docker quick start

1. Copy `.env.example` to `.env`.
2. Replace the bootstrap administrator values with private, unique values. Use a password of at least 12 characters.
3. Keep `AICS_REGISTRATION_ENABLED=0` and `AICS_COOKIE_SECURE=1` for the first public HTTPS start.
4. Set `AICS_PUBLIC_BASE_URL` to the exact external HTTPS origin, without a path or trailing slash.
5. Run `docker compose up -d --build`.
6. Check `docker compose ps`, `/healthz`, and `/mcp/ready` on the host.
7. Put the loopback-bound service behind an HTTPS reverse proxy that preserves the public Host header.
8. After the administrator exists, remove the bootstrap password from `.env` and recreate the container.

The named `studio_data` volume stores `/data/studio.sqlite3` and `/data/images`. Never run `docker compose down -v` unless permanent deletion is intentional. Read the complete [deployment and upgrade guide](docs/DEPLOYMENT.md) before changing an existing installation.

## Local development

Use temporary data and disable Secure cookies only for local plain HTTP:

```sh
export AICS_ADMIN_USERNAME=local-admin
export AICS_ADMIN_DISPLAY_NAME="Local Admin"
export AICS_ADMIN_PASSWORD="local-development-password"
export AICS_DB_PATH=/tmp/ai-content-studio-dev.sqlite3
export AICS_COOKIE_SECURE=0
export AICS_PUBLIC_BASE_URL=http://127.0.0.1:8787
python3 -m pip install --require-hashes -r requirements.txt
python3 launcher.py
```

Open `http://127.0.0.1:8787`. Never use `AICS_COOKIE_SECURE=0` for a publicly reachable installation. Keep `.env`, SQLite files, exports, backups, logs, and real media out of Git.

## Security defaults and limitations

Registration starts disabled and can create regular users only. Passwords use salted PBKDF2-SHA256 records. Sessions are server-side, fixed-lifetime, and sent in HttpOnly, SameSite Strict cookies that are Secure by default. State changes require a session CSRF token and same-origin context. Login, enabled account registration, public OAuth client registration, and OAuth authorization-flow creation have bounded, source-based throttles. Forwarded client addresses are accepted only from explicitly trusted proxy networks. Compose exposes the service on loopback only.

Remote MCP clients discover OAuth metadata on the same origin and use authorization code plus S256 PKCE. Access and refresh tokens are random and stored only as hashes. Browser cookies are not accepted as MCP credentials. Users can review and revoke integrations from Account. Private image upload and deletion remain browser-only.

Public OAuth client registrations are capped and unclaimed registrations expire after 30 days. Compose health checks both `/healthz` and `/mcp/ready`, so a stopped MCP worker makes the container unhealthy for operator monitoring or orchestration.

The project does not provide email verification, password-reset email, MFA, external identity, or an audit log. JSON export is text-only and excludes images. A complete backup must preserve both SQLite and `/data/images`. Report vulnerabilities through the private process in [Security](docs/SECURITY.md).

## Documentation

- [Technical reference](docs/TECHNICAL.md)
- [Deployment, migration, backup, and rollback](docs/DEPLOYMENT.md)
- [Version 0.3.0 release notes](docs/RELEASE_NOTES_v0.3.0.md)
- [Version 0.2.0 release notes](docs/RELEASE_NOTES_v0.2.0.md)
- [Version 0.1.0 release notes](docs/RELEASE_NOTES_v0.1.0.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Security policy](docs/SECURITY.md)
- [Changelog](CHANGELOG.md)

## Contributing

Review [Contributing](docs/CONTRIBUTING.md) before opening a change. Keep examples fictional and never commit credentials, private workspaces, databases, backups, logs, or personal media.

## License and release status

The source is licensed under the [MIT License](LICENSE). See [Releases](https://github.com/iamjor/ai-content-studio/releases) for published versions. A source release does not deploy or back up any installation.
