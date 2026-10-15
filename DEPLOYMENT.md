# AI server deployment plan

This is a review-only plan for deploying AI Content Studio to a separate AI server. The coding VPS is only for development and tests. Do not run the production steps on the coding VPS, and do not assume its containers, networks, proxy, ports or DNS match the AI server.

Commands use public placeholders and repository-defined names only. Keep hostnames, IP addresses, credentials, access policies and infrastructure details out of Git and pull request discussion.

## 1. Release gate on a development or CI host

- [ ] Confirm the reviewed commit is on `main` after the pull request is approved and merged.
- [ ] Confirm `git status --short` is empty.
- [ ] Run `node --check dist/app.js` and `node --check dist/seed.js`.
- [ ] Run `python3 -m py_compile server.py`.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `docker build -t ai-content-studio:review .` where Docker is available.
- [ ] Scan the tracked files and Git history for secrets, private exports, database files and personal media.
- [ ] Confirm a license has been selected before changing repository visibility to public.

Do not promote a commit if any required check fails. Tooling that is unavailable is unverified, not passed.

## 2. AI server preflight

Every item in this section requires authorized access to the separate AI server. Do not run these checks on the coding VPS.

- [ ] **AI server access required:** record the currently deployed commit or image tag and confirm the intended target commit.
- [ ] **AI server access required:** inspect the installed Docker and Compose versions.
- [ ] **AI server access required:** inspect existing containers, Compose projects, networks, volumes and port bindings for conflicts. Do not remove or rename unrelated resources.
- [ ] **AI server access required:** inspect the existing HTTPS proxy or tunnel path and its private network reachability. Do not copy private topology into Git.
- [ ] **AI server access required:** verify the intended host port is available and will remain bound to `127.0.0.1`, or use a private container network without publishing the app port.
- [ ] **AI server access required:** create `.env` locally on the AI server from `.env.example`, with a unique username and long random password. Never print or commit the values.
- [ ] **AI server access required:** confirm sufficient disk space and choose an off-server backup destination.

## 3. Backup and change window

- [ ] **AI server access required:** notify the owner of the maintenance window and pause edits in open browser tabs.
- [ ] **AI server access required:** identify the production Compose project and its SQLite volume without guessing from the coding VPS.
- [ ] **AI server access required:** create a consistent SQLite backup using the command in `README.md`.
- [ ] **AI server access required:** copy the backup off the AI server, protect it as sensitive data and verify that the file is non-empty.
- [ ] **AI server access required:** record a private rollback reference for the prior commit or image. Do not place private server details in the repository.

No schema migration is currently planned. The application creates its single `workspace` table if it does not exist. A future schema-changing release must include explicit forward and rollback steps before deployment.

## 4. Production deployment

These steps are intentionally not authorized by this plan alone. Run them only after the pull request is reviewed and merged and the owner explicitly approves deployment.

- [ ] **AI server access required:** fetch the reviewed merge commit from the canonical repository.
- [ ] **AI server access required:** build the image from that exact commit and review the build result before replacing the running app.
- [ ] **AI server access required:** start or update only the AI Content Studio Compose project. Do not use `docker compose down -v`.
- [ ] **AI server access required:** confirm the `studio_data` volume remains attached and no unexpected volume was created.

## 5. Production verification

- [ ] **AI server access required:** check `docker compose ps` and the container health result.
- [ ] **AI server access required:** check `http://127.0.0.1:8787/healthz` from the AI server, or the private service address if the proxy runs in Docker.
- [ ] **AI server access required:** confirm the app port is not publicly reachable over plain HTTP.
- [ ] **AI server access required:** verify the public route uses valid HTTPS before sending Basic authentication credentials.
- [ ] **AI server access required:** verify an unauthenticated app or API request is rejected while `/healthz` returns only its minimal status.
- [ ] **AI server access required:** sign in through the HTTPS route and smoke-test workspace read, save and revision-conflict behavior without using sensitive content.
- [ ] **AI server access required:** confirm existing projects remain present, then create and remove only an agreed fictional smoke-test record.
- [ ] **AI server access required:** review proxy and application logs for errors without copying credentials or private data into the pull request.

## 6. Rollback

- [ ] **AI server access required:** if verification fails, stop the rollout and restore the prior reviewed commit or image while keeping the existing data volume.
- [ ] **AI server access required:** restore the SQLite backup only if data integrity was affected. Preserve the failed database separately for diagnosis.
- [ ] **AI server access required:** repeat health, authentication, HTTPS and data checks after rollback.

## Deployment record

Keep private infrastructure details in an approved private operations record. A public-safe release note may include only the deployed version, verification result, whether a migration occurred and known limitations.
