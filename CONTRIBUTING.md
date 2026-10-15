# Contributing

Thanks for improving AI Content Studio. Open an issue with a concrete use case before large changes. Keep sample data fictional and avoid committing `.env`, database files, exports, media, credentials or personal project content.

For changes, run `node --check dist/app.js`, `node --check dist/seed.js`, `python3 -m py_compile server.py` and `python3 -m unittest discover -s tests -v`. Build the Docker image where Docker is available. Keep UI copy and README instructions current. Use small pull requests and note any database migration or backward compatibility impact.

Use plain punctuation in prose and do not use em dashes. En dashes are acceptable for numeric ranges such as `0–3 seconds`.

The repository owner will choose a license before public release. Until then, this code is available only under the repository's access settings.
