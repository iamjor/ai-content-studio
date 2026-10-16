# AI server deployment plan

This review-only plan applies to the separate production AI server. The coding VPS is only for source edits, tests, builds, screenshots, and Git operations. Do not copy private infrastructure details into Git.

## 1. Development and review gate

- [ ] Confirm the intended reviewed commit is on `main`.
- [ ] Confirm `git status --short` is empty.
- [ ] Run both JavaScript syntax checks.
- [ ] Compile `server.py` and `tests/test_server.py`.
- [ ] Run the full unittest suite.
- [ ] Build the Docker image where Docker is available.
- [ ] Review narrow mobile and desktop layouts in dark and light themes.
- [ ] Complete `PUBLIC_RELEASE_CHECKLIST.md` before a visibility change.
- [ ] Confirm the owner selected a license before adding one.

Unavailable tooling is unverified, not passed. Local header simulation does not count as live Cloudflare Tunnel verification.

## 2. AI server preflight

Every item below requires separately authorized AI server access.

- [ ] **AI server access required:** record deployed and target commits.
- [ ] **AI server access required:** inspect Docker, Compose, containers, networks, volumes, and port conflicts without changing them.
- [ ] **AI server access required:** inspect the HTTPS proxy or tunnel privately and confirm it preserves the public Host header.
- [ ] **AI server access required:** identify the app's immediate proxy peer and set `AICS_TRUSTED_PROXY_NETWORKS` to the smallest verified peer CIDR needed to distinguish client addresses.
- [ ] **AI server access required:** confirm untrusted peers cannot influence `CF-Connecting-IP` at the app boundary.
- [ ] **AI server access required:** set finite `AICS_MAX_USERS` and `AICS_REGISTRATION_ATTEMPT_LIMIT` values appropriate for the installation.
- [ ] **AI server access required:** keep the app loopback-only or on a private container network.
- [ ] **AI server access required:** confirm disk space and an off-server backup destination.
- [ ] **AI server access required:** keep registration off and Secure cookies on.

## 3. Backup and migration preparation

- [ ] **AI server access required:** pause browser edits.
- [ ] **AI server access required:** identify the production Compose project and volume without guessing from development.
- [ ] **AI server access required:** create and verify a consistent off-server SQLite backup.
- [ ] **AI server access required:** record a private rollback image or commit.
- [ ] **AI server access required:** set the initial admin values in private `.env`.

The first start creates schema version 2 and copies the shared workspace to the initial admin. It leaves the legacy table unchanged and cannot overwrite a newer per-user workspace.

## 4. Production rollout

These steps require explicit approval after review and merge.

- [ ] **AI server access required:** fetch and build the exact reviewed commit.
- [ ] **AI server access required:** update only AI Content Studio.
- [ ] **AI server access required:** never run `docker compose down -v`.
- [ ] **AI server access required:** confirm `studio_data` remains attached.
- [ ] **AI server access required:** inspect migration logs without exposing private data.
- [ ] **AI server access required:** remove the bootstrap password after successful creation and recreate the container.

## 5. Production verification

- [ ] **AI server access required:** check Compose status and `/healthz`.
- [ ] **AI server access required:** confirm plain HTTP is not public and HTTPS is valid.
- [ ] **AI server access required:** verify the in-app login replaces the browser Basic Auth dialog.
- [ ] **AI server access required:** verify blocked login sources are rejected before credential work, a separate trusted client can sign in, untrusted peers cannot spoof client addresses, and unauthenticated API access is rejected.
- [ ] **AI server access required:** verify enabled registration attempt limits and the total account cap.
- [ ] **AI server access required:** verify HTTPS Origin matches the preserved public Host and the session cookie is Secure, HttpOnly, and SameSite Strict in the deployed browser.
- [ ] **AI server access required:** verify migrated owner data and revision.
- [ ] **AI server access required:** test logout, expiry, CSRF, account changes, and reauthentication.
- [ ] **AI server access required:** confirm registration is off unless intentionally opened.
- [ ] **AI server access required:** confirm regular-user isolation and denied admin access.
- [ ] **AI server access required:** audit mobile and desktop layouts in both themes.
- [ ] **AI server access required:** review logs without exposing private data.

## 6. Rollback

- [ ] **AI server access required:** restore the prior reviewed image while preserving the volume.
- [ ] **AI server access required:** restore the backup only if integrity requires it.
- [ ] **AI server access required:** preserve the failed database for diagnosis.
- [ ] **AI server access required:** repeat health, authentication, HTTPS, and data checks.

Keep hostnames, addresses, credentials, policies, and topology in a private operations record.
