"""The lead tools: every log_lead rule (docs/02-architecture.md 1-7), dedup, fill-in, leads_query, calculate_stage.

Each test gets its own empty database (no seed), so counts are exact.
"""
import json

import pytest
from sqlalchemy.orm import Session

from app.db import Lead, init_db, make_engine
from app.tools import registry
from app.tools.leads import calculate_stage, leads_query, log_lead, lookup_business, parse_money

ALL_2 = {d: [2, 2, 2, 2] for d in ("strategy", "management", "systems", "people", "finance")}  # total 40, בנאי


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'tools.db'}")
    init_db(engine, data_dir=tmp_path)  # no leads.csv there: an empty table
    with Session(engine) as s:
        yield s


def rows(db):
    return db.query(Lead).order_by(Lead.id).all()


# --- rule 1: domain averages are optional -----------------------------------

def test_total_without_averages_is_logged_with_empty_domain_stages(db):
    r = log_lead(db, business_name="אופק הדרכות", total_score=41)
    assert r["action"] == "created" and r["record_status"] == "logged"
    lead = rows(db)[0]
    assert lead.total_score == 41 and lead.stage == "builder"
    assert lead.strategy_avg is None and lead.strategy_stage is None
    assert r["row"]["stage_he"] == "בנאי" and r["row"]["domains"] is None


# --- rule 2: the score is given, or the sum of all 20 answers ---------------

def test_twenty_answers_give_the_total_and_the_domain_averages(db):
    answers = dict(ALL_2, systems=[1, 1, 1, 2])  # 8+8+5+8+8 = 37
    r = log_lead(db, business_name="נוף שילוח", answers=answers)
    lead = rows(db)[0]
    assert lead.total_score == 37 and lead.stage == "builder"
    assert lead.systems_avg == 1.3 and lead.systems_stage == "firefighter"
    assert r["record_status"] == "logged"


def test_partial_answers_are_not_a_score(db):
    r = log_lead(db, business_name="סלע ייצור", answers={"strategy": [1, 1, 1, 1], "finance": [2, 2]})
    lead = rows(db)[0]
    assert lead.total_score is None and lead.stage is None and lead.strategy_avg is None
    assert r["record_status"] == "needs_a_look"
    assert "partial answers" in lead.notes and "score missing" in lead.notes


def test_score_is_never_derived_from_domain_averages(db):
    averages = {"strategy": 2.0, "management": 2.0, "systems": 2.0, "people": 2.0, "finance": 2.0}
    r = log_lead(db, business_name="דקל מדיה", domain_averages=averages)
    lead = rows(db)[0]
    assert lead.total_score is None and lead.stage is None  # 5 x 2.0 x 4 = 40 would be a guess
    assert lead.strategy_avg == 2.0 and lead.strategy_stage == "builder"
    assert r["record_status"] == "needs_a_look"


# --- rule 3: a total that disagrees with the answers -----------------------

def test_total_and_answers_disagree_stores_neither(db):
    r = log_lead(db, business_name="ערבה ביטוח", total_score=45, answers=ALL_2)
    lead = rows(db)[0]
    assert lead.total_score is None and lead.strategy_avg is None
    assert r["record_status"] == "needs_a_look" and "disagree" in lead.notes


def test_total_that_matches_the_answers_is_fine(db):
    r = log_lead(db, business_name="ערבה ביטוח", total_score=40, answers=ALL_2)
    assert r["record_status"] == "logged" and rows(db)[0].total_score == 40


# --- rule 4: out of range ---------------------------------------------------

@pytest.mark.parametrize("score", [75, 19, 0, -3, 41.5, "ארבעים"])
def test_out_of_range_score_is_not_stored(db, score):
    r = log_lead(db, business_name="חצב קליניקה", total_score=score)
    lead = rows(db)[0]
    assert lead.total_score is None and lead.stage is None
    assert r["record_status"] == "needs_a_look"
    assert "out of range" in lead.notes


def test_out_of_range_average_is_dropped_and_the_rest_kept(db):
    log_lead(db, business_name="גפן נכסים", total_score=50, domain_averages={"finance": 3.4, "people": 2.5})
    lead = rows(db)[0]
    assert lead.finance_avg is None and lead.people_avg == 2.5 and lead.people_stage == "inspector"
    assert lead.total_score == 50 and "finance average 3.4 out of range" in lead.notes


def test_answer_outside_1_to_3_is_out_of_range(db):
    r = log_lead(db, business_name="זית מטבח", answers=dict(ALL_2, people=[2, 2, 2, 4]))
    assert r["record_status"] == "needs_a_look" and rows(db)[0].total_score is None
    assert "answers out of range" in rows(db)[0].notes


# --- rule 5: missing score ---------------------------------------------------

