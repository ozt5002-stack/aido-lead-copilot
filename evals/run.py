"""Run the eval cases against the real model and grade them.

    python -m evals.run                 # all cases once
    python -m evals.run --runs 3        # each case three times (agents vary)
    python -m evals.run --judge         # also grade wording with a cheaper model
    python -m evals.run --baseline 0.8  # exit 1 if the pass rate is below 80%
                                        # (a failed must_pass case exits 1 with or without --baseline)

Facts are graded exactly (which tools ran, what rows exist). Wording is graded
by a second model only when --judge is passed, and never for the facts.
Every run appends a row to evals/history.csv. Costs real money: a full pass is
one new turn per case in cases.yaml (a case's `history` turns are stored, not
sent to the model one by one); check the tokens column in history.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Always a fresh, throwaway database: every case empties and reseeds the leads table, so the evals must
# never see a real one, even when DATABASE_URL is set in the shell (for example under `railway run`).
_tmp = Path(tempfile.mkdtemp(prefix="aido-lead-copilot-evals-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'evals.db'}"
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("DAILY_CAP_USD", "1000")

from app import agent as agent_module  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Conversation, Lead, Message, SessionLocal, User, business_key, init_db, seed_leads  # noqa: E402
from app.tools.leads import log_lead  # noqa: E402


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "nogit"


def _seed_history(db, user: User, turns: list[dict]) -> Conversation | None:
    """Store a case's earlier turns the way the app stores them, so the model gets them through `_history()`."""
    if not turns:
        return None
    conversation = Conversation(user_id=user.id, title=turns[0]["content"][:60])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    for t in turns:
        db.add(Message(conversation_id=conversation.id, user_id=user.id, role=t["role"], content=t["content"]))
    db.commit()
    return conversation


def run_case(case: dict, client) -> dict:
    with SessionLocal() as db:
        # Each case starts from exactly the seeded, fictional leads: a fill-in case changes a seeded row,
        # so the table is emptied and seeded again (300 rows, well under a second).
        db.query(Lead).delete()
        db.commit()
        seed_leads(db, ROOT / "data" / "leads.csv")
        for lead in case.get("setup_leads", []):
            log_lead(db, **lead)
        user = db.query(User).filter_by(name="eval").one_or_none() or User(name="eval")
        if user.id is None:
            db.add(user)
            db.commit()
        conversation = _seed_history(db, user, case.get("history", []))
        text_parts, tools, usage, cost, status = [], [], {}, 0.0, "ok"
        for ev in agent_module.run_turn(db, user=user, conversation=conversation, text=case["input"], image=None,
                                        client=client):
            if ev["type"] == "text":
                text_parts.append(ev["text"])
            elif ev["type"] == "tool" and ev["status"] == "start":
                tools.append(ev["name"])
            elif ev["type"] == "done":
                usage, cost = ev.get("usage", {}), ev.get("cost_usd", 0.0)
            elif ev["type"] == "error":
                status = "error"
                text_parts.append(f"[error: {ev['message']}]")
        if status == "error":  # keep the real exception from the runs row, not only the friendly message
            from app.db import Run
            last = db.query(Run).order_by(Run.id.desc()).first()
            if last is not None and last.error:
                text_parts.append(f" [run error: {last.error[:300]}]")
        leads = [{"business_name": r.business_name, "business_key": r.business_key, "total_score": r.total_score,
                  "stage": r.stage, "record_status": r.record_status, "source_ref": r.source_ref,
                  "deal_value": r.deal_value,
                  "origin": r.origin, "id": r.id}
                 for r in db.query(Lead).filter(Lead.origin == "chat").order_by(Lead.id).all()]
        touched = {}
        for key in case.get("expect", {}).get("watched", {}):
            row = db.query(Lead).filter(Lead.business_key == business_key(key)).one_or_none()
            touched[key] = None if row is None else {"total_score": row.total_score, "stage": row.stage,
                                                     "record_status": row.record_status}
    return {"answer": "".join(text_parts), "tools": tools, "leads": leads, "watched": touched, "usage": usage,
            "cost": cost, "status": status}


