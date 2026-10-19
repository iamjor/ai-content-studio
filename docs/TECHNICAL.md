# Technical reference

This document is the canonical technical reference for AI Content Studio. It follows the owner's Project Technical Documentation Standard v1.2 at a scale appropriate to this application. Repository code and configuration are authoritative when this document and implementation differ.

## 1. Overview and scope

AI Content Studio is a self-hosted planning dashboard for project Bibles, episodes, shot plans, characters, reusable prompts, production gates, private reference images, and a shared tools catalog. It provides local account management and private per-user workspaces. It does not generate media, publish content, send email, or provide external identity services.

## 2. Goals and non-goals

The application favors a small deployable surface, private workspace isolation, explicit destructive actions, and a reversible migration path from the single-owner edition. High availability, distributed storage, horizontal scaling, billing, service-level objectives, and managed account recovery are not implemented or specified.

## 3. Sources of truth

`server.py` is the source of truth for API behavior, schema migration, security controls, configuration parsing, and the application version. `dist/index.html`, `dist/style.css`, `dist/app.js`, and `dist/seed.js` define the browser application. `compose.yaml`, `Dockerfile`, and `.env.example` define the packaged runtime. SQLite and the configured image directory are the runtime data sources of truth.

## 4. Data lifecycle

An administrator is bootstrapped only when no administrator exists. Each user owns one revisioned workspace JSON document. Project Bibles, prompt libraries, production gates, episode synopses, beat outlines, shots, character continuity, and archive states live in that document. Permanent workspace deletions are saved through the same revision-aware update. Character image metadata lives in SQLite and bytes live under the image root. Version 0.2 retains one approved private image per character. User deletion cascades through database-owned records and removes that user's uploaded files. JSON export moves text only. Complete backup and restore must include the database and image directory together.

## 5. System architecture

```mermaid
flowchart LR
  B[Browser] -->|HTTPS via operator proxy| P[Reverse proxy or tunnel]
  P -->|Loopback or private HTTP| S[Python HTTP service]
  S --> F[Static assets]
  S --> D[(SQLite)]
  S --> I[Private image directory]
```

The provided container runs the browser HTTP service and a loopback-only official-SDK MCP worker under one launcher. Static files and JSON routes share the same origin. The reverse proxy is operator-managed and is not included in this repository.

## 6. Trust boundaries

The public browser boundary ends at the HTTPS proxy. The application trusts forwarded client identity only when the immediate peer belongs to `AICS_TRUSTED_PROXY_NETWORKS`; otherwise it uses the peer address. Browser state changes require same-origin checks, an authenticated server-side session, and a CSRF token. Administrator routes enforce the role on the server. The database and image directory are private persistent data and must not be served directly.

## 7. Request and data flows

Unauthenticated clients may load static assets, query session state, sign in, and register only when registration is enabled. Successful login creates a random token, stores only its hash in SQLite, and returns the raw token in a cookie. Authenticated reads load the account, workspace, tools, or owner-scoped image. Writes validate input and use the CSRF header. Workspace saves compare revisions and return a conflict instead of silently overwriting concurrent changes.

## 8. Technology stack

- Python standard library HTTP server and `sqlite3`
- Official MCP Python SDK pinned to 2.2.0 through a hash-locked dependency set
- SQLite in WAL mode with foreign keys and a busy timeout
- Dependency-free HTML, CSS, and JavaScript frontend
- Python 3.13 Alpine container image
- Docker Compose with a named persistent volume


## 9. Data model

Schema version 5 uses `users`, `workspaces`, `sessions`, `app_settings`, `login_attempts`, `tools`, `character_images`, `oauth_clients`, `oauth_flows`, `oauth_codes`, `oauth_grants`, `oauth_tokens`, and `mcp_rate_limits`. Users have a role, active state, optional archive time, display name, password record, and theme. Workspaces are keyed by user ID and contain a revision plus JSON. Sessions contain token hashes, CSRF tokens, and fixed expiry times. Tools are shared catalog records. Image metadata is unique per user and character.

Workspace JSON retains existing project, episode, character, prompt, and shot IDs and accepts legacy structures through migration and normalization. Missing v0.2 fields receive empty defaults without replacing descriptions, hooks, scripts, revisions, or stored images. A shot may link to a reusable prompt by ID, but stores its own final image and video prompt text so later library edits do not rewrite production instructions. The legacy `workspace` table is left intact after its first non-destructive copy to the initial administrator.

## 10. Identity and access

Roles are `admin` and `user`. Self-registration can create only `user` accounts. Administrators manage registration, roles, user lifecycle, and tools. Users can change their own display name, password, and theme. Disabled or archived users cannot sign in, and their sessions are revoked. A signed-in administrator cannot delete themselves, and the final active administrator cannot be removed from that role or access state.

