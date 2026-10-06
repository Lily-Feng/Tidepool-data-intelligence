# TwiistLab — project guide for Claude

A privacy-first personal analytics pipeline and app that joins Twiist pump/CGM
data (via Tidepool) with Apple Health data. The source code is open source;
the owner's health data and non-public planning are not.

- **Stage 1 (current):** data pipeline + personal app for one user (the owner).
  Plan: [docs/stage1-plan.md](docs/stage1-plan.md).
- **Stage 2+ (later):** de-identified sharing, template for others, go-to-market.
  Plans live in `private/` only.

## Public / private boundary

`private/` is git-ignored and must **never** be committed. Anything that should
not be public goes there, including:

- Real data: Tidepool exports, Apple Health exports, query results, screenshots
  of real dashboards, notebooks with real cell output.
- Identifiers: names, Tidepool user IDs, device IDs/serials (e.g. `twiist_…`),
  upload IDs, birth dates, locations, care-team names.
- Secrets: tokens, API keys, `.databrickscfg`, real `terraform.tfvars`,
  `backend.tf`, Terraform state, workspace URLs and account IDs.
- Non-public planning: mission plan, Stage 2+ roadmap, business models,
  partner/interview notes, findings about the owner's own health.

Public repo content is limited to: code, schemas, docs written generically,
Terraform with `.example` files, and **synthetic** fixtures that have no lineage
to real records.

When writing code or docs, never paste a real value from `private/` into a
public file — not as an example, test fixture, comment, or log line. Use
synthetic values.

## Required review before every GitHub check-in

Before any `git commit` or `git push`, Claude must:

1. Run `git status` and `git diff --cached` and read the full staged diff.
2. Confirm no staged path is under `private/`, `data/`, or matches
   `.gitignore` patterns forced in with `git add -f`.
3. Scan the diff for real data or identifiers (list above), secrets, workspace
   URLs, personal names, and content copied from `private/` documents
   (including Stage 2+ plans and business ideas).
4. Confirm fixtures are synthetic and data files are small.
5. Summarise the review result to the owner and **get explicit approval**
   before committing or pushing. Never use `--no-verify` to bypass the hook.

A pre-commit hook in `scripts/git-hooks/pre-commit` automates part of this.
Install it once per clone: `git config core.hooksPath scripts/git-hooks`.
The hook is a safety net; the manual review above is still required.

If real data is ever pushed, deleting the file is not enough: stop, tell the
owner, and plan a history rewrite and exposure review.

## Product guardrails

- Descriptive, retrospective insight only. Never recommend insulin doses or
  pump-setting changes, and no real-time alerting — that crosses into a
  regulated medical device.
- Every AI-written insight describes the data, cites the days behind it, and
  suggests discussing changes with the care team.
- Never write back to the pump or Tidepool.
- Secrets live in macOS Keychain or a Databricks secret scope, never in code,
  notebooks, or logs. Logs contain counts and batch IDs, not health values.

## Repo map

- `scripts/` — ingest scripts (run on the owner's Mac); `scripts/git-hooks/`
- `infra/terraform/` — AWS + Unity Catalog infra (`*.example` files only)
- `docs/v1/` — earlier V1 specs (AWS/S3-based); see Stage 1 plan decision D1
- `docs/archive/` — deferred scope
- `github-pages/` — public landing page
- `private/` — git-ignored; see `private/README.md`
