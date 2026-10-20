# AI Content Studio 0.4.0 release notes

Version 0.4.0 adds account recovery, long-form prompt assets, private tool ownership, and per-user MCP entitlements. It is a source release for owner review. It has not been deployed to production by this change.

## Account security

Administrators can reset a selected account to a supplied or generated temporary password. The response displays that value once. Reset revokes browser sessions, OAuth authorization grants and tokens, pending authorization codes, and all previous recovery codes. The default requires a password change at next login. A minimal security event records only event type, actor, subject, and time.

Every new account, and every existing account without a confirmed set, must generate eight random recovery codes and confirm one before dashboard entry. Only salted PBKDF2 hashes are stored. Recovery responses are generic, codes are consumed atomically, requests are bounded and throttled by source and normalized account, and success revokes connected access. Account Settings can replace the set after current-password confirmation. An optional validated HTTPS Contact page can be configured without exposing an administrator email.

## Prompt library and private files

Prompt bodies accept up to 120,000 characters of exact raw Markdown. The browser preview escapes raw HTML before applying a small readable Markdown subset. Prompts also support an optional HTTPS source URL and up to 20,000 characters of source notes.

A prompt can own up to 20 files and 100 MB total, with a 20 MB per-file limit. Supported files are PDF, DOCX, Markdown, UTF-8 text, PNG, JPEG, and WebP. The server validates signatures and structure, uses random storage identifiers, and serves files only through authenticated account and project-scoped routes. Images can render inline; PDF and DOCX text or embedded images are not extracted. Prompt deletion removes current attachments while episode shot prompt snapshots remain unchanged.

The browser JSON command is explicitly text-only. A complete backup must preserve SQLite, `/data/images`, and `/data/prompt-attachments` from one consistent backup point.

## Tools and MCP

Regular users see their own tools and active administrator tools explicitly assigned to them. Assigned administrator tools are view and use only. Administrators can manage all user-created tools. Existing shared tools become hidden from regular users until assigned, while IDs, categories, links, purpose text, and archive state are preserved.

Regular users have no MCP access by default. Administrators can independently grant enabled, read, write, archive/restore, and permanent-delete permissions. A new UI grant defaults to read-only. Consent, code exchange, refresh, bearer resolution, tools/list discovery, and tool execution use current entitlements. Permission reductions revoke existing grants and tokens immediately. Administrators retain v0.3.0 MCP compatibility.

## Migration and limitations

Schema version 6 additively adds recovery state and hashes, security events, prompt attachment metadata, tool ownership and assignments, and MCP permissions. Existing records and workspace revisions are preserved. Uploaded files remain outside SQLite in the persistent private volume.

This release does not add SMTP, email verification, resend behavior, security questions, external identity, paid services, PDF or DOCX extraction, or a new database. Production deployment, backup, and verification require separate owner authorization.
