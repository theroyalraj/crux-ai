"""_parse_mark_done_numbers for inbound WhatsApp."""

from server.routes.whatsapp import _parse_mark_done_numbers


def test_parse_digits_only() -> None:
    assert _parse_mark_done_numbers("8") == [8]
    assert _parse_mark_done_numbers("1 3 5") == [1, 3, 5]


def test_parse_with_done_suffix() -> None:
    assert _parse_mark_done_numbers("8 done") == [8]
    assert _parse_mark_done_numbers("1 2 done") == [1, 2]
    assert _parse_mark_done_numbers("done 3") == [3]


def test_parse_mark_prefix() -> None:
    assert _parse_mark_done_numbers("mark 4") == [4]
    assert _parse_mark_done_numbers("mark 1 2 done") == [1, 2]


def test_parse_rejects_free_text() -> None:
    assert _parse_mark_done_numbers("hello") is None
    assert _parse_mark_done_numbers("Performance Cycle FY'26") is None
