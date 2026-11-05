[Aegis](../README.md) › [Docs](README.md) › **Deploy**

# Hosting the demo

> [!TIP]
> **In short:** click the Render button to get a free, public demo link with no secrets. It runs every
> control in one container. Open it a couple of minutes before you need it, because free instances
> sleep after 15 minutes without traffic.

There are two ways to run Aegis: the full topology (`make up`), or a single container for a public
demo link. This page covers the single container.

## One-click on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kumarlakshya24/personal-projects)

1. Render reads the Blueprint (`render.yaml` at the repository root) from the default branch. If the
   repository is private, connect your GitHub account to Render and grant it access to the repository
   first.
2. Click the button, sign in to Render, and approve the Blueprint. It creates one free web service,
   `aegis-gateway-demo`, which builds `secure-ai-gateway/Dockerfile`.
3. When the health check (`/healthz`) passes, open the service URL. The banner at the top confirms
   hosted demo mode.

No secrets are needed. Keys are generated per process (demo mode), and the models are in-process mocks.

## What the hosted demo is

`AEGIS_EMBEDDED_DEMO=true` runs everything in **one process**:

| Component | Full topology (`make up`) | Hosted demo |
|-----------|---------------------------|-------------|
| Identity provider | separate `idp` container, JWKS over HTTP | in-process mock IdP (same RS256 verification path) |
| External LLM | separate `mock-llm` container on an egress network | in-process mock |
| Local model | separate `local-llm` container on an internal network | in-process mock |
| Audit and policies | Postgres (append-only triggers) | SQLite in `/tmp` (same triggers) |
| Token vault | Redis, no persistence | in-memory, same TTL and encryption |
| Keys | from `.env` (`make env`) | generated at start-up |

Every control is the same code: DLP, tokenization, classifier routing, tool guard, injection
detection, approvals, audit chain, and regression gate. What the hosted demo does **not**
demonstrate is network segmentation and the separate trust zones. Show `docker-compose.yml` and
`ARCHITECTURE.md` for that. `AEGIS_ENV=prod` refuses to start in embedded mode.

## Things to know before sharing the link

* **Public and shared.** Anyone with the URL can sign in as any synthetic demo user and sees the same
  state. All data is synthetic, the models are mocks, and tools are sandboxed, so nothing real can
  leak. If a visitor tightened the policy, use *Policy console → Restore default policy*. The
  regression gate refuses any change that weakens protection anyway.
* **Resets.** The audit log, approvals, and policy edits live in the container's `/tmp`. They reset
  when the service restarts or wakes from sleep. The UI signs in again by itself after a restart.
* **Free-plan performance**, measured locally with the same limits (`--cpus 0.1 --memory 512m`,
  `PORT=10000`, read-only filesystem):

  | Measurement | Result |
  |-------------|--------|
  | Cold start to healthy | 27 s (Render also needs time to wake the instance; its docs say about a minute) |
  | Memory | about 145 MiB of 512 MiB |
  | Gateway overhead per chat request | about 200 ms (versus 7-21 ms at full CPU) |
  | Policy change through the regression gate | about 4 s |
  | `scripts/demo.py --base-url <url>` | 20 / 20 checks pass |

  Free services sleep after 15 minutes without traffic, so open the link a couple of minutes before
  an interview. A paid instance with more CPU removes the latency gap.
* **Rate limit** is per demo user (120 per minute), so visitors share it.

## Any other container host

The image honors `$PORT` and runs as a non-root user with a read-only root filesystem:

```bash
docker build -t aegis-gateway secure-ai-gateway
docker run -p 8080:8080 --read-only --tmpfs /tmp \
  -e AEGIS_EMBEDDED_DEMO=true -e DATABASE_URL=sqlite:////tmp/aegis.db \
  -e OIDC_ISSUER=aegis-embedded-idp -e LLM_MODEL=mock-gpt aegis-gateway
```

The same environment works on Fly.io, Google Cloud Run, Railway, or Azure Container Apps. Run one
instance only: the in-memory vault and SQLite are per process.

## Verify a deployment

```bash
python scripts/demo.py --base-url https://<your-service>.onrender.com
```
