#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

IMPORT_STATUS=0
python3 "$REPO_ROOT/scripts/import_queued_skills.py" || IMPORT_STATUS=$?
python3 "$REPO_ROOT/scripts/sync_skills.py" "$@"
exit "$IMPORT_STATUS"
