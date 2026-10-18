# AI Content Studio 0.2.0 release notes

Version 0.2.0 is the content-planning feature release after v0.1.0. This development change does not deploy an installation, create a tag, or create a GitHub Release.

## Highlights

- Edit a project title, genre, description, stage, and structured project Bible.
- Keep episode synopsis and beat outline separate from the existing hook and full script.
- Build and reorder compact shot cards with timing, visual, camera, dialogue, audio, prompt, reference, settings, output, and status fields.
- Save project-scoped reusable prompts and copy their bodies. Linked shots retain their own final prompt snapshots.
- Record character reference requirements plus must-keep, must-avoid, wardrobe, and voice continuity locks.
- Track editable project gates and explicit shot progress without treating text presence as approval.
- Transfer all new text records through the existing JSON import and export workflow.

## Compatibility and migration

Startup records schema version 4 and normalizes existing workspace JSON in place. Missing v0.2 fields receive empty values or lists. Existing users, sessions, workspace revisions, project IDs, episode IDs, descriptions, hooks, scripts, characters, archive flags, image metadata, and image bytes are preserved. Existing v0.1 JSON remains importable, and v0.2 export remains text-only.

Back up the SQLite database and private image directory together before any production rollout. Keep the application offline for edits during backup and migration verification. Never use `docker compose down -v` during a normal upgrade.

## Private image limit

Version 0.2 intentionally retains the existing one approved private image per character. Replacement, viewing, deletion, account scoping, and persistence continue through the existing image route, SQLite metadata, and image volume. Multiple labeled character or prop references are deferred. Public URLs are not used to imitate private multi-image storage.

## Security and privacy

The release retains server-side sessions, CSRF and same-origin enforcement, optimistic revision conflicts, account-scoped workspaces, administrator role checks, archived records, and private image authorization. It adds no AI generation, paid API, external MCP connection, or anonymous workspace access.

## Validation targets

- Python compilation and full integration tests
- JavaScript syntax checks for `dist/app.js` and `dist/seed.js`
- HTML-compatible markup review
- Docker image build and local health check where Docker is available
- Manual narrow-screen and keyboard review where a browser is available

Unavailable tools or production checks must be reported as unverified. Production rollout is a separate owner-approved task.

## Later integration direction

A later integration may expose account-scoped read and list operations for projects, episodes, characters, prompts, and shots, plus controlled create and update operations with workspace revision conflicts. The initial integration should have no delete tool. It should use revocable, expiring, narrowly scoped credentials, never a browser session cookie as a permanent API credential.

## License

The source remains licensed under the [MIT License](../LICENSE). Historical v0.1.0 tags, release notes, and release archives remain unchanged.
