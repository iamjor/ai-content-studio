# AI Content Studio (self-hosted)

Private project, episode and character dashboard. This edition runs as one Docker container with a SQLite database on a persistent Docker volume. Python's standard library is the only app dependency.

## Deploy on your VPS

1. Clone this repository on your VPS and enter its directory.
2. Copy `.env.example` to `.env`. Set your own long random `AICS_PASSWORD` and username. Keep `.env` out of Git.
3. Run `docker compose up -d --build`.
4. Check `docker compose ps` and `curl http://127.0.0.1:8787/healthz` on the VPS.
5. Put the service behind your HTTPS reverse proxy or Cloudflare Tunnel. The Compose port is bound to **127.0.0.1 only**. Route your chosen hostname to `http://127.0.0.1:8787` if the proxy runs on the host. If your tunnel runs inside another container, attach it to the Compose network and route it to `http://studio:8787` instead. Do not expose the container's HTTP port directly to the internet: Basic authentication requires HTTPS in transit.
6. Visit the HTTPS URL and sign in with the `.env` credentials. For an extra gate, add your existing Cloudflare Access policy in front of the service.

SQLite lives in the named `studio_data` volume at `/data/studio.sqlite3`, not in the image. `docker compose up -d --build` updates the app while preserving that volume. Never run `docker compose down -v` unless you intentionally want to delete its data.

## Move existing browser records

The current Sites edition stores data only in the browser where it was created. Open that edition in the **same browser/profile** with your records and choose **Export JSON**. Then open this Docker edition, choose **Import JSON**, and confirm the shared-database replacement. Check projects, episodes and characters before retiring the old edition. Repeat export from any other browser that has unique records; importing replaces the entire workspace, so merge separate exports manually before importing if needed. Keep an offline backup.

Once imported, edits to this Docker edition are shared between browsers and devices. A stale tab's save is rejected instead of silently overwriting a newer edit. Export JSON before reloading if the dashboard reports a failed save.

## Backup

Run a consistent SQLite backup from the VPS (adjust the service name if changed):

```sh
docker compose exec -T studio python -c "import sqlite3; src=sqlite3.connect('/data/studio.sqlite3'); dst=sqlite3.connect('/data/studio-backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker compose cp studio:/data/studio-backup.sqlite3 ./studio-backup.sqlite3
```

Store the backup outside the VPS too. The dashboard's **Export JSON** is a portable data backup, but it is not a substitute for a routine off-server backup.

## Development

Without Docker, set `AICS_USERNAME`, `AICS_PASSWORD`, `AICS_DB_PATH` and optional `PORT` in your shell, then run `python3 server.py`. The server serves `dist/` and offers `GET/PUT /api/workspace`. Writes include a revision so a stale tab cannot overwrite newer data. `GET /healthz` is public for a local health check. The app intentionally uses a single workspace and a single credential; do not share this login with separate untrusted users.

## Scope and future releases

This is a single-owner MVP. It tracks projects, scripts and character sheets; it does not yet upload media, delete or rename projects, manage teams, or publish to social platforms. Automation is planned but is not enabled. The software stack is free and open source; your VPS and domain may have their own hosting costs.

The public source contains fictional sample data only. Your actual workspace lives in the SQLite volume and is excluded from Git. Keep exported JSON and `.env` private. Before switching a private repository to public, select an open-source license, review repository history and GitHub settings, and verify there are no secrets or personal production assets.

Releases can use `v0.1.0`, `v0.2.0`, and so on. See [CHANGELOG.md](CHANGELOG.md) for the baseline and [CONTRIBUTING.md](CONTRIBUTING.md) for development guidance.
