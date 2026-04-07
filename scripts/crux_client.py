#!/usr/bin/env python3
"""Optional dev helper: same HTTP as curl (see CONTRIBUTING.md). Rules use curl, not this file.

Environment (optional):
  CRUX_BASE_URL   default http://127.0.0.1:9090
  CRUX_INTERNAL_SECRET  for hourly-decision (must match server; server loads from its .env)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:9090"


def base_url() -> str:
    return os.environ.get("CRUX_BASE_URL", DEFAULT_BASE).rstrip("/")


def http_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 120.0,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | str]:
    url = base_url() + path
    headers: dict[str, str] = {}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace") if e.fp else ""
        print(err_body or str(e), file=sys.stderr)
        code = e.code if isinstance(e.code, int) and e.code > 0 else 1
        sys.exit(code)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        print(f"crux_client: cannot reach {base_url()}: {reason}", file=sys.stderr)
        print(
            "hint: start Crux or set CRUX_BASE_URL; without server use plain git/gh",
            file=sys.stderr,
        )
        sys.exit(2)


def cmd_health(_: argparse.Namespace) -> None:
    status, data = http_request("GET", "/health", body=None, timeout=15.0)
    print(json.dumps(data, indent=2))
    if status >= 400:
        sys.exit(1)


def cmd_speak(args: argparse.Namespace) -> None:
    """Delegates to scripts/speak.sh so all speech goes through one client (see speak skill)."""
    script = Path(__file__).resolve().parent / "speak.sh"
    cmd: list[str] = ["bash", str(script)]
    if args.sync:
        cmd.append("--sync")
    cmd.append(args.text)
    cmd.append("1" if args.priority else "0")
    if args.persona:
        cmd.append(args.persona)
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        sys.exit(r.returncode)


def cmd_git_status(_: argparse.Namespace) -> None:
    _, data = http_request("GET", "/git/status", body=None, timeout=30.0)
    print(json.dumps(data, indent=2))


def cmd_git_commit(args: argparse.Namespace) -> None:
    body = {"message": args.message or "chore: checkpoint"}
    _, data = http_request("POST", "/git/commit", body=body, timeout=60.0)
    print(json.dumps(data, indent=2))


def cmd_git_review(args: argparse.Namespace) -> None:
    src = Path(args.diff_file) if args.diff_file != "-" else None
    if src is not None:
        diff = src.read_text(encoding="utf-8", errors="replace")
    else:
        diff = sys.stdin.read()
    if not diff.strip():
        print("crux_client: empty diff", file=sys.stderr)
        sys.exit(1)
    _, data = http_request("POST", "/git/review", body={"diff": diff}, timeout=180.0)
    print(json.dumps(data, indent=2))


def cmd_git_mr(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"title": args.title, "body": args.body}
    if args.base:
        body["base"] = args.base
    _, data = http_request("POST", "/git/mr", body=body, timeout=120.0)
    print(json.dumps(data, indent=2))


def cmd_llm_chat(args: argparse.Namespace) -> None:
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    body = json.loads(raw)
    _, data = http_request("POST", "/llm/chat", body=body, timeout=300.0)
    print(json.dumps(data, indent=2))


def cmd_hourly_decision(args: argparse.Namespace) -> None:
    secret = (os.environ.get("CRUX_INTERNAL_SECRET") or "").strip()
    if not secret:
        print(
            "crux_client: set CRUX_INTERNAL_SECRET in your environment for this command",
            file=sys.stderr,
        )
        sys.exit(3)
    _, data = http_request(
        "POST",
        "/internal/hourly-decision",
        body={"decision": args.decision.strip().lower()},
        timeout=30.0,
        extra_headers={"X-Crux-Secret": secret},
    )
    print(json.dumps(data, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Crux HTTP client (stdlib only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("health", help="GET /health")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("speak", help="runs scripts/speak.sh (server /speak or /speak-async)")
    sp.add_argument("text", help="Plain English only (see rule 050)")
    sp.add_argument("--persona", default=None)
    sp.add_argument("--priority", action="store_true")
    sp.add_argument(
        "--sync",
        action="store_true",
        help="use /speak and wait for playback (default is /speak-async)",
    )
    sp.set_defaults(func=cmd_speak)

    sp = sub.add_parser("git-status", help="GET /git/status")
    sp.set_defaults(func=cmd_git_status)

    sp = sub.add_parser("git-commit", help="POST /git/commit (add -A + commit on server cwd)")
    sp.add_argument("-m", "--message", default=None)
    sp.set_defaults(func=cmd_git_commit)

    sp = sub.add_parser("git-review", help="POST /git/review (diff from file or stdin)")
    sp.add_argument(
        "diff_file",
        nargs="?",
        default="-",
        help="file path or - for stdin (default stdin)",
    )
    sp.set_defaults(func=cmd_git_review)

    sp = sub.add_parser("git-mr", help="POST /git/mr (runs gh pr create on server)")
    sp.add_argument("--title", required=True)
    sp.add_argument("--body", required=True)
    sp.add_argument("--base", default=None)
    sp.set_defaults(func=cmd_git_mr)

    sp = sub.add_parser("llm-chat", help="POST /llm/chat (JSON body from --file or stdin)")
    sp.add_argument("-f", "--file", default=None)
    sp.set_defaults(func=cmd_llm_chat)

    sp = sub.add_parser(
        "hourly-decision",
        help="POST /internal/hourly-decision (needs CRUX_INTERNAL_SECRET)",
    )
    sp.add_argument("decision", help="yes or no")
    sp.set_defaults(func=cmd_hourly_decision)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