def test_missing_score_is_needs_a_look_with_no_stage(db):
    r = log_lead(db, business_name="שחר מפעלים בדיקה", industry="ייצור ותעשייה קלה", employees=40,
                 pains="תזרים לוחץ", deal_value="₪30,000")
    lead = rows(db)[0]
    assert r["action"] == "created" and r["record_status"] == "needs_a_look"
    assert lead.total_score is None and lead.stage is None
    assert lead.pipeline_status == "new" and lead.deal_value == 30000 and lead.origin == "chat"
    assert lead.fictional is False


# --- rule 6: one business is one row; fill-in; never overwrite -------------

@pytest.mark.parametrize("second_name", ['אופק הדרכות בע"מ', "אופק  הדרכות", "אופק הדרכות בע״מ.", "אופק (הדרכות)"])
def test_same_business_by_key_is_one_row(db, second_name):
    log_lead(db, business_name="אופק הדרכות", total_score=41)
    r = log_lead(db, business_name=second_name, total_score=41)
    assert r["action"] == "duplicate" and len(rows(db)) == 1


def test_same_source_ref_is_one_row_even_with_another_name(db):
    log_lead(db, business_name="ברוש פרסום", source_ref="img_abc", total_score=30)
    r = log_lead(db, business_name="ברוש פרסום ומדיה", source_ref="img_abc", total_score=30)
    assert r["action"] == "duplicate" and len(rows(db)) == 1


def test_diagnosis_fills_an_existing_lead_without_a_score(db):
    log_lead(db, business_name="תמר משפטים", industry="משרד עורכי דין", deal_value=20000)
    assert rows(db)[0].record_status == "needs_a_look"
    r = log_lead(db, business_name="תמר משפטים", total_score=29, industry="נדל\"ן", deal_value=99000)
    lead = rows(db)[0]
    assert r["action"] == "filled" and len(rows(db)) == 1
    assert lead.total_score == 29 and lead.stage == "firefighter" and lead.record_status == "logged"
    assert lead.industry == "משרד עורכי דין" and lead.deal_value == 20000  # non-diagnosis fields untouched


def test_existing_score_is_never_overwritten(db):
    log_lead(db, business_name="כרמל קבלנות", total_score=50, domain_averages={"finance": 2.5})
    r = log_lead(db, business_name="כרמל קבלנות", total_score=22, domain_averages={"finance": 1.0, "people": 1.0})
    lead = rows(db)[0]
    assert r["action"] == "duplicate"
    assert lead.total_score == 50 and lead.finance_avg == 2.5 and lead.people_avg is None


def test_fill_with_averages_only_keeps_needs_a_look(db):
    log_lead(db, business_name="לוטם סטודיו")
    r = log_lead(db, business_name="לוטם סטודיו", domain_averages={"systems": 1.2})
    lead = rows(db)[0]
    assert r["action"] == "filled" and lead.systems_avg == 1.2 and lead.record_status == "needs_a_look"


def test_nothing_new_for_an_unscored_lead_is_a_duplicate(db):
    log_lead(db, business_name="לוטם סטודיו")
    assert log_lead(db, business_name="לוטם סטודיו", industry="שיווק ופרסום")["action"] == "duplicate"


@pytest.mark.parametrize("name", ["", "   ", 'בע"מ', "Ltd."])
def test_empty_business_key_is_refused(db, name):
    r = log_lead(db, business_name=name, total_score=40)
    assert "error" in r and rows(db) == []


# --- rule 7: stages from app/stage.py, averages rounded --------------------

def test_stages_come_from_app_stage_with_rounding(db):
    log_lead(db, business_name="רימון מרפאה", total_score=47, domain_averages={"strategy": 1.65, "finance": 2.35})
    lead = rows(db)[0]
    assert lead.stage == "inspector"
    assert lead.strategy_avg == 1.7 and lead.strategy_stage == "builder"
    assert lead.finance_avg == 2.4 and lead.finance_stage == "inspector"


# --- other fields -------------------------------------------------------------

@pytest.mark.parametrize("raw, value", [("₪25,000", 25000), (18000.0, 18000), ("30k", 30000), ("40 אלף", 40000),
                                        ("unknown", None), (0, None), (-5, None), (None, None), ("-2000", None)])
def test_parse_money(raw, value):
    assert parse_money(raw) == value


def test_bad_status_and_employees_are_noted_not_stored(db):
    log_lead(db, business_name="יובל שיפוצים", total_score=35, pipeline_status="hot", employees=-4,
             lead_date="not a date")
    lead = rows(db)[0]
    assert lead.pipeline_status == "diagnosed" and lead.employees is None and lead.lead_date is not None
    assert "unknown pipeline status" in lead.notes and "employees" in lead.notes and "lead date" in lead.notes


# --- lookup_business ----------------------------------------------------------

def test_lookup_exact_and_similar(db):
    log_lead(db, business_name='אופק הדרכות בע"מ', total_score=41)
    exact = lookup_business(db, name="אופק הדרכות")
    assert exact["known"] is True and exact["matches"][0]["stage_he"] == "בנאי"
    similar = lookup_business(db, name="אופק")
    assert similar["known"] is False and similar["matches"]
    assert lookup_business(db, name="אין כזה עסק")["matches"] == []
    assert lookup_business(db, name="")["known"] is False


