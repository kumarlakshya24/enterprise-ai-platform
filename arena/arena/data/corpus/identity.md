---
doc_id: identity
title: Identity
visibility: internal
in_freeze: true
---

## Enforcement

SSO enforcement starts on the next login and does not end active sessions.

<!-- fact id=sso.enforcement | include=does not end active sessions | length=short | aliases=sso enforcement -->

## Idle

An idle session will expire after 15 minutes.

<!-- fact id=session.idle | include=expire after 15 minutes | freeze_include=expire after 60 minutes | length=short | aliases=idle session -->
<!-- freeze An idle session will expire after 60 minutes. -->
