# AI Content Studio

AI Content Studio is a self-hosted project, episode, and character dashboard. It runs as one Python standard-library service with a SQLite database on a persistent Docker volume.

Each account has a private workspace. Administrators manage user access and decide whether regular-user registration is open. New registrations can never request an administrator role.

## Security defaults

- Registration is disabled on a new database.
- Passwords are salted and hashed with PBKDF2-SHA256.
- Sessions are stored server-side. Cookies are HttpOnly, SameSite Strict, and Secure by default.
- State-changing requests require a per-session CSRF token and same-origin browser context.
- Repeated login failures are throttled.
- Password changes revoke every session for that account.
- Compose binds the container port to `127.0.0.1`.

This is a personal-project application, not an identity provider. Use a separate password and keep the login behind HTTPS and normal access controls.

## Clean installation on the AI server

Production belongs on the separate AI server. The coding VPS is only for development and tests.

1. Clone the reviewed repository on the AI server.
2. Copy `.env.example` to `.env`.
3. Set a unique admin username, display name, and password of at least 12 characters.
4. Leave registration disabled for the first start.
5. Keep `AICS_COOKIE_SECURE=1`, place the service behind HTTPS, and preserve the public Host header through the proxy.
6. Run `docker compose up -d --build`.
7. Check `docker compose ps` and `curl http://127.0.0.1:8787/healthz` on the AI server.
8. Sign in through the HTTPS URL and verify the workspace.
9. Remove the bootstrap password from `.env` after the administrator exists, then recreate the container.
10. Enable registration in Admin only when new regular users should be accepted.

SQLite lives in `studio_data` at `/data/studio.sqlite3`. Never run `docker compose down -v` unless permanent deletion is intentional.

The application version is maintained once in `APP_VERSION` in `server.py` and returned to both footers through `/api/session`.

## Upgrade from the single-owner edition

Back up SQLite first. On the first start of this version:

1. The service creates user, session, settings, and per-user workspace tables.
2. It creates the initial admin from the new admin environment settings. Legacy `AICS_USERNAME` and `AICS_PASSWORD` names remain an upgrade fallback.
3. It copies the existing `workspace` row to the initial admin with the same revision and JSON.
4. It leaves the legacy table unchanged for rollback inspection.
5. It keeps registration disabled unless an admin explicitly enables it.

The copy uses `INSERT OR IGNORE`, so restarts cannot overwrite newer admin data. Verify projects, episodes, characters, and revision conflicts after upgrading. See [DEPLOYMENT.md](DEPLOYMENT.md).

## Accounts and registration

The Account view changes display name, password, and saved theme. Password changes sign out all sessions.

The Admin view opens or closes registration, changes roles, and disables access without deleting workspace data. Registration always creates a regular user. Regular users cannot access Admin or promote themselves. The final active admin cannot be demoted or disabled.

Sessions expire at a fixed time after login. `AICS_SESSION_HOURS` defaults to 12. An expired session returns to login. Export backups regularly.

## Import browser-only records

Export JSON from the same browser profile that holds the old Sites records. Sign in to the intended account here, choose **Import JSON**, and confirm replacement. Import affects only that account but replaces its entire workspace.

## Backup

Run on the AI server:

```sh
docker compose exec -T studio python -c "import sqlite3; src=sqlite3.connect('/data/studio.sqlite3'); dst=sqlite3.connect('/data/studio-backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker compose cp studio:/data/studio-backup.sqlite3 ./studio-backup.sqlite3
```

Store backups off-server as sensitive data. JSON export is a per-user portable backup, not a full database backup.

## Local development

Use a temporary database and disable the Secure cookie only for local plain HTTP:

```sh
export AICS_ADMIN_USERNAME=local-admin
export AICS_ADMIN_DISPLAY_NAME="Local Admin"
export AICS_ADMIN_PASSWORD="local-development-password"
export AICS_DB_PATH=/tmp/ai-content-studio-dev.sqlite3
export AICS_COOKIE_SECURE=0
python3 server.py
```

Never use `AICS_COOKIE_SECURE=0` on a publicly reachable installation.

Run:

```sh
node --check dist/app.js
node --check dist/seed.js
python3 -m py_compile server.py tests/test_server.py
python3 -m unittest discover -s tests -v
docker build -t ai-content-studio:review .
```

A missing tool is unverified, not passed.

## Scope and release

The app does not upload media, send password-reset email, provide MFA or external identity, delete users, or publish to social platforms.

Keep `.env`, SQLite files, exports, backups, logs, and real media out of Git. Before a public release, complete [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md), choose a license, inspect history, and review repository settings.
