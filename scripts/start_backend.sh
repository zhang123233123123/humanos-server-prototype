#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install -r requirements.txt

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

python humanos_server.py
