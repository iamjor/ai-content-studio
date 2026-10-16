# AI Content Studio build prompts

This file records the build direction and copy-ready prompts for Codex. Keep it at the repository root for now. The historical entries below are reconstructions from the project conversation, repository commits, PR #1, and the completed deployment. They are summaries of intent, not verbatim copies of the original IDE prompts. Do not treat a historical entry as an instruction to repeat completed work.

## Project rules for every new prompt

- AI Content Studio is a general workspace for multiple AI content projects, not an app dedicated to one story.
- Development happens in the coding VPS repository through the VS Code Codex extension. The separate AI server hosts production.
- Use a feature branch and a draft PR. The owner and reviewer discuss code changes in the PR. Do not merge or deploy without a separate instruction.
- Read `AGENTS.md` before editing. Preserve production data and keep private exports, credentials, database files, and real media out of Git.
- Check that every commit author and committer uses the configured `iamjor` identity. No Codex author, committer, or co-author trailer.
- Document meaningful functions and behavior with useful docstrings or comments. Do not use the em dash character in code or documentation.
- Prepare for eventual open-source publication, but do not change repository visibility or choose a public license without the owner's explicit decision.

## Historical record

### 01. Creative studio concept (completed in the earlier ChatGPT Sites edition)

**Reconstructed direction:** Build a dashboard for planning original AI-generated short-form story series. Support consistent characters, character sheets, story arcs, episode scripts, dialogue, timing, shot or scene prompts, tools, and a repeatable production workflow. The first experiment may be a dramatic short series, but the dashboard itself must work for future projects too.

**Owner decisions:** This is AI content generation, with no required filming or photography. A typical episode target is about one minute. The user wanted free tools where practical and room for future automation.

**Outcome:** An initial Sites edition provided the dashboard. It stored data in browser localStorage and was later retired after the VPS edition was deployed and data was imported.

### 02. General product scope (completed in the first app iteration)

**Reconstructed direction:** Remove hard-coded emphasis on the first story title. Make the home page and navigation generic, with separate projects, episodes, characters, scripts, and production planning. Keep sample content fictional and easy to distinguish from real user data.

**Outcome:** A multi-project dashboard was carried into this repository. The production app currently supports a single shared workspace.

### 03. Self-hosted Docker and SQLite MVP (completed)

**Reconstructed direction:** Move from browser-only storage to a free, self-hosted stack suitable for the owner's AI server. Package the app in Docker, use SQLite in a persistent volume, provide JSON import/export, and make it accessible through the owner's existing HTTPS route. Keep the repository safe for a possible later public release.

**Implementation:** Static dashboard in `dist/`, Python standard-library server in `server.py`, SQLite in a Docker volume, `compose.yaml`, Basic Auth from local environment variables, and revision-aware saves. The app port binds to localhost.

**Source:** [MVP commit](https://github.com/iamjor/ai-content-studio/commit/b748176c) and [README](README.md).

### 04. Repository standards and deployment audit (completed)

**Reconstructed direction:** Clarify that the coding VPS and production AI server are different machines. Add deployment guidance and API integration tests. Enforce readable function documentation, no em dashes, private data exclusions, and owner-only Git commit attribution. Use a draft PR and leave merge and deployment to separate review steps.

**Outcome:** [PR #1](https://github.com/iamjor/ai-content-studio/pull/1) was reviewed and merged as `ea693151`. It added [DEPLOYMENT.md](DEPLOYMENT.md) and [API tests](tests/test_server.py). The attribution rules are in [AGENTS.md](AGENTS.md). This entry describes completed work, not a request to reopen PR #1.

### 05. First AI server deployment (completed by the owner)

**Reconstructed operational direction:** Inspect the AI server independently, build the reviewed commit there, run only the AI Content Studio Compose project, check health and unauthenticated API behavior, connect the existing Cloudflare Tunnel route, then import the JSON exported from the original browser.

**Verified in the conversation:** Docker container became healthy, `/healthz` returned `{"ok": true}`, an unauthenticated workspace request returned HTTP 401, the dashboard was reachable at `https://aics.jomaroliverreyes.com`, and the owner reported a successful import. The earlier Sites edition and the merged branch were later deleted. These observations do not claim a complete production feature audit.

**Owner preference:** No routine backup while this is still an experiment; revisit backups after a project is completed. This does not authorize a risky production migration without a separate rollout decision. The current [AGENTS.md](AGENTS.md) and [DEPLOYMENT.md](DEPLOYMENT.md) still call for a backup before data-changing production migrations, so keep that decision explicit at deployment time.

## Prompt 06: Responsive UI, accounts, and open-source readiness

**Status:** Ready to copy into the VS Code Codex extension. Not started or deployed as of 2026-10-16.

```text
Work in the existing iamjor/ai-content-studio checkout on the coding VPS. Read AGENTS.md and AICS_Build_Prompts.md first. Create a feature branch. Do not edit the production AI server.

Owner feedback from phone screenshots:
- The browser-generated Basic Auth dialog looks like a merged username/password field on iPhone.
- The dashboard overflows horizontally and reads like a zoomed desktop view.
- There is no favicon.
- The violet palette should become light blue, inspired by the owner's portfolio.

Implement:
1. Add an original favicon that suits AI Content Studio.
2. Replace violet accents with a cohesive light blue palette. Provide dark and light themes, default to dark, with an accessible icon control and a saved preference per user.
3. Make the full app responsive for phone, tablet, and desktop. Check navigation, headings, cards, forms, dialogs, action rows, long content, and touch targets. Eliminate document-level horizontal scrolling at narrow widths.
4. Replace HTTP Basic Auth with an in-app login form with distinct labeled username and password inputs. Provide logout and an account settings view where each user can change display name and password.
5. Move from one shared workspace to private per-user workspaces. Preserve the existing single-owner workspace for the initial admin through a tested migration.
6. Add self-registration for regular users and an admin role with basic user management and a registration on/off setting. Never permit public admin registration or self-promotion. Choose safe defaults for a publicly reachable installation.
7. Implement password hashing, secure server-side session handling with HttpOnly and Secure cookies behind HTTPS, protection for state-changing requests, login throttling, and clear session expiry behavior. Keep secrets out of Git and logs.
8. Update tests for login, registration policy, roles, account changes, user data isolation, session behavior, and migration. Update README, .env.example, deployment and contributor guidance for self-hosters and eventual open-source release.

Respect the repository's attribution, comments/docstrings, and no-em-dash rules. Do not change repository visibility or add a public license.

Test on the coding environment. Open a draft PR to main with a concise migration plan, test results, screenshots for narrow mobile and desktop widths in both themes, and any limitations. Do not merge, deploy, or touch the production SQLite volume. The owner will request a browser audit after review and deployment are separately authorized.
```

## How to continue this log

For each later prompt, add a numbered section with the exact copy-ready request, date, status, related PR or commit, and verification outcome. If an original prompt is missing, label the replacement as reconstructed. Never put credentials, private exports, or production database contents in this file.
