#!/usr/bin/env bash
# Print the interview script. A TTY can page it; CI and agents just see the text.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="$ROOT/docs/INTERVIEW_WALKTHROUGH.md"
if [[ -t 1 && -n "${PAGER:-}" ]]; then
  exec "$PAGER" "$DOC"
fi
cat "$DOC"
