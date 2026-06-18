# agent-file-chat

Two reusable AI-agent skills (`simple-agent-comms` and `simple-agent-room`)
plus the Python scripts that power them. Both are designed for AI agents
that need to exchange messages without depending on a chat broker — the
entire interface is a file on disk and a few CLI tools on `$PATH`.

## Skills

| skill | when to use | files |
|-------|-------------|-------|
| [`simple-agent-comms`](skills/simple-agent-comms/SKILL.md) | one-to-one streaming with a long-running subagent | two append-only files + a `Monitor` |
| [`simple-agent-room`](skills/simple-agent-room/SKILL.md)  | many-to-many room chat | one append-only file per room + three CLIs |

Both are designed so the agent **never has to know the on-disk paths** —
it just calls the tools by short name. The location is a single
well-known directory (`~/.cache/simple-agent-room/` for rooms,
`~/.cache/agent-comms/` for comms), overridable via env var.

## Install (one-shot)

```sh
# 1. clone
git clone https://github.com/clankercode/agent-file-chat.git
cd agent-file-chat

# 2. expose the three room CLIs on $PATH
ln -sf "$PWD/scripts/simple_room_send.py"    ~/.local/bin/simple-room-send
ln -sf "$PWD/scripts/simple_room_monitor.py" ~/.local/bin/simple-room-monitor
ln -sf "$PWD/scripts/simple_room_scan.py"    ~/.local/bin/simple-room-scan

# 3. install the skills globally (Claude Code + pi)
ln -snf "$PWD/skills/simple-agent-comms" ~/.claude/skills/simple-agent-comms
ln -snf "$PWD/skills/simple-agent-room"  ~/.claude/skills/simple-agent-room
ln -snf "$PWD/skills/simple-agent-comms" ~/.agents/skills/simple-agent-comms
ln -snf "$PWD/skills/simple-agent-room"  ~/.agents/skills/simple-agent-room
```

Dependencies: `python3 >= 3.10` and `pyinotify` (`pip install pyinotify`
on most distros; pre-installed on Arch / Manjaro).

## Usage

### Room (many-to-many)

```sh
# send
simple-room-send kitchen -a alice -m "stove is on"

# monitor (drop into a Monitor tool's command field)
simple-room-monitor kitchen -a alice --backfill 10

# scan (read-only)
simple-room-scan kitchen count
simple-room-scan kitchen tail -n 5
simple-room-scan kitchen active --window 60
simple-room-scan kitchen grep "stove"
simple-room-scan kitchen ids
```

See [`skills/simple-agent-room/SKILL.md`](skills/simple-agent-room/SKILL.md)
for the full reference and failure modes.

### Comms (one-to-one with a subagent)

```
~/.cache/agent-comms/
  alice-to-coord.md     # agent → you  (you Monitor this)
  coord-to-alice.md     # you → agent  (agent tails this)
```

```sh
# watch-file.sh is shipped in skills/simple-agent-comms/
~/.local/bin/watch-file.sh ~/.cache/agent-comms/alice-to-coord.md
```

See [`skills/simple-agent-comms/SKILL.md`](skills/simple-agent-comms/SKILL.md).

## On-disk format (rooms)

Each room is a JSON-Lines append-only file:

```jsonl
{"id":"7daed4d0…","ts":"2026-06-18T08:30:00Z","agent":"alice","kind":"msg","msg":"hi"}
{"id":"a136ec8e…","ts":"2026-06-18T08:30:05Z","agent":"bob","kind":"msg","msg":"hey"}
```

- Records are < 4 KiB; `O_APPEND` is atomic on POSIX for writes ≤ `PIPE_BUF`,
  so concurrent posters never tear a record.
- `\n`, `\t`, `\\` in `msg` are escaped by `json.dumps` to the standard
  JSON sequences; every record is exactly one line.
- `kind` is `msg` (default), `system`, or `meta`.

## Tests

```sh
# unit + integration
python3 -m pytest tests/test_unit.py tests/test_cli.py -v

# install smoke + inotify timing + concurrency
./tests/test_install.sh
./tests/test_inotify.sh

# e2e with two real pi agents in tmux (uses ~1-3 min, real LLM cost)
./tests/test_e2e_pi.sh
```

48 pytest tests + 3 bash scripts. The e2e test is skippable: if the
model is unreachable, it exits 0 with a `SKIP:` message.

## Architecture

```
scripts/
  simple_agent_room_lib.py     # shared lib (format, parse, inotify, scan)
  simple_room_send.py          # entry: simple-room-send
  simple_room_monitor.py       # entry: simple-room-monitor
  simple_room_scan.py          # entry: simple-room-scan
skills/
  simple-agent-comms/
    SKILL.md                   # the skill definition
    watch-file.sh              # the Monitor command
  simple-agent-room/
    SKILL.md
tests/
  conftest.py
  test_unit.py                 # 28 in-process tests
  test_cli.py                  # 20 subprocess tests
  test_install.sh              # bash: install smoke
  test_inotify.sh              # bash: inotify timing + concurrency
  test_e2e_pi.sh               # bash: tmux + two pi agents
```

## License

Dual-licensed under [The Unlicense](https://unlicense.org/) and
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).
You may pick whichever you prefer; both place this work in the public
domain. See [LICENSE](LICENSE) for the full texts.
