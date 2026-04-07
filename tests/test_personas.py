from __future__ import annotations

from server.personas.registry import PERSONAS, default_persona_key


def test_default_persona_key() -> None:
    assert default_persona_key() == "forge"


def test_registry_forge_key() -> None:
    assert PERSONAS["forge"].key == "forge"
    assert PERSONAS["forge"].title


def test_persona_dataclass_fields() -> None:
    assert set(PERSONAS["forge"].__dataclass_fields__) == {"key", "name", "title", "actions"}


def test_siri_persona() -> None:
    p = PERSONAS["siri"]
    assert p.key == "siri"
    assert "general" in p.actions
