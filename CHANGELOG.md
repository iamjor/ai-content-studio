# Changelog

## Unreleased

## 0.4.1 - 2026-10-20

- Fixed login, registration, password recovery, and required security setup layout so one explicit authentication view is visible at a time on desktop and mobile.
- Made recovery setup confirmation consume its submitted code and made public password recovery atomic under concurrent replay.
- Kept recovery failure responses generic while providing an explicit success response, revoking sessions and OAuth access after a successful reset.
- Split login and recovery throttles into hashed normalized-account, account-and-source, and higher-ceiling source scopes with bounded storage and retry guidance.
- Hardened attachment filenames against decoded control characters while retaining safe Unicode downloads.
- Separated prompt attachment metadata from responsive Download and Delete attachment actions, including long names and multiple files.
- Added accessible confirmed assignment and MCP-permission notifications, a searchable per-user assignment dialog, and duplicate-click protection while saves are pending.
- Added canonical domain identities for active tools, safe linking to existing admin tools, admin sharing of user-owned tools without owner changes, and non-destructive preservation of legacy duplicates.
- Added permission-scoped search, result counts, empty states, and bounded pagination for tools, users, projects, episodes, characters, and prompts.
- Added UTC last-login and bounded last-seen account timestamps with administrator-only Online, Offline, and local-time activity display.
- Added the additive schema version 7 migration for canonical tool domains and account activity timestamps.

## 0.4.0 - 2026-10-20

- Added administrator-assisted password reset with one-time temporary-password display, optional forced change, session and OAuth revocation, recovery-code invalidation, and minimal secret-free security events.
- Added mandatory eight-code recovery setup, generic no-email password recovery, single-use salted code hashes, source and account throttling, replay protection, and authenticated regeneration.
- Added a validated administrator-configured public Contact page URL for users without a valid code.
- Expanded project prompts to 120,000-character raw Markdown with sanitized preview, HTTPS source metadata, and private project-scoped attachments.
- Added PDF, DOCX, Markdown, text, PNG, JPEG, and WebP signature validation with 20 MB per-file, 20-file, and 100 MB per-prompt limits.
- Added user-owned private tools, hidden-by-default administrator tools, explicit per-user assignments, and backend-enforced view-and-use-only access.
- Added independent MCP enabled, read, write, archive/restore, and permanent-delete permissions with immediate token invalidation after reductions.
- Added schema version 6 additive migration, v0.4.0 security and isolation tests, and complete-volume backup guidance.

## 0.3.0 - 2026-10-19

- Added an OAuth 2.1 authorization-code flow with S256 PKCE, discovery metadata, exact redirect validation, short access tokens, rotating refresh tokens, and revocation.
- Added account-visible connected integrations with narrow read and write scopes.
- Added an official-SDK Streamable HTTP MCP endpoint at /mcp.
- Added account-scoped read, planning update, prompt, gate, archive, restore, and separately confirmed permanent-delete tools with optimistic workspace revision conflicts.
- Added bounded tool schemas, structured errors, request limiting, precise deletion receipts, and MCP safety annotations.
- Added additive schema version 5 tables for OAuth clients, flows, codes, grants, hashed tokens, and MCP rate limits.
- Added proxy-safe OAuth public-write limits, a bounded expiring client policy, per-token effective scopes, and MCP-aware container health.
- Added OAuth, transport, scope, expiry, isolation, migration, conflict, preservation, limit, and deletion tests.
- Accepted bounded optional OAuth `ui_locales` hints without persisting them in OAuth records.
- Allowed consent submission only to the validated registered callback origin and completed successful consent with `303 See Other`.
- Added opt-in sanitized MCP initialization diagnostics without recording credentials, tool arguments, or workspace content.
- Preserved modern `Mcp-Method`, `Mcp-Name`, and case-insensitive `Mcp-Param-*` routing headers through the public proxy.
- Verified a live self-hosted HTTPS deployment with successful OAuth consent, token exchange, ChatGPT tool discovery, read-only project listing, and healthy web and MCP readiness checks.
- Disabled temporary MCP diagnostics after production verification.

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
