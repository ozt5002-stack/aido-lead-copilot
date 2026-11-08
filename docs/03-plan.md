# Step 3: Plan - AIDO Lead Copilot

Board: [AIDO Lead Copilot project](https://github.com/users/ozt5002-stack/projects/2). The tasks in order, one branch and one PR each, following [CONTRIBUTING.md](../CONTRIBUTING.md). Each task is a GitHub issue and a card on the Projects board. A task starts only after the previous one is merged. Its "done when" lines are what the reviewer checks.

The app keeps working after every task: tasks 2 and 3 add the leads side before the bakery side is removed.

## Tasks

### 1. Stage calculator - `feat/stage-calculator` (#4)
`app/stage.py`, a Python port of lesson 8's `score.js`, with `STAGE_HE`. The outputs of `score.js` on the lesson 8 examples and on the boundary cases go in `tests/fixtures/score_js_cases.json`.
- Done when: tests pass for the boundaries 33/34 and 46/47, the averages 1.6/1.7 and 2.3/2.4, one-decimal rounding and invalid answers, and the port gives the same result as the fixture on every case.

### 2. Fictional leads dataset - `feat/leads-dataset` (#5)
`scripts/generate_leads.py` (fixed seed) writes `data/leads.csv` (300 rows) and `data/README.md` (the fictional notice). There is a `Lead` table in `app/db.py`, seeded at start. Stages are computed with `app/stage.py`.
- Done when: running the generator twice gives the same file; every row is in range and its stage matches `app/stage.py`; some rows have no score; every pipeline status appears; the seed loads into SQLite in tests; every row has `fictional=true`.

### 3. Lead tools - `feat/lead-tools` (#6)
`app/tools/leads.py` with `leads_query`, `lookup_business`, `log_lead` and `calculate_stage`, plus the registry, the agent's tool summaries and `/api/leads`. Remove the bakery tools, tables and data (`sales`, `suppliers`, `invoices`, the two CSVs). Schema version 2.
- Done when: tests cover every `log_lead` rule in the architecture (1-7), dedup normalisation including בע"מ, the fill-in, `leads_query` aggregates against a small fixture, and `calculate_stage`; no bakery code is left (`git grep -i "invoice\|supplier\|sales_query"` finds only history notes).

### 4. Evals for leads - `feat/evals` (#7)
`evals/cases.yaml` gets new cases (stages, hot leads, lookup, logging, duplicate, fill-in, missing score, out-of-range score, no BI for כבאי, refuses delete, Hebrew reply, no number without a tool, off-topic). `evals/run.py` grades lead rows and supports `must_pass`. Tests cover the runner's plumbing with the fake model.
- Done when: `pytest` is green, and a real eval run (needs Oz's key in `.env`) reports a pass rate, which goes in the PR as the **before** number for task 5.

### 5. Hebrew system prompt - `feat/system-prompt` (#8)
`app/prompts/system.md` is rewritten: AIDO consultants, Hebrew first, numbers only from tools, stages only from tools, no BI for כבאי, the logging steps, the refusals. The placeholders are industries and the data range. The refusal and error texts in `app/agent.py` are in Hebrew.
- Done when: evals pass at 80% or more and every `must_pass` case passes. The before and after pass rates are in the PR.

### 6. Hebrew RTL UI - `feat/hebrew-ui` (#9)
`static/` gets `dir="rtl"`, Hebrew labels, its own AIDO look, a recent-leads panel from `/api/leads` (stage in Hebrew, status badges) and a visible "fictional data" note.
- Done when: the page loads with no console errors, works at phone width, and spec checks 1, 3, 6 and 8 can be done in the browser.

### 7. Morning digest - `feat/digest` (#10)
`app/digest.py` prints Hebrew lines: new leads from yesterday (`origin = chat`), hot leads waiting (with the top names), and model spend against the cap.
- Done when: tests show that seeded rows are not counted, that yesterday is the local day, and that hot-and-waiting is right on a fixture.

### 8. Docs for the new app - `docs/readme-runbook` (#11)
README (what it is, the credit, run it, tests vs evals, deploy, cost), `runbook.md`, `docs/deploy-railway.md`, `docs/watch.md`, `.env.example`. Remove bakery wording.
- Done when: `git grep -i bakery` finds only credit and history lines, and every command in the README works on Windows.

### 9. Deploy to Railway - `chore/railway-deploy` (#12)
`.railway/railway.ts` points at this repo and the project name. Oz creates or approves the Railway account and project and puts the secrets into Variables. The web service, the Postgres and the digest cron go up.
- Done when: `/health` on the Railway URL returns 200, spec §7 checks 1-12 pass on the deployed app, and the digest cron has run once. The URL is in the README.

### 10. Final audit and retrospective - `docs/audit-retrospective` (#13)
Check what really happened against every rule here and in CONTRIBUTING.md, with real commands. Write `docs/retrospective.md` with what was planned, what happened, and what changes next time.
- Done when: every audit item is OK or written in the retrospective as a gap.

## Definition of done (every task)

- The PR closes its issue, CI is green, and an independent review comment is on the PR, with the fixes pushed.
- Tests were added for the task's deterministic parts. If the prompt, a tool or the model changed, the eval pass rates are in the PR.
- The docs were updated if a decision or a check changed.
- Merged with a merge commit, the branch deleted locally and on GitHub, the card in Done.

## Where Oz is needed

- **Task 4/5:** `ANTHROPIC_API_KEY` in `.env` (Oz fills it in himself), and optionally as a GitHub Actions secret so CI runs the evals.
- **Task 9:** the Railway account, the project (Hobby plan, about $5 a month) and the Variables.
- Installing Python 3.12 and the Railway CLI: approved on 2026-11-08.
