# Loop state — vertciti-dealdesk

Updated: 2026-11-01 (loop bootstrap). Facts here are the standing state;
when one changes, the PR that changes it updates this file.

## Direction channel

- Tasks: GitHub Issues labeled `jarvis-task` in this repo.
- Reviews and verdicts: PR comments only (off-repo documents do not count).
- Merge owner: Jarvis. External Claude opens PRs from `claude/*` branches.
- A daily improvement line ships one small verified improvement per day
  through Jarvis (branch, PR, merge, production readback).

## Decisions in force

- License: MIT, Copyright (c) Jiahui Miao (personal, not the LLC).
- Production parity baseline: engine version and DB revision are read from
  `/api/health` after each deployment; a deploy is not done until the
  health read matches the merged tree.
- The improvement backlog lives with Jarvis; items enter this repo only as
  tasked branches.

## Acceptance rules

- Full CI green on the current head (CI, quality, CodeQL, gitleaks,
  Dependency Review).
- Code PRs: TN structural self-check recorded (pilot gate TN-GATE-001).
- Post-merge production health readback.
