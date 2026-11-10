# Arena eval

Domain: Harborline support runbooks. Freeze 2026-03-01. Corpus `eb0792f71fc6`.

Task success is exact-phrase support. Cost and model latency are projections. Overhead is measured wall clock and is not added into the dollars.

## Counts

| | |
| --- | ---: |
| docs | 12 |
| facts | 21 |
| questions | 61 |
| train | 36 |
| holdout | 16 |
| staleness | 5 |
| unanswerable | 4 |
| adapter_facts | 19 |
| student_facts | 15 |

## Quality

| Slice | prompt | rag | lora | distilled |
| --- | ---: | ---: | ---: | ---: |
| freeze_full | 8/20 (0.40) | 20/20 (1.00) | 19/20 (0.95) | 15/20 (0.75) |
| freeze_common_short | 8/16 (0.50) | 16/16 (1.00) | 15/16 (0.94) | 15/16 (0.94) |
| current_full | 8/25 (0.32) | 25/25 (1.00) | 19/25 (0.76) | 15/25 (0.60) |
| current_common_short | 8/19 (0.42) | 19/19 (1.00) | 15/19 (0.79) | 15/19 (0.79) |
| staleness | 0/5 (0.00) | 5/5 (1.00) | 0/5 (0.00) | 0/5 (0.00) |
| holdout_freeze | 4/16 (0.25) | 16/16 (1.00) | 15/16 (0.94) | 11/16 (0.69) |

## Scenarios

| Scenario | Winner | Do not fine-tune | Slice |
| --- | --- | --- | --- |
| weekly-cited | rag | True | current_full |
| high-volume-stable | lora | False | freeze_full |
| narrow-fast | distilled | False | freeze_common_short |
| low-volume | rag | True | freeze_full |
| cited-stable | rag | True | freeze_full |

## Overhead (measured)

| Arm | p50 ms | p95 ms | n |
| --- | ---: | ---: | ---: |
| prompt | 0.011 | 0.018 | 500 |
| rag | 0.048 | 0.07 | 500 |
| lora | 0.018 | 0.024 | 500 |
| distilled | 0.015 | 0.021 | 500 |

In-process wall clock. Catalog model latency is not slept.

