# agent-file-chat

Two reusable AI-agent skills (`simple-agent-comms` and `simple-agent-room`)
for inter-agent messaging on disk. Each skill bundles its own scripts;
the whole thing installs with one command and ships zero Python
packages.

## Skills

| skill | when to use | ships |
|-------|-------------|-------|
| [`simple-agent-comms`](skills/simple-agent-comms/SKILL.md) | one-to-one streaming with a long-running subagent | `bin/watch-file.sh` |
| [`simple-agent-room`](skills/simple-agent-room/SKILL.md)  | many-to-many room chat | `bin/{simple-room-send,monitor,scan}` + `lib/` |

Both are designed so the agent **never has to know the on-disk paths** —
it just calls the tools by short name. The location is a single
well-known directory (`~/.cache/simple-agent-room/` for rooms,
`~/.cache/agent-comms/` for comms), overridable via env var.

## Install

**One command** (idempotent; safe to re-run):

```sh
git clone https://github.com/clankercode/agent-file-chat.git
cd agent-file-chat
./install.sh
```

This:
- symlinks every `skills/<skill>/` into `~/.claude/skills/` and `~/.agents/skills/`
  (the two directories pi and Claude Code scan for `SKILL.md`)
- symlinks every `bin/*` into `~/.local/bin/` (assumed on `$PATH`)

Run `./install.sh --uninstall` to reverse it, or `--force` to overwrite
existing symlinks.

### By hand, if you'd rather

```sh
ln -s "$PWD/skills/simple-agent-comms"  ~/.claude/skills/simple-agent-comms
ln -s "$PWD/skills/simple-agent-comms"  ~/.agents/skills/simple-agent-comms
ln -s "$PWD/skills/simple-agent-room"   ~/.claude/skills/simple-agent-room
ln -s "$PWD/skills/simple-agent-room"   ~/.agents/skills/simple-agent-room
ln -s "$PWD/skills/"*/bin/*             ~/.local/bin/
```

### Dependencies

- `python3 >= 3.10`
- `pyinotify` — required only by the monitor; `simple-room-send` and
  `simple-room-scan` work without it. (`pip install pyinotify` on most
  distros; pre-installed on Arch / Manjaro.)

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
watch-file.sh ~/.cache/agent-comms/alice-to-coord.md
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
# unit + integration (49 tests)
python3 -m pytest tests/test_unit.py tests/test_cli.py -v

# bash: install smoke + inotify timing + concurrency
./tests/test_install.sh
./tests/test_inotify.sh

# e2e with two real pi agents in tmux (uses ~1-3 min, real LLM cost)
./tests/test_e2e_pi.sh
```

The e2e test is skippable: if the model is unreachable, it exits 0
with a `SKIP:` message.

## Architecture

```
agent-file-chat/
├── install.sh                       # one-command installer (idempotent)
├── LICENSE                          # dual Unlicense + CC0-1.0
├── README.md
├── skills/
│   ├── simple-agent-comms/
│   │   ├── SKILL.md
│   │   └── bin/
│   │       └── watch-file.sh
│   └── simple-agent-room/
│       ├── SKILL.md
│       ├── bin/
│       │   ├── simple-room-send     # thin wrapper → lib/simple_room_send.py
│       │   ├── simple-room-monitor  # thin wrapper → lib/simple_room_monitor.py
│       │   └── simple-room-scan     # thin wrapper → lib/simple_room_scan.py
│       └── lib/
│           ├── simple_agent_room_lib.py   # shared lib
│           ├── simple_room_send.py
│           ├── simple_room_monitor.py
│           └── simple_room_scan.py
└── tests/
    ├── conftest.py
    ├── test_unit.py                 # 28 in-process lib tests
    ├── test_cli.py                  # 21 subprocess entry-point tests
    ├── test_install.sh              # install smoke + symlink validation
    ├── test_inotify.sh              # inotify timing + 100-process concurrency
    └── test_e2e_pi.sh               # tmux + two real pi agents
```

The `bin/` wrappers each contain a 12-line Python file that does:

```python
_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "lib"))
from simple_room_send import main
```

…so the same code runs whether you invoke it as
`skills/simple-agent-room/bin/simple-room-send` (direct) or as
`~/.local/bin/simple-room-send` (via the install.sh symlink).

## License

Dual-licensed under [The Unlicense](https://unlicense.org/) and
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).
You may pick whichever you prefer; both place this work in the public
domain. See [LICENSE](LICENSE) for the full texts.
