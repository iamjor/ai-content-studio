# AI Content Studio 0.4.2 release notes

Version 0.4.2 is a focused search-interface and presence-refresh hotfix. It is prepared for owner review and has not been deployed by this change.

## Search controls

Projects, Episodes, Characters, Prompts, Tools, and Users now use the same responsive search control. Each control includes an in-field search icon, a contextual placeholder, a compact labeled clear action that appears only when needed, and an aligned live result count. Existing permission-scoped filtering and bounded pagination are unchanged. The control uses explicit light and dark theme values with keyboard focus and accessible labels.

## Presence refresh

Signed-in browsers send an authenticated heartbeat every 60 seconds while the page is visible. The endpoint uses the existing session validation, CSRF protection, and one-minute last-seen write bound. Heartbeats stop while hidden and resume when visible.

Administrators viewing Users receive a fresh bounded user list every 30 seconds without a page reload. Polling stops outside that section and while the page is hidden. Online still requires an active, non-archived account, recent activity within five minutes, and at least one unexpired session. Logout, disabled or archived accounts, and expired sessions therefore display Offline. The status includes both a colored indicator and visible text, and the existing local-time Last login display remains unchanged.

## Compatibility

This hotfix keeps schema version 7. It does not migrate or rewrite user, workspace, prompt, attachment, tool, assignment, OAuth, MCP, recovery, or session records. Existing authentication and authorization behavior remains in place.

## Validation scope

Focused coverage includes heartbeat authentication, bounded last-seen writes, visible-page timer contracts, automatic administrator presence refresh, logout presence, ineligible and expired-session presence, accessible status markup, and both search themes. The complete automated suite should be run against the reviewed commit. Browser appearance and live production behavior still require operator verification in the target environment.
