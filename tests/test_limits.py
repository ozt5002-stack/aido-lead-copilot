"""The three limits: per user per hour, per day in dollars, file size at the door."""
from app.db import Conversation, Message, Run, User
from app.limits import local_day_start_utc, messages_last_hour, spend_today_usd


def _user(db, name="Dana"):
    return db.query(User).filter_by(name=name).one()


def test_31st_message_in_the_hour_is_refused(client, db, logged_in, fake):
    user = _user(db)
    conv = Conversation(user_id=user.id, title="limits")
    db.add(conv)
    db.commit()
    before = messages_last_hour(db, user.id)
    for i in range(30 - before):
        db.add(Message(conversation_id=conv.id, user_id=user.id, role="user", content=f"m{i}"))
    db.commit()
    r = client.post("/api/chat", json={"message": "one more"})
    assert r.status_code == 429
    assert "limit is 30" in r.json()["detail"]
    # clean up so later tests are not rate limited
    db.query(Message).filter_by(conversation_id=conv.id).delete()
    db.commit()


def test_daily_cap_stops_the_app(client, db, logged_in, fake):
    user = _user(db)
    db.add(Run(user_id=user.id, model="fake", status="ok", cost_usd=1.50))
    db.commit()
    assert spend_today_usd(db) >= 1.0
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 402
    assert "Back tomorrow" in r.json()["detail"]
    db.query(Run).filter(Run.cost_usd == 1.50).delete()
    db.commit()


def test_oversized_image_is_refused(client, db, logged_in, fake):
    big = "A" * (6 * 1024 * 1024)  # ~4.5 MB decoded... make it clearly over 5 MB
    big = "A" * (8 * 1024 * 1024)
    r = client.post("/api/chat", json={"message": "meeting notes", "image": {"media_type": "image/png", "data": big}})
    assert r.status_code == 413


def test_day_start_is_midnight_in_business_timezone():
    start = local_day_start_utc()
    assert start.tzinfo is None
    # Asia/Jerusalem is UTC+2 or UTC+3, so local midnight is 21:00 or 22:00 UTC the day before.
    assert start.hour in (21, 22)
