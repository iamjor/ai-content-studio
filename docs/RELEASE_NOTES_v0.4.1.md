# AI Content Studio 0.4.1 release notes

Version 0.4.1 is a focused authentication, recovery, and prompt attachment hotfix. It is prepared for owner review and has not been deployed by this change.

## Fixed

- Login, registration, password recovery, and required security setup now use explicit mutually exclusive views. Registration controls appear only when registration is enabled, and closing a secondary view returns to a clean Sign in state.
- Required security setup fits the eight recovery codes and actions with balanced desktop and mobile spacing.
- The recovery code used to confirm setup is consumed immediately. Password recovery checks a fixed eight hashes for valid requests and atomically allows only one concurrent use of a code.
- Recovery failures keep one generic public response shape. Successful password changes are explicit and revoke browser sessions plus OAuth grants and tokens.
- Login and recovery now use separate bounded throttle scopes. Login combines the normal account-and-source limit with a bounded account limit across sources and a higher source ceiling, while trusting forwarded addresses only from configured proxies.
- Decoded attachment filenames containing ASCII controls or DEL are rejected. Safe Unicode filenames remain available through UTF-8 Content-Disposition encoding.
- Prompt attachment rows separate long filename and MIME metadata from responsive Download and Delete attachment actions.

## Upgrade notes

No schema change or data rewrite is required. The application remains on schema version 6. Back up SQLite, /data/images, and /data/prompt-attachments together, replace the application image, and retain the existing volume.

After upgrade, verify account login, forced password changes, recovery-code setup and replay rejection, prompt attachment download names, and both /healthz and /mcp/ready.

## Scope

This hotfix does not add features, deploy to production, create a tag, or publish a release.
