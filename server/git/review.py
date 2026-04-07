from __future__ import annotations

import json
import re

import structlog

from server.llm.router import chat

log = structlog.get_logger(__name__)

SENTINEL_SYSTEM = (
    "You are Sentinel, a senior code reviewer. Given a git diff, respond with ONLY valid JSON:\n"
    '{"issues": [{"severity": "low|medium|high", "file": "path or unknown", '
    '"summary": "plain English"}],\n'
    ' "score": 0-100,\n'
    ' "summary": "one short paragraph plain English"}\n'
    "No markdown, no code fences."
)


async def review_diff(diff: str) -> dict:
    diff = diff[:120000]
    raw = await chat(
        f"Review this diff:\n\n{diff}",
        system=SENTINEL_SYSTEM,
        source="git_review",
    )
    text = raw.get("response", "")
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group())
    except json.JSONDecodeError:
        log.warning("review_json_parse_failed", snippet=text[:200])
    return {
        "issues": [{"severity": "low", "file": "unknown", "summary": text[:500]}],
        "score": 70,
        "summary": text[:2000] or "No summary.",
    }
