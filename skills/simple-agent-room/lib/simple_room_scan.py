#!/usr/bin/env python3
"""
simple-room-scan — read-only queries against a simple-agent-room.

Usage:
    simple-room-scan <room> count
    simple-room-scan <room> ids
    simple-room-scan <room> path
    simple-room-scan <room> active [--window SECONDS]
    simple-room-scan <room> tail [-n N] [-a AGENT] [--json]
    simple-room-scan <room> grep <pattern> [--since-seq N] [--json] [--agent A]

Subcommands are positional for easy scripting (e.g. in shell for-loops).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from simple_agent_room_lib import (
    active_agents,
    iter_records,
    record_count,
    room_path,
)


# ---------------------------------------------------------------------------
# subcommand impls
# ---------------------------------------------------------------------------


def cmd_count(args: argparse.Namespace) -> int:
    p = room_path(args.room)
    print(record_count(p))
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    print(room_path(args.room))
    return 0


def cmd_ids(args: argparse.Namespace) -> int:
    p = room_path(args.room)
    seen: set[str] = set()
    for rec in iter_records(p):
        a = rec.get("agent")
        if isinstance(a, str):
            seen.add(a)
    for a in sorted(seen):
        print(a)
    return 0


def cmd_active(args: argparse.Namespace) -> int:
    p = room_path(args.room)
    agents = active_agents(p, args.window)
    # Sort by ts desc; print "agent  ts".
    for agent, ts in sorted(agents.items(), key=lambda kv: kv[1], reverse=True):
        print(f"{agent}\t{ts}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    p = room_path(args.room)
    buf: list[dict] = []
    for rec in iter_records(p):
        if args.agent and rec.get("agent") != args.agent:
            continue
        buf.append(rec)
    if args.n is not None and args.n >= 0:
        buf = buf[-args.n:] if args.n else []
    for rec in buf:
        if args.json:
            print(json.dumps(rec, ensure_ascii=False))
        else:
            ts = rec.get("ts", "")
            if isinstance(ts, str) and len(ts) >= 19:
                ts = ts[11:19]
            print(f"{ts} {rec.get('agent','?')}: {rec.get('msg','')}")
    return 0


def cmd_grep(args: argparse.Namespace) -> int:
    p = room_path(args.room)
    pat = re.compile(args.pattern)
    matched = 0
    for rec in iter_records(p):
        if args.agent and rec.get("agent") != args.agent:
            continue
        msg = rec.get("msg", "")
        if not isinstance(msg, str) or not pat.search(msg):
            continue
        if isinstance(args.since_seq, int) and isinstance(rec.get("seq"), int):
            if rec["seq"] < args.since_seq:
                continue
        if args.json:
            print(json.dumps(rec, ensure_ascii=False))
        else:
            ts = rec.get("ts", "")
            if isinstance(ts, str) and len(ts) >= 19:
                ts = ts[11:19]
            print(f"{ts} {rec.get('agent','?')}: {msg}")
        matched += 1
    if args.count_only:
        print(matched, file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser(sub: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=f"simple-room-scan <room> {sub}", add_help=True
    )
    ap.add_argument("room")
    if sub == "active":
        ap.add_argument(
            "--window", type=int, default=120, help="seconds (default 120)"
        )
    elif sub == "tail":
        ap.add_argument("-n", type=int, default=20)
        ap.add_argument("-a", "--agent", default=None)
        ap.add_argument("--json", action="store_true")
    elif sub == "grep":
        ap.add_argument("pattern")
        ap.add_argument("--since-seq", type=int, default=None, dest="since_seq")
        ap.add_argument("-a", "--agent", default=None)
        ap.add_argument("--json", action="store_true")
        ap.add_argument(
            "-c", "--count", dest="count_only", action="store_true",
            help="print match count to stderr (still print matches to stdout)"
        )
    return ap


_DISPATCH = {
    "count": cmd_count,
    "path": cmd_path,
    "ids": cmd_ids,
    "active": cmd_active,
    "tail": cmd_tail,
    "grep": cmd_grep,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (len(argv) == 1 and argv[0] in ("-h", "--help")):
        print(__doc__)
        return 0
    if len(argv) < 2:
        print(
            "simple-room-scan: usage: simple-room-scan <room> <subcommand> [args]",
            file=sys.stderr,
        )
        print(__doc__, file=sys.stderr)
        return 2

    sub = argv[1]
    if sub not in _DISPATCH:
        print(
            f"simple-room-scan: unknown subcommand {sub!r} (expected: "
            f"{', '.join(sorted(_DISPATCH))})",
            file=sys.stderr,
        )
        return 2

    # Build a parser that takes <room> [subcommand-args…] and feeds the
    # subcommand function a Namespace with the right fields.
    ap = _build_parser(sub)
    try:
        args = ap.parse_args([argv[0]] + argv[2:])
    except SystemExit:
        return 2
    return _DISPATCH[sub](args)


if __name__ == "__main__":
    raise SystemExit(main())
