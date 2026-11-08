"""The morning digest: yesterday's leads, hot leads waiting, and spend.

Runs as a Railway cron service (`python -m app.digest`, schedule in README.md)
or through POST /internal/digest. It only reads; the rows it reports were
written by the chat turns during the day.
"""
from __future__ import annotations

import sys

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Lead, Message, Run, SessionLocal, init_db
from .stage import STAGE_HE
from .tools.leads import HOT_DEAL_VALUE, WAITING_STATUSES


def _local_bounds(day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


STATUS_HE = {"new": "חדש", "contacted": "נוצר קשר"}


def _he_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def build_digest(db: Session, day: date | None = None) -> str:
    """The morning digest in Hebrew (spec §2.5).

    - New leads: rows consultants logged through the chat (origin = chat) during `day`, the local day in
      settings.timezone. Seeded, fictional rows never count as new.
    - Hot leads waiting: every lead, seeded or logged, with a deal value of 25,000 or more whose status is
      new or contacted; the top five by deal value are named.
    - Spend: messages, model runs and their cost during `day`, against the daily cap.
    """
    tz = ZoneInfo(settings.timezone)
    day = day or (datetime.now(tz).date() - timedelta(days=1))
    start, end = _local_bounds(day)

    new = db.scalars(select(Lead).where(Lead.origin == "chat", Lead.created_at >= start, Lead.created_at < end)
                     .order_by(Lead.created_at)).all()
    needs = [r for r in new if r.record_status == "needs_a_look"]
    hot_waiting = db.scalars(select(Lead).where(Lead.deal_value >= HOT_DEAL_VALUE,
                                                Lead.pipeline_status.in_(WAITING_STATUSES))
                             .order_by(Lead.deal_value.desc(), Lead.id)).all()

    messages = db.scalar(select(func.count()).select_from(Message)
                         .where(Message.role == "user", Message.created_at >= start, Message.created_at < end)) or 0
    runs = db.execute(select(func.count(Run.id), func.coalesce(func.sum(Run.cost_usd), 0.0),
                             func.sum(case((Run.status != "ok", 1), else_=0)))
                      .where(Run.created_at >= start, Run.created_at < end)).one()
    run_count, cost, not_ok = int(runs[0] or 0), float(runs[1] or 0.0), int(runs[2] or 0)

    def stage(r: Lead) -> str:
        return STAGE_HE.get(r.stage or "", "ללא אבחון")

    lines = [f"AIDO Lead Copilot · סיכום בוקר ל-{_he_date(day)}"]
    if new:
        lines.append(f"לידים חדשים אתמול: {len(new)}"
                     + (f" (מתוכם {len(needs)} צריכים בדיקה)" if needs else "")
                     + " · " + "; ".join(f"{r.business_name} ({stage(r)})" for r in new[:5])
                     + (" ועוד" if len(new) > 5 else ""))
    else:
        lines.append("לידים חדשים אתמול: אין")
    if needs:
        lines.append("צריכים בדיקה: " + "; ".join(r.business_name for r in needs[:5]))
    if hot_waiting:
        lines.append(f"לידים חמים שמחכים לטיפול: {len(hot_waiting)} · "
                     + "; ".join(f"{r.business_name} ₪{r.deal_value:,} ({STATUS_HE.get(r.pipeline_status, r.pipeline_status)})"
                                 for r in hot_waiting[:5]))
    else:
        lines.append("לידים חמים שמחכים לטיפול: אין")
    lines.append(f"צ'אט: {messages} הודעות · {run_count} ריצות מודל · ${cost:.2f} מתוך תקרה של ${settings.daily_cap_usd:.2f}")
    lines.append(f"ריצות שנכשלו: {not_ok}" + (" · כדאי לבדוק את טבלת runs ואת runbook.md" if not_ok else ""))
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
    if hasattr(sys.stdout, "reconfigure"):  # Hebrew and ₪ on a Windows console or a redirected file
        sys.stdout.reconfigure(encoding="utf-8")
    init_db()
    with SessionLocal() as db:
        body = build_digest(db)
    print(body)
    sent = send_digest(body)
    print(f"\n[sent to webhook: {sent}]")


if __name__ == "__main__":
    main()
