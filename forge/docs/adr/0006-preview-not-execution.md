# ADR 0006: The unprotected path is a preview

* Status: accepted
* Date: 2026-11-05

## Context

The demo should show the difference between a raw interpreter and Forge. Running the denied snippet "for contrast" would execute the thing the product exists to stop.

## Decision

Every call builds a `Preview` with `executed: false`. If the snippet parses and the guard would deny it, `would_allow` is true and the note says a raw interpreter would run it. Forge then returns the denial and does not spawn. Syntax errors are `would_allow: false` on both sides, because a raw interpreter would reject them too.

## Consequences

The UI can still teach the contrast. The repository does not contain a working shell, a socket client, or a file read outside the workspace. Tests assert `spawned is false` and that marker text such as `RAN` never appears for denied snippets.
