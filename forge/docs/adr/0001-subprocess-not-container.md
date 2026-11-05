# ADR 0001: Subprocess sandbox, not a container, as the default

* Status: accepted
* Date: 2026-11-05

## Context

The demo has to run with `make test` and `make demo` on a laptop and in CI. A container is a stronger boundary. It is also a daemon, a privileged install, and a slower inner loop.

## Decision

The default isolation is a short-lived `python -I` process with a cleaned environment, `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_FSIZE`, `RLIMIT_NPROC`, `RLIMIT_CORE`, an audit hook, and a second AST gate inside the child. Docker is not required.

## Consequences

The policy and the limits are real and tested. A same-user process is not a hypervisor. A production deployment should put a sandbox user or a container under this same guard, not instead of it. In-process `exec` was rejected because a restricted dict in the parent is not a process boundary.
