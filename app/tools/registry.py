"""Tool definitions the model sees, and the dispatcher that runs them."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..db import PIPELINE_STATUSES
from ..stage import DOMAIN_IDS
from . import leads

_ANSWERS_SCHEMA = {
    "type": "object",
    "description": "all 20 answers, 4 per domain, each 1 (כבאי), 2 (בנאי) or 3 (פקח). Only answers written in the notes.",
    "properties": {d: {"type": "array", "items": {"type": "integer"}} for d in DOMAIN_IDS},
    "additionalProperties": False,
}
_AVERAGES_SCHEMA = {
    "type": "object",
    "description": "domain averages 1.0-3.0 exactly as written in the notes; leave out a domain that is not written",
    "properties": {d: {"type": "number"} for d in DOMAIN_IDS},
    "additionalProperties": False,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "leads_query",
        "description": (
            "Read-only query over AIDO's leads and diagnoses (one row per business). Use it for any question about "
            "how many leads, which stage, industry, pipeline status, weakest domain, month, deal values or scores. "
            "Pick a metric and a grouping and filter; set list=true to get the matching businesses by name. "
            "Hot = deal value of 25,000 ILS or more; waiting = status new or contacted. "
            "Never guess numbers: if the answer needs data, call this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": list(leads.METRICS),
                           "description": "count of leads, deal_value_sum / deal_value_avg (ILS), or score_avg (20-60)."},
                "group_by": {"type": "string", "enum": list(leads.GROUP_BY),
                             "description": "none for one number; stage, industry, pipeline_status, month, weakest_domain, or a domain's stage."},
                "date_from": {"type": "string", "description": "inclusive lead date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "inclusive lead date YYYY-MM-DD"},
                "stage": {"type": "string", "description": "firefighter / builder / inspector, or כבאי / בנאי / פקח"},
                "industry": {"type": "string", "description": "substring of the industry name"},
                "pipeline_status": {"type": "string", "enum": list(PIPELINE_STATUSES)},
                "hot_only": {"type": "boolean", "default": False},
                "waiting_only": {"type": "boolean", "default": False},
                "diagnosed_only": {"type": "boolean", "default": False, "description": "only leads with a score"},
                "min_employees": {"type": "integer"},
                "max_employees": {"type": "integer"},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "list": {"type": "boolean", "default": False, "description": "return matching leads (name, stage, status, deal value) instead of aggregates"},
            },
            "required": ["metric", "group_by"],
            "additionalProperties": False,
        },
    },
    {
        "name": "lookup_business",
        "description": (
            "Look up a business by (partial) name among the existing leads. known=true means this exact business "
            "already exists. Call it before log_lead, so no business is added twice, and to answer "
            "'do we already have X?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "the business name as written"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "log_lead",
        "description": (
            "Record one business as a new lead, or add a diagnosis to an existing lead that has no score yet. "
            "Pass only what is written in the notes. Never guess a score: if no total and no full set of 20 answers "
            "is written, leave total_score and answers out; the row is marked needs_a_look. The tool computes the "
            "stage itself. Pass source_ref (the image reference in the message) when there is one. "
            "It never overwrites or deletes anything; an existing business with a score is reported as duplicate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string"},
                "industry": {"type": ["string", "null"]},
                "employees": {"type": ["integer", "null"]},
                "lead_date": {"type": ["string", "null"], "description": "YYYY-MM-DD; the day the lead came in"},
                "total_score": {"type": ["integer", "null"], "description": "the total 20-60 exactly as written; null if not written"},
                "answers": _ANSWERS_SCHEMA,
                "domain_averages": _AVERAGES_SCHEMA,
                "pains": {"type": ["string", "null"], "description": "main pains, separated by ';'"},
                "pipeline_status": {"type": ["string", "null"], "description": "one of: " + ", ".join(PIPELINE_STATUSES)},
                "deal_value": {"type": ["number", "null"], "description": "estimated deal value in ILS, only if written"},
                "source_ref": {"type": ["string", "null"], "maxLength": 120, "description": "the image reference from the message, e.g. img_8f3a2c"},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["business_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_stage",
        "description": (
            "Compute the AIDO stage (כבאי / בנאי / פקח) from a total score (20-60), from domain averages (1.0-3.0), "
            "or from all 20 answers, with the boundaries used. Use it whenever a stage is asked for a number; "
            "never work a stage out yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "total_score": {"type": "integer"},
                "domain_averages": _AVERAGES_SCHEMA,
                "answers": _ANSWERS_SCHEMA,
            },
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}
MAX_RESULT_CHARS = 12000


def execute(name: str, tool_input: dict[str, Any], db: Session, *, user_id: int | None = None) -> str:
    """Run one tool and return its result as a JSON string for the model."""
    try:
        if name == "leads_query":
            args = _clean(tool_input)
            if "list" in args:
                args["list_leads"] = args.pop("list")
            result = leads.leads_query(db, **args)
        elif name == "lookup_business":
            result = leads.lookup_business(db, name=str(tool_input.get("name", "")))
        elif name == "log_lead":
            result = leads.log_lead(db, logged_by=user_id, **_clean(tool_input))
        elif name == "calculate_stage":
            result = leads.calculate_stage(**_clean(tool_input))
        else:
            result = {"error": f"unknown tool '{name}'"}
    except Exception as exc:  # the loop must survive a bad input; the model sees the error
        db.rollback()
        result = {"error": f"{type(exc).__name__}: {exc}"}
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... (truncated)"}'
    return text


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
