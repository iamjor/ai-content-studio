# AI Content Studio agent notes

This repository is intended to be safe to publish later. Keep sample content fictional and keep private workspace data, credentials, exports, and VPS details out of Git.

## App

- Single-owner MVP: static dashboard in `dist/`, Python standard-library HTTP API in `server.py`, SQLite database in a Docker named volume.
- `compose.yaml` binds the app to localhost port 8787. Serve it through an existing HTTPS reverse proxy or tunnel.
- The current ChatGPT Sites edition stores records in browser localStorage. Move real data only through an explicit JSON export from that browser and import into this database edition.

## Working rules

- Inspect the existing code, running containers, networks, proxy/tunnel setup, and port conflicts before changing VPS services.
- Use a feature branch for substantive changes and present a diff for review. Do not force-push or overwrite existing containers, volumes, DNS records, or production data.
- Keep `.env`, database files, exports and real media out of Git. Ask the owner to enter credentials locally; never print secrets in logs or commit them.
- Preserve existing user data. Back up the SQLite volume before schema changes or deployments that could affect it.
- Run focused checks: `node --check dist/app.js`, `node --check dist/seed.js`, `python3 -m py_compile server.py`, API auth/read/write/conflict tests, then Docker build and an HTTP health check on the VPS.
- Do not expose the HTTP port to the public internet. Verify HTTPS and authentication before sharing the URL.
- Report the deployed URL, container status, data volume name, backup method, migration steps and any remaining limitations.
- Do not add a public license or change repository visibility without the owner's explicit choice.

## Writing and code documentation

- Do not use the em dash character (U+2014) in code comments, user-facing copy, documentation, commit messages, or pull request text. Use a comma, colon, period, or ordinary hyphen where appropriate. This rule does not ban the normal hyphen-minus used in code syntax, flags, filenames, or identifiers.
- Document each meaningful function, class, and feature so another developer can understand its purpose, inputs, outputs, important side effects, and failure behavior. Use Python docstrings for Python functions and classes, and concise JSDoc or nearby comments for JavaScript functions and event handlers.
- Explain non-obvious business rules, data migration, authentication, persistence, and deployment choices near the relevant code. Avoid comments that merely repeat what a line of code says. Update comments and README when behavior changes.
- Before declaring a task complete, review changed code for missing or stale documentation and scan changed text for U+2014.
