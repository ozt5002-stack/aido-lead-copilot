"""The morning digest: yesterday's leads, hot leads waiting, and spend.

Runs as a Railway cron service (`python -m app.digest`, schedule in README.md)
or through POST /internal/digest. It only reads; the rows it reports were
written by the chat turns during the day.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Lead, Message, Run, SessionLocal, init_db
from .tools.leads import HOT_DEAL_VALUE, WAITING_STATUSES


def _local_bounds(day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def build_digest(db: Session, day: date | None = None) -> str:
    """Minimal leads digest (plan task 3). Task 7 turns it into the Hebrew version."""
    tz = ZoneInfo(settings.timezone)
    day = day or (datetime.now(tz).date() - timedelta(days=1))
    start, end = _local_bounds(day)

    new = db.scalars(select(Lead).where(Lead.origin == "chat", Lead.created_at >= start, Lead.created_at < end)
                     .order_by(Lead.created_at)).all()
    needs = [r for r in new if r.record_status == "needs_a_look"]
    hot_waiting = db.scalars(select(Lead).where(Lead.deal_value >= HOT_DEAL_VALUE,
                                                Lead.pipeline_status.in_(WAITING_STATUSES))
                             .order_by(Lead.deal_value.desc())).all()

    messages = db.scalar(select(func.count()).select_from(Message)
                         .where(Message.role == "user", Message.created_at >= start, Message.created_at < end)) or 0
    runs = db.execute(select(func.count(Run.id), func.coalesce(func.sum(Run.cost_usd), 0.0),
                             func.sum(case((Run.status != "ok", 1), else_=0)))
                      .where(Run.created_at >= start, Run.created_at < end)).one()
    run_count, cost, not_ok = int(runs[0] or 0), float(runs[1] or 0.0), int(runs[2] or 0)

    lines = [f"AIDO Lead Copilot - {day.isoformat()}",
             f"New leads logged: {len(new)}",
             f"Needs a look: {len(needs)}" + (" - " + "; ".join(r.business_name for r in needs[:5]) if needs else ""),
             f"Hot leads waiting: {len(hot_waiting)}" + (" - " + "; ".join(f"{r.business_name} ₪{r.deal_value:,}" for r in hot_waiting[:5]) if hot_waiting else ""),
             f"Chat: {messages} messages · {run_count} model runs · ${cost:.2f} of ${settings.daily_cap_usd:.2f} cap",
             f"Runs not OK: {not_ok}" + (" - check the runs table and runbook.md" if not_ok else "")]
    return "\n".join(lines)


def send_digest(text: str) -> bool:
    """POST {"text": ...} to DIGEST_WEBHOOK_URL (Slack-compatible). Returns False when no URL is set."""
    if not settings.digest_webhook_url:
        return False
    import httpx

    r = httpx.post(settings.digest_webhook_url, json={"text": text}, timeout=15)
    r.raise_for_status()
    return True


def main() -> None:
    init_db()
    with SessionLocal() as db:
        body = build_digest(db)
    print(body)
    sent = send_digest(body)
    print(f"\n[sent to webhook: {sent}]")


if __name__ == "__main__":
    main()
