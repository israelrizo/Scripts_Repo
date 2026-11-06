#!/usr/bin/env python3
"""Start the web app with waitress (production WSGI server) on SR_HOST:SR_PORT (127.0.0.1:8090)."""
import sys

from waitress import serve

from srapp import scheduler, users
from srapp.app import app
from srapp.config import Config

if __name__ == "__main__":
    if users.count() == 0:
        sys.exit("No users yet. Create the first admin:\n"
                 "  python3 manage_users.py add <username> --role admin")
    scheduler.start_background()
    print(f"JMeter Control Center on http://{Config.HOST}:{Config.PORT}  repo={Config.REPO_ROOT}")
    serve(app, host=Config.HOST, port=Config.PORT, threads=8, max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
