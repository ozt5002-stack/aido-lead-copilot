"""The morning digest: new = chat rows from the local yesterday only, hot-and-waiting, spend. Own empty database."""
from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.db import Lead, Message, Run, User, Conversation, business_key, init_db, make_engine, seed_leads
from app.digest import build_digest

DAY = date(2026, 7, 15)  # summer: Israel is UTC+3, so the local day is 2026-07-14 21:00 to 2026-07-15 21:00 UTC


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'digest.db'}")
    init_db(engine, data_dir=tmp_path)  # empty leads table
    with Session(engine) as s:
        yield s


def lead(db, name, *, origin="chat", created=datetime(2026, 7, 15, 9, 0), status="new", value=None,
         record="logged", stage="builder", score=40):
    db.add(Lead(business_name=name, business_key=business_key(name), origin=origin, created_at=created,
                pipeline_status=status, deal_value=value, record_status=record, stage=stage, total_score=score,
                fictional=origin == "seed"))
    db.commit()


def line(text, prefix):
    return next(l for l in text.split("\n") if l.startswith(prefix))


def test_only_chat_rows_from_the_local_day_count_as_new(db):
    lead(db, "א חדש", created=datetime(2026, 7, 15, 9, 0))
    lead(db, "ב בלילה", created=datetime(2026, 7, 14, 22, 30))   # 01:30 local on the 15th: counts
    lead(db, "ג מוקדם", created=datetime(2026, 7, 14, 20, 30))   # 23:30 local on the 14th: does not
    lead(db, "ד מאוחר", created=datetime(2026, 7, 15, 21, 30))   # 00:30 local on the 16th: does not
    lead(db, "ה בדיוני", origin="seed", created=datetime(2026, 7, 15, 9, 0))  # seeded: never new
    text = build_digest(db, DAY)
    new = line(text, "לידים חדשים אתמול:")
    assert new.startswith("לידים חדשים אתמול: 2")
    assert "א חדש" in new and "ב בלילה" in new
    assert "ג מוקדם" not in text and "ד מאוחר" not in text and "ה בדיוני" not in text


def test_the_full_seed_is_never_counted_as_new(db):
    from pathlib import Path

    seed_leads(db, Path(__file__).resolve().parent.parent / "data" / "leads.csv")
    db.query(Lead).update({Lead.created_at: datetime(2026, 7, 15, 9, 0)})  # inside DAY: only the origin filter keeps them out
    db.commit()
    assert line(build_digest(db, DAY), "לידים חדשים אתמול:") == "לידים חדשים אתמול: אין"


def test_a_seeded_lead_filled_in_by_chat_is_not_new(db):
    from app.tools.leads import log_lead

    lead(db, "ז מהזרע", origin="seed", created=datetime(2026, 1, 1), stage=None, score=None)
    assert log_lead(db, business_name="ז מהזרע", total_score=40)["action"] == "filled"
    assert line(build_digest(db, DAY), "לידים חדשים אתמול:") == "לידים חדשים אתמול: אין"


@pytest.mark.parametrize("day, inside, outside", [
    # winter, UTC+2: the local day is 22:00 to 22:00 UTC
    (date(2026, 1, 15), [datetime(2026, 1, 14, 22, 30)], [datetime(2026, 1, 14, 21, 30), datetime(2026, 1, 15, 22, 30)]),
    # 2026-03-27, clocks go forward at 02:00 local: the day starts at 22:00 UTC and ends at 21:00 UTC (23 hours)
    (date(2026, 3, 27), [datetime(2026, 3, 26, 22, 30), datetime(2026, 3, 27, 20, 30)],
     [datetime(2026, 3, 26, 21, 30), datetime(2026, 3, 27, 21, 30)]),
    # 2026-10-25, clocks go back at 02:00 local: the day starts at 21:00 UTC and ends at 22:00 UTC (25 hours)
    (date(2026, 10, 25), [datetime(2026, 10, 24, 21, 30), datetime(2026, 10, 25, 21, 30)],
     [datetime(2026, 10, 24, 20, 30), datetime(2026, 10, 25, 22, 30)]),
])
def test_local_day_in_winter_and_on_clock_change_days(db, day, inside, outside):
    for i, when in enumerate(inside):
        lead(db, f"בפנים {i}", created=when)
    for i, when in enumerate(outside):
        lead(db, f"בחוץ {i}", created=when)
    new = line(build_digest(db, day), "לידים חדשים אתמול:")
    assert new.startswith(f"לידים חדשים אתמול: {len(inside)}")
    assert "בחוץ" not in new


