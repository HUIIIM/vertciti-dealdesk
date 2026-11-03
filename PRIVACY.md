# Privacy and data handling / 数据处理说明

DealDesk is self-hosted: deal data lives in the operator's own database
(SQLite by default, Postgres via `DATABASE_URL`). This page states what is
stored, how long, who can see it, and what is redacted.

## What is stored
- **Accounts**: email address and role for invited users (`users`), and
  web sessions (`web_sessions`). Sign-in is Google OAuth against existing
  users; there is no public registration.
- **Deal data**: deals and versions, underwriting runs, field provenance
  (source, page, reviewer, freshness), conflicts, committee packs, votes,
  decisions, tasks, approvals, uploaded documents, templates, saved views.
- **Audit trail**: `audit_log` and `deal_events` record who changed what.
- **Caches**: an address cache of looked-up property records.
- **Not stored by this repo**: payment data. Provider credentials are read
  from the environment (see `.env.example`), never written to the database.

## Third parties
Addresses and property identifiers may be sent to the data providers the
operator enables: TopHap (off by default, `TOPHAP_ENABLED`) and RentCast
(only when `RENTCAST_API_KEY` is set). Google receives sign-in requests.
No analytics or advertising trackers are embedded by the backend.

## Retention
- Deal data and the audit log are kept until the operator deletes them; the
  application does not auto-expire them.
- Web sessions expire per the session TTL and may be revoked at any time.
- Database backups follow the operator's backup schedule (see
  [docs/RUNBOOK.md](docs/RUNBOOK.md)); deleted rows persist in backups until
  those backups rotate out.

## Redaction
- Secrets, tokens and keys are never committed (gitleaks runs in CI) and
  `.env` is git-ignored.
- Server-error notifications (`DEALDESK_ERROR_WEBHOOK`) and logs should not
  carry credentials; report any leak as a vulnerability via
  [SECURITY.md](SECURITY.md).

## Access and deletion
- Only signed-in, invited users can read deal data; administrators manage
  roles.
- To delete a user or a deal, an administrator removes the records in the
  admin console or database. To request deletion on the vertciti-operated
  instance, contact the operator via [vertciti.com](https://vertciti.com).

## Changes
Material changes to what is stored are recorded in
[CHANGELOG.md](CHANGELOG.md).
