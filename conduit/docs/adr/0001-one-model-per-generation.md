# ADR 0001: One model version per generation

* Status: accepted
* Date: 2026-11-10

## Context

An embedding model defines a vector space. Two models can share a dimension and still place the same sentence in unrelated directions. Conduit's fake models do that on purpose: `emb-v1` and `emb-v2` are both 256-dimensional, and the only difference is the hash salt. A check of `len(vector)` does not catch a mixed index.

Lumen stores one embedding column on one chunk table. That matches a world with one embedder. A model upgrade there either overwrites in place, so readers see a half-rebuilt table, or it has to grow a second column and teach every query which column is live.

## Decision

A generation is bound to one `model_version` at creation. Every chunk row stores that same version. Search embeds the query with the active generation's version and refuses a vector whose width does not match. The read alias is a single row. Swap changes the row. It does not merge generations.

The cache key is `(model_version, content_hash)`. A hit on `emb-v1` is not a vector for `emb-v2`.

## Consequences

Good:

* A bug in query planning cannot return a neighbor from the other space. The other space is a different set of rows.
* Rollback is "point the alias at the generation you just left." The vectors are still there, still one model.
* The salt experiment is a test, not a diagram. Same text, different version, cosine well below 1.

Bad:

* Disk holds two copies during a migration.
* You cannot search "whichever model is better for this query" without a second alias and a product decision about mixing scores. We do not mix scores.

Rejected:

* One index, a `model_version` column, and a filter. The filter is easy to forget, and the ANN structure would still mix neighborhoods if someone built it across the column.
* Refusing the second model because the dimension matches. That is the bug.
* Letting the caller pass a query vector. They will pass the one from before the swap.
