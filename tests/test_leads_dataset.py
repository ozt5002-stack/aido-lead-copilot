"""The fictional leads dataset: deterministic, in range, stages from app/stage.py, and seeded at start."""
import csv
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import PIPELINE_STATUSES, Lead, business_key
from app.stage import DOMAIN_IDS, stage_for_average, stage_for_total
from scripts import generate_leads

CSV = Path(__file__).resolve().parent.parent / "data" / "leads.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8", newline="")))


def test_generator_is_deterministic_and_matches_the_committed_file():
    first = generate_leads.to_csv(generate_leads.generate())
    second = generate_leads.to_csv(generate_leads.generate())
    assert first == second
    assert CSV.read_bytes() == first.encode("utf-8"), "data/leads.csv was edited by hand or not regenerated"


def test_a_different_seed_gives_a_different_file():
    assert generate_leads.generate(seed=1) != generate_leads.generate()


def test_size_and_columns():
    assert len(ROWS) == generate_leads.ROWS == 300
    assert list(ROWS[0].keys()) == generate_leads.COLUMNS


def test_every_row_is_marked_fictional():
    assert {r["fictional"] for r in ROWS} == {"true"}


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["lead_date"])
def test_row_in_range_and_stage_from_app_stage(row):
    assert 1 <= int(row["employees"]) <= 400
    assert generate_leads.FIRST_DAY.isoformat() <= row["lead_date"] <= generate_leads.LAST_DAY.isoformat()
    assert row["pipeline_status"] in PIPELINE_STATUSES
    assert row["industry"] in generate_leads.INDUSTRIES
    if row["deal_value"]:
        assert 1000 <= int(row["deal_value"]) <= 200_000
    if row["total_score"]:
        total = int(row["total_score"])
        assert 20 <= total <= 60
        assert row["stage"] == stage_for_total(total)
        for d in DOMAIN_IDS:
            avg = float(row[f"{d}_avg"])
            assert 1.0 <= avg <= 3.0
            assert row[f"{d}_stage"] == stage_for_average(avg)
    else:
        assert row["stage"] == ""
        assert all(row[f"{d}_avg"] == "" and row[f"{d}_stage"] == "" for d in DOMAIN_IDS)
        assert row["pipeline_status"] in ("new", "contacted", "meeting")


def test_the_mix_looks_like_real_work():
    stages = Counter(r["stage"] for r in ROWS)
    assert stages[""] >= 20, "some leads have no diagnosis yet"
    assert all(stages[s] >= 10 for s in ("firefighter", "builder", "inspector"))
    assert set(PIPELINE_STATUSES) <= {r["pipeline_status"] for r in ROWS}
    hot_waiting = [r for r in ROWS if r["deal_value"] and int(r["deal_value"]) >= 25000
                   and r["pipeline_status"] in ("new", "contacted")]
    assert hot_waiting, "the digest needs some hot leads that are waiting"


def test_business_names_are_unique_by_key():
    keys = [business_key(r["business_name"]) for r in ROWS]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("a, b", [
    ('אופק חנויות בע"מ', "אופק חנויות"),
    ("אופק חנויות בע״מ", "אופק  חנויות"),
    ("אופק חנויות בעמ", "אופק חנויות."),
    ("Ofek Stores Ltd.", "ofek stores"),
    ('נחל עו"ד', "נחל עו״ד"),
])
def test_business_key_treats_spellings_as_the_same_business(a, b):
    assert business_key(a) == business_key(b)


def test_business_key_keeps_different_businesses_apart():
    assert business_key("אופק חנויות") != business_key("אופק מרכולים")
    assert business_key("") == ""


def test_seeded_into_the_database_at_start(client, db):
    assert db.scalar(select(func.count()).select_from(Lead).where(Lead.origin == "seed")) == 300
    first = db.scalar(select(Lead).where(Lead.business_key == business_key(ROWS[0]["business_name"])))
    assert first is not None and first.fictional is True
    assert client.app.state.init_report["leads_seeded"] in (0, 300)
