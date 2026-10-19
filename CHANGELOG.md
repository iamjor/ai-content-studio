# Changelog

## Unreleased

## 0.3.0 - 2026-10-19

- Added an OAuth 2.1 authorization-code flow with S256 PKCE, discovery metadata, exact redirect validation, short access tokens, rotating refresh tokens, and revocation.
- Added account-visible connected integrations with narrow read and write scopes.
- Added an official-SDK Streamable HTTP MCP endpoint at /mcp.
- Added account-scoped read, planning update, prompt, gate, archive, restore, and separately confirmed permanent-delete tools with optimistic workspace revision conflicts.
- Added bounded tool schemas, structured errors, request limiting, precise deletion receipts, and MCP safety annotations.
- Added additive schema version 5 tables for OAuth clients, flows, codes, grants, hashed tokens, and MCP rate limits.
- Added OAuth, transport, scope, expiry, isolation, migration, conflict, preservation, limit, and deletion tests.
- Prepared release and upgrade documentation without creating a tag, GitHub Release, OAuth client, or deployment.

## 0.2.0 - 2026-10-18

- Added editable project details and structured project Bible sections.
- Added separate episode synopsis and beat outline fields without changing hooks or scripts.
- Added compact, reorderable shot plans with prompt snapshots, settings, assets, review links, and status.
- Added project-scoped reusable prompt libraries with copy actions and update timestamps.
- Added character reference requirements and continuity locks while retaining one private approved image per character.
- Added editable project production gates, project links, and explicit shot progress.
- Added non-destructive workspace normalization and schema version 4 migration coverage.
- Prepared release documentation for v0.2.0 without creating a tag or GitHub Release.

## 0.1.0 - 2026-10-17

- Replaced browser Basic Auth with an accessible in-app login and logout flow.
- Added password hashing, server-side sessions, CSRF protection, expiry, and login throttling.
- Added private per-user workspaces with non-destructive legacy owner migration.
- Added closed-by-default registration and administrator user management.
- Added account profile, password, and saved theme settings.
- Added responsive light-blue dark and light themes, an original favicon, and attribution footer.
- Added explicit user disable, archive, restore, and scoped permanent deletion.
- Added archive, restore, and deletion for projects, episodes, and characters, including empty workspaces.
- Added private validated character reference images with replacement and cleanup.
- Migrated the shared production tool catalog into administrator-managed SQLite records.
- Replaced the spark mark with an original film and story mark and added explicit responsive sidebar controls.
- Expanded integration tests and self-hosting, migration, backup, security, and release guidance.
- Selected the MIT License for the first public source release.

Repository visibility, a GitHub Release, and installation upgrades are separate operations.
