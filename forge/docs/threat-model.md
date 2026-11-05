# Threat model

This is the STRIDE view of Forge. The diagrams and the decision table live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

## Assets

* Files outside the session workspace.
* The ability to spawn a process, load a native module, or open a socket.
* The audit log, which has to stay a record of decisions rather than a second copy of the files.
* The policy file, because a quiet edit can weaken a soft control.

## Trust boundaries

| ID | From | To | Control |
|----|------|----|---------|
| TB1 | Caller | Guard | Allowlisted tools, AST, paths, size |
| TB2 | Guard | Child process | Clean environment, `python -I`, limits on stdin |
| TB3 | File tools | Workspace | No `..`, no absolute path, no symlink |
| TB4 | Child | Host and network | Hard-denied imports, restricted builtins, audit hook |
| TB5 | Parent | Audit log | HMAC chain, redaction, verify |

## STRIDE

| Threat | Property | Example | Mitigation |
|--------|----------|---------|------------|
| Spoofing | Tool identity | `Python` instead of `python`, or `send_email` | `R-TOOL-UNKNOWN`. No aliasing. |
| Tampering | Path and log integrity | `notes/../../secret.txt`, a symlink, a flipped JSONL outcome | Path rules. `verify` reports `broken_seq`. |
| Repudiation | Whether the call happened | A denied import with no record | Append-only record with rule, code hash, and `spawned`. |
| Information disclosure | Host data | Absolute read, snippet `open`, `Path.read_text` after a pathlib grant | Refused before I/O, or `R-SANDBOX-OPEN` if a process was spawned. Audit keeps a short redacted preview. |
| Denial of service | CPU, memory, output | `while True`, a large `bytearray`, a huge `print` | `R-LIMIT-WALL`, `R-LIMIT-MEMORY`, `R-LIMIT-OUTPUT`. Ceilings are schema-capped. |
| Elevation of privilege | Snippet becomes the host | `import os`, `import socket`, a shell string | Hard deny. No shell executor. Policy cannot grant the hard set. |

## Out of scope

* Stealing a credential from this repository. There isn't one. The demo audit key is a public placeholder.
* Kernel exploits and hostile native code. The child is a same-user process. A production deployment adds a sandbox user or a container in front of these same policy checks. ADR 0001 records that choice.
* Prompt injection into a model. Forge does not call a model. It decides tool calls the caller already formed.
