# Self-hosted deployment plan

This review-only plan separates development work from a target self-hosted production installation. Do not copy private infrastructure details into Git or infer production topology from a development environment.

## 1. Development and review gate

- [ ] Confirm the intended reviewed commit is on `main`.
- [ ] Confirm `git status --short` is empty.
- [ ] Run both JavaScript syntax checks.
- [ ] Compile `server.py` and `tests/test_server.py`.
- [ ] Run the full unittest suite.
- [ ] Build the Docker image where Docker is available.
- [ ] Review narrow mobile and desktop layouts in dark and light themes.
- [ ] Complete [public release checklist](PUBLIC_RELEASE_CHECKLIST.md) before a visibility change.
- [x] Confirm the owner-selected MIT License is present.

Unavailable tooling is unverified, not passed. Local header simulation does not count as live Cloudflare Tunnel verification.

## 2. Production host preflight

Every item below requires separately authorized production host access.

- [ ] **Production access required:** record deployed and target commits.
- [ ] **Production access required:** inspect Docker, Compose, containers, networks, volumes, and port conflicts without changing them.
- [ ] **Production access required:** inspect the HTTPS proxy or tunnel privately and confirm it preserves the public Host header.
- [ ] **Production access required:** identify the app's immediate proxy peer and set `AICS_TRUSTED_PROXY_NETWORKS` to the smallest verified peer CIDR needed to distinguish client addresses.
- [ ] **Production access required:** confirm untrusted peers cannot influence `CF-Connecting-IP` at the app boundary.
- [ ] **Production access required:** set finite `AICS_MAX_USERS` and `AICS_REGISTRATION_ATTEMPT_LIMIT` values appropriate for the installation.
- [ ] **Production access required:** keep the app loopback-only or on a private container network.
- [ ] **Production access required:** confirm disk space and an off-server backup destination.
- [ ] **Production access required:** keep registration off and Secure cookies on.

## 3. Backup and migration preparation

- [ ] **Production access required:** pause browser edits.
- [ ] **Production access required:** identify the production Compose project and volume without guessing from development.
- [ ] **Production access required:** create and verify a consistent off-server SQLite backup.
- [ ] **Production access required:** record a private rollback image or commit.
- [ ] **Production access required:** set the initial admin values in private `.env`.

The first start creates schema version 3 and copies the shared workspace to the initial admin, adds non-destructive archive fields, seeds the SQLite tool catalog, and creates private image metadata. It leaves the legacy table unchanged and cannot overwrite a newer per-user workspace or revision.

## 4. Production rollout

These steps require explicit approval after review and merge.

- [ ] **Production access required:** fetch and build the exact reviewed commit.
- [ ] **Production access required:** update only AI Content Studio.
- [ ] **Production access required:** never run `docker compose down -v`.
- [ ] **Production access required:** confirm `studio_data` remains attached and contains both SQLite and the private `/data/images` directory.
- [ ] **Production access required:** inspect migration logs without exposing private data.
- [ ] **Production access required:** remove the bootstrap password after successful creation and recreate the container.

## 5. Production verification

- [ ] **Production access required:** check Compose status and `/healthz`.
- [ ] **Production access required:** confirm plain HTTP is not public and HTTPS is valid.
- [ ] **Production access required:** verify the in-app login replaces the browser Basic Auth dialog.
- [ ] **Production access required:** verify concurrent login bursts stop at the source limit without password work, session creation, or HTTP 500 responses beyond that limit.
- [ ] **Production access required:** verify a separate trusted client can sign in, untrusted peers cannot spoof client addresses, and unauthenticated API access is rejected.
- [ ] **Production access required:** verify enabled registration attempt limits and the total account cap.
- [ ] **Production access required:** verify HTTPS Origin matches the preserved public Host and the session cookie is Secure, HttpOnly, and SameSite Strict in the deployed browser.
- [ ] **Production access required:** verify migrated owner data, stable IDs, revision, seeded tool catalog, and lifecycle flags.
- [ ] **Production access required:** test logout, expiry, CSRF, account changes, and reauthentication.
- [ ] **Production access required:** confirm registration is off unless intentionally opened.
- [ ] **Production access required:** confirm regular-user workspace and image isolation, denied admin access, user lifecycle controls, and last-admin protection.
- [ ] **Production access required:** test image upload, replacement, removal, persistence after container restart, and a complete volume backup and restore.
- [ ] **Production access required:** audit mobile and desktop layouts in both themes.
- [ ] **Production access required:** review logs without exposing private data.

## 6. Rollback

- [ ] **Production access required:** restore the prior reviewed image while preserving the volume.
- [ ] **Production access required:** restore the backup only if integrity requires it.
- [ ] **Production access required:** preserve the failed database for diagnosis.
- [ ] **Production access required:** repeat health, authentication, HTTPS, and data checks.

Keep hostnames, addresses, credentials, policies, and topology in a private operations record.
