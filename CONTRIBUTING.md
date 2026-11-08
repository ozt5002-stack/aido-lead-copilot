# CONTRIBUTING - how work is done on AIDO Lead Copilot

This file is the process. [spec.md](spec.md) and [docs/01-design.md](docs/01-design.md) say what we build, [docs/02-architecture.md](docs/02-architecture.md) says how, and [docs/03-plan.md](docs/03-plan.md) lists the tasks in order. If the work and this file disagree, change this file first (in a PR), then do the work. Never leave a rule here that the work breaks.

It replaces bakery-copilot's `practice.md`, which is still in the Git history.

## Order

1. Design, architecture and plan are merged to `main` before any code branch exists. Then **Stop 1**: Oz approves a short summary before task 1 starts.
2. Tasks are done **one at a time, in the order of the plan**. A branch is created only when the previous task's PR is merged. Branches are never created ahead of time.
3. After the last task (the audit), **Stop 2**: Oz sees the app working and the audit, and confirms it does what was agreed.
4. If a review shows the design or the architecture was wrong, stop and ask Oz. Do not change course quietly.

## On every task

1. **Issue.** Every task has a GitHub issue and a card on the Projects board. Move the card to *In Progress* when the branch is created.
2. **Branch.** `git checkout main && git pull`, then `git checkout -b <type>/<name>`. Types: `design`, `feat`, `fix`, `docs`, `chore`. Example: `feat/stage-calculator`.
3. **Commits.** Small, with clear messages that say what changed and why.
4. **Tests.** `pytest -q` is green before the PR. Each "done when" line of the issue has a test where it can be tested deterministically.
5. **Evals.** If the system prompt, a tool, the model or the effort changed, run `python -m evals.run --baseline 0.8` before and after, and put both pass rates in the PR. One written exception: plan task 3 brings in the lead tools and the first lead eval cases together, so there is no "before" run; its PR reports the first pass rate only.
6. **Docs.** If a decision changed, update `docs/02-architecture.md` in the same PR. If a spec check changed, update `spec.md` §7.
7. **Pull request.** Push, open a PR into `main` with `Closes #<issue>` in the body.
8. **Review.** Wait for CI to pass. Then an independent review: a reviewer that did not write the code (the `code-review` skill or a separate reviewer agent) reads the diff against the design and architecture. Fix what it finds and push. Post a PR comment saying what was reviewed and what was fixed, so the review is visible. Merge only when CI is green on the last commit **and** the review comment was posted after the last push. That is checkable from the timestamps, and the final audit checks it.
9. **Merge.** `gh pr merge --merge --delete-branch`: a merge commit, and the branch is deleted locally and on GitHub. Card to *Done*. A merged branch never stays.
10. Only then the next task starts.

## Tests and evals are different things

- **Tests** (`tests/`, `pytest`): deterministic code, where the same input always gives the same output. They pass or fail, the model is mocked, and they run in CI on every PR.
- **Evals** (`evals/`, `python -m evals.run`): the real model's answers, scored against expectations. The result is a pass rate (for example 14/16). The baseline is 80%, and every case marked `must_pass` must pass. They run when the prompt, a tool or the model changes, before release, and in CI when the `ANTHROPIC_API_KEY` secret is set.

Name every file and every doc by what it really is.

## Never

- Push to `main` directly, force-push, or rewrite or backdate history. Mistakes go in `docs/retrospective.md`.
- Put a secret in a file, a commit, a PR or a chat. Secrets live in `.env` (gitignored, filled in by Oz) and in Railway Variables. `git grep -nE "sk-ant-[A-Za-z0-9_-]{20,}"` (a real key, not the word) must come back empty.
- Edit `data/leads.csv` by hand. It changes only by rerunning `python scripts/generate_leads.py` in a PR.
- Put real client data in the repo. The repo is public, and the dataset is fictional.
- Touch the customer-facing project `aido-final-project`, or copy code into it.
- Write a number into a reply without a tool result behind it (a rule for the agent, checked by evals).

## Ask Oz first

Anything public or outward-facing, anything that costs money or needs a key, anything destructive, and any change to the approved scope or architecture.

## Local commands (Windows, PowerShell)

```powershell
Copy-Item .env.example .env       # Oz fills in the secrets
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload   # http://localhost:8000
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m evals.run --baseline 0.8
.venv\Scripts\python -m app.digest
```
