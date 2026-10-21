# AI Content Studio 0.4.2 release notes

Version 0.4.2 is a focused search-interface and presence-refresh hotfix. The final source and live self-hosted deployment were reviewed and verified by the owner.

## Search controls

Projects, Episodes, Characters, Prompts, Tools, and Users now use the same responsive search control. Each control includes an in-field search icon, a contextual placeholder, a compact labeled clear action that appears only when needed, and an aligned live result count. Existing permission-scoped filtering and bounded pagination are unchanged. The control uses explicit light and dark theme values with keyboard focus and accessible labels.

## Presence refresh

Signed-in browsers send an authenticated heartbeat every 60 seconds while the page is visible. The endpoint uses the existing session validation, CSRF protection, and one-minute last-seen write bound. Heartbeats stop while hidden and resume when visible.

Administrators viewing Users receive a fresh bounded user list every 30 seconds without a page reload. Polling stops outside that section and while the page is hidden. Online still requires an active, non-archived account, recent activity within five minutes, and at least one unexpired session. Logout, disabled or archived accounts, and expired sessions therefore display Offline. Online uses light-green text and an aligned matching dot. Offline uses red text and an aligned matching dot. The visible label remains available without relying on color, and the existing local-time Last login display stays on the row below.

## Compatibility

This hotfix keeps schema version 7. It does not migrate or rewrite user, workspace, prompt, attachment, tool, assignment, OAuth, MCP, recovery, or session records. Existing authentication and authorization behavior remains in place.

## Validation scope

Focused coverage includes heartbeat authentication, bounded last-seen writes, visible-page timer contracts, automatic administrator presence refresh, logout presence, ineligible and expired-session presence, accessible status markup, CSS specificity, status alignment, and both search themes. The final complete suite reported 56 passing tests. Python compilation, JavaScript syntax, and whitespace checks passed. The owner verified the compact search controls, automatic Online and Offline transitions, status colors, dot alignment, and responsive behavior in the live self-hosted browser deployment. The runtime checkpoint before this documentation receipt is `0b8793e`.
