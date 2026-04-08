from server.routes.whatsapp import _user_asks_action_plan, _user_wants_voice


def test_asks_action_plan_natural_language() -> None:
    assert _user_asks_action_plan("tell me my action plan")
    assert _user_asks_action_plan("what do I have today")
    assert _user_asks_action_plan("show me the full plan")
    assert _user_asks_action_plan("action plan please")
    assert _user_asks_action_plan("what's on my list")
    assert not _user_asks_action_plan("/action")
    assert not _user_asks_action_plan("8 done")


def test_wants_voice_keywords() -> None:
    assert _user_wants_voice("speak it")
    assert _user_wants_voice("talk to me")
    assert _user_wants_voice("read the plan aloud")
    assert _user_wants_voice("tell me my action plan with voice")
    assert not _user_wants_voice("perfect")
    assert not _user_wants_voice("tell me my action plan")
