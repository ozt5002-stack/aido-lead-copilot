"""The four lead tools: leads_query, lookup_business, log_lead, calculate_stage.

The rules live here, not in the prompt (docs/02-architecture.md, "Rules log_lead enforces"):
- a score is never guessed: it is the total as given, or the sum of all 20 answers;
- out-of-range values are not stored, and the row goes to "needs_a_look";
- one business is one row (business_key or source_ref); an existing row without a
  score gets its empty diagnosis fields filled, and nothing is ever overwritten;
- stages come from app/stage.py only.

leads_query loads the filtered rows and aggregates them in Python. The table holds
hundreds of rows, so this is simpler than dialect-specific SQL and runs the same
on SQLite and Postgres. Revisit it at tens of thousands of rows.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import PIPELINE_STATUSES, Lead, business_key
from ..stage import (DOMAIN_IDS, DOMAIN_NAME_HE, MAX_TOTAL, MIN_TOTAL, STAGE_HE, STAGES, StageError, as_whole,
                     round1, score_business, stage_for_average, stage_for_total)

HOT_DEAL_VALUE = 25_000  # spec.md §5
WAITING_STATUSES = ("new", "contacted")
STATUS_HE = {"new": "חדש", "contacted": "נוצר קשר", "meeting": "נקבעה פגישה", "diagnosed": "אבחון בוצע",
             "proposal": "הצעה נשלחה", "won": "נסגר", "lost": "אבד"}
METRICS = ("count", "deal_value_sum", "deal_value_avg", "score_avg")
GROUP_BY = ("none", "stage", "industry", "pipeline_status", "month", "weakest_domain",
            *[f"{d}_stage" for d in DOMAIN_IDS])
_STAGE_BY_NAME = {**{s: s for s in STAGES}, **{he: s for s, he in STAGE_HE.items()}}
_MONEY_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stage_name(value: str | None) -> str | None:
    return _STAGE_BY_NAME.get((value or "").strip().lower()) or _STAGE_BY_NAME.get((value or "").strip())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _iso_date(value: str | None) -> date | None:
    """leads_query takes YYYY-MM-DD only, as its schema says: 10/1/2026 is ambiguous."""
    try:
        return date.fromisoformat(str(value).strip()) if value else None
    except ValueError:
        return None


def parse_money(value) -> int | None:
    """'₪25,000' -> 25000; 18000.0 -> 18000; 'unknown', 0, negatives -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value)) if value > 0 else None
    text = str(value).replace("₪", "").replace("ש\"ח", "").replace("ILS", "").replace("NIS", "").replace(" ", "")
    if text.startswith("-"):
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    number = float(m.group(0).replace(",", ""))
    if re.search(r"\d\s*[kK]|אלף", str(value)):
        number *= 1000
    return int(round(number)) if number > 0 else None


def is_hot(lead: Lead) -> bool:
    return (lead.deal_value or 0) >= HOT_DEAL_VALUE


def lead_row(lead: Lead) -> dict:
    """A lead as the model and the UI see it: stages in English and Hebrew."""
    out = {
        "id": lead.id, "business_name": lead.business_name, "industry": lead.industry, "employees": lead.employees,
        "lead_date": lead.lead_date.isoformat() if lead.lead_date else None,
        "total_score": lead.total_score, "stage": lead.stage, "stage_he": STAGE_HE.get(lead.stage or ""),
        "domains": {d: {"average": getattr(lead, f"{d}_avg"), "stage": getattr(lead, f"{d}_stage"),
                        "stage_he": STAGE_HE.get(getattr(lead, f"{d}_stage") or "")} for d in DOMAIN_IDS},
        "pains": lead.pains, "pipeline_status": lead.pipeline_status,
        "pipeline_status_he": STATUS_HE.get(lead.pipeline_status), "deal_value": lead.deal_value,
        "hot": is_hot(lead), "record_status": lead.record_status, "fictional": lead.fictional, "origin": lead.origin,
        "notes": lead.notes, "created_at": lead.created_at.isoformat(timespec="seconds") if lead.created_at else None,
    }
    if not any(v["average"] is not None for v in out["domains"].values()):
        out["domains"] = None
    return out


