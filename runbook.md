# runbook.md - when AIDO Lead Copilot breaks

Written while everything works. Each entry is a sequence: click here, run this, check that. Add an entry after every incident.

## App is down (health check red, URL not loading)

1. Railway → the web service → **Deployments**. Is the latest deploy red? Open its logs; the last lines say why (usually a missing variable or a failed import).
2. Click the previous green deploy → **Redeploy**. The app is back on the old version within a minute.
3. Open an issue with the log lines. Fix forward through a PR. Do not edit anything in the Railway shell.

## Model errors (replies fail with "try again in a minute")

1. Check `https://status.anthropic.com`. If there is an incident, wait; the SDK already retries 429/529.
2. Check the day cap: `GET /api/stats` (signed in). If `spend_today_usd ≥ daily_cap_usd`, the app is doing its job; raise `DAILY_CAP_USD` in Variables only if the team lead agrees to the cost.
3. Check the key: `/health` says `ANTHROPIC_API_KEY missing` if the variable was lost. Set it in Variables and redeploy.
4. Look at the `runs` table for `status = 'error'` and the `error` column.

## A key leaked (in a commit, a chat, a screenshot)

1. **Rotate first.** platform.claude.com → API keys → revoke the key, create a new one. For `APP_PASSWORD` or `APP_SECRET`: generate new values.
2. Update the Railway Variables, redeploy. Sessions will be invalidated when `APP_SECRET` changes; users sign in again.
3. Only then clean Git history (`git filter-repo` or a fresh repo for a small project) and force-push. Tell anyone who cloned.
4. Add a `bug` issue describing how it leaked, and a rule to CONTRIBUTING.md if one is missing.

## Wrong rows written (a business logged twice, a wrong score, a wrong stage)

1. Pause the cron service so the digest does not report it again.
2. Find the turn: `runs` table → by time → `conversation_id`; the UI's leads panel (לידים אחרונים) shows the rows. A score is never edited by hand: a wrong one means a tool rule or the prompt let it through.
3. Fix forward via a ticket: a migration or a one-off script committed to the repo, reviewed, run once. Never edit rows in the database console by hand.
4. If the cause was the prompt or the tool rules, add an eval case first, then fix.

## Database restore

1. Railway → Postgres → **Backups** → pick the snapshot → restore into the **staging** environment's database.
2. Point a staging deploy at it; open the app; check the leads panel and ask "כמה לידים יש בכל שלב?".
3. Promote: restore into production in the same way, during a quiet hour; redeploy the web service.

## Deploy is stuck or the health check never passes

1. Logs → look for the seed report (`schema_version: 2, leads_seeded: 300` on a first deploy, `leads_seeded: 0` later). The seed takes seconds; the health check timeout is 120 s.
2. If the database URL is wrong, `/health` returns 503 with `db:` in `problems`. Check the `DATABASE_URL` reference variable.
3. Rollback to the previous deploy if users are waiting; fix in a PR.

## Who to call

- You (the implementer), then Oz (team lead for this course project; decides on cost and data).
- Railway status: `https://status.railway.com` · Anthropic status: `https://status.anthropic.com`.
