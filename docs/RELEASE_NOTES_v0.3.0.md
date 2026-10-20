# AI Content Studio 0.3.0 release notes

Version 0.3.0 adds secure, account-scoped remote MCP access to the v0.2 content-planning workspace. The release was verified on a live self-hosted HTTPS installation with a private ChatGPT connection. The public repository does not include production credentials, OAuth token values, private workspace records, or the private ChatGPT app configuration.

## Integration

- Added the official MCP Python SDK 2.2.0 with an exact runtime pin.
- Added Streamable HTTP at `/mcp` on the existing public origin.
- Added OAuth authorization-server and protected-resource discovery.
- Added public-client registration with exact redirect validation.
- Added authorization code with mandatory S256 PKCE and explicit AICS sign-in and consent.
- Added one-hour access tokens and rotating 30-day refresh tokens stored only as hashes.
- Added `aics.read` and `aics.write` scope checks tied to the owning account.
- Added Account integration visibility and revocation without exposing token values.
- Accepted bounded optional OAuth `ui_locales` hints as non-persisted UI hints for compatible clients.
- Restricted consent form submission to the validated registered callback origin and used `303 See Other` after successful authorization.
- Preserved client-provided `Mcp-Method`, `Mcp-Name`, and case-insensitive `Mcp-Param-*` routing metadata through the public proxy for modern MCP discovery and tool calls.

## Tools

Read tools cover workspace summaries, projects, project Bibles, episodes, characters, prompts, and production gates. Write tools cover partial Bible changes, episode synopsis and beats, complete episode shot replacement, character reference planning, prompt upsert, and non-destructive gate updates. Archive and restore apply to projects, episodes, characters, and prompts. Separate permanent-delete tools cover projects, episodes, characters, project prompts, episode shots, and production gates.

Every mutation requires the caller's expected workspace revision. A stale value returns a conflict with the current revision. Successful mutations return the new revision and exact changed-record metadata. Partial writes preserve scripts, hooks, IDs, images, archive state, descriptions, and unrelated records. Prompt changes do not rewrite final prompt snapshots already stored on shots.

Tools use bounded input schemas and server-side validation. The server rejects unknown nested fields, excessive text, oversized arrays, malformed identifiers, and prompt links outside the selected project. Tool annotations distinguish reads, ordinary writes, archive, restore, and destructive deletes. Every delete requires the expected revision and an exact title or name confirmation. Because shots have no title or name, shot deletion requires the exact stable shot ID. Project receipts enumerate nested episode, character, prompt, shot, gate, and private-image cleanup; character deletion removes its approved private image; prompt deletion preserves shot snapshots.

## Security and privacy

The MCP worker binds only to loopback. The public service validates bearer tokens, applies a per-token request limit, forwards only protocol headers, and never forwards browser cookies. Public OAuth registration and authorization flows have proxy-safe per-source limits, bounded storage, and safe expiry cleanup. Effective scope is stored per token so a narrowed refresh remains read-only. Compose checks both web and MCP readiness. Browser session, CSRF, Origin, Host, proxy, and cookie protections remain unchanged.

An opt-in `AICS_MCP_DIAGNOSTICS` mode records only bounded transport failure metadata. It excludes authorization values, cookies, OAuth credentials, tool arguments, full request and response bodies, and workspace content. It is disabled by default and was returned to disabled after the controlled production verification.

MCP reads never return image bytes, private image URLs, storage paths, passwords, sessions, OAuth secrets, administrator data, or another account's workspace. Direct image upload and image-only deletion remain browser-only. Confirmed character and project deletion also remove associated private images as required. The MCP tool catalog contains no account deletion, administrator, registration, deployment, publishing, shell, arbitrary file or database, AI generation, or paid API tools.

## Migration and compatibility

Schema version 5 adds OAuth clients, consent flows, authorization codes, grants, hashed tokens, and MCP rate-limit tables. Workspace normalization adds stable IDs only to prompts, gates, or shots that lack one. Existing users, sessions, workspace revisions, project IDs, descriptions, episodes, hooks, scripts, characters, images, v0.2 planning records, and legacy tables are preserved.

JSON import and export remain text-only and compatible with older workspace data. Private images remain in the SQLite and image volume backup boundary.

## Self-hosting

Set `AICS_PUBLIC_BASE_URL` to the exact external HTTPS origin. The default loopback HTTP origin exists only for local development. Install the exact dependency pin, run `launcher.py`, and keep the published container port bound to loopback behind an HTTPS reverse proxy or tunnel.

A compatible client connects to `https://your-origin.example/mcp`, follows discovery, registers its exact callback, and opens the AICS consent screen. Never put a bearer token in a URL, source file, log, browser export, or plugin package.

## Validation scope

The focused suite covers discovery, redirect validation, PKCE consent, token rotation and revocation, unauthenticated rejection, account isolation, revisions and conflicts, partial preservation, size limits, archive and restore, deletion confirmation and isolation, cascade and image cleanup, actual MCP initialization, tool listing, and representative read and write calls.

The release was then built and started through Docker Compose on the maintained self-hosted installation. `/healthz` and `/mcp/ready` returned healthy results. A private ChatGPT connection completed OAuth authorization and token exchange, loaded the MCP tool catalog through `server/discover`, and completed a read-only project-listing request. Temporary sanitized diagnostics identified and verified the modern routing-header compatibility fix, then were disabled. No production credential, token value, project content, prompt body, script, image, or private plugin configuration was committed to the public repository.

Rollback restoration and a destructive production MCP operation were not exercised as part of release verification.

## Known limits

- One approved private reference image per character remains the storage model.
- Direct image upload and image-only deletion remain browser-only.
- OAuth client registration is intended for compatible public MCP clients and does not issue client secrets.
- There is no email recovery, MFA, external identity provider, or audit log.
- The single-container launcher is suitable for the current self-hosted scope, not horizontal multi-replica deployment.
