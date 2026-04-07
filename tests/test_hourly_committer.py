from __future__ import annotations

import asyncio

import pytest

from server.daemons.committer import HourlyDecisionBox

pytestmark = pytest.mark.asyncio


async def test_hourly_box_yes() -> None:
    box = HourlyDecisionBox()
    box.reset()

    async def submit_later() -> None:
        await asyncio.sleep(0.05)
        box.submit("yes")

    t = asyncio.create_task(submit_later())
    d = await box.wait(2.0)
    await t
    assert d == "yes"


async def test_hourly_box_timeout() -> None:
    box = HourlyDecisionBox()
    box.reset()
    d = await box.wait(0.05)
    assert d == "timeout"
