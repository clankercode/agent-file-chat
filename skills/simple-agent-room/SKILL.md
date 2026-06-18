---
name: simple-agent-room
description: One-file-per-room chat log for many-to-many inter-agent messaging. The room is a JSON-Lines append-only file under ~/.cache/simple-agent-room/, and three CLI tools (simple-room-send, simple-room-monitor, simple-room-scan) on $PATH are all an agent needs to know. The monitor filters out the local agent's own messages by default and uses inotify (no polling), so it slots directly into a `Monitor(...)` tool as the command. Use when several agents need to discover each other, exchange mid-task findings, or coordinate without depending on c2c / SendMessage brokers.
license: MIT
---

# Simple agent room

## When to use

A **room** is a many-to-many chat log. Any number of agents can post to a
room, and any agent can `Monitor` it. Typical uses:

- Several sub-agents working on related tasks and needing to share
  intermediate findings (a coder reporting a parser bug, a researcher
  reporting a URL, a tester reporting a failing assertion).
- A long-running agent that needs to be discoverable by other agents
  that may spawn later.
- A coordination channel for an "agent team" doing a multi-step plan.

For one-to-one comms with a single long-running subagent, the
sister skill `simple-agent-comms` (two files + a monitor) is lighter.

## What you (the agent) need to know

Three commands, all on `$PATH`. **You do not need to know any file
paths.** The room name is the only thing you pass around.

```sh
simple-room-send    <room> [args]    # post a message
simple-room-monitor <room> [args]    # stream new messages (Monitor-friendly)
simple-room-scan    <room> <subcmd>  # count / tail / active / grep / ids / path
```

That's it. You pick a room name (alphanumerics, dot, underscore, dash;
max 64 chars), you pick an agent id for yourself, and you send / read.

If the rest of the system needs to know where the room is stored, the
single canonical location is `~/.cache/simple-agent-room/<room>.log`,
overridable via `$SIMPLE_AGENT_ROOM_DIR` (rare — only for testing or
multi-tenant layouts).

## Quickstart (one agent, one line)

```sh
simple-room-send kitchen "stove is on"      # you posted a message
simple-room-scan  kitchen tail -n 5          # you read the last 5
simple-room-scan  kitchen active --window 60 # who is in here
```

## Quickstart (two agents coordinating)

```sh
# agent A                                            # agent B
simple-room-send tasks -m "I'm starting"             \
                                                      simple-room-monitor tasks   # in a Monitor:
                                                                       ▲           #   new lines arrive,
                                                                       │           #   self-msgs filtered
# --- later, in another terminal/turn ---            simple-room-send tasks -m "ack"
```

The right pattern: spawn the monitor as a **persistent** background
command in a `Monitor(...)` tool call, then send / scan / talk in the
foreground.

## ASCII flowcharts

### Posting a message

```
       agent                       simple-room-send              on disk
       ─────                       ────────────────              ───────
  $ simple-room-send kitchen \         │
        -a alice -m "hi"             │  format_record
                                     │  → JSON line + '\n'
                                     │  → os.open(O_APPEND|O_CREAT, 0o644)
                                     │  → os.write(fd, line)
                                     ▼
                          ~/.cache/simple-agent-room/kitchen.log
                          ─────────────────────────────────────────
                          {"id":"…","ts":"…","agent":"alice", … }
                          {"id":"…","ts":"…","agent":"bob",   … }
                          …
```

Concurrent posters do not tear each other's records: O_APPEND writes
are atomic on POSIX for buffers ≤ PIPE_BUF (4096 B), and the JSON
record is always < 1 KiB in practice.

### Monitoring (the `Monitor(...)` shape)

```
       simple-room-monitor                  Monitor tool
       ───────────────────                  ───────────
  backfill: tail the last N records         stdout
             (or 0 for "live only")             │
             parse JSON, drop self       ──────►│  each line is a
                                                │  background event,
  live:    pyinotify.watch on the file          │  not a user reply
           IN_MODIFY  ─► read new bytes
           IN_DELETE  ─► wait for recreate
           IN_MOVE    ─► wait for recreate
                                                ▼
                                          agent reads the line,
                                          decides what to do
```

The script does not poll. It blocks in `pyinotify.Notifier` and wakes
on kernel events. Latency from send → event delivery is sub-millisecond
on local filesystems.

### Scanning (read-only)

```
       simple-room-scan <room> <subcmd> [args]
       ────────────────────────────────────────
              │
              ├─ count                 → 1 line: total record count
              ├─ ids                   → 1 id per line (sorted)
              ├─ path                  → 1 line: absolute file path
              ├─ active  [--window S]  → "agent<TAB>ts" per active agent
              ├─ tail    [-n N] [-a A] → last N (or agent's) records
              └─ grep    <pattern>     → records whose msg matches
                       [--since-seq N]
                       [-a A] [--json]
              │
              ▼
       iter_records(path) → dict stream
       (skips blank / '#' / malformed lines)
```

## Reference

### `simple-room-send <room> [-m MSG] [-k {msg,system,meta}] [-a AGENT] [--stdin]`

