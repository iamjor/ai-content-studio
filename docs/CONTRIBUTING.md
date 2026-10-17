# Contributing

Keep sample data fictional. Never commit `.env`, SQLite files, exports, backups, media, credentials, logs, or personal content.

## Development standard

Document meaningful functions, classes, features, security decisions, migrations, side effects, and failure behavior. Use Python docstrings and concise JSDoc or nearby JavaScript comments.

Do not use U+2014 in code comments, UI copy, documentation, commit messages, or pull request text. En dashes remain acceptable for numeric ranges such as `0–3 seconds`.

Run:

```sh
node --check dist/app.js
node --check dist/seed.js
python3 -m py_compile server.py tests/test_server.py
python3 -m unittest discover -s tests -v
docker build -t ai-content-studio:review .
```

Review phone, tablet, and desktop widths in both themes, including a long page with the sidebar open and closed. Use only fictional or approved screenshot content. Report missing runtime, browser, or Docker tooling as unverified.

Explain authentication, persistence, migration, compatibility, tests, screenshots, and limitations in the pull request. Do not add a license or change visibility until the owner decides.