def test_needs_a_look_is_named(db):
    lead(db, "ו בלי ציון", record="needs_a_look", stage=None, score=None)
    text = build_digest(db, DAY)
    assert "(אחד מהם צריך בדיקה)" in text
    assert line(text, "צריכים בדיקה:") == "צריכים בדיקה: ו בלי ציון"
    assert "ו בלי ציון (ללא אבחון)" in text


def test_hot_and_waiting(db):
    old = datetime(2026, 1, 1)
    lead(db, "חם ממתין גדול", origin="seed", created=old, status="new", value=60000)
    lead(db, "חם ממתין", origin="seed", created=old, status="contacted", value=25000)  # exactly the threshold
    lead(db, "חם אבל נסגר", origin="seed", created=old, status="won", value=90000)
    lead(db, "ממתין אבל קר", origin="seed", created=old, status="new", value=24999)
    lead(db, "ממתין בלי שווי", origin="seed", created=old, status="contacted", value=None)
    hot = line(build_digest(db, DAY), "לידים חמים שמחכים לטיפול:")
    assert hot.startswith("לידים חמים שמחכים לטיפול: 2 · ")
    assert hot.index("חם ממתין גדול ₪60,000 (חדש)") < hot.index("חם ממתין ₪25,000 (נוצר קשר)")
    assert "נסגר" not in hot and "קר" not in hot and "בלי שווי" not in hot


def test_spend_and_failed_runs_for_the_day(db):
    user = User(name="עוז")
    db.add(user)
    db.commit()
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    in_day, out_of_day = datetime(2026, 7, 15, 8, 0), datetime(2026, 7, 13, 8, 0)
    db.add_all([Message(conversation_id=conv.id, user_id=user.id, role="user", content="x", created_at=in_day),
                Message(conversation_id=conv.id, user_id=user.id, role="assistant", content="y", created_at=in_day),
                Message(conversation_id=conv.id, user_id=user.id, role="user", content="z", created_at=out_of_day),
                Run(model="m", status="ok", cost_usd=0.12, created_at=in_day),
                Run(model="m", status="error", cost_usd=0.03, created_at=in_day),
                Run(model="m", status="ok", cost_usd=5.0, created_at=out_of_day)])
    db.commit()
    text = build_digest(db, DAY)
    assert "צ'אט: 1 הודעות · 2 ריצות מודל · $0.15 מתוך תקרה של $" in text
    assert line(text, "ריצות לא תקינות").startswith("ריצות לא תקינות (שגיאה, סירוב או ניתוק): 1 · ")


def test_empty_day_says_so(db):
    text = build_digest(db, DAY)
    assert text.split("\n")[0] == "AIDO Lead Copilot · סיכום בוקר ל-15.07.2026"
    assert "לידים חדשים אתמול: אין" in text and "לידים חמים שמחכים לטיפול: אין" in text
    assert line(text, "ריצות לא תקינות") == "ריצות לא תקינות (שגיאה, סירוב או ניתוק): 0"


def test_more_than_five_are_counted_not_silently_cut(db):
    for i in range(7):
        lead(db, f"עסק {i}")
        lead(db, f"חם {i}", origin="seed", created=datetime(2026, 1, 1), value=30000 + i)
    text = build_digest(db, DAY)
    assert line(text, "לידים חדשים אתמול:").endswith(" ועוד 2")
    assert line(text, "לידים חמים שמחכים לטיפול:").endswith(" ועוד 2")
