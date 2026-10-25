#!/usr/bin/env bash
# VoiceOps 2026 run command (wrapper around run.py)
set -euo pipefail
cd "$(dirname "$0")"
python3 run.py "$@"