## 11. Authentication and sessions

Passwords are limited to 12 through 256 characters and stored using salted PBKDF2-SHA256 with 600,000 iterations. Login requests are size-limited and throttled atomically by source before password verification. Sessions are random, stored server-side by token hash, and expire at a fixed time. Cookies are HttpOnly, SameSite Strict, and Secure unless explicitly disabled for local HTTP development. Password changes revoke all sessions for that user.

## 12. Configuration

Documented variables are `AICS_ADMIN_USERNAME`, `AICS_ADMIN_DISPLAY_NAME`, `AICS_ADMIN_PASSWORD`, `AICS_REGISTRATION_ENABLED`, `AICS_MAX_USERS`, `AICS_REGISTRATION_ATTEMPT_LIMIT`, `AICS_OAUTH_CLIENT_LIMIT`, `AICS_OAUTH_FLOW_LIMIT`, `AICS_COOKIE_SECURE`, `AICS_SESSION_HOURS`, `AICS_TRUSTED_PROXY_NETWORKS`, `AICS_IMAGE_ROOT`, `AICS_PUBLIC_BASE_URL`, and `AICS_MCP_INTERNAL_PORT`. The container also sets `AICS_DB_PATH=/data/studio.sqlite3` and `PORT=8787`. Legacy `AICS_USERNAME` and `AICS_PASSWORD` remain bootstrap fallbacks for upgrade compatibility.

Secrets belong in an untracked `.env` or an operator-managed secret mechanism. Bootstrap credentials should be removed after the initial administrator exists.

## 13. Hosting and environments

Development may run natively with a temporary SQLite path and insecure local cookie setting. The packaged self-hosted environment uses Docker Compose, a loopback port binding, and `studio_data`. A public installation requires an operator-managed HTTPS endpoint. Hostnames, proxy products, network ranges, storage locations, and production topology are intentionally installation-specific and are not defined here.

## 14. Delivery behavior

The service returns static assets and API responses with `Cache-Control: no-store`, content-type sniffing protection, same-origin referrer and opener policy, a restrictive permissions policy, and a self-only content security policy. HSTS is returned when Secure cookies are enabled. Compose checks both `/healthz` and `/mcp/ready`, so either a stopped web process or an unreachable loopback MCP worker makes the container unhealthy. The application version comes from `APP_VERSION` and is delivered through `/api/session` for both authenticated and signed-out footers.

## 15. Stable links and assets

Browser routes use one document and client-side section selection; deep-linkable section URLs are not implemented. API paths under `/api/` and `/healthz` are operational interfaces, but no external compatibility guarantee or formal API version exists. `/favicon.svg` is the original project mark used by login and application chrome. External tool URLs are administrator-managed HTTPS links and are not endorsements or availability guarantees.

## 16. Operations, backup, and restore

Monitor container health, restart behavior, persistent storage capacity, authentication failures, and application logs without recording request bodies or credentials. The server logs method, path, and status only. A consistent SQLite backup plus a copy of the image directory is required for complete recovery. Restore both from the same backup point and verify login, workspace revisions, images, tools, and lifecycle flags. No retention period, recovery objective, or service objective is defined by the repository.

## 17. Deployment and change management

Build and test the exact reviewed commit. Before upgrades, stop edits and create an off-host backup. Preserve the volume and never use `docker compose down -v` during a normal update. First startup applies idempotent schema creation and migration. Validate health, HTTPS, Host and Origin behavior, cookies, authentication, migrated content, and backups before declaring rollout complete. Use the [deployment guide](DEPLOYMENT.md) for preparation and rollback checks.

## 18. Validation evidence

The repository contains Python integration tests in `tests/test_server.py`, JavaScript syntax checks, Python compilation checks, and HTML validation-compatible markup. Test results belong in each pull request and must state the exact commit and environment. Browser appearance, live proxy behavior, backup restoration, and production rollout are unverified unless the relevant pull request records direct evidence. Historical claims are not promoted to current evidence here.

## 19. Security, privacy, limitations, and troubleshooting

Private data includes credentials, session material, workspace content, images, databases, exports, backups, and logs. Keep it out of Git and protect it at rest and in transit. The application has no MFA, email verification, password-reset email, external identity provider, audit log, malware scanner, or image transcoder. It validates supported image signatures and size but is not a general hostile-file analysis service.

For startup failures, verify required bootstrap values only when no admin exists, writable database and image paths, and valid trusted-proxy CIDRs. For login loops, verify the public Host is preserved, HTTPS is active, and Secure cookies are not being tested over plain HTTP. For 403 writes, inspect Origin, Host, session expiry, and CSRF state. For revision conflicts, reload before retrying. For missing images after restore, confirm the database and image directory came from the same backup.

