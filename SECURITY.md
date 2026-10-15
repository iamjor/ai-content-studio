# Security

Please do not post credentials, database backups, private story assets or vulnerabilities in public issues. Once the repository exists, use its private GitHub vulnerability reporting or security advisory flow to report a security issue. Rotate the studio password if it is exposed.

Run the app behind HTTPS; the container binds only to localhost by default. Authentication is single-owner HTTP Basic authentication. The SQLite database and `.env` are not tracked by Git. Review the deployment's proxy and access settings before inviting others.
