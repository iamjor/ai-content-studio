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

- [ ] Record deployed and target commits.
- [ ] Inspect Docker, Compose, containers, networks, volumes, and port conflicts without changing them.
- [ ] Inspect the HTTPS proxy or tunnel privately and confirm it preserves the public Host header.
- [ ] Identify the app's immediate proxy peer and set `AICS_TRUSTED_PROXY_NETWORKS` to the smallest verified peer CIDR needed to distinguish client addresses.
- [ ] Confirm untrusted peers cannot influence `CF-Connecting-IP` at the app boundary.
- [ ] Set finite `AICS_MAX_USERS` and `AICS_REGISTRATION_ATTEMPT_LIMIT` values appropriate for the installation.
- [ ] Set `AICS_PUBLIC_BASE_URL` to the exact external HTTPS origin with no path.
- [ ] Confirm the proxy forwards `/mcp` and OAuth discovery and endpoint paths without rewriting their origin.
- [ ] Keep the app loopback-only or on a private container network.
- [ ] Confirm disk space and an off-server backup destination.
- [ ] Keep registration off and Secure cookies on.

## 3. Backup and migration preparation

- [ ] Pause browser edits.
- [ ] Identify the production Compose project and volume without guessing from development.
- [ ] Create and verify a consistent off-server SQLite backup.
- [ ] Record a private rollback image or commit.
- [ ] Set the initial admin values in private `.env`.

The first v0.2 start records schema version 4 and normalizes each workspace with empty project Bible, prompt, episode planning, shot, and character continuity fields. It preserves existing IDs, descriptions, hooks, scripts, revisions, archive state, sessions, users, and image records. Older startup behavior still copies the shared workspace to the initial admin, seeds the tool catalog, and creates private image metadata. The legacy table remains unchanged, and migration cannot overwrite a newer per-user workspace or revision.

The first v0.3 start records schema version 5 and additively creates OAuth client, consent flow, authorization code, grant, hashed token, and MCP request-limit tables. It also adds stable IDs only where older prompts, gates, or shots lack one. Existing users, sessions, workspace revisions, projects, descriptions, episodes, scripts, hooks, characters, prompts, images, planning fields, and legacy tables are not replaced. Back up SQLite and the image directory together before upgrade.

The first v0.4 start records schema version 6 and additively adds recovery-code hashes, forced-setup flags, minimal security events, prompt attachment metadata, tool ownership and assignments, and MCP entitlements. Existing users, projects, episodes, characters, scripts, images, prompt text and snapshots, tools, OAuth clients and grants, tokens, sessions, revisions, IDs, and archive state are preserved. Existing administrator tools remain visible to administrators and are hidden from regular users until explicitly assigned. Existing administrators retain MCP access. Existing users without confirmed recovery codes are directed through setup after their next browser login. Back up SQLite, `/data/images`, and `/data/prompt-attachments` together before upgrade.

The v0.4.1 hotfix records schema version 7 through an additive migration. It adds nullable UTC last-login and last-seen fields and a nullable canonical tool-domain field, then populates identities without merging or deleting existing duplicates. Existing account IDs, tool IDs, owners, assignments, workspaces, recovery sets, attachments, MCP permissions, grants, tokens, sessions, and archive state remain in place. Upgrade by replacing the application image while preserving the existing volume. Take the normal complete backup before upgrade, then verify login, recovery setup, one-use recovery, attachment downloads, tool sharing and canonical linking, search pagination, administrator-only activity status, and MCP readiness.

The v0.3 image installs the hash-locked official MCP SDK dependency set from `requirements.txt`; `requirements.in` records the direct SDK pin and starts a loopback-only MCP worker behind the existing public service. No external database, paid API, or production OAuth client is required.

## 4. Production rollout

Carry out these steps only on an installation you administer.

- [ ] Fetch and build the exact reviewed commit.
- [ ] Update only AI Content Studio.
- [ ] Never run `docker compose down -v`.
- [ ] Confirm `studio_data` remains attached and contains SQLite plus the private `/data/images` and `/data/prompt-attachments` directories.
- [ ] Inspect migration logs without exposing private data.
- [ ] Remove the bootstrap password after successful creation and recreate the container.

## 5. Production verification

- [ ] Check Compose status, `/healthz`, and `/mcp/ready`.
- [ ] Confirm stopping the MCP child makes `/mcp/ready` fail and marks the container unhealthy for operator monitoring or orchestration.
- [ ] Check `/mcp/ready` without expecting it to reveal account or workspace data.
- [ ] Verify OAuth authorization-server and protected-resource discovery use the configured public HTTPS origin.
- [ ] Connect a disposable compatible MCP client, approve only required scopes, verify one read and one revision-safe write, then revoke it from Account.
- [ ] Confirm plain HTTP is not public and HTTPS is valid.
- [ ] Verify the in-app login replaces the browser Basic Auth dialog.
- [ ] Verify concurrent login bursts stop at the source limit without password work, session creation, or HTTP 500 responses beyond that limit.
- [ ] Verify a separate trusted client can sign in, untrusted peers cannot spoof client addresses, and unauthenticated API access is rejected.
- [ ] Verify enabled registration attempt limits and the total account cap.
- [ ] Verify HTTPS Origin matches the preserved public Host and the session cookie is Secure, HttpOnly, and SameSite Strict in the deployed browser.
- [ ] Verify migrated owner data, stable IDs, revision, seeded tool catalog, and lifecycle flags.
- [ ] Verify project Bible edits, episode synopsis and beats, shot order, prompts, character reference requirements, gates, JSON transfer, and the existing approved private image.
- [ ] Test logout, expiry, CSRF, account changes, and reauthentication.
- [ ] Confirm registration is off unless intentionally opened.
- [ ] Confirm regular-user workspace and image isolation, denied admin access, user lifecycle controls, and last-admin protection.
- [ ] Test image upload, replacement, removal, persistence after container restart, and a complete volume backup and restore.
- [ ] Audit mobile and desktop layouts in both themes.
- [ ] Review logs without exposing private data.
- [ ] Confirm no bearer token appears in URLs, logs, browser exports, or source-controlled configuration.

## 6. Rollback

- [ ] Restore the prior reviewed image while preserving the volume.
- [ ] Restore the backup only if integrity requires it.
- [ ] Preserve the failed database for diagnosis.
- [ ] Repeat health, authentication, HTTPS, and data checks.

Keep hostnames, addresses, credentials, policies, and topology in a private operations record.

## Temporary MCP initialization diagnostics

Use this procedure only while investigating a failed authenticated MCP initialization. The setting is disabled by default and does not change OAuth clients, tokens, scopes, or workspace data.

1. Set `AICS_MCP_DIAGNOSTICS=1` in the private deployment environment.
2. Restart the AI Content Studio container so the setting takes effect.
3. Trigger ChatGPT Refresh tools once.
4. Inspect the container logs for the generated `MCP diagnostic` correlation ID and bounded transport metadata. Do not publish deployment logs.
5. Set `AICS_MCP_DIAGNOSTICS=0` or remove the variable, then restart the container.

The diagnostic reports only the internal response status, safe JSON-RPC method and initialize protocol version when parseable, required header presence, request byte length, and a bounded sanitized JSON-RPC error code and message. It never intentionally records authorization values, cookies, OAuth credentials, tool arguments, full bodies, or workspace content.
