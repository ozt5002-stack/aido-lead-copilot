"""app/stage.py: the stage boundaries, the rounding, and the port against score.js's own outputs."""
import json
from pathlib import Path

import pytest

from app.stage import STAGE_HE, StageError, round1, score_business, stage_for_average, stage_for_total

CASES = json.loads((Path(__file__).parent / "fixtures" / "score_js_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("total, stage", [(20, "firefighter"), (33, "firefighter"), (34, "builder"),
                                          (46, "builder"), (47, "inspector"), (60, "inspector")])
def test_total_boundaries(total, stage):
    assert stage_for_total(total) == stage


@pytest.mark.parametrize("total", [19, 61, 0, -5, 75, 41.5, "41", None, True, float("nan"), float("inf"), 1e308])
def test_total_out_of_range_or_not_a_whole_number(total):
    with pytest.raises(StageError):
        stage_for_total(total)


@pytest.mark.parametrize("average, stage", [(1.0, "firefighter"), (1.6, "firefighter"), (1.7, "builder"),
                                            (2.3, "builder"), (2.4, "inspector"), (3.0, "inspector")])
def test_average_boundaries(average, stage):
    assert stage_for_average(average) == stage


@pytest.mark.parametrize("average, stage", [(1.65, "builder"), (1.64, "firefighter"),
                                            (2.35, "inspector"), (2.34, "builder")])
def test_average_is_rounded_to_one_decimal_before_the_cutoffs(average, stage):
    assert stage_for_average(average) == stage


@pytest.mark.parametrize("average", [0.9, 0.95, 3.04, 3.1, 3.4, -1, None, "2", float("nan"), float("inf"), 1e308])
def test_average_out_of_range(average):
    with pytest.raises(StageError):
        stage_for_average(average)


def test_rounding_is_half_up_like_javascript():
    # Python's round(2.25, 1) is 2.2; Math.round(22.5) / 10 is 2.3.
    assert round1(2.25) == 2.3
    assert round1(1.75) == 1.8
    assert round1(1.25) == 1.3
    assert round1(1.5) == 1.5


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_port_matches_score_js(case):
    expected = case["expected"]
    if "error" in expected:
        with pytest.raises(StageError) as err:
            score_business(case["answers"])
        assert str(err.value) == expected["error"]
        return
    got = score_business(case["answers"])
    assert got["total"] == expected["total"]
    assert got["max"] == expected["max"]
    assert got["stage"] == expected["stage"]
    assert [(d["id"], d["name"], d["sum"], d["average"], d["stage"]) for d in got["domains"]] == \
           [(d["id"], d["name"], d["sum"], d["average"], d["stage"]) for d in expected["domains"]]


def test_fixture_covers_the_lesson8_examples_and_the_boundaries():
    totals = {c["expected"].get("total") for c in CASES}
    assert {20, 33, 34, 46, 47, 60} <= totals
    assert sum(1 for c in CASES if "error" in c["expected"]) >= 3
    assert sum(1 for c in CASES if "תרגיל הכיתה" in c["name"]) == 3


def test_hebrew_stage_names():
    assert STAGE_HE == {"firefighter": "כבאי", "builder": "בנאי", "inspector": "פקח"}
    result = score_business({d: [2, 2, 2, 2] for d in ["strategy", "management", "systems", "people", "finance"]})
    assert result["stage_he"] == "בנאי"
    assert all(d["stage_he"] == "בנאי" for d in result["domains"])


def test_bool_is_not_an_answer():
    answers = {d: [1, 1, 1, 1] for d in ["strategy", "management", "systems", "people", "finance"]}
    answers["people"] = [True, 1, 1, 1]
    with pytest.raises(StageError):
        score_business(answers)


def test_whole_floats_from_json_are_accepted():
    # The model's JSON may send 41.0 or an answer of 2.0; they mean 41 and 2.
    assert stage_for_total(41.0) == "builder"
    answers = {d: [2.0, 2, 2, 2] for d in ["strategy", "management", "systems", "people", "finance"]}
    result = score_business(answers)
    assert result["total"] == 40 and isinstance(result["total"], int)


def test_fractional_answer_is_rejected():
    answers = {d: [1, 1, 1, 1] for d in ["strategy", "management", "systems", "people", "finance"]}
    answers["finance"] = [1.5, 1, 1, 1]
    with pytest.raises(StageError):
        score_business(answers)
