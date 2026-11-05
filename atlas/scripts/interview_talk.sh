#!/bin/sh
# Print the Atlas interview walkthrough. `make interview` calls this.
cd "$(dirname "$0")/.." || exit 1
exec cat docs/INTERVIEW_WALKTHROUGH.md
