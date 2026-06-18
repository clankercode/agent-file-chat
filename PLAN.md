# PLAN.md — agent-file-chat

## High-level

Build two reusable agent skills (one renamed from a sister repo, one new), publish
them as a public GitHub repo under the `clankercode` org, and complete end-to-end
testing of every feature using subagents + tmux + the `pi` CLI.

## Deliverables

1. `skills/simple-agent-comms/` — rename of `subagent-file-comms`. Two-file (coord↔agent) stream-of-updates comms.
2. `skills/simple-agent-room/` — new. Single-file room (shared log). Monitor-compatible, self-messages filtered, inotify-driven, agent doesn't need to know file paths.
3. Python scripts in `scripts/` (one per concern): send, monitor, scan, plus a shared lib.
4. Global install: scripts in `~/.local/bin/`, skill symlinks in `~/.claude/skills/` and `~/.agents/skills/`.
5. E2E test suite under `tests/` (Python + bash). Includes a real-`pi`-agent scenario run in tmux.
6. GitHub repo `clankercode/agent-file-chat` (public), with description + README + LICENSE.

## Architecture

### File location strategy (so agents never need absolute paths)

- All rooms are stored under `~/.cache/simple-agent-room/<room>.log`.
- Configurable via `SIMPLE_AGENT_ROOM_DIR` env var (rare).
- A sentinel `~/.cache/simple-agent-room/.version` records the schema version of the on-disk format.
- Scripts are exposed as commands on `$PATH` (`~/.local/bin/`): `simple-room-send`, `simple-room-monitor`, `simple-room-scan`. Each is a thin Python entry-point shebang.

### Message format (single-file, append-only)

Each room is a UTF-8 text file with one JSON Lines record per line:

```json
{"id":"01HXY...","ts":"2026-06-18T05:22:18Z","agent":"alice","msg":"hello","kind":"msg","seq":17}
```

- `id` — ULID, unique, sortable.
- `ts` — ISO-8601 UTC.
- `agent` — agent name (string, <=64 chars; `[A-Za-z0-9._-]+`).
- `msg` — text body; `\n` replaced with U+23CE / escaped, never literal newline in the record.
- `kind` — `"msg"` (default), or `"system"` (e.g. join/leave markers), or `"meta"` (e.g. self-id broadcast).
- `seq` — monotonic per-agent counter (optional, used for ordering in dense bursts).

Why JSON-Lines:
- Trivially appendable from many processes under `O_APPEND`.
- Grepable with `jq`.
- Resilient to torn writes (each line is independent).
- Self-describing for any future consumer.

### Python scripts (in `scripts/`)

Shared lib `simple_agent_room_lib.py`:
- `room_path(room)` → str (creates the directory)
- `parse_record(line)` → dict | None
- `format_record(agent, msg, kind='msg')` → str
- `iter_records(room, since_seq=None)` → generator
- `latest_seq(agent, room)` → int
- `inotify_follow(path, on_line)` → iterator that yields new lines as they appear (pyinotify)

Entry points (each a thin wrapper shebang `#!/usr/bin/env python3`):
- `simple_room_send.py` — `simple-room-send <room> [agent] [--message/-m MSG] [--kind/-k K] [--stdin]`
  - If `--stdin`, reads from stdin (handy for `echo … | simple-room-send …`).
  - `agent` defaults to `$SIMPLE_AGENT_ID` else `os.environ['USER']` else `agent-<pid>`.
- `simple_room_monitor.py` — `simple-room-monitor <room> [--exclude-self/--no-self] [--agent A] [--grep P] [--json]`
  - Streams new lines to stdout, line-buffered.
  - With `--exclude-self` (default on), lines whose `agent` matches the local id are dropped silently.
  - With `--json`, emits the raw JSON record (so downstream tooling can parse).
  - Otherwise emits a human line: `HH:MM:SS alice: hello`.
  - Backfills the existing tail (so the first call shows the last N lines, like a tail-on-attach) when `--backfill N` is set; default 0 (events-only).
- `simple_room_scan.py` — read-only operations on the log:
  - `simple-room-scan <room> count` — total record count.
  - `simple-room-scan <room> tail [--n N] [--agent A] [--json]` — last N records.
  - `simple-room-scan <room> active [--window S]` — agents seen within last S seconds (default 120).
  - `simple-room-scan <room> grep <pattern> [--since SEQ] [--json]` — full-text search (msg field), case-insensitive substring.
  - `simple-room-scan <room> ids` — list of all known agents in this room.
  - `simple-room-scan <room> path` — print the absolute file path (for debugging; the agent normally never needs this).

### `simple-agent-comms` (rename)

Pretty much the existing `subagent-file-comms` skill, with the name updated and
a few tightening edits (id is a ULID-style string, monitor command uses our
`simple-room-monitor` if both agents are in the same "room"; new scripts work
in the comms pattern too).

### E2E tests (`tests/`)

1. `tests/test_unit.py` — pytest. Drives the lib + entry-points directly. Covers:
   - send + read-back roundtrip
   - self-filter on monitor (uses a subprocess monitor in the background)
   - count, tail, active, grep, ids, path
   - message with newlines / unicode / very long
   - concurrent writers (multi-process append) — no torn lines
2. `tests/test_inotify.sh` — bash. Spawns the monitor in background, sends a message, asserts it appears within 1s.
3. `tests/test_e2e_pi.sh` — bash + tmux. Spins up a tmux session with two `pi --print` panes, each given the `simple-agent-room` skill, then drives a scripted dialogue and asserts the transcript.
4. `tests/test_skill_install.sh` — bash. Asserts scripts are on PATH, symlinks exist, and SKILL.md frontmatter parses.

### Subagent testing strategy

- For unit + e2e in-process tests, I use my own subagents (via the `Agent` tool, `general-purpose` subagent type) to write/verify Python and bash tests.
- For "real pi agent" tests, I use tmux + `pi --print --provider google --model <model>` with a scripted prompt. The exact model is determined at test-run time (we record what works in `tests/MODEL_NOTES.md`).
- I will discover available models with `pi --models` or by reading the project's `settings.json` once we have a working `pi` invocation.

## Acceptance criteria

- [ ] `simple-agent-comms` SKILL.md loads in pi and Claude Code, and the watch command in the README works.
- [ ] `simple-agent-room` SKILL.md loads; `simple-room-send` / `-monitor` / `-scan` are on `$PATH`; `which simple-room-send` succeeds.
- [ ] `tests/test_unit.py` and `tests/test_inotify.sh` pass.
- [ ] `tests/test_e2e_pi.sh` runs a two-pane tmux session where two `pi` agents successfully exchange at least one message each way through the room; transcript is recorded in `tests/transcripts/`.
- [ ] Public repo `clankercode/agent-file-chat` exists, has a description, README, LICENSE, and all source code.
- [ ] `git log` shows a clean history with regular commits as the work progressed.

## Out of scope (v1)

- Cross-host rooms (e.g. NFS / sshfs / git-backed).
- Encryption / auth on rooms.
- A TUI client (the skill is meant for AI agents + the `Monitor` tool).
- A daemon process (everything is on-demand; inotify is per-monitor).

## Open questions

- What model string to use for `pi --model` in e2e (MiniMax-M2.7-highspeed or whatever is actually available). To resolve at test-run time.
- Whether to use pyinotify (already installed) or `inotifywait` subprocess (no Python dep). Going with pyinotify (matches the "python scripts" brief).
