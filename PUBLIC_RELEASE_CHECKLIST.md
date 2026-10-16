# Public release checklist

Complete this before changing repository visibility. This file does not authorize a visibility change or add a license.

## Source and history

- [ ] Scan tracked files for credentials, tokens, private keys, `.env`, SQLite files, exports, backups, logs, personal media, hostnames, addresses, and infrastructure details.
- [ ] Scan every reachable Git object and commit diff, not only the current tree.
- [ ] Review ignored and untracked files before packaging artifacts.
- [ ] Confirm commit attribution follows `AGENTS.md`.
- [ ] Confirm no production database or volume entered development artifacts.

## Content and dependencies

- [ ] Confirm all samples and screenshots are fictional or approved.
- [ ] Confirm the favicon and interface assets are original or properly licensed.
- [ ] Review every external link, including the verified owner portfolio.
- [ ] Confirm the runtime has no undeclared dependency and review every dependency license.
- [ ] Review base-image provenance and security support.

## Install and upgrade

- [ ] Test a clean clone, environment setup, Docker build, admin bootstrap, login, and health check.
- [ ] Test local non-Docker development with a temporary database.
- [ ] Test the legacy single-owner migration against a backup copy.
- [ ] Confirm rollback preserves the backup and legacy table.
- [ ] Verify registration defaults off and Secure cookies default on.
- [ ] Confirm README and deployment commands match the release.

## Security and privacy

- [ ] Review hashing, session lifetime, cookie flags, CSRF, throttling, roles, isolation, and last-admin protection.
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

Recommended starting point: **Apache License 2.0**. It is permissive, widely understood, and includes an explicit patent grant. **MIT** is a shorter permissive alternative.

- [ ] Owner selects a license after reviewing goals and third-party obligations.
- [ ] Add only the owner-approved license in a separate reviewed change.
- [ ] Do not claim an open-source release until license and visibility are intentionally changed.
