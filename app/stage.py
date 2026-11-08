"""The business stage model: a Python port of lesson 8's src/score.js.

20 questions in 5 domains (4 each); every answer is 1 (כבאי), 2 (בנאי) or 3 (פקח).
Total 20-33 firefighter, 34-46 builder, 47-60 inspector. A domain's average is
rounded to one decimal, then 1.0-1.6 firefighter, 1.7-2.3 builder, 2.4-3.0 inspector.

Stages are rules, not judgement: the model never computes them, this module does
(docs/02-architecture.md, decisions). tests/test_stage.py checks this port
against score.js's own outputs (tests/fixtures/score_js_cases.json).
"""
from __future__ import annotations

import math

DOMAINS: list[dict] = [
    {"id": "strategy", "name": "אסטרטגיה ויעדים"},
    {"id": "management", "name": "הנהלה ומבנה ארגוני"},
    {"id": "systems", "name": "תהליכים ומערכות מידע"},
    {"id": "people", "name": "אנשים ותרבות ארגונית"},
    {"id": "finance", "name": "פיננסים"},
]
DOMAIN_IDS = [d["id"] for d in DOMAINS]
DOMAIN_NAME_HE = {d["id"]: d["name"] for d in DOMAINS}
QUESTIONS_PER_DOMAIN = 4
QUESTION_COUNT = QUESTIONS_PER_DOMAIN * len(DOMAINS)  # 20
MIN_TOTAL, MAX_TOTAL = QUESTION_COUNT, QUESTION_COUNT * 3  # 20, 60
MIN_AVERAGE, MAX_AVERAGE = 1.0, 3.0

STAGES = ("firefighter", "builder", "inspector")
STAGE_HE = {"firefighter": "כבאי", "builder": "בנאי", "inspector": "פקח"}


class StageError(ValueError):
    """An input outside the model's rules (wrong count, an answer not 1/2/3, a total out of range)."""


def round1(value: float) -> float:
    """Round to one decimal the way JavaScript's Math.round does (half up), not Python's round (half to even).

    score.js: Math.round((sum / n) * 10) / 10. For 2.25, Python's round gives 2.2; Math.round gives 2.3.
    """
    return math.floor(value * 10 + 0.5) / 10


def as_whole(value) -> int | None:
    """1, 1.0 -> 1 (JSON from the model may send 41.0); 41.5, "41", True, NaN -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def stage_for_total(total: int) -> str:
    whole = as_whole(total)
    if whole is None or not MIN_TOTAL <= whole <= MAX_TOTAL:
        raise StageError(f"total must be a whole number from {MIN_TOTAL} to {MAX_TOTAL} (got {total!r})")
    total = whole
    if total <= 33:
        return "firefighter"
    if total <= 46:
        return "builder"
    return "inspector"


def stage_for_average(average: float) -> str:
    """Stage for a domain average. The average is rounded to one decimal first, as score.js does."""
    if isinstance(average, bool) or not isinstance(average, (int, float)) or not math.isfinite(average):
        raise StageError(f"average must be a number (got {average!r})")
    # The range is checked on the value as given (architecture rule 4), then it is rounded.
    if not MIN_AVERAGE <= average <= MAX_AVERAGE:
        raise StageError(f"average must be from {MIN_AVERAGE} to {MAX_AVERAGE} (got {average!r})")
    avg = round1(float(average))
    if avg < 1.7:
        return "firefighter"
    if avg < 2.4:
        return "builder"
    return "inspector"


def score_business(answers: dict) -> dict:
    """answers: {"strategy": [1, 2, 3, 1], "management": [...], ...} -> total, stage and one entry per domain.

    Same output shape as score.js's scoreBusiness, plus Hebrew names for the stages.
    """
    if not isinstance(answers, dict):
        raise StageError("answers must be an object with the five domains")
    domains = []
    for domain in DOMAINS:
        values = answers.get(domain["id"])
        if not isinstance(values, list) or len(values) != QUESTIONS_PER_DOMAIN:
            raise StageError(f'Domain "{domain["id"]}" needs {QUESTIONS_PER_DOMAIN} answers')
        values = [as_whole(v) if as_whole(v) is not None else v for v in values]
        for v in values:
            if isinstance(v, bool) or not isinstance(v, int) or v not in (1, 2, 3):
                raise StageError(f'Answers must be 1, 2 or 3 (got {v} in "{domain["id"]}")')
        total = sum(values)
        average = round1(total / len(values))
        stage = stage_for_average(average)
        domains.append({"id": domain["id"], "name": domain["name"], "sum": total, "average": average,
                        "stage": stage, "stage_he": STAGE_HE[stage]})
    total = sum(d["sum"] for d in domains)
    stage = stage_for_total(total)
    return {"total": total, "max": MAX_TOTAL, "stage": stage, "stage_he": STAGE_HE[stage], "domains": domains}
