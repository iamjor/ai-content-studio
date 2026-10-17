# Public release checklist

Complete this before changing repository visibility. This file does not authorize a visibility change, tag, release, or deployment.

## Source and history

- [x] Scan tracked files for credentials, tokens, private keys, `.env`, SQLite files, exports, backups, logs, personal media, hostnames, addresses, and infrastructure details.
- [x] Scan every locally reachable Git object and commit diff, not only the current tree.
- [x] Review ignored and untracked files before packaging artifacts.
- [ ] Confirm commit attribution follows `AGENTS.md` for the final reviewed branch.
- [x] Confirm no production database or volume entered development artifacts.

The local audit result and its limitations are recorded in the [version 0.1.0 release notes](RELEASE_NOTES_v0.1.0.md). GitHub-hosted artifacts and repository settings require a separate authenticated review.

## Content and dependencies

- [ ] Confirm all samples and screenshots are fictional or approved.
- [x] Confirm the favicon and interface assets are original or properly licensed.
- [ ] Review every external link, including the verified owner portfolio.
- [x] Confirm the runtime has no undeclared third-party library dependency.
- [ ] Review base-image provenance and security support.

## Install and upgrade

- [ ] Test a clean clone, environment setup, Docker build, admin bootstrap, login, and health check.
- [ ] Test local non-Docker development with a temporary database.
- [ ] Test the legacy single-owner migration against a backup copy.
- [ ] Confirm rollback preserves the backup, legacy table, private image directory, and tool catalog.
- [ ] Verify registration defaults off and Secure cookies default on.
- [ ] Confirm README and deployment commands match the release.

## Security and privacy

- [ ] Review hashing, session lifetime, cookie flags, CSRF, throttling, roles, workspace and image isolation, scoped deletion, and last-admin protection.
- [ ] Verify logs exclude passwords, cookies, CSRF tokens, bodies, and private content.
- [ ] Enable private vulnerability reporting or document a private channel.
- [ ] Review branch protection, required reviews, alerts, secret scanning, and release permissions.
- [ ] Document unsupported password reset, MFA, external identity, and audit logging.

## Presentation and accessibility

- [ ] Review phone, tablet, and desktop widths in both themes.
- [ ] Confirm there is no document-level horizontal scrolling.
- [ ] Test keyboard navigation, focus, labels, dialogs, touch targets, contrast, and reduced motion.
- [ ] Capture approved screenshots with fictional data only.
- [ ] Verify footer app name, version, year, copyright, and portfolio link.

## License decision

The owner selected the permissive MIT License for version 0.1.0.

- [x] Record the owner's license choice.
- [x] Add the canonical MIT text with the owner's 2026 copyright notice.
- [ ] Do not claim a completed public release until this change is merged and visibility is intentionally changed.
