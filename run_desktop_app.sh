#!/bin/sh
# Run the AZAN TV desktop app from repo root.
# The app finds ffplayout/ and bin/ at repo root automatically (app_backend uses REPO_ROOT).
cd "$(dirname "$0")"
exec python3 app/desktop_app.py "$@"