# --- leads_query ----------------------------------------------------------------

@pytest.fixture
def small(db):
    for name, score, industry, status, value, date in [
        ("א עסק", 25, "קמעונאות", "new", 30000, "2026-01-10"),
        ("ב עסק", 40, "קמעונאות", "contacted", 10000, "2026-01-20"),
        ("ג עסק", 50, "מסעדנות", "won", 60000, "2026-02-05"),
        ("ד עסק", None, "מסעדנות", "new", None, "2026-02-15"),
        ("ה עסק", 33, "מסעדנות", "proposal", 25000, "2026-03-01"),
    ]:
        log_lead(db, business_name=name, total_score=score, industry=industry, pipeline_status=status,
                 deal_value=value, lead_date=date)
    return db


def test_query_count_by_stage(small):
    r = leads_query(small, metric="count", group_by="stage")
    assert [(x["key"], x["count"], x["label_he"]) for x in r["rows"]] == [
        ("firefighter", 2, "כבאי"), ("builder", 1, "בנאי"), ("inspector", 1, "פקח"), ("none", 1, "ללא אבחון")]


def test_query_hot_waiting_and_sums(small):
    assert leads_query(small, metric="count", group_by="none", hot_only=True)["value"] == 3
    assert leads_query(small, metric="count", group_by="none", hot_only=True, waiting_only=True)["value"] == 1
    assert leads_query(small, metric="deal_value_sum", group_by="none")["value"] == 125000
    assert leads_query(small, metric="score_avg", group_by="none")["value"] == 37.0
    by_ind = leads_query(small, metric="count", group_by="industry", hot_only=True)
    assert by_ind["rows"][0] == {"key": "מסעדנות", "label_he": None, "value": 2, "count": 2}


def test_query_filters_month_and_list(small):
    months = leads_query(small, metric="count", group_by="month")
    assert [x["key"] for x in months["rows"]] == ["2026-01", "2026-02", "2026-03"]
    feb = leads_query(small, metric="count", group_by="none", date_from="2026-02-01", date_to="2026-02-28")
    assert feb["value"] == 2
    assert leads_query(small, metric="count", group_by="none", stage="כבאי")["value"] == 2
    listed = leads_query(small, metric="count", group_by="none", list_leads=True, top_n=2)
    assert [x["business_name"] for x in listed["leads"]] == ["ג עסק", "א עסק"]


def test_query_errors_are_returned_not_raised(small):
    assert "error" in leads_query(small, metric="revenue", group_by="none")
    assert "error" in leads_query(small, metric="count", group_by="branch")
    assert "error" in leads_query(small, metric="count", group_by="none", stage="דרקון")
    assert leads_query(small, metric="count", group_by="none", date_from="10/1/2026")["error"] == "dates must be YYYY-MM-DD"


def test_query_weakest_domain(db):
    log_lead(db, business_name="ו עסק", answers=dict(ALL_2, systems=[1, 1, 1, 1]))
    log_lead(db, business_name="ז עסק", answers=dict(ALL_2, finance=[1, 1, 1, 2], people=[1, 1, 1, 2]))
    r = leads_query(db, metric="count", group_by="weakest_domain")
    assert {x["key"]: x["count"] for x in r["rows"]} == {"systems": 1, "finance": 1, "people": 1}
    assert "tie" in r["note"]


# --- calculate_stage --------------------------------------------------------------

def test_calculate_stage():
    assert calculate_stage(total_score=33)["stage_he"] == "כבאי"
    assert calculate_stage(total_score=34)["stage_he"] == "בנאי"
    assert calculate_stage(domain_averages={"finance": 2.4})["domains"]["finance"]["stage_he"] == "פקח"
    assert calculate_stage(answers=ALL_2)["total_score"] == 40
    assert "error" in calculate_stage(total_score=75)
    assert "error" in calculate_stage()
    assert calculate_stage(total_score=47)["boundaries"]["total"]["פקח"] == "47-60"


# --- registry ------------------------------------------------------------------------

def test_registry_lists_the_four_tools_and_survives_bad_input(db):
    assert registry.TOOL_NAMES == {"leads_query", "lookup_business", "log_lead", "calculate_stage"}
    out = json.loads(registry.execute("leads_query", {"metric": "count", "group_by": "none", "bogus": 1}, db))
    assert "error" in out
    assert json.loads(registry.execute("log_invoice", {}, db))["error"] == "unknown tool 'log_invoice'"
    via_tool = json.loads(registry.execute("leads_query", {"metric": "count", "group_by": "none", "list": True}, db))
    assert via_tool["leads"] == []  # the tool's "list" reaches leads_query
    ok = json.loads(registry.execute("log_lead", {"business_name": "ח עסק", "total_score": 40}, db, user_id=None))
    assert ok["action"] == "created"
