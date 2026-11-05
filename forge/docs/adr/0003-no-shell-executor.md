# ADR 0003: No shell executor

* Status: accepted
* Date: 2026-11-05

## Context

Agents ask for "a tiny shell" for `ls` and `cat`. Those are already `list_dir` and `read_file`. A general shell does not stay tiny.

## Decision

The tool name `shell` is recognized so the denial is explicit (`R-TOOL-NO-EXECUTOR`). There is no code that interprets a command string. `enabled: true` in YAML does not add an executor.

## Consequences

File and Python tools cover the demo. Callers cannot reach `sh -c` by editing policy. The preview still says a host shell would have accepted the string, and then does not run it.
