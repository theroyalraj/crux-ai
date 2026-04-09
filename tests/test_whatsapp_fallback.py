from server.routes.whatsapp import _fallback_reply_text


def test_fallback_positive_ack() -> None:
    t = _fallback_reply_text("perfect")
    assert "Noted" in t
    assert "/action" in t


def test_fallback_thanks() -> None:
    t = _fallback_reply_text("thanks")
    assert "Got it" in t


def test_fallback_unknown() -> None:
    t = _fallback_reply_text("hello world")
    low = t.lower()
    assert "action plan" in low or "/action" in low
