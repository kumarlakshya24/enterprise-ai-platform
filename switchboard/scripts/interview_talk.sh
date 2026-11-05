#!/usr/bin/env bash
# Print the interview talk track. Speak it; do not scroll the file in the meeting.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC="$ROOT/docs/INTERVIEW_WALKTHROUGH.md"
if [[ ! -f "$DOC" ]]; then
  echo "missing $DOC" >&2
  exit 1
fi
echo "Switchboard interview walkthrough"
echo "Source: docs/INTERVIEW_WALKTHROUGH.md"
echo "Demo UI: make run-local  then  http://127.0.0.1:8092"
echo "Checks:  make demo && make test"
echo
cat "$DOC"
