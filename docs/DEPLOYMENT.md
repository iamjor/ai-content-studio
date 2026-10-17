# Self-hosted deployment and upgrade guide

Use this guide to prepare and verify an installation you administer. Keep hostnames, credentials, and infrastructure details in your private operations records.

## 1. Source and review

- [ ] Confirm the intended reviewed commit or release tag.
- [ ] Confirm `git status --short` is empty.
- [ ] Run both JavaScript syntax checks.
- [ ] Compile `server.py` and `tests/test_server.py`.
- [ ] Run the full unittest suite.
- [ ] Build the Docker image where Docker is available.
- [ ] Review narrow mobile and desktop layouts in dark and light themes.
- [x] Confirm the owner-selected MIT License is present.

Unavailable tooling is unverified, not passed. Local header simulation does not count as live reverse-proxy verification.

## 2. Production host preflight

Run these checks on the target host before changing the installation.

- [ ] record deployed and target commits.
- [ ] inspect Docker, Compose, containers, networks, volumes, and port conflicts without changing them.
- [ ] inspect the HTTPS proxy or tunnel privately and confirm it preserves the public Host header.
- [ ] identify the app's immediate proxy peer and set `AICS_TRUSTED_PROXY_NETWORKS` to the smallest verified peer CIDR needed to distinguish client addresses.
- [ ] confirm untrusted peers cannot influence `CF-Connecting-IP` at the app boundary.
- [ ] set finite `AICS_MAX_USERS` and `AICS_REGISTRATION_ATTEMPT_LIMIT` values appropriate for the installation.
- [ ] keep the app loopback-only or on a private container network.
- [ ] confirm disk space and an off-server backup destination.
- [ ] keep registration off and Secure cookies on.

## 3. Backup and migration preparation

- [ ] pause browser edits.
- [ ] identify the production Compose project and volume without guessing from development.
- [ ] create and verify a consistent off-server SQLite backup.
- [ ] record a private rollback image or commit.
- [ ] set the initial admin values in private `.env`.

The first start creates schema version 3 and copies the shared workspace to the initial admin, adds non-destructive archive fields, seeds the SQLite tool catalog, and creates private image metadata. It leaves the legacy table unchanged and cannot overwrite a newer per-user workspace or revision.

## 4. Production rollout

Carry out these steps only on an installation you administer.

- [ ] fetch and build the exact reviewed commit.
- [ ] update only AI Content Studio.
- [ ] never run `docker compose down -v`.
- [ ] confirm `studio_data` remains attached and contains both SQLite and the private `/data/images` directory.
- [ ] inspect migration logs without exposing private data.
- [ ] remove the bootstrap password after successful creation and recreate the container.

## 5. Production verification

- [ ] check Compose status and `/healthz`.
- [ ] confirm plain HTTP is not public and HTTPS is valid.
- [ ] verify the in-app login replaces the browser Basic Auth dialog.
- [ ] verify concurrent login bursts stop at the source limit without password work, session creation, or HTTP 500 responses beyond that limit.
- [ ] verify a separate trusted client can sign in, untrusted peers cannot spoof client addresses, and unauthenticated API access is rejected.
- [ ] verify enabled registration attempt limits and the total account cap.
- [ ] verify HTTPS Origin matches the preserved public Host and the session cookie is Secure, HttpOnly, and SameSite Strict in the deployed browser.
- [ ] verify migrated owner data, stable IDs, revision, seeded tool catalog, and lifecycle flags.
- [ ] test logout, expiry, CSRF, account changes, and reauthentication.
- [ ] confirm registration is off unless intentionally opened.
- [ ] confirm regular-user workspace and image isolation, denied admin access, user lifecycle controls, and last-admin protection.
- [ ] test image upload, replacement, removal, persistence after container restart, and a complete volume backup and restore.
- [ ] audit mobile and desktop layouts in both themes.
- [ ] review logs without exposing private data.

## 6. Rollback

- [ ] restore the prior reviewed image while preserving the volume.
- [ ] restore the backup only if integrity requires it.
- [ ] preserve the failed database for diagnosis.
- [ ] repeat health, authentication, HTTPS, and data checks.

Keep hostnames, addresses, credentials, policies, and topology in a private operations record.