Security reporting guidance is in [SECURITY.md](SECURITY.md). Installation-specific investigation may require authorized production access.

## 20. OAuth and MCP endpoint contract

The public Streamable HTTP endpoint is `/mcp` on the exact origin configured by `AICS_PUBLIC_BASE_URL`. OAuth authorization-server metadata is at `/.well-known/oauth-authorization-server`; RFC 9728 protected-resource metadata is at `/.well-known/oauth-protected-resource/mcp`. Dynamic registration accepts public clients with exact HTTPS redirect URIs or HTTP loopback redirects. Public registration and authorization-flow creation use proxy-safe per-source limits with bounded durable state. Unclaimed client registrations expire after 30 days, and expired flows and codes are cleaned transactionally. Total clients are capped by `AICS_OAUTH_CLIENT_LIMIT`, which defaults to 1000, and live consent flows are capped by `AICS_OAUTH_FLOW_LIMIT`, which defaults to 5000. Authorization code is the only interactive grant, PKCE S256 is mandatory, and access tokens target the exact MCP resource.

Access tokens live for one hour. Refresh tokens live for 30 days, rotate on every use, and revoke their family on replay. The database stores only SHA-256 hashes of high-entropy token values. `aics.read` and `aics.write` are enforced for each tool. Every token resolves one active, non-archived AICS account; administrator role does not widen record access. Password change and Account revocation invalidate grants. Ordinary browser logout ends the browser session but intentionally leaves separately consented integrations visible and revocable in Account.

The official MCP SDK worker listens only on configurable loopback port `AICS_MCP_INTERNAL_PORT`. The public server validates and rate-limits the bearer token, forwards an allowlist of protocol headers without cookies, and caps request and response bodies. Effective scopes are persisted on each access and refresh token, so refresh-token narrowing cannot regain a broader grant scope. Browser session, CSRF, Origin, Host, proxy, and cookie controls remain separate and unchanged.

Read tools are `get_workspace_summary`, `list_projects`, `get_project`, `get_project_bible`, `list_episodes`, `get_episode`, `list_characters`, `get_character`, `list_prompts`, and `list_production_gates`. Planning writes are `update_project_bible`, `update_episode_planning`, `replace_episode_shots`, `update_character_planning`, `upsert_project_prompt`, and `update_production_gates`. `archive_content_record` and `restore_content_record` support projects, episodes, characters, and prompts. Separate destructive tools are `delete_project`, `delete_episode`, `delete_character`, `delete_project_prompt`, `delete_episode_shot`, and `delete_production_gate`.

Every write requires `expected_revision`, rejects stale revisions, and returns the new revision plus an exact changed-record summary. Partial updates preserve omitted values. Shot replacement validates the complete list and affects only the selected episode. Prompt changes never rewrite prompt snapshots stored on existing shots. Gate updates never remove omitted gates. Every permanent deletion requires an exact title or name confirmation plus the expected revision; unnamed shots use their exact stable ID. Project deletion reports and removes nested content and associated character images, character deletion removes only its own image, episode deletion removes only its shots, and prompt deletion preserves shot snapshots. Input schemas and service validation reject unknown nested fields, cross-project prompt IDs, malformed IDs, excessive text, and oversized arrays.

MCP character reads expose only whether an approved private image exists. Image bytes, direct upload, and image-only deletion remain browser-only. Confirmed character and project deletion cleans up associated private images without exposing paths. The MCP surface exposes no account deletion, administrator, registration, deployment, publishing, shell, arbitrary database or file, AI generation, or paid API operations. It never returns password hashes, browser sessions, OAuth secrets, private storage paths, or unrelated workspace data.

To connect a compatible client, configure `AICS_PUBLIC_BASE_URL`, deploy behind HTTPS, and enter `https://your-origin.example/mcp` in the client. The client follows discovery, registers its exact callback, opens AICS sign-in and consent, and stores the returned credentials. Never paste a token into a URL, source file, log, or plugin package. This repository contains no owner-specific plugin package or OAuth client.

## 21. Roadmap and appendices

Deferred possibilities include stronger account recovery and identity controls, formal API versioning, automated browser coverage, and documented recovery objectives. None is committed to a date. The owner selected the MIT License for version 0.1.0.

Related references:

- [README](../README.md)
- [Deployment guide](DEPLOYMENT.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](../CHANGELOG.md)

Glossary: a workspace is one user's revisioned JSON planning document; the image root is private file storage for character references; a trusted proxy is an explicitly configured immediate network peer permitted to supply `CF-Connecting-IP`.
