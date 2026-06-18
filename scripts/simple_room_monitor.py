#!/usr/bin/env python3
"""
simple-room-monitor — stream new lines from a room to stdout.

Usage:
    simple-room-monitor <room> [-a AGENT] [--exclude-self|--no-exclude-self]
                              [-b N] [--grep PATTERN] [--json]
                              [--on-rotation CMD]

* Filters out records from AGENT (the "self" agent) by default.
* --backfill N emits the last N existing records before going live
  (default 0; -1 means "all").
* --grep PATTERN additionally filters by regex against the rendered line.
* --json prints the raw JSON record (one per line); otherwise prints a
  human line: "HH:MM:SS alice: hello".
* Runs until killed. Designed to be used as the `command` of a Monitor.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from simple_agent_room_lib import (
    default_agent,
    inotify_follow,
    iter_records,
    room_path,
    valid_agent,
)


def _format_human(rec: dict) -> str:
    ts = rec.get("ts", "")
    if isinstance(ts, str) and len(ts) >= 19:
        ts = ts[11:19]
    agent = rec.get("agent", "?")
    msg = rec.get("msg", "")
    kind = rec.get("kind", "msg")
    if kind != "msg":
        return f"{ts} [{kind}] {agent}: {msg}"
    return f"{ts} {agent}: {msg}"


def _tail_records(p: Path, n: int) -> list[dict]:
    if n == 0:
        return []
    out: list[dict] = []
    for rec in iter_records(p):
        out.append(rec)
        if len(out) > 50_000:  # safety cap for "all"
            out = out[-n:] if n > 0 else out
    if n > 0:
        return out[-n:]
    return out  # n == -1 → all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="simple-room-monitor",
        description="Stream new records from a simple-agent-room to stdout.",
    )
    ap.add_argument("room", help="room name")
    ap.add_argument(
        "-a",
        "--agent",
        default=None,
        help="local agent id for self-filter (default: $SIMPLE_AGENT_ID else $USER)",
    )
    excl = ap.add_mutually_exclusive_group()
    excl.add_argument(
        "--exclude-self",
        dest="exclude_self",
        action="store_true",
        default=True,
        help="drop records from local agent (default: on)",
    )
    excl.add_argument(
        "--no-exclude-self",
        dest="exclude_self",
        action="store_false",
        help="include records from local agent",
    )
    ap.add_argument(
        "-b",
        "--backfill",
        type=int,
        default=0,
        help="emit last N existing records before going live (-1 = all)",
    )
    ap.add_argument(
        "--grep",
        default=None,
        help="regex; only emit records whose rendered line matches",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="emit the raw JSON record per line (else human format)",
    )
    ap.add_argument(
        "--on-rotation",
        default=None,
        help="ignored for now (reserved for future log-rotation hooks)",
    )
    args = ap.parse_args(argv)

    agent = args.agent or default_agent()
    if not valid_agent(agent):
        print(
            f"simple-room-monitor: invalid agent id {agent!r}",
            file=sys.stderr,
        )
        return 2

    p = room_path(args.room)
    grep_re = re.compile(args.grep) if args.grep else None

    def emit(line: str) -> None:
        if not line or line.startswith("#"):
            return
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return
        if args.exclude_self and rec.get("agent") == agent:
            return
        if grep_re is not None:
            rendered = (
                json.dumps(rec, ensure_ascii=False)
                if args.json
                else _format_human(rec)
            )
            if not grep_re.search(rendered):
                return
        out = (
            json.dumps(rec, ensure_ascii=False)
            if args.json
            else _format_human(rec)
        )
        sys.stdout.write(out + "\n")
        sys.stdout.flush()

    # 1) backfill (if any)
    for rec in _tail_records(p, args.backfill):
        if args.exclude_self and rec.get("agent") == agent:
            continue
        rendered = (
            json.dumps(rec, ensure_ascii=False)
            if args.json
            else _format_human(rec)
        )
        if grep_re is not None and not grep_re.search(rendered):
            continue
        sys.stdout.write(rendered + "\n")
    sys.stdout.flush()

    # 2) live
    try:
        inotify_follow(p, on_line=emit)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
