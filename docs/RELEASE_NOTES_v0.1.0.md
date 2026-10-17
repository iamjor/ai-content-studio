# AI Content Studio 0.1.0 release notes

Version 0.1.0 is the first public source release of AI Content Studio. Publishing source code does not upgrade any existing installation.

## Highlights

- Private, revision-aware workspaces for projects, episodes, characters, and production notes
- Private character reference images with validated PNG, JPEG, and WebP uploads
- Administrator-managed registration, account lifecycle, roles, and shared tools
- In-app authentication with password hashing, server-side sessions, CSRF checks, and bounded attempt handling
- Responsive dark and light interfaces with an original film and story mark
- Archive, restore, and confirmed deletion flows for workspace records and users
- Text-only JSON transfer plus documented complete backup of SQLite and image data

## Docker quick start

1. Copy `.env.example` to `.env`.
2. Set private bootstrap administrator values and keep registration disabled.
3. Keep Secure cookies enabled for HTTPS.
4. Run `docker compose up -d --build`.
5. Verify `docker compose ps` and `curl http://127.0.0.1:8787/healthz`.
6. Place the loopback-bound service behind an operator-managed HTTPS reverse proxy.
7. Remove the bootstrap password from `.env` after the administrator exists, then recreate the container.

Read [Deployment](DEPLOYMENT.md) before an installation or upgrade.

## Migration and backups

Startup creates schema version 3 idempotently. For a legacy single-owner database, it copies the existing workspace to the initial administrator without changing project IDs or overwriting a newer per-user workspace revision. The legacy table remains available for rollback review.

Back up the SQLite database and private image directory together before upgrading. JSON export contains text workspace records only and does not contain uploaded images. A complete round-trip backup must preserve both `/data/studio.sqlite3` and `/data/images` from a consistent point in time. Never use `docker compose down -v` during a normal upgrade.

## Known limits

- The service targets a single-node SQLite deployment and does not provide high availability.
- Email verification, password-reset email, MFA, external identity, and an audit log are not implemented.
- Uploaded images receive type and size validation but no malware scan or transcoding.
- JSON import and export do not carry image bytes.
- Live proxy behavior, browser layout, backup restoration, and production rollout require installation-specific verification.
- No service-level, recovery-time, recovery-point, or retention objective is defined.

## License

The version 0.1.0 source is licensed under the [MIT License](../LICENSE). A source release does not upgrade an existing installation.