def _short(lead: Lead) -> dict:
    return {"id": lead.id, "business_name": lead.business_name, "industry": lead.industry,
            "stage": lead.stage, "stage_he": STAGE_HE.get(lead.stage or ""), "total_score": lead.total_score,
            "pipeline_status": lead.pipeline_status, "deal_value": lead.deal_value, "hot": is_hot(lead),
            "lead_date": lead.lead_date.isoformat() if lead.lead_date else None}


def _weakest(lead: Lead) -> list[str]:
    avgs = {d: getattr(lead, f"{d}_avg") for d in DOMAIN_IDS}
    if any(v is None for v in avgs.values()):
        return []
    low = min(avgs.values())
    return [d for d, v in avgs.items() if v == low]


def data_range(db: Session) -> tuple[date | None, date | None]:
    return db.execute(select(func.min(Lead.lead_date), func.max(Lead.lead_date))).one()


def industries(db: Session) -> list[str]:
    return [i for i in db.scalars(select(Lead.industry).distinct().order_by(Lead.industry)) if i]


def recent_leads(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit)).all()
    return [lead_row(r) for r in rows]


# ---------------------------------------------------------------------------
# leads_query (read only)
# ---------------------------------------------------------------------------

def leads_query(db: Session, *, metric: str = "count", group_by: str = "none", date_from: str | None = None,
                date_to: str | None = None, stage: str | None = None, industry: str | None = None,
                pipeline_status: str | None = None, hot_only: bool = False, waiting_only: bool = False,
                diagnosed_only: bool = False, min_employees: int | None = None, max_employees: int | None = None,
                top_n: int = 10, list_leads: bool = False) -> dict:
    """The tool's `list` parameter arrives here as `list_leads` (registry.py), so the builtin stays usable."""
    if metric not in METRICS:
        return {"error": f"unknown metric '{metric}'", "allowed": METRICS}
    if group_by not in GROUP_BY:
        return {"error": f"unknown group_by '{group_by}'", "allowed": GROUP_BY}
    if pipeline_status and pipeline_status not in PIPELINE_STATUSES:
        return {"error": f"unknown pipeline_status '{pipeline_status}'", "allowed": PIPELINE_STATUSES}
    stage_key = _stage_name(stage) if stage else None
    if stage and not stage_key:
        return {"error": f"unknown stage '{stage}'", "allowed": [*STAGES, *STAGE_HE.values()]}
    d_from, d_to = _iso_date(date_from), _iso_date(date_to)
    if (date_from and not d_from) or (date_to and not d_to):
        return {"error": "dates must be YYYY-MM-DD"}
    top_n = max(1, min(int(top_n or 10), 50))

    q = select(Lead)
    if d_from:
        q = q.where(Lead.lead_date >= d_from)
    if d_to:
        q = q.where(Lead.lead_date <= d_to)
    if stage_key:
        q = q.where(Lead.stage == stage_key)
    if industry:
        q = q.where(func.lower(Lead.industry).like(f"%{industry.strip().lower()}%"))
    if pipeline_status:
        q = q.where(Lead.pipeline_status == pipeline_status)
    if hot_only:
        q = q.where(Lead.deal_value >= HOT_DEAL_VALUE)
    if waiting_only:
        q = q.where(Lead.pipeline_status.in_(WAITING_STATUSES))
    if diagnosed_only:
        q = q.where(Lead.total_score.is_not(None))
    if min_employees is not None:
        q = q.where(Lead.employees >= int(min_employees))
    if max_employees is not None:
        q = q.where(Lead.employees <= int(max_employees))
    leads = db.scalars(q).all()

    filters = {"date_from": str(d_from) if d_from else None, "date_to": str(d_to) if d_to else None,
               "stage": stage_key, "industry": industry, "pipeline_status": pipeline_status, "hot_only": hot_only,
               "waiting_only": waiting_only, "diagnosed_only": diagnosed_only,
               "min_employees": min_employees, "max_employees": max_employees}
    base = {"metric": metric, "group_by": group_by, "filters": filters, "matched": len(leads),
            "hot_threshold": HOT_DEAL_VALUE}

    if list_leads:
        ordered = sorted(leads, key=lambda r: (-(r.deal_value or 0), -(r.lead_date or date.min).toordinal()))
        return {**base, "leads": [_short(r) for r in ordered[:top_n]], "listed": min(top_n, len(leads))}

    if group_by == "none":
        return {**base, "value": _metric(metric, leads), "count": len(leads)}

    groups: dict[str, list[Lead]] = defaultdict(list)
    for r in leads:
        if group_by == "weakest_domain":
            keys = _weakest(r)
        elif group_by == "month":
            keys = [r.lead_date.strftime("%Y-%m")] if r.lead_date else []
        else:
            value = getattr(r, group_by)
            keys = [value if value is not None else "none"]
        for k in keys:
            groups[k].append(r)

    rows = [{"key": k, "label_he": _label_he(group_by, k), "value": _metric(metric, g), "count": len(g)}
            for k, g in groups.items()]
    if group_by == "month":
        rows.sort(key=lambda x: x["key"])
    elif group_by == "stage" or group_by.endswith("_stage"):
        order = {s: i for i, s in enumerate([*STAGES, "none"])}
        rows.sort(key=lambda x: order.get(x["key"], 99))
    elif group_by == "pipeline_status":
        order = {s: i for i, s in enumerate([*PIPELINE_STATUSES, "none"])}
        rows.sort(key=lambda x: order.get(x["key"], 99))
    else:
        rows.sort(key=lambda x: (-(x["value"] or 0), x["key"]))
        rows = rows[:top_n]
    out = {**base, "rows": rows, "row_count": len(rows)}
    if group_by == "weakest_domain":
        out["note"] = "only diagnosed leads; a lead with a tie is counted under each tied domain"
    return out


