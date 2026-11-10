---
doc_id: incidents
title: Incidents
visibility: internal
in_freeze: true
---

## Severity one

Severity one pages the primary on-call within 5 minutes.

<!-- fact id=incident.sev1 | include=within 5 minutes | length=short | aliases=severity one -->

## Severity two

Severity two gets a human reply within 1 hour.

<!-- fact id=sev2.response | include=within 1 hour | freeze_include=within 4 hours | length=short | aliases=severity two -->
<!-- freeze Severity two gets a human reply within 4 hours. -->

## Bridge

Open the incident bridge, name an incident commander, post a customer notice within 15 minutes, and refresh that notice every 30 minutes until the incident is resolved.

<!-- fact id=incident.bridge | include=every 30 minutes | length=long | aliases=incident bridge -->