def grade_facts(case: dict, result: dict) -> list[str]:
    exp, failures = case.get("expect", {}), []
    for t in exp.get("tools_called", []):
        if t not in result["tools"]:
            failures.append(f"expected tool {t} to be called")
    for t in exp.get("tools_not_called", []):
        if t in result["tools"]:
            failures.append(f"tool {t} must not be called")
    answer = result["answer"].lower()
    if exp.get("answer_contains_any") and not any(s.lower() in answer for s in exp["answer_contains_any"]):
        failures.append(f"answer contains none of {exp['answer_contains_any']}")
    for s in exp.get("answer_contains_all", []):
        if s.lower() not in answer:
            failures.append(f"answer must contain {s!r}")
    for s in exp.get("answer_not_contains", []):
        if s.lower() in answer:
            failures.append(f"answer must not contain {s!r}")
    for pattern in exp.get("answer_not_matches", []):
        if re.search(pattern, result["answer"], re.IGNORECASE):
            failures.append(f"answer matches forbidden pattern {pattern!r}")
    if exp.get("answer_hebrew") and hebrew_share(result["answer"]) < 0.6:
        failures.append(f"answer is not mainly Hebrew ({hebrew_share(result['answer']):.0%} Hebrew letters)")
    if exp.get("no_lead_rows") and result["leads"]:
        failures.append("lead rows were written")
    if "lead" in exp:
        want, rows = exp["lead"], result["leads"]
        if not rows:
            failures.append("no lead row written")
        else:
            row = rows[-1]
            if "name_contains" in want and want["name_contains"].lower() not in (row["business_name"] or "").lower():
                failures.append(f"business {row['business_name']!r} does not contain {want['name_contains']!r}")
            for key in ("record_status", "total_score", "stage", "source_ref", "deal_value"):
                if key in want and row.get(key) != want[key]:
                    failures.append(f"lead.{key} = {row.get(key)!r}, expected {want[key]!r}")
    if "lead_count_for_name" in exp:
        c = exp["lead_count_for_name"]
        n = sum(1 for r in result["leads"] if r["business_key"] == business_key(c["name"]))
        if n != c["count"]:
            failures.append(f"{n} chat rows for {c['name']!r}, expected {c['count']}")
    for key, want in exp.get("watched", {}).items():
        got = result["watched"].get(key)
        if got is None:
            failures.append(f"no row for {key!r}")
            continue
        for k, v in want.items():
            if got.get(k) != v:
                failures.append(f"{key}.{k} = {got.get(k)!r}, expected {v!r}")
    if result["status"] != "ok":
        failures.append("turn ended in error")
    return failures


def hebrew_share(text: str) -> float:
    """Share of letters that are Hebrew. Numbers, names in English and punctuation do not count either way."""
    letters = [c for c in text if c.isalpha()]
    return sum("֐" <= c <= "׿" for c in letters) / len(letters) if letters else 0.0


def verdict(passed: int, total: int, must_failed: list[str], baseline: float) -> tuple[int, list[str]]:
    """Exit code and reasons: below the baseline, or any must_pass case failed (whatever the rate)."""
    reasons = []
    rate = passed / total if total else 0.0
    if baseline and rate < baseline:
        reasons.append(f"below baseline {baseline:.0%}")
    if must_failed:
        reasons.append("must_pass cases failed: " + ", ".join(sorted(set(must_failed))))
    return (1 if reasons else 0), reasons


def grade_wording(case: dict, result: dict, judge_model: str) -> str | None:
    """PASS/FAIL from a cheaper model against the rubric. Never used for facts."""
    import anthropic

    client = anthropic.Anthropic()
    earlier = "".join(f"{t['role'].capitalize()}: {t['content']}\n\n" for t in case.get("history", []))
    prompt = (f"You grade an assistant's reply against a rubric. Reply with PASS or FAIL and one short reason.\n\n"
              + (f"Earlier in the conversation:\n\n{earlier}" if earlier else "")
              + f"User asked: {case['input']}\n\nAssistant replied:\n{result['answer']}\n\nRubric: {case['rubric']}")
    msg = client.messages.create(model=judge_model, max_tokens=100, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return None if text.upper().startswith("PASS") else text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", default="claude-haiku-5-5")
    ap.add_argument("--baseline", type=float, default=0.0)
    ap.add_argument("--only", help="case id")
    args = ap.parse_args()

    if settings.model_provider != "anthropic" or not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; evals need the real model.", file=sys.stderr)
        return 2

    init_db()
    client = agent_module.get_model_client()
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
        if not cases:
            print(f"no case with id {args.only!r}", file=sys.stderr)
            return 2

    passed = total = 0
    must_failed: list[str] = []
    tokens_in = tokens_out = 0
    cost = 0.0
    out_dir = HERE / "out"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    details = []
    for case in cases:
        for n in range(args.runs):
            total += 1
            result = run_case(case, client)
            failures = grade_facts(case, result)
            if args.judge and case.get("rubric"):
                judged = grade_wording(case, result, args.judge_model)
                if judged:
                    failures.append(f"rubric: {judged}")
            ok = not failures
            passed += ok
            if not ok and case.get("must_pass"):
                must_failed.append(case["id"])
            tokens_in += int(result["usage"].get("input_tokens", 0))
            tokens_out += int(result["usage"].get("output_tokens", 0))
            cost += float(result["cost"] or 0)
            print(f"{'PASS' if ok else 'FAIL'}  {case['id']}" + (" [must_pass]" if case.get("must_pass") else "")
                  + (f" (run {n + 1})" if args.runs > 1 else ""))
            for f in failures:
                print(f"      - {f}")
            details.append({"id": case["id"], "run": n + 1, "ok": ok, "failures": failures, **result})

    rate = passed / total if total else 0.0
    (out_dir / f"{stamp}.json").write_text(json.dumps(details, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    history = HERE / "history.csv"
    new = not history.exists()
    with history.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "git_sha", "model", "effort", "passed", "total", "pass_rate", "input_tokens", "output_tokens", "cost_usd", "judge"])
        w.writerow([stamp, git_sha(), settings.model, settings.model_effort, passed, total, f"{rate:.3f}", tokens_in, tokens_out, f"{cost:.4f}", args.judge])
    print(f"\n{passed}/{total} passed ({rate:.0%}) · {tokens_in} in / {tokens_out} out · ${cost:.4f} · {settings.model} @ {settings.model_effort}")
    code, reasons = verdict(passed, total, must_failed, args.baseline)
    for r in reasons:
        print(r, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
