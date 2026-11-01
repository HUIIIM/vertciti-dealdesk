# vertciti-dealdesk

DealDesk: a real-estate deal analysis tool (underwriting, valuation, rent
verification). Public showcase and lead-generation funnel; production at
dealdesk.vertciti.com. MIT, Copyright (c) Jiahui Miao.

## How work happens here

- Direction arrives in-repo: GitHub Issues labeled `jarvis-task`, PR review
  comments, and the committed files `CLAUDE.md` (this file) and `LOOP.md`.
  Read both at session start.
- External Claude (Claude Code web) works on `claude/*` branches and opens
  PRs. It never merges its own PRs and never deploys to production.
- Jarvis reviews, runs the gates, merges, and owns production. Review
  verdicts exist only as PR comments.
- When a change alters a fact stated in `CLAUDE.md` or `LOOP.md`, update the
  file in the same PR.

## Repository map

- `app/` — FastAPI backend (services include the TopHap integration).
- `frontend/` — Vite + TypeScript client; built assets are hashed and all
  references update in the same change.
- Tests: pytest (backend), vitest + Playwright (frontend).

## Working rules

- Before running pytest locally, delete the stray dev database:
  `rm -f dealdesk.db`. A repo-root `dealdesk.db` cross-talks into the test
  suite and fails unrelated tests.
- The production Vercel project is deliberately NOT git-connected.
  Never change its git connection — that needs Central approval first.
- Login is Google OAuth against the existing user table; no public
  registration.
- This repo is a TN-GATE-001 pilot repo: code PRs get a structural
  self-check recorded with the merge. Workflow/config/docs-only PRs are
  exempt.