def _metric(metric: str, leads: list[Lead]):
    if metric == "count":
        return len(leads)
    if metric == "deal_value_sum":
        return sum(r.deal_value or 0 for r in leads)
    values = [r.deal_value for r in leads if r.deal_value is not None] if metric == "deal_value_avg" \
        else [r.total_score for r in leads if r.total_score is not None]
    return round(sum(values) / len(values), 1) if values else None


def _label_he(group_by: str, key: str) -> str | None:
    if group_by == "stage" or group_by.endswith("_stage"):
        return STAGE_HE.get(key, "ללא אבחון" if key == "none" else None)
    if group_by == "pipeline_status":
        return STATUS_HE.get(key)
    if group_by == "weakest_domain":
        return DOMAIN_NAME_HE.get(key)
    return None


# ---------------------------------------------------------------------------
# lookup_business (read only)
# ---------------------------------------------------------------------------

def lookup_business(db: Session, *, name: str) -> dict:
    key = business_key(name)
    if not key:
        return {"matches": [], "known": False, "error": "business name missing"}
    exact = db.scalar(select(Lead).where(Lead.business_key == key))
    if exact:
        return {"matches": [_short(exact)], "known": True, "exact": True}
    rows = db.scalars(select(Lead).where(Lead.business_key.like(f"%{key}%")).limit(10)).all()
    if not rows:
        seen: dict[int, Lead] = {}
        for word in [w for w in key.split() if len(w) > 2]:
            for r in db.scalars(select(Lead).where(Lead.business_key.like(f"%{word}%")).limit(10)):
                seen.setdefault(r.id, r)
        rows = list(seen.values())[:10]
    return {"matches": [_short(r) for r in rows], "known": False, "exact": False,
            "note": "no exact match; these are similar names, not the same business" if rows else None}


