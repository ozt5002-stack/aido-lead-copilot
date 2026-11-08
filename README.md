# AIDO Lead Copilot

An internal chat assistant for AIDO consultants, in Hebrew, right to left. Consultants ask about leads and business diagnoses, check whether a business is already a lead, and log a new lead or diagnosis from pasted meeting notes or a photo of them. Every number comes from a tool. The stage (כבאי, בנאי, פקח) is computed by code, never by the model. A missing score is never guessed. The assistant never recommends BI to a business in the כבאי stage. A morning digest reports yesterday's new leads, the hot leads that are waiting, and model spend.

**All the data is fictional.** `data/leads.csv` holds 300 invented leads, written by a seeded script (`scripts/generate_leads.py`). See [data/README.md](data/README.md).

**Credit.** This project is built on [MaceTenth/bakery-copilot](https://github.com/MaceTenth/bakery-copilot), the AIDO course project, and keeps its structure and its Git history: FastAPI backend, agent loop, tools, Postgres, chat UI, morning digest, auth, limits, tests and evals, Railway config. The bakery domain was replaced by leads, step by step, in the PRs listed on the [board](https://github.com/users/ozt5002-stack/projects/2).

Live app: the URL goes in [docs/deploy-railway.md](docs/deploy-railway.md), section 9, once plan task 9 has deployed it.

## Docs

| File | What it says |
|---|---|
| [docs/01-design.md](docs/01-design.md) | the problem, the users, the rules for logging, the success metric, what is out of scope (Hebrew) |
| [spec.md](spec.md) | jobs, limits and the thirteen checks a stranger can run |
| [docs/02-architecture.md](docs/02-architecture.md) | components, data flow, data shapes, the `log_lead` rules, and the decisions with their reasons |
| [docs/03-plan.md](docs/03-plan.md) | the ten tasks in order, each one an issue and a PR |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how work is done: one branch at a time, CI, an independent review, merge, delete the branch |
| [runbook.md](runbook.md) | what to do when it breaks |
| [docs/deploy-railway.md](docs/deploy-railway.md) | deploying on Railway, every variable, day two |
| [docs/watch.md](docs/watch.md) | the six numbers to watch every week |

## Run it locally (Windows, PowerShell)

You need Python 3.12 (`winget install Python.Python.3.12`).

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in `APP_PASSWORD`, `APP_SECRET` (any 32+ random characters) and `ANTHROPIC_API_KEY`. Never paste them anywhere else.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://localhost:8000, type your name and the password. The first start seeds the 300 fictional leads into SQLite (`local.db`), which takes a second or two.

Try: "כמה לידים יש בכל שלב?", "אילו לידים חמים מחכים לטיפול?", "מה השלב של עסק עם ציון 41?", or paste meeting notes and ask to log them.

On macOS or Linux the same steps are `cp .env.example .env`, `python3.12 -m venv .venv && source .venv/bin/activate`, `pip install -r requirements.txt`, `uvicorn app.main:app --reload`.

## Tests and evals

These are two different things, and each is named for what it is (CONTRIBUTING.md).

- **Tests** check the deterministic parts: the stage calculator against lesson 8's `score.js`, the dataset generator, every `log_lead` rule, `leads_query`, the digest, auth and limits, and the chat loop with a scripted fake model. Same input, same output. They pass or fail, need no key, and run in CI on every PR.

  ```powershell
  .venv\Scripts\python -m pytest -q
  ```

- **Evals** check the real model's answers to 21 cases in `evals/cases.yaml`. The result is a **pass rate**, appended to `evals/history.csv`. The baseline is 80%, and every case marked `must_pass` (the four where no score may be stored) must pass, whatever the rate. They cost about $0.30 a run (the `--judge` grading with a small model adds a cent or two). Run them whenever the prompt, a tool or the model changes, and before release. CI runs them when the `ANTHROPIC_API_KEY` secret is set.

  ```powershell
  .venv\Scripts\python -m evals.run --baseline 0.8
  .venv\Scripts\python -m evals.run --baseline 0.8 --judge
  ```

  The second command also grades the wording with a cheaper model against each case's rubric.

The digest prints yesterday's lines on its own:

```powershell
.venv\Scripts\python -m app.digest
```

## The data

```powershell
.venv\Scripts\python scripts\generate_leads.py --check
```

This checks that `data/leads.csv` is exactly what the generator writes. To change the data, change the script and run it without `--check`. The CSV is never edited by hand.

## Deploy on Railway

The full walkthrough is in [docs/deploy-railway.md](docs/deploy-railway.md): the CLI and the dashboard, every variable and secret, and day-two operations. The short version:

1. A Railway project with a **Postgres** database and two services from this repo: **web** (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check `/health`) and **digest** (`python -m app.digest`, cron `30 4 * * *` UTC). Both are described in `.railway/railway.ts`.
2. Variables on `web`: `APP_ENV=production`, `APP_PASSWORD`, `APP_SECRET`, `ANTHROPIC_API_KEY`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `MODEL=claude-opus-5-5`, `DAILY_CAP_USD=3.00`, `CRON_SECRET`, `TIMEZONE=Asia/Jerusalem`. The `digest` service references the same values.
3. Push to `main` deploys. Check `/health` returns 200, then go through spec.md §7.

## Cost

| Item | Estimate |
|---|---|
| Railway: web service, Postgres, cron | about $5 a month (the Hobby plan) |
| Claude (Opus 5.5), a few hundred turns a month | a few dollars; `DAILY_CAP_USD` stops the app at $3 a day |
| One eval run (21 cases) | about $0.30, a cent or two more with `--judge` |

## Layout

```
app/            main.py (API), agent.py (loop), stage.py (כבאי/בנאי/פקח), tools/ (leads.py, registry.py),
                db.py, config.py, auth.py, limits.py, costs.py, digest.py
app/prompts/    system.md - the assistant's instructions, in Hebrew
static/         the chat UI: Hebrew, right to left
data/           leads.csv (fictional, generated), README.md
scripts/        generate_leads.py
tests/          pytest, model mocked; fixtures/score_js_cases.json from lesson 8's score.js
evals/          cases.yaml, run.py, history.csv
docs/           design, architecture, plan, deploy guide, watch
.railway/       railway.ts - the Railway project as code (services, health check, cron)
.github/        workflows/ci.yml - tests on every PR, evals when the key secret is set
```
