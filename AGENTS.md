# AI Content Studio agent notes

This repository is intended to be safe to publish later. Keep sample content fictional and keep private workspace data, credentials, exports, and server details out of Git.

## App

- Single-owner MVP: static dashboard in `dist/`, Python standard-library HTTP API in `server.py`, SQLite database in a Docker named volume.
- `compose.yaml` binds the app to localhost port 8787. Serve it through an existing HTTPS reverse proxy or tunnel.
- The current ChatGPT Sites edition stores records in browser localStorage. Move real data only through an explicit JSON export from that browser and import into this database edition.

## Working rules

- Inspect the existing code, running containers, networks, proxy/tunnel setup, and port conflicts before changing AI server services.
- Treat development hosts and the production AI server as separate environments. Never infer production containers, networks, proxy settings or port availability from the coding VPS.
- Use a feature branch for substantive changes and present a diff for review. Do not force-push or overwrite existing containers, volumes, DNS records, or production data.
- Keep `.env`, database files, exports and real media out of Git. Ask the owner to enter credentials locally; never print secrets in logs or commit them.
- Preserve existing user data. Back up the SQLite volume before schema changes or deployments that could affect it.
- Run focused checks: `node --check dist/app.js`, `node --check dist/seed.js`, `python3 -m py_compile server.py`, API auth/read/write/conflict tests, then Docker build and an HTTP health check on the AI server.
- Do not expose the HTTP port to the public internet. Verify HTTPS and authentication before sharing the URL.
- Report the deployed URL, container status, data volume name, backup method, migration steps and any remaining limitations.
- Do not add a public license or change repository visibility without the owner's explicit choice.
- Do not use em dashes in code comments, UI copy or documentation. En dashes remain acceptable for numeric ranges.
