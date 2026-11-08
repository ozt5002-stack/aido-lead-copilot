"""Session tokens (app/auth.py): a token made at login must read back on the next request."""
import base64

from app import auth


def test_session_token_round_trips_for_every_second(monkeypatch):
    # The expiry is a whole second, so 1,000 consecutive seconds give 1,000 different
    # signatures; about one raw HMAC digest in nine contains the byte '|' (ticket 25).
    start = 1_800_000_000
    for offset in range(1000):
        monkeypatch.setattr(auth.time, "time", lambda: start + offset)
        assert auth.read_token(auth.make_token(1, "Dana")) == (1, "Dana"), f"rejected at second {offset}"


def test_tampered_token_is_rejected():
    payload, sig = base64.urlsafe_b64decode(auth.make_token(1, "Dana")).rsplit(b"|", 1)

    def encode(p: bytes, s: bytes) -> str:
        return base64.urlsafe_b64encode(p + b"|" + s).decode()

    other_user = payload.replace(b"1|", b"2|", 1)  # claims user 2 under user 1's signature
    flipped = sig[:-1] + (b"0" if sig[-1:] != b"0" else b"1")
    assert auth.read_token(encode(payload, sig)) == (1, "Dana")
    assert auth.read_token(encode(other_user, sig)) is None
    assert auth.read_token(encode(payload, flipped)) is None
    assert auth.read_token("not-a-token") is None


def test_me_answers_null_not_401_when_signed_out(client):
    # Plan task 6: the page's boot check must not log a 401 in the console.
    client.cookies.clear()
    r = client.get("/api/me")
    assert r.status_code == 200 and r.json() is None
    assert client.get("/api/conversations").status_code == 401  # the rest of the API still needs a session
    client.cookies.set("bc_session", "forged")  # a cookie that does not verify
    assert client.get("/api/me").json() is None


def test_me_returns_the_user_when_signed_in(client):
    client.cookies.clear()
    assert client.post("/api/login", json={"name": "עוז", "password": "test-pass"}).status_code == 200
    assert client.get("/api/me").json()["name"] == "עוז"


def test_me_is_null_when_the_cookie_points_at_a_deleted_user(client):
    from app import auth

    client.cookies.clear()
    client.cookies.set("bc_session", auth.make_token(99999, "x"))  # signed correctly, but no such user row
    assert client.get("/api/me").json() is None
    assert client.get("/api/conversations").status_code == 401
