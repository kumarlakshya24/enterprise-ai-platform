# ADR 0002: Hard guards are not policy switches

* Status: accepted
* Date: 2026-11-05

## Context

If every denial lives in YAML, one edit enables `os`, absolute paths, or a shell. The regression gate can catch a soft change. It cannot help if the dangerous capability was only ever a boolean.

## Decision

`os`, `socket`, `subprocess`, `ctypes`, path escape, symlinks, and the absence of a shell are enforced in code. YAML may shrink the import allowlist and may lower limits. It cannot raise a ceiling, set `network: allow`, or create a shell. `pathlib` and the code-size cap are policy on purpose, so a weaker file is something the gate can refuse.

## Consequences

A reviewer can see the hard set in `forge/guard/constants.py` without diffing a policy. The demo's "weaken policy" button changes only the soft controls, and `import os` stays denied under that candidate.
