---
doc_id: eng-oncall-runbook
title: Production On-Call and Incident Runbook (ENG-RUN-001)
team: engineering
doc_type: runbook
version: "7.0"
updated: 2026-05-20
visibility: team
audience: [engineering]
---
# Production On-Call and Incident Runbook (ENG-RUN-001)

Internal to Engineering.

## Severity Levels

| Severity | Definition | Acknowledge within |
| --- | --- | --- |
| SEV1 | Customer-facing outage or data loss | 5 minutes |
| SEV2 | Major feature degraded for many customers | 15 minutes |
| SEV3 | Minor bug or internal tooling issue | Next business day |

## SEV1 Procedure

1. The on-call engineer acknowledges the PagerDuty page and declares the incident in the #incident Slack channel.
2. An Incident Commander is assigned within 10 minutes.
3. The public status page is updated every 30 minutes until resolution.

## Postmortems

A blameless postmortem is required for every SEV1 and SEV2 and must be published within 5 business days.
