# AI Content Studio 0.3.0 release notes

Version 0.3.0 adds secure, account-scoped remote MCP access to the v0.2 content-planning workspace. This development change does not deploy an installation, create a tag or GitHub Release, register a production OAuth client, or include a private ChatGPT plugin package.

## Integration

- Added the official MCP Python SDK 2.2.0 with an exact runtime pin.
- Added Streamable HTTP at `/mcp` on the existing public origin.
- Added OAuth authorization-server and protected-resource discovery.
- Added public-client registration with exact redirect validation.
- Added authorization code with mandatory S256 PKCE and explicit AICS sign-in and consent.
- Added one-hour access tokens and rotating 30-day refresh tokens stored only as hashes.
- Added `aics.read` and `aics.write` scope checks tied to the owning account.
- Added Account integration visibility and revocation without exposing token values.

## Tools

Read tools cover workspace summaries, projects, project Bibles, episodes, characters, prompts, and production gates. Write tools cover partial Bible changes, episode synopsis and beats, complete episode shot replacement, character reference planning, prompt upsert, and non-destructive gate updates. Archive and restore apply to projects, episodes, characters, and prompts. Separate permanent-delete tools cover projects, episodes, characters, project prompts, episode shots, and production gates.

Every mutation requires the caller's expected workspace revision. A stale value returns a conflict with the current revision. Successful mutations return the new revision and exact changed-record metadata. Partial writes preserve scripts, hooks, IDs, images, archive state, descriptions, and unrelated records. Prompt changes do not rewrite final prompt snapshots already stored on shots.

Tools use bounded input schemas and server-side validation. The server rejects unknown nested fields, excessive text, oversized arrays, malformed identifiers, and prompt links outside the selected project. Tool annotations distinguish reads, ordinary writes, archive, restore, and destructive deletes. Every delete requires the expected revision and an exact title or name confirmation. Because shots have no title or name, shot deletion requires the exact stable shot ID. Project receipts enumerate nested episode, character, prompt, shot, gate, and private-image cleanup; character deletion removes its approved private image; prompt deletion preserves shot snapshots.

## Security and privacy

The MCP worker binds only to loopback. The public service validates bearer tokens, applies a per-token request limit, forwards only protocol headers, and never forwards browser cookies. Browser session, CSRF, Origin, Host, proxy, and cookie protections remain unchanged.

MCP reads never return image bytes, private image URLs, storage paths, passwords, sessions, OAuth secrets, administrator data, or another account's workspace. Direct image upload and image-only deletion remain browser-only. Confirmed character and project deletion also remove associated private images as required. The MCP tool catalog contains no account deletion, administrator, registration, deployment, publishing, shell, arbitrary file or database, AI generation, or paid API tools.

## Migration and compatibility

Schema version 5 adds OAuth clients, consent flows, authorization codes, grants, hashed tokens, and MCP rate-limit tables. Workspace normalization adds stable IDs only to prompts, gates, or shots that lack one. Existing users, sessions, workspace revisions, project IDs, descriptions, episodes, hooks, scripts, characters, images, v0.2 planning records, and legacy tables are preserved.

JSON import and export remain text-only and compatible with older workspace data. Private images remain in the SQLite and image volume backup boundary.

## Self-hosting

Set `AICS_PUBLIC_BASE_URL` to the exact external HTTPS origin. The default loopback HTTP origin exists only for local development. Install the exact dependency pin, run `launcher.py`, and keep the published container port bound to loopback behind an HTTPS reverse proxy or tunnel.

A compatible client connects to `https://your-origin.example/mcp`, follows discovery, registers its exact callback, and opens the AICS consent screen. Never put a bearer token in a URL, source file, log, browser export, or plugin package.

## Validation scope

The focused suite covers discovery, redirect validation, PKCE consent, token rotation and revocation, unauthenticated rejection, account isolation, revisions and conflicts, partial preservation, size limits, archive and restore, deletion confirmation and isolation, cascade and image cleanup, actual MCP initialization, tool listing, and representative read and write calls.

Browser appearance, Docker build and health, and live reverse-proxy behavior must be reported as unverified when their required tools are unavailable. Production migration, OAuth clients, real records, media, deployment, and rollback were not exercised by this development PR.

## Known limits

- One approved private reference image per character remains the storage model.
- Direct image upload and image-only deletion remain browser-only.
- OAuth client registration is intended for compatible public MCP clients and does not issue client secrets.
- There is no email recovery, MFA, external identity provider, or audit log.
- The single-container launcher is suitable for the current self-hosted scope, not horizontal multi-replica deployment.
