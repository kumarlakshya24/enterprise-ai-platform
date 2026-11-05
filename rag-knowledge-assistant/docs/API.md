# API reference

Base URL: `http://localhost:8000`. Interactive OpenAPI docs: **`/docs`** (Swagger UI) and `/redoc`.

## Authentication

The demo identifies callers with an `X-User-Id` header that maps to a user in
[`config/users.yaml`](../config/users.yaml):

| User | Team | Roles | Useful for |
|:--|:--|:--|:--|
| `alice` | finance | employee, analyst | Finance-scoped policies |
| `bob` | sales | employee, analyst | cross-team and RBAC refusals |
| `carol` | engineering | employee, manager | manager-only documents |
| `frank` | engineering | employee | engineering team-only runbook |
| `dave` | hr | employee, hr_admin | restricted compensation bands |
| `erin` | it | employee, it_admin, **kb_admin** | admin endpoints and comparison profiles |

> In production, replace the `principal()` dependency in [`app/main.py`](../app/main.py) with OIDC/JWT
> validation that maps IdP group claims to `team` and `roles`. Nothing downstream changes.

## Endpoints

| Method | Path | Who | Purpose |
|:--|:--|:--|:--|
| `GET` | `/health` | anyone | DB, Redis and model status |
| `POST` | `/ask` | any user | ask a question (see below) |
| `POST` | `/ingest` | `kb_admin` | upload a file (`multipart`: `file`, optional `metadata` JSON) |
| `POST` | `/ingest/directory` | `kb_admin` | incrementally (re)ingest the configured docs directory |
| `POST` | `/reindex` | `kb_admin` | `{"doc_id"?}`: re-parse and re-embed one document or all |
| `DELETE` | `/documents/{doc_id}` | `kb_admin` | delete a document, its chunks, postings and dependent cache entries |
| `GET` | `/documents` | any user | documents the caller is allowed to see |
| `GET` | `/documents/{doc_id}/lineage` | `kb_admin` | chunk lineage across versions |
| `GET` | `/ingestion/status` | `kb_admin` | documents, chunks created / replaced / reused / removed, failed files |
| `POST` | `/eval` | `kb_admin` | run the eval suite against the current index |
| `GET` | `/eval/results` | anyone | latest saved eval summary |
| `GET` | `/cache/stats` | any user | hit rate, entries, invalidations |
| `POST` | `/cache/clear` | `kb_admin` | clear the semantic cache |
| `GET` | `/users`, `/profiles` | anyone | demo identities and pipeline profiles (used by the UI) |

## `POST /ask`

```bash
curl -s localhost:8000/ask -H 'X-User-Id: alice' -H 'Content-Type: application/json' \
     -d '{"question": "Remote work policy for analysts?", "debug": true}'
```

| Field | Type | Default | Notes |
|:--|:--|:--|:--|
| `question` | string | required | 2–2000 characters |
| `profile` | string | `full` | `full`, `full_cached`; `baseline`…`filtered` disable access control and are **admin-only** |
| `teams` | string[] | – | restrict to documents owned by these teams |
| `doc_types` | string[] | – | e.g. `["policy"]` |
| `audience_teams` | string[] | – | answer as if for these teams |
| `debug` | bool | `false` | include the top-10 candidates with per-stage ranks |

Response (abridged):

```jsonc
{
  "answer": "… Finance analysts may work remotely up to 4 days per week … [2]",
  "refused": false,
  "refusal_reason": null,             // e.g. "low_rerank_score", "identifier_not_in_evidence:vpn-err-999"
  "citations": [{"index": 2, "doc_id": "fin-analyst-remote-addendum", "title": "…", "section": "Remote Allowance",
                 "chunk_index": 0, "version": "1.2"}],
  "timings_ms": {"embed_query": 5, "retrieval": 3, "multiquery": 33, "rerank": 331, "generation": 72, "total": 445},
  "cache": {"enabled": true, "hit": false},
  "degraded": [],                      // e.g. ["rerank_timeout"] when a latency budget was exceeded
  "cost": {"llm_usd": 0.0, "projected_usd": 0.0044, "projection_model": "claude-opus-5-5"},
  "query_variants": ["…"],
  "retrieved": [{"doc_id": "…", "ranks": {"vector": 1, "bm25": 1, "fused": 1, "rerank": 2}, "scores": {"rerank": 5.05}}]
}
```

<sub>Field values above are illustrative of the shape; run the curl command for live values.</sub>

## `POST /ingest`

```bash
curl -s localhost:8000/ingest -H 'X-User-Id: erin' \
     -F file=@data/updates/remote-work-policy.md \
     -F 'metadata={"team":"hr","visibility":"public","audience":["all"]}'
```

Returns the ingest result: `action` (`created` | `updated` | `unchanged` | `failed`), `version`,
`chunks_created`, `chunks_replaced`, `chunks_unchanged`, `chunks_removed`, `embeddings_computed`, `duration_ms`.

Supported formats: `.md`, `.txt` (YAML front-matter for metadata), `.pdf` (metadata from a sidecar
`<file>.meta.yaml` or the `metadata` form field). `visibility` is `public`, `team` or `restricted`
(which requires `allowed_roles`).
