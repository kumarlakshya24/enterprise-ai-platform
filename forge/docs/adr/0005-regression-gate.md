# ADR 0005: Regression gate on protected case ids

* Status: accepted
* Date: 2026-11-05

## Context

A policy change can look small and drop a denial. Reviewers should not have to re-read every case by hand.

## Decision

`eval/regression/baseline.json` lists the case ids the default policy must not allow, and the utility ids it must allow. `make eval` reruns the corpus. A protected id whose outcome is now `allow` fails the gate. A utility id that becomes stricter is a warning. `--update` is not part of CI. Tests also assert the baseline set equals the corpus, so deleting ids from the file fails `make test`.

## Consequences

Granting `pathlib` and raising `max_code_bytes` fails on `prot-import-pathlib` and `prot-code-size`. Hard-denied cases do not flip when the same candidate adds `os` to the allowlist, because the guard ignores that grant. The corpus is a development set, not a blind holdout.
