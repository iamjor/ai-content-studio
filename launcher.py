"""Run the browser server and official-SDK MCP process in one container."""

import os
import subprocess
import sys

import server


def main():
    """Start the private MCP listener, then serve the public same-origin app."""
    server.setup()
    environment = dict(os.environ)
    child = subprocess.Popen(
        [sys.executable, "mcp_server.py"],
        env=environment,
        close_fds=True,
    )
    try:
        httpd = server.ThreadingHTTPServer(
            ("0.0.0.0", int(os.environ.get("PORT", "8787"))),
            server.Handler,
        )
        httpd.daemon_threads = True
        httpd.serve_forever()
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


if __name__ == "__main__":
    main()
