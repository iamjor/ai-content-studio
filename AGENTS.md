# AI Content Studio agent notes

This repository is intended to be safe to publish later. Keep sample content fictional and keep private workspace data, credentials, exports, media, and infrastructure details out of Git.

## Environments

- Use a development environment for source edits, code checks, local builds, screenshots, and Git operations.
- Treat every production installation as a separate, explicitly authorized environment. Do not deploy from a development task or assume development containers, networks, proxies, or ports match production.
- Inspect a production installation only through an owner-approved access path. Until then, document assumptions and mark production checks as unverified.

## App

- AI Content Studio serves the static dashboard in `dist/` and its authenticated JSON API from the Python standard-library service in `server.py`.
- SQLite and private character images belong in persistent storage. The provided Compose configuration binds the service to localhost port 8787 for use behind an HTTPS reverse proxy or tunnel.
- Browser-only legacy records move into this edition only through an explicit JSON export and import. JSON exports are text-only and do not include images.

## Working rules

- Use a feature branch for substantive changes and present a diff for review. Do not force-push, deploy, or overwrite containers, volumes, DNS records, or production data without explicit authorization.
- Use the repository owner's configured Git identity associated with `iamjor` for every commit. Before committing, check the effective `git config user.name` and `git config user.email`; stop if either value is missing or does not match the owner identity. Before pushing, inspect every commit in `origin/main..HEAD` and stop unless each author and committer matches that identity. Never use Codex as the author or committer, and do not add a `Co-authored-by: Codex` trailer.
- Keep `.env`, database files, exports, backups, logs, and real media out of Git. Ask the owner to enter credentials locally; never print secrets in logs or commit them.
- Preserve existing user data. Back up persistent SQLite and image data before schema changes or deployments that could affect it.
- Run focused checks: `node --check dist/app.js`, `node --check dist/seed.js`, `python3 -m py_compile server.py tests/test_server.py`, and `python3 -m unittest discover -s tests -v`. Build the Docker image and run a local health check where Docker is available. Mark production verification separately.
- Do not expose the HTTP port directly to the public internet. Verify HTTPS, proxy trust, origin handling, secure cookies, authentication, backups, and rollback in the target installation.
- The owner selected the MIT License for the first public release. Do not change the license or repository visibility without explicit owner approval.
- Keep public documentation under `docs/`. Use `docs/TECHNICAL.md` as the canonical technical reference and keep `README.md` concise.

## Writing and code documentation

- Do not use the em dash character (U+2014) in code comments, user-facing copy, documentation, commit messages, or pull request text. Use a comma, colon, period, or ordinary hyphen where appropriate. This rule does not ban the normal hyphen-minus used in code syntax, flags, filenames, or identifiers.
- Document each meaningful function, class, and feature so another developer can understand its purpose, inputs, outputs, important side effects, and failure behavior. Use Python docstrings for Python functions and classes, and concise JSDoc or nearby comments for JavaScript functions and event handlers.
- Explain non-obvious business rules, data migration, authentication, persistence, and deployment choices near the relevant code. Avoid comments that merely repeat what a line of code says. Update comments and documentation when behavior changes.
- Before declaring a task complete, review changed code for missing or stale documentation and scan changed text for U+2014.
