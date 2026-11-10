# ADR 0004: Lumen and Switchboard are ports with offline stand-ins

* Status: accepted
* Date: 2026-11-10

## Context

Arena's RAG arm is the same job Lumen does: answer from company documents and cite the section. The model that serves an arm is the job Switchboard does. Importing either project would make Arena's tests depend on a second process, a database, or a key. Copying their stacks would hide the seam.

The rest of this repo already uses ports for that reason. Atlas talks to a Lumen-shaped `POST /ask` and an Aegis-shaped guard, each with an offline stand-in.

## Decision

`LumenPort.ask` returns the subset of Lumen's `POST /ask` that the bench needs: `answer`, `refused`, `refusal_reason`, `citations[]` with `doc_id`, `title`, `section`. The default implementation is a local BM25 index over the Harborline runbooks. `ARENA_LUMEN_URL` switches the probe to HTTP with `X-User-Id: frank`. A connection error is reported and the eval stays on the stub. The bench does not treat a Lumen refusal as a retrieved fact.

`serving` on the price card names the Switchboard catalog model and policy for each arm: prompt and RAG on `balanced` / `default`, the adapter on `premium` / `quality-first` (the catalog has no adapter id, and the stand-in says so), the student on `fast-cheap` / `latency-first`. `ARENA_SWITCHBOARD_URL` probes `POST /v1/route` with the Switchboard demo prompt. A disagreement is recorded. It does not change the Arena winner.

The committed eval never opens a socket.

## Consequences

Good: `make test` is one process. The contract is small enough to diff against Lumen's API doc and Switchboard's demo table.

Bad: the stub does not implement Lumen's RBAC. Harborline is one audience. Pointed at a live Lumen, a principal without access gets a refusal that can look like a retrieval miss. The probe says the eval numbers stayed on the frozen corpus. Switchboard's catalog still has no LoRA endpoint, so the premium mapping is a stand-in until that id exists.
