#!/usr/bin/env python3
"""
simple-room-send — append a record to a room.

Usage:
    simple-room-send <room> [-m MESSAGE] [-k {msg,system,meta}] [-a AGENT]
                        [--stdin] [--seq N] [--id ID] [--ts ISO]

If --message is omitted, the message is read from stdin. The agent id
defaults to $SIMPLE_AGENT_ID, else $USER, else 'agent-<pid>'.
"""
from __future__ import annotations

import argparse
import os
import sys

from simple_agent_room_lib import (
    append_record,
    default_agent,
    format_record,
    room_path,
    valid_agent,
)


def _read_stdin() -> str:
    if sys.stdin.isatty():
        print(
            "simple-room-send: reading from stdin (Ctrl-D to finish)…",
            file=sys.stderr,
        )
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="simple-room-send",
        description="Append a record to a simple-agent-room.",
    )
    ap.add_argument("room", help="room name (filename-safe)")
    ap.add_argument("-m", "--message", help="message text (else read stdin)")
    ap.add_argument(
        "-k",
        "--kind",
        default="msg",
        choices=("msg", "system", "meta"),
        help="record kind (default: msg)",
    )
    ap.add_argument(
        "-a",
        "--agent",
        default=None,
        help=f"agent id (default: $SIMPLE_AGENT_ID else $USER else agent-<pid>)",
    )
    ap.add_argument(
        "--stdin",
        action="store_true",
        help="force reading message from stdin (overrides -m)",
    )
    ap.add_argument("--seq", type=int, default=None, help="explicit seq number")
    ap.add_argument("--id", dest="record_id", default=None, help="explicit record id")
    ap.add_argument("--ts", default=None, help="explicit ISO-8601 timestamp")
    ap.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="do not print the written record id on success",
    )
    args = ap.parse_args(argv)

    agent = args.agent or default_agent()
    if not valid_agent(agent):
        print(
            f"simple-room-send: invalid agent id {agent!r}",
            file=sys.stderr,
        )
        return 2

    if args.message is not None and not args.stdin:
        msg = args.message
    else:
        msg = _read_stdin()

    msg = msg.rstrip("\n")
    if not msg and args.kind == "msg":
        # Empty user messages are usually a mistake; error rather than spam.
        print(
            "simple-room-send: refusing to send empty message (use --kind system/meta)",
            file=sys.stderr,
        )
        return 2

    p = room_path(args.room)
    line = format_record(
        agent,
        msg,
        kind=args.kind,
        seq=args.seq,
        record_id=args.record_id,
        ts=args.ts,
    )
    append_record(p, line)

    if not args.quiet:
        # Print the id to stderr so it doesn't pollute a piped consumer.
        import json

        rec = {
            "id": json.loads(line)["id"],
            "room": args.room,
            "agent": agent,
            "path": str(p),
        }
        print(
            f"sent id={rec['id']} room={rec['room']} agent={rec['agent']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
