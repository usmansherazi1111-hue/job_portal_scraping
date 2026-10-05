#!/bin/sh
# Mac / Linux: first run sets up .venv, then starts Hireline on http://127.0.0.1:${HIRELINE_PORT:-8100}
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt; } || exit 1
mkdir -p data
echo "Hireline is running at http://127.0.0.1:${HIRELINE_PORT:-8100} (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn hireline.app:app --host 127.0.0.1 --port "${HIRELINE_PORT:-8100}"