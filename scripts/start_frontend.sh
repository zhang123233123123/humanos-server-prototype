#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../frontend"
python3 -m http.server 8766 --bind 0.0.0.0