| flag          | meaning                                                  |
|---------------|----------------------------------------------------------|
| `-m MESSAGE`  | the message text (else read stdin)                       |
| `--stdin`     | force reading from stdin (overrides `-m`)                |
| `-k KIND`     | `msg` (default), `system`, or `meta`                     |
| `-a AGENT`    | local agent id; default `$SIMPLE_AGENT_ID` else `$USER-<host>-<pid>` |
| `--seq N`     | explicit monotonic seq (optional)                        |
| `--id ID`     | explicit record id (uuid4 hex, optional)                 |
| `--ts ISO`    | explicit timestamp (optional)                            |
| `-q`          | suppress the "sent id=…" confirmation on stderr          |

The message is stored verbatim (newlines, tabs, backslashes are JSON-escaped
inside the record; you see them on the read side as normal characters).

### `simple-room-monitor <room> [-a AGENT] [--exclude-self] [--backfill N] [--grep PATTERN] [--json]`

| flag               | meaning                                                |
|--------------------|--------------------------------------------------------|
| `-a AGENT`         | local agent id (default as above)                      |
| `--exclude-self`   | drop records from local agent (default: **on**)        |
| `--no-exclude-self`| include them (use when you want to see your own msgs)  |
| `-b N`             | emit the last N existing records before going live     |
|                    | (`-1` = all; `0` = events-only, the default)            |
| `--grep PATTERN`   | only emit records whose rendered line matches regex     |
| `--json`           | emit raw JSON record per line (else `HH:MM:SS agent: msg`) |

The script runs until killed. **Use it as the `command` of a persistent
`Monitor(...)` tool call** — the right pattern is one Monitor per room
per session. The Monitor events are background events, not user
replies; do not treat them as a turn-ending user message.

### `simple-room-scan <room> <subcommand> [args]`

| subcommand | args                          | output                          |
|------------|-------------------------------|---------------------------------|
| `count`    | —                             | total record count              |
| `ids`      | —                             | one agent id per line           |
| `path`     | —                             | absolute file path              |
| `active`   | `--window SECONDS` (120)      | `agent<TAB>ts` per active agent |
| `tail`     | `-n N` (20), `-a AGENT`, `--json` | last N records              |
| `grep`     | `PATTERN`, `--since-seq N`, `-a A`, `--json`, `-c` (count→stderr) | matching records |

`grep` is case-sensitive and uses Python regex syntax (which is close
to PCRE for the common cases — `.`, `*`, `+`, `?`, `\b`, character
classes).

## Self-filter pattern (the "don't talk to yourself" recipe)

The monitor defaults to `--exclude-self` because in a single-agent
turn-loop the agent has just sent its own message, and replaying it
back as an event is noise. If you need both sides of a single-agent
debug session visible, pass `--no-exclude-self`.

Two agents in the same room must pick **different** agent ids. The
default (`$USER-<host>-<pid>`) is unique per process; if you spawn
multiple agents from the same shell, set `SIMPLE_AGENT_ID` for each
to keep them distinct.

## What you don't need to know

- The on-disk path. It's `~/.cache/simple-agent-room/<room>.log`. You
  never write to it directly. `simple-room-scan <room> path` will tell
  you if you're curious.
- The schema. The lib reads the file, parses JSON, drops malformed
  lines, and unescapes msg strings. You see a dict with `id`, `ts`,
  `agent`, `msg`, `kind`, optional `seq`.
- Polling. The monitor is fully event-driven (inotify).
- Locking. Records are < 4 KiB, O_APPEND is atomic on POSIX, so no
  flock / fcntl is needed. Two writers can post simultaneously
  without tearing each other's records.

## Failure modes worth knowing

- **Stale inotify after delete/rename**: the lib re-attaches the watch
  on `IN_CREATE` for the same path, so a log-rotation tool that
  replaces the file is handled. If you `rm` the file by hand, the
  monitor will create a new empty one on the next send.
- **Agent id collision**: two agents with the same id will see each
  other's messages as their own (and filter them out by default).
  Always use `SIMPLE_AGENT_ID` or the `$USER-<host>-<pid>` default.
- **Clock skew**: `ts` is wall-clock UTC of the sender. If you sort
  by `ts` across agents, set NTP. For ordering within a single agent,
  use `seq`.
- **Very long messages**: there is no hard cap, but if you regularly
  post > 4 KiB you may hit PIPE_BUF and start seeing torn records.
  Keep messages < 4 KiB.
- **Malformed lines**: the reader silently skips any line that
  doesn't parse as a JSON object. Garbage in = garbage silently
  dropped; valid records around it are unaffected.

## Files

```
skills/simple-agent-room/
  SKILL.md           ← this file
```

```
scripts/                              ← relative to the repo root
  simple_agent_room_lib.py            shared lib (inotify, format/parse, scan)
  simple_room_send.py                 entry: simple-room-send
  simple_room_monitor.py              entry: simple-room-monitor
  simple_room_scan.py                 entry: simple-room-scan
```

Symlinks for the entries live in `~/.local/bin/` so the agent
invokes them by short name.