# ---------------------------------------------------------------------------
# calculate_stage (no database)
# ---------------------------------------------------------------------------

def calculate_stage(*, total_score=None, domain_averages: dict | None = None, answers: dict | None = None) -> dict:
    if answers is not None:
        try:
            r = score_business(answers)
        except StageError as exc:
            return {"error": str(exc)}
        return {"total_score": r["total"], "stage": r["stage"], "stage_he": r["stage_he"], "domains": r["domains"],
                "boundaries": _boundaries()}
    out: dict = {"boundaries": _boundaries()}
    if total_score is not None:
        try:
            s = stage_for_total(total_score)
        except StageError as exc:
            return {"error": str(exc), "boundaries": _boundaries()}
        out.update(total_score=as_whole(total_score), stage=s, stage_he=STAGE_HE[s])
    if domain_averages:
        domains = {}
        for d, v in domain_averages.items():
            if d not in DOMAIN_IDS:
                return {"error": f"unknown domain '{d}'", "allowed": DOMAIN_IDS}
            try:
                s = stage_for_average(v)
            except StageError as exc:
                return {"error": f"{d}: {exc}", "boundaries": _boundaries()}
            domains[d] = {"average": round1(float(v)), "stage": s, "stage_he": STAGE_HE[s], "name_he": DOMAIN_NAME_HE[d]}
        out["domains"] = domains
    if "stage" not in out and "domains" not in out:
        return {"error": "pass total_score, domain_averages or answers", "boundaries": _boundaries()}
    return out


def _boundaries() -> dict:
    return {"total": {"כבאי": "20-33", "בנאי": "34-46", "פקח": "47-60"},
            "domain_average": {"כבאי": "1.0-1.6", "בנאי": "1.7-2.3", "פקח": "2.4-3.0"},
            "rounding": "a domain average is rounded to one decimal before the cut-offs"}


# ---------------------------------------------------------------------------
# log_lead (insert one business, or fill an empty diagnosis)
# ---------------------------------------------------------------------------

def _diagnosis(total_score, answers, domain_averages) -> tuple[int | None, dict[str, float], list[str]]:
    """Apply rules 1-5 and 7: what score and averages may be stored, and the notes on why not."""
    notes: list[str] = []
    computed_total, computed_avgs = None, {}
    if answers:
        complete = isinstance(answers, dict) and all(isinstance(answers.get(d), list) and len(answers[d]) == 4
                                                     for d in DOMAIN_IDS)
        if complete:
            try:
                r = score_business(answers)
                computed_total = r["total"]
                computed_avgs = {d["id"]: d["average"] for d in r["domains"]}
            except StageError as exc:
                notes.append(f"answers out of range, not stored: {exc}")
        else:
            notes.append("partial answers, not a score: " + json.dumps(answers, ensure_ascii=False)[:300])

    given_total = None
    if total_score is not None:
        whole = as_whole(total_score)
        if whole is None or not MIN_TOTAL <= whole <= MAX_TOTAL:
            notes.append(f"score {total_score!r} out of range ({MIN_TOTAL}-{MAX_TOTAL}), not stored")
        else:
            given_total = whole

    if given_total is not None and computed_total is not None and given_total != computed_total:
        notes.append(f"total and answers disagree ({given_total} vs {computed_total}); neither stored")
        return None, {}, notes

    avgs = dict(computed_avgs)
    for d, v in (domain_averages or {}).items():
        if d not in DOMAIN_IDS:
            notes.append(f"unknown domain {d!r} ignored")
            continue
        try:
            stage_for_average(v)
        except StageError:
            notes.append(f"{d} average {v!r} out of range (1.0-3.0), not stored")
            continue
        if d in avgs:
            if round1(float(v)) != avgs[d]:
                notes.append(f"{d} average {v} differs from the answers ({avgs[d]}); the answers were used")
            continue
        avgs[d] = round1(float(v))

    total = given_total if given_total is not None else computed_total
    return total, avgs, notes


