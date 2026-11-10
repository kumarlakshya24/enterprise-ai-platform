# CLAUDE.md: kumarlakshya24/personal-projects

## Goal
I'm Lakshya Kumar, targeting **Applied AI Architect / AI Engineer / Solutions Architect** roles. This repo is my portfolio. Every project must foreground **architecture, trade-offs, and system design**: an architecture doc, ADRs, diagrams, an offline-runnable Python demo, and tests.

Priorities, in order: (1) job-ready resumes, (2) a polished GitHub profile and repo, (3) the portfolio site.

## Hard rules
- **Never** deploy, make a repo public, change repo settings, or change profile pins without asking me first.
- **Never** commit secrets. Don't touch or rewrite commit `eb6ba8f`.
- Merge your own PR only if **CI is green, GitGuardian is clean, and there are no new high or critical dependency alerts**. Otherwise stop and tell me.
- No force-pushing over other people's commits. Resolve conflicts by merging or rebasing main.
- Loop caps: a real pass/fail check, **max 5 tries**, and stop and report if the same error happens twice.
- Small, focused PRs. No huge rewrites.
- **Always pull first, and always check repo and branch status before opening or updating a PR.** See the two checklists below. No exceptions.

## Every session starts the same way
1. `git checkout main && git pull --ff-only origin main`, then read the last 15 commits.
2. `git fetch --all --prune`, then list open PRs with their check status (`gh pr list`, `gh pr checks <n>`).
3. Compare against the "Work queue" below. If reality differs, trust reality and update this file in the same PR.
4. Take the top unfinished item only. One item, one branch, one PR.
5. Report back: PR link, check status, what you need from me.

## Before every PR (open or update)
1. `git status` is clean: nothing uncommitted, nothing untracked that belongs in the change.
2. `git branch --show-current` is the branch you mean to push, and it is not `main`.
3. `git fetch origin`, then pull the branch itself (`git pull --ff-only origin <branch>`) in case someone else pushed to it.
4. Merge or rebase the latest `origin/main` into the branch and resolve conflicts.
5. `git log --oneline origin/main..HEAD` and `git diff --stat origin/main...HEAD` show only the commits and files this PR is about.
6. `gh pr list --head <branch>`: if a PR already exists for this branch, update it instead of opening a second one.
7. Run the project's tests and `python scripts/check_docs.py` locally. Only then push and open the PR.

## README standard
- Hero image or GIF, badges, a table of contents, a quick start, an architecture diagram, and trade-offs.
- Shared section order: Overview, Quickstart, Usage, Architecture, Design decisions, Results, Project layout, Where it fits, Documentation, Limitations.
- **Every image and GIF must actually render.** Check that relative paths resolve and the files exist.
- **Do not use `<video>` tags.** GitHub strips them when the source is a file in the repo. Use a poster image that links to the MP4:
  `[![Watch the demo](docs/assets/poster.png)](docs/assets/demo.mp4)`
- No "for recruiters", "Interview", or portfolio section in any README.
- Verify by rendering, not by reading:
  `gh api -H "Accept: application/vnd.github.html" "repos/kumarlakshya24/personal-projects/readme/<dir>?ref=<branch>"`
  then confirm every `<img>` is present and no expected media is missing.

## State as of Nov 10, 2026 (verified)
- Main is at `9050874` (README polish, PR #17).
- On main: Aegis (`secure-ai-gateway/`), Lumen (`rag-knowledge-assistant/`), Switchboard, Forge, Atlas, Lens, Charter, Arena, Skyline, Conduit.
- Merged since the Nov 9 handoff: **#11** (diagram colours), **#15** (Conduit), **#17** (README polish).
- Open PRs:
  - **#18** Portfolio site, branch `feat/portfolio-site`. Not reviewed. Not deployed.
- All ten project READMEs follow the shared section order. No README uses a `<video>` tag. `scripts/check_docs.py` covers the root README and all ten project READMEs.
- Root README counts: 10 projects, 477 tests (the sum of the per-project row in its standards table).
- Still open: the license decision in item 1.

## Work queue

### 1. PR #17 (README polish): merged, one decision left
- [x] Replace the `<video>` tags in `forge`, `atlas`, `lens`, `charter`, and `arena` READMEs (also `skyline` and `conduit`) with a poster image linking to the MP4. Update the nearby sentences that say "the clip at the top of this page and this video".
- [x] Bring `arena/README.md` and `skyline/README.md` into the shared section order, with the same badge row and anchor table of contents as the others.
- [x] Remove the `## Interview` section from `skyline/README.md`. Move the link into the Documentation table as "Design walkthrough", matching the other projects.
- [x] Add `arena/README.md` and `skyline/README.md` to the file list in `scripts/check_docs.py` (and `conduit/README.md`).
- [ ] License badges: each `pyproject.toml` declares MIT but the repo has no `LICENSE` file. Ask me whether to add a root MIT `LICENSE` or drop the badges. Do not decide alone.
- [x] `check_docs.py` passed and #17 merged on Nov 10. The GitHub-API render check was not run from the cloud session, which cannot call that endpoint.

### 2. PR #11 (diagrams, one colour per project): done
- [x] Merged on Nov 10 before #17. The conflicts were resolved on `docs/readme-polish` instead: #17's structure, #11's diagrams.
- [x] Conduit has its own accent colour (item 3).

### 3. Conduit follow-up: done
- [x] It has an architecture doc, four ADRs, an offline demo that prints PASS, 17 tests, and its own CI workflow.
- [x] `conduit/README.md` follows the shared section order.
- [x] Conduit is in the root README (project table, badges, counts) and has its own colour (brown `#8a6238`) in the root diagram and its "Where it fits" diagram.

### 4. PR #18 (portfolio site)
- [ ] `cd portfolio-site && npm ci && npm run build` must pass.
- [ ] Add Charter, Arena, Skyline, and Conduit cards if missing.
- [ ] Do not deploy. Tell me when it is ready to review.

### 5. Resumes (my top priority, needs my input)
- [ ] Ask me for my current resume and two or three target job descriptions before writing anything.
- [ ] Bullets may only cite numbers that a project's `reports/` or `eval_results/` folder regenerates.

## Definition of done for any project
- `make install && make test && make demo` passes offline with no API key.
- `ARCHITECTURE.md` and at least three ADRs with real trade-offs.
- A CI workflow and a README that meets the standard and passes `check_docs.py`.
- A Limitations section that names what doesn't work and what would fix it.
- Root README counts (projects, tests) match what the suites actually report.

## Keep this file current
When an item is done, tick it and update "State" in the same PR. When the queue is empty, propose the next three items to me rather than starting new projects unasked.
