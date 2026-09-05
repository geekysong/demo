#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ] || [ ! -f .env ]; then
  echo 'Complete the setup in LOCAL_SETUP.md first.' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn orchestrator:app --host 127.0.0.1 --port 8000
