# Failure modes

How Forge behaves when a dependency of the decision is missing or a limit fires. The bias is to refuse the call.

| Failure | Behavior | Why |
|---------|----------|-----|
| Tool name is unknown or mistyped | `R-TOOL-UNKNOWN`, no spawn | Names are exact. `Python` is not `python`. |
| `shell`, even if the YAML says enabled | `R-TOOL-NO-EXECUTOR`, no spawn | There is no shell code path to turn on. |
| Path has `..`, is absolute, or is a symlink | `R-PATH-TRAVERSAL`, `R-PATH-ABSOLUTE`, or `R-PATH-SYMLINK` | The file tools never call `open` on that path. |
| Snippet imports `os`, `socket`, `subprocess`, or another hard-denied module | `R-IMPORT-HARD-DENY`, no spawn | The set lives in code. Adding the name to `imports.allow` does not grant it. |
| Snippet imports `pathlib` under the default policy | `R-IMPORT-DENY` | This one is policy, so the regression gate can see a weaker file. |
| Snippet uses `open`, `eval`, `exec`, or a dunder attribute | `R-NAME-DENIED` or `R-ATTR-DENIED`, no spawn | The AST gate runs on the snippet only. Allowed stdlib modules are already compiled. |
| Policy sets `network: allow` | Schema rejection. The policy does not load. | Network is not a switch. |
| Policy raises a timeout or a byte cap above the ceiling | The ceiling wins. `effective_limits` takes the minimum. | A YAML edit cannot move the hard cap. |
| Child cannot install `RLIMIT_AS` | The child does not execute. The parent records `R-LIMIT-MEMORY`. | Fail closed rather than run without a memory cap. |
| Tight loop | Parent kills the process. Outcome `limited`, rule `R-LIMIT-WALL`. | The wall clock is the authority. The CPU limit is set higher so it does not race the wall clock. |
| Large allocation | `MemoryError` inside the child, or a fatal signal mapped to `R-LIMIT-MEMORY`. | The call does not return the allocation as a success. |
| Huge print | Stdout is truncated. Outcome `limited`, rule `R-LIMIT-OUTPUT`. | The parent also refuses a stdout larger than the cap. |
| `pathlib` granted, then `Path.read_text` | The import can succeed. The read is `R-SANDBOX-OPEN`. | The hook is a second line. The regression gate still fails because the import case flipped to allow. |
| Audit file edited | `verify` returns `ok: false` and the broken sequence. | Tamper evidence. It is not tamper prevention. Someone who also has the HMAC key can recompute the chain. |
| Audit key left as the demo default | The chain still verifies. The key is public. | Fine for the offline demo. A shared machine should set `FORGE_AUDIT_KEY`. |
| Empty audit | `verify` is ok with zero events. | A new session is valid. |
| Missing workspace file | `R-PATH-NOT-FILE`, outcome `error` | That is a usage error, not a security deny. It is not in the protected baseline. |
| User snippet raises `ZeroDivisionError` | `R-SANDBOX-EXCEPTION`, spawned true | The sandbox ran it. The exception is not a policy allow. |
| Same-user process escape outside this corpus | Not claimed to be impossible | See the limit below. |

## What this does not catch

* A bug in CPython or a native extension that never hits the audit hook.
* A network namespace. Socket use is blocked by the import list and the hook, not by a separate network stack.
* Time-of-check to time-of-use if the workspace is swapped for a symlink by another process of the same user between the check and the read. The demo workspace is private to the session.
* Throughput of the hash chain under many writers. Appends take a file lock. That is enough for one demo process.

## Operator response

* `make eval` fails: a protected case became `allow`. Revert the policy or the guard change. Do not update the baseline to hide it.
* `verify` fails: treat the log as suspect from `broken_seq` onward. Do not repair it by rewriting hashes with the demo key and calling it intact.
* Child crashes with no JSON: the runner maps fatal signals to a limit rule and does not treat the call as allow.
