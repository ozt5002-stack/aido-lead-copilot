"""The eval runner's own plumbing, with the fake model: no network, no cost."""
from app.agent import FakeModelClient
from evals import run as evals_run


def test_case_history_reaches_the_model_as_earlier_turns(client):
    fake = FakeModelClient()
    case = {"id": "t", "input": "Do you have airplane tickets?",
            "history": [{"role": "user", "content": "how much does vanilla cost?"},
                        {"role": "assistant", "content": "We usually pay $89 per litre to Madagascar Vanilla Co."}]}
    result = evals_run.run_case(case, fake)
    sent = fake.last_messages
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "how much does vanilla cost?"
    assert "Madagascar Vanilla Co." in sent[1]["content"]
    assert sent[2]["content"][-1]["text"] == "Do you have airplane tickets?"
    assert result["status"] == "ok"


def test_case_without_history_is_a_single_turn(client):
    fake = FakeModelClient()
    evals_run.run_case({"id": "t", "input": "Revenue by branch for August 2026"}, fake)
    assert [m["role"] for m in fake.last_messages] == ["user"]


# --- grading (deterministic): the eval runner's own rules, tested without the model ---------------

import csv  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import yaml  # noqa: E402

from app.db import business_key  # noqa: E402

CASES = yaml.safe_load((Path(evals_run.HERE) / "cases.yaml").read_text(encoding="utf-8"))
SEEDED = {business_key(r["business_name"])
          for r in csv.DictReader((Path(evals_run.ROOT) / "data" / "leads.csv").open(encoding="utf-8"))}


def _result(**kw):
    return {"answer": "", "tools": [], "leads": [], "watched": {}, "usage": {}, "cost": 0, "status": "ok", **kw}


def test_hebrew_share():
    assert evals_run.hebrew_share("יש 12 לידים בשלב בנאי") == 1.0
    assert evals_run.hebrew_share("There are 12 leads") == 0.0
    assert evals_run.hebrew_share("123 !!") == 0.0
    assert evals_run.hebrew_share("שקד בוטיק uses Excel") < 0.6


def test_verdict_fails_on_a_must_pass_case_even_above_the_baseline():
    assert evals_run.verdict(19, 20, [], 0.8) == (0, [])
    code, reasons = evals_run.verdict(19, 20, ["missing_score"], 0.8)
    assert code == 1 and "missing_score" in reasons[0]
    assert evals_run.verdict(15, 20, [], 0.8)[0] == 1
    assert evals_run.verdict(1, 20, [], 0.0) == (0, [])


def test_grade_lead_row_and_watched():
    case = {"expect": {"lead": {"record_status": "needs_a_look", "total_score": None},
                       "watched": {"נחל מכללה": {"total_score": 38}}}}
    good = _result(leads=[{"business_name": "רימון", "record_status": "needs_a_look", "total_score": None}],
                   watched={"נחל מכללה": {"total_score": 38}})
    assert evals_run.grade_facts(case, good) == []
    guessed = _result(leads=[{"business_name": "רימון", "record_status": "logged", "total_score": 40}],
                      watched={"נחל מכללה": None})
    failures = evals_run.grade_facts(case, guessed)
    assert any("total_score" in f for f in failures) and any("no row" in f for f in failures)


def test_no_bi_patterns_catch_a_recommendation_but_not_a_refusal():
    case = next(c for c in CASES if c["id"] == "no_bi_for_firefighter")
    patterns = case["expect"]["answer_not_matches"]
    recommend = "שקד בוטיק בשלב כבאי. אני ממליץ להם על דשבורד BI כבר עכשיו."
    refuse = "שקד בוטיק בשלב כבאי, ולכן לא מתאים להם BI עכשיו. קודם סדר בסיסי: יעדים כתובים ומלאי מסודר."
    assert any(re.search(p, recommend, re.IGNORECASE) for p in patterns)
    assert not any(re.search(p, refuse, re.IGNORECASE) for p in patterns)


def test_cases_file_is_consistent():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) and len(ids) >= 15
    missing_score = [c for c in CASES if c.get("expect", {}).get("lead", {}).get("record_status") == "needs_a_look"]
    assert len(missing_score) >= 3 and all(c.get("must_pass") for c in missing_score)
    tools = {t for c in CASES for t in c.get("expect", {}).get("tools_called", [])}
    assert tools == {"leads_query", "lookup_business", "log_lead", "calculate_stage"}


NEW_NAMES = ["אופק הדרכות", "גבעה לוגיסטיקה", "רימון קייטרינג", "צאלון סטודיו", "תכלת נכסים", "אגם פתרונות משפטיים",
             "פסגה רובוטיקה", "סלע שיפוצים"]


@pytest.mark.parametrize("name", NEW_NAMES)
def test_new_business_names_in_cases_are_not_in_the_seed(name):
    # A "new lead" case must use a name the seed does not have, or it silently becomes a duplicate case.
    assert name in "".join(c["input"] + str(c.get("setup_leads", "")) for c in CASES)
    assert business_key(name) not in SEEDED


@pytest.mark.parametrize("name", ["שקד בוטיק", "נחל מכללה", "אופק סוכנות"])
def test_seeded_names_the_cases_rely_on_exist(name):
    assert business_key(name) in SEEDED


def test_each_case_starts_from_the_seed(client):
    from app.db import Lead, SessionLocal

    fake = FakeModelClient()
    with SessionLocal() as db:
        lead = db.query(Lead).filter(Lead.business_key == business_key("נחל מכללה")).one()
        lead.total_score = 38
        db.commit()
    evals_run.run_case({"id": "t", "input": "שלום"}, fake)
    with SessionLocal() as db:
        assert db.query(Lead).filter(Lead.business_key == business_key("נחל מכללה")).one().total_score is None
        assert db.query(Lead).count() == 300


def test_watched_rows_are_read_back_after_the_turn(client):
    fake = FakeModelClient()
    result = evals_run.run_case({"id": "t", "input": "שלום", "expect": {"watched": {"שקד בוטיק": {}}}}, fake)
    assert result["watched"]["שקד בוטיק"]["stage"] == "firefighter"
