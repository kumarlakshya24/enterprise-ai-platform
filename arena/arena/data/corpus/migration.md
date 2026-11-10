---
doc_id: migration
title: Migration
visibility: internal
in_freeze: true
---

## Cutover

The tenant cutover is: freeze writes, export the tenant snapshot, verify row counts, point DNS at the new region, and keep the old region read-only for 24 hours.

<!-- fact id=migration.cutover | include=read-only for 24 hours | length=long | aliases=tenant cutover -->
