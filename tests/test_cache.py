from __future__ import annotations

from server.llm.cache import prompt_fingerprint


def test_prompt_fingerprint_stable() -> None:
    a = prompt_fingerprint("sys", "p")
    b = prompt_fingerprint("sys", "p")
    assert a == b
    assert len(a) == 32
