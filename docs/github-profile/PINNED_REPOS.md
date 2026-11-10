# Pinned repositories

Proposal only. This file does not change GitHub pins or profile settings.

Checked with `gh repo list kumarlakshya24` on 10 Nov 2026 (public repos, plus the private `personal-projects` repo this file lives in). Nothing below was invented. If a name is not in this list, it is not a repository on the account.

## What exists

`personal-projects` is the only portfolio-grade repository. It is **private**, so it cannot be a public pin. The six systems a hiring manager should see (Aegis, Lumen, Switchboard, Forge, Atlas, Lens) are folders inside it, not their own repositories.

Public repositories on the account, and why none of them should be one of the six pins for AI Architect, AI Engineer, or Solutions Architect:

| Repository | What it actually is | Pin it? |
|---|---|---|
| [kumarlakshya24](https://github.com/kumarlakshya24/kumarlakshya24) | Profile README repo. Last push 2021. Empty description. | Not a project pin. Paste [`PROFILE_README.md`](PROFILE_README.md) here when the project links are public. |
| [laughing-chainsaw](https://github.com/kumarlakshya24/laughing-chainsaw) | Public, no description, no detected language. Pushed Jan 2026. | No. Nothing in the listing ties it to the target roles. |
| [Sentiment_Analysis](https://github.com/kumarlakshya24/Sentiment_Analysis) | Public Python repo, no description. Pushed 2021. | No. Too old, and not one of the six systems. |
| [Data-Science-Projects](https://github.com/kumarlakshya24/Data-Science-Projects) | Public Jupyter repo. Pushed 2021. | No. Coursework-era notebook collection. |
| [kumarlakshya24.github.io](https://github.com/kumarlakshya24/kumarlakshya24.github.io) | "Portfolio Website". No detected language. Pushed 2020. | No. |
| [web-development](https://github.com/kumarlakshya24/web-development) | "INFO 6205 Coursework". | No. |
| [INFO6205-Algorithms](https://github.com/kumarlakshya24/INFO6205-Algorithms) | "INFO 6205 (Program Structures and Algorithms)". Java. | No. |
| [INFO-5100-Application-Engineering-and-Development-Assignments](https://github.com/kumarlakshya24/INFO-5100-Application-Engineering-and-Development-Assignments) | Class assignments. Java. | No. |
| [hackUMBC2020](https://github.com/kumarlakshya24/hackUMBC2020) | Team hackathon repo, 2020. | No. |
| [hexo](https://github.com/kumarlakshya24/hexo) | Public, no description. JavaScript. Pushed 2020. | No. |
| [todo-astra-jamstack-netlify](https://github.com/kumarlakshya24/todo-astra-jamstack-netlify) | Public, no description, no detected language. Pushed 2020. | No. |
| [amazon-ecs-fargate-cdk-v2-cicd](https://github.com/kumarlakshya24/amazon-ecs-fargate-cdk-v2-cicd) | Fork. "Amazon CI/CD pipeline deploying to ECS Fargate using CDK V2". | No. Not original work. |
| [create-react-app-auth-amplify](https://github.com/kumarlakshya24/create-react-app-auth-amplify) | Fork. Amplify auth sample. | No. |
| [home](https://github.com/kumarlakshya24/home) | Fork. React portfolio template. | No. |
| [devilution](https://github.com/kumarlakshya24/devilution) | Fork of the Diablo source port. | No. |

## The six pins

Do not pin six public repos today. There are not six public repos that support these roles.

Publish the six existing folders as their own **public** repositories, then pin those. Suggested names match the product names already used in this monorepo. The folders are the source of truth; the repo names below do not exist yet.

| Pin | Folder that exists today | Repo to create, then pin | One-line reason |
|---|---|---|---|
| 1 | `secure-ai-gateway/` | `aegis` | Security gateway (DLP, tool guard, audit) is the trust-boundary story for an AI Architect and a Solutions Architect. |
| 2 | `rag-knowledge-assistant/` | `lumen` | Cited RAG with access control and an eval suite is the core AI Engineer build. |
| 3 | `switchboard/` | `switchboard` | Policy-based model routing (cost, latency, capability, local pin) is the platform decision a Solutions Architect has to defend. |
| 4 | `forge/` | `forge` | A sandbox that denies a tool call before a process exists shows how an AI Engineer contains agent tools. |
| 5 | `atlas/` | `atlas` | Durable multi-agent workflows (crash, idempotency, sagas) are the AI Architect runtime story. |
| 6 | `lens/` | `lens` | Sampling, a measured judge, drift, SLOs, and a CI quality gate are the LLMOps story. |

Until those six repositories exist, the honest public profile is the profile README plus a pointer at this monorepo. Making `personal-projects` public and pinning that one repo is the smaller step; it still uses only one of the six pin slots, which is why the split above is the proposal.
