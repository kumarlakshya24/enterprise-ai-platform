---
doc_id: it-vpn-access
title: VPN and Remote Access Troubleshooting (IT-KB-005)
team: it
doc_type: guide
version: "3.2"
updated: 2026-04-08
visibility: public
audience: [all]
---
# VPN and Remote Access Troubleshooting (IT-KB-005)

Lumen Analytics uses the GlobalProtect VPN client. Connect to the portal vpn.lumen.internal and sign in with Okta.

## Common Error Codes

| Error code | Meaning | Fix |
| --- | --- | --- |
| VPN-ERR-809 | Device certificate expired | Re-enroll the device in Company Portal, then restart GlobalProtect |
| VPN-ERR-412 | MFA push timed out | Approve the Okta Verify push within 60 seconds and retry |
| VPN-ERR-503 | Gateway under maintenance | Wait; maintenance runs Sundays 02:00-04:00 UTC |
| VPN-ERR-221 | Split tunnel conflict with a home router | Disable the router's VPN passthrough setting |

## Still Not Working

If the error persists after the fix, open a ticket in the ServiceDesk portal and attach the GlobalProtect logs (Settings > Troubleshooting > Collect Logs).
