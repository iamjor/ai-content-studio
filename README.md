# AI Content Studio

AI Content Studio is a self-hosted workspace for planning creative projects, episodes, characters, and repeatable AI-assisted production workflows. Each account has a private workspace, while administrators control registration, users, and a shared tools catalog.

## Current capabilities

- Private per-user projects, episodes, characters, workflow notes, and reference images
- Archive, restore, and confirmed deletion flows
- Administrator-managed users, registration policy, and shared tool catalog
- Dark and light themes with responsive navigation
- Text-only JSON workspace transfer and volume-level complete backup
- Non-destructive migration from the legacy single-owner workspace

The application uses a Python 3.13 standard-library HTTP service, SQLite, and a dependency-free HTML, CSS, and JavaScript frontend. Docker Compose is the supported packaged runtime. Native development requires a compatible Python 3 and Node.js for JavaScript syntax checks.

## Docker quick start

1. Copy `.env.example` to `.env`.
2. Replace the bootstrap administrator values with private, unique values. Use a password of at least 12 characters.
3. Keep `AICS_REGISTRATION_ENABLED=0` and `AICS_COOKIE_SECURE=1` for the first public HTTPS start.
4. Run `docker compose up -d --build`.
5. Check `docker compose ps` and `curl http://127.0.0.1:8787/healthz` on the host.
6. Put the loopback-bound service behind an HTTPS reverse proxy that preserves the public Host header.
7. After the administrator exists, remove the bootstrap password from `.env` and recreate the container.

The named `studio_data` volume stores `/data/studio.sqlite3` and `/data/images`. Never run `docker compose down -v` unless permanent deletion is intentional. Review the complete [deployment and upgrade guide](docs/DEPLOYMENT.md) before changing an existing installation.

## Local development

Use temporary data and disable Secure cookies only for local plain HTTP:

```sh
export AICS_ADMIN_USERNAME=local-admin
export AICS_ADMIN_DISPLAY_NAME="Local Admin"
export AICS_ADMIN_PASSWORD="local-development-password"
export AICS_DB_PATH=/tmp/ai-content-studio-dev.sqlite3
export AICS_COOKIE_SECURE=0
python3 server.py
```

Open `http://127.0.0.1:8787`. Never use `AICS_COOKIE_SECURE=0` for a publicly reachable installation. Keep `.env`, SQLite files, exports, backups, logs, and real media out of Git.

## Security defaults and limits

Registration starts disabled and can create regular users only. Passwords use salted PBKDF2-SHA256 records. Sessions are server-side, fixed-lifetime, and sent in HttpOnly, SameSite Strict cookies that are Secure by default. State changes require a session CSRF token and same-origin context. Login and enabled registration have bounded, source-based throttles; forwarded client addresses are accepted only from explicitly trusted proxy networks. Compose exposes the service on loopback only.

This personal project does not provide email verification, password-reset email, MFA, external identity, or an audit log. JSON export is text-only and excludes images. A complete backup must preserve both SQLite and `/data/images`. See [Security](docs/SECURITY.md) and the [technical reference](docs/TECHNICAL.md) for the trust model and known limitations.

## Documentation

- [Technical reference](docs/TECHNICAL.md)
- [Deployment, migration, backup, and rollback](docs/DEPLOYMENT.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Security policy](docs/SECURITY.md)
- [Public release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md)
- [Changelog](CHANGELOG.md)

## Release and license status

The repository is preparing for a possible public release. No license has been selected or added, so the project must not yet be described as open source. The owner must choose a license and explicitly approve any visibility change after completing the public-release checklist.