def _set_diagnosis(lead: Lead, total: int | None, avgs: dict[str, float], only_empty: bool) -> bool:
    changed = False
    if total is not None and (lead.total_score is None or not only_empty):
        lead.total_score, lead.stage = total, stage_for_total(total)
        changed = True
    for d, v in avgs.items():
        if getattr(lead, f"{d}_avg") is None or not only_empty:
            setattr(lead, f"{d}_avg", v)
            setattr(lead, f"{d}_stage", stage_for_average(v))
            changed = True
    return changed


def _append_notes(lead: Lead, notes: list[str]) -> None:
    if notes:
        lead.notes = "; ".join(filter(None, [lead.notes, *notes]))[:2000]


def log_lead(db: Session, *, business_name: str | None, industry: str | None = None, employees=None,
             lead_date: str | None = None, total_score=None, answers: dict | None = None,
             domain_averages: dict | None = None, pains: str | list | None = None, pipeline_status: str | None = None,
             deal_value=None, source_ref: str | None = None, notes: str | None = None,
             logged_by: int | None = None) -> dict:
    name = " ".join((business_name or "").split())
    key = business_key(name)
    if not key:
        return {"error": "business name missing: a lead needs a business name; nothing was logged"}
    source_ref = (source_ref or "").strip() or None
    total, avgs, problems = _diagnosis(total_score, answers, domain_averages)

    # Rule 6: one business is one row.
    existing = db.scalar(select(Lead).where(Lead.source_ref == source_ref)) if source_ref else None
    existing = existing or db.scalar(select(Lead).where(Lead.business_key == key))
    if existing is not None:
        if existing.total_score is None and _set_diagnosis(existing, total, avgs, only_empty=True):
            if existing.total_score is not None:
                existing.record_status = "logged"
            _append_notes(existing, [f"diagnosis filled in by chat {datetime.now(ZoneInfo(settings.timezone)).date().isoformat()}", *problems])
            db.commit()
            db.refresh(existing)
            return {"action": "filled", "record_status": existing.record_status, "notes": problems,
                    "row": lead_row(existing)}
        return {"action": "duplicate", "record_status": existing.record_status,
                "reason": "the business already exists; nothing was changed", "notes": problems,
                "row": lead_row(existing)}

    status = (pipeline_status or "").strip().lower() or None
    if status and status not in PIPELINE_STATUSES:
        problems.append(f"unknown pipeline status {pipeline_status!r}; set to the default")
        status = None
    status = status or ("diagnosed" if total is not None else "new")

    money = parse_money(deal_value)
    if deal_value not in (None, "") and money is None:
        problems.append(f"deal value {deal_value!r} unreadable, not stored")
    people = as_whole(employees) if employees is not None else None
    if employees is not None and (people is None or people <= 0):
        problems.append(f"employees {employees!r} not a positive whole number, not stored")
        people = None
    when = _parse_date(lead_date)
    if lead_date and when is None:
        problems.append(f"lead date {lead_date!r} unreadable; today was used")
    when = when or datetime.now(ZoneInfo(settings.timezone)).date()
    if total is None:
        problems.append("score missing: a person needs to add it")

    lead = Lead(business_name=name[:120], business_key=key[:120], industry=(industry or "").strip()[:60] or None,
                employees=people, lead_date=when, pains="; ".join(pains) if isinstance(pains, (list, tuple)) else pains,
                pipeline_status=status, deal_value=money, fictional=False,
                record_status="logged" if total is not None else "needs_a_look",
                source_ref=source_ref, origin="chat", logged_by=logged_by)
    _set_diagnosis(lead, total, avgs, only_empty=False)
    lead.notes = "; ".join(filter(None, [notes, *problems]))[:2000] or None
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return {"action": "created", "record_status": lead.record_status, "notes": problems, "row": lead_row(lead)}
