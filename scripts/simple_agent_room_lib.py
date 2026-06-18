#!/usr/bin/env python3
"""
simple_agent_room_lib — shared library for the simple-agent-room skill.

On-disk format
--------------
A room is a single file at ``$SIMPLE_AGENT_ROOM_DIR/<room>.log`` (default
``~/.cache/simple-agent-room/<room>.log``). It contains one JSON Lines
record per line:

    {"id":"<uuid4hex>","ts":"<iso8601utc>","agent":"<name>",
     "msg":"<text>","kind":"msg|system|meta","seq":<int|null>}

Notes
-----
* Records are <4 KiB; on POSIX, ``O_APPEND`` writes are atomic up to
  ``PIPE_BUF`` (4096), so two concurrent writers never tear a record.
* Embedded newlines / tabs / backslashes in ``msg`` are escaped by
  ``json.dumps`` to the standard JSON two-char sequences (``\\n``,
  ``\\t``, ``\\\\``), so every record is exactly one line. No custom
  escape layer is needed (and would double-escape).
* ``seq`` is a monotonic per-agent counter; the lib does not enforce it
  (it is informational, useful for ordering within a dense burst from
  the same sender).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

# ---------------------------------------------------------------------------
# Constants & locations
# ---------------------------------------------------------------------------

DEFAULT_DIRNAME = "simple-agent-room"
SCHEMA_VERSION = 1

AGENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ROOM_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def room_dir() -> Path:
    """Return the directory rooms are stored in (creating it)."""
    env = os.environ.get("SIMPLE_AGENT_ROOM_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = Path.home() / ".cache" / DEFAULT_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def room_path(room: str) -> Path:
    """Return the path to a room's log file (does not create the file)."""
    if not ROOM_RE.match(room):
        raise ValueError(
            f"invalid room name {room!r}: must match {ROOM_RE.pattern}"
        )
    return room_dir() / f"{room}.log"


def version_path() -> Path:
    return room_dir() / ".version"


def ensure_schema_version() -> None:
    """Write the schema version sentinel if missing (idempotent)."""
    vp = version_path()
    if not vp.exists():
        try:
            vp.write_text(f"{SCHEMA_VERSION}\n")
        except FileExistsError:
            pass


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def default_agent() -> str:
    """Best-effort default agent id (the monitor/send scripts use this)."""
    env = os.environ.get("SIMPLE_AGENT_ID")
    if env and AGENT_RE.match(env):
        return env
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "agent"
    host = os.environ.get("HOSTNAME") or ""
    suffix = f"-{host}" if host and re.match(r"^[A-Za-z0-9._-]+$", host) else ""
    candidate = f"{user}{suffix}-{os.getpid()}"
    if AGENT_RE.match(candidate):
        return candidate
    return f"agent-{os.getpid()}"


def valid_agent(name: str) -> bool:
    return bool(AGENT_RE.match(name))


# ---------------------------------------------------------------------------
# Record encode / decode
# ---------------------------------------------------------------------------
# Note on escaping: ``json.dumps`` already escapes ``\n``, ``\t``, ``\\`` and
# any control characters in the ``msg`` field, and every record is therefore
# guaranteed to be exactly one line. We do NOT add our own escape layer on
# top — doing so leads to double-escape bugs (a literal newline becomes the
# two-char sequence ``\n`` in JSON, not three-char ``\\n``). Callers that
# want to embed a real newline in a message can do so; the JSON encoding
# will represent it as the two-char sequence ``\n`` and the record stays
# on one line.


def now_iso() -> str:
    """ISO-8601 UTC timestamp, second precision (compact)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Random unique id (uuid4 hex)."""
    return uuid.uuid4().hex


def format_record(
    agent: str,
    msg: str,
    kind: str = "msg",
    seq: Optional[int] = None,
    *,
    record_id: Optional[str] = None,
    ts: Optional[str] = None,
) -> str:
    """Build a one-line JSON record (without trailing newline)."""
    if not valid_agent(agent):
        raise ValueError(
            f"invalid agent name {agent!r}: must match {AGENT_RE.pattern}"
        )
    rec = {
        "id": record_id or new_id(),
        "ts": ts or now_iso(),
        "agent": agent,
        "kind": kind if kind in ("msg", "system", "meta") else "msg",
        "msg": msg,
    }
    if seq is not None:
        rec["seq"] = int(seq)
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def parse_record(line: str) -> Optional[dict]:
    """Parse one line; return None for blank/comment/malformed lines."""
    line = line.rstrip("\r\n")
    if not line or line.startswith("#"):
        return None
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict):
        return None
    return rec


# ---------------------------------------------------------------------------
# Read / write operations
# ---------------------------------------------------------------------------


def append_record(room_path_obj: Path, line: str) -> None:
    """Append a single record line to the room file (newline-terminated)."""
    # O_APPEND makes POSIX-guarantee the write is atomic for records < PIPE_BUF.
    fd = os.open(
        str(room_path_obj),
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        0o644,
    )
    try:
        if not line.endswith("\n"):
            line = line + "\n"
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def iter_records(room: str | Path) -> Iterator[dict]:
    """Yield parsed records from a room (skips blank/comment/bad lines)."""
    p = Path(room)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            rec = parse_record(line)
            if rec is not None:
                yield rec


def record_count(room: str | Path) -> int:
    p = Path(room)
    if not p.exists():
        return 0
    n = 0
    with p.open("rb") as f:
        for line in f:
            line = line.rstrip(b"\r\n")
            if not line or line.startswith(b"#"):
                continue
            n += 1
    return n


def active_agents(room: str | Path, window_seconds: int) -> dict[str, str]:
    """Return {agent: latest_iso_ts} for agents seen within the window."""
    cutoff = time.time() - window_seconds
    out: dict[str, str] = {}
    for rec in iter_records(room):
        ts = rec.get("ts")
        agent = rec.get("agent")
        if not isinstance(ts, str) or not isinstance(agent, str):
            continue
        try:
            epoch = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ).timestamp()
        except ValueError:
            continue
        if epoch < cutoff:
            continue
        prev = out.get(agent)
        if prev is None or ts > prev:
            out[agent] = ts
    return out


def latest_seq_for(agent: str, room: str | Path) -> int:
    """Return the highest ``seq`` seen for ``agent`` in the room (0 if none)."""
    best = 0
    for rec in iter_records(room):
        if rec.get("agent") == agent and isinstance(rec.get("seq"), int):
            if rec["seq"] > best:
                best = rec["seq"]
    return best


# ---------------------------------------------------------------------------
# inotify follow
# ---------------------------------------------------------------------------

# We import pyinotify lazily so the lib is still importable (and the read-only
# scan/send paths still work) on systems without it.
def inotify_follow(
    path: Path,
    on_line: Callable[[str], None],
    on_rotation: Optional[Callable[[], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Block-and-emit: invoke ``on_line`` for every NEW line appended to ``path``.

    Uses ``pyinotify``. Handles file deletion/rotation by re-creating the
    watch when the file reappears. Creates the file if missing.

    Args:
        path: file to follow
        on_line: callback invoked with each new line (without trailing \\n)
        on_rotation: optional callback fired when the file is deleted/renamed
        stop: optional predicate; return True to break the loop
    """
    import pyinotify  # type: ignore

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()

    # Position in the file we have already emitted.
    pos = path.stat().st_size

    mask = (
        pyinotify.IN_MODIFY
        | pyinotify.IN_CLOSE_WRITE
        | pyinotify.IN_MOVE_SELF
        | pyinotify.IN_DELETE_SELF
        | pyinotify.IN_CREATE
    )

    wm = pyinotify.WatchManager()
    # Watch the file (for modify/delete) AND the parent dir (for recreate).
    file_wd: Optional[int] = None

    def _drain() -> None:
        nonlocal pos
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size < pos:
            # truncated/rotated; restart from 0
            pos = 0
        if size == pos:
            return
        with path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(pos)
            data = f.read()
        pos += len(data.encode("utf-8", errors="replace"))
        # Split keeping partial trailing buffer.
        lines = data.split("\n")
        # The last element is either '' (file ends with \\n) or a partial
        # line; we should not emit it yet. Decrement pos by the length of
        # the partial line so we re-read it next time.
        if lines and lines[-1] != "":
            partial = lines.pop()
            partial_bytes = len(partial.encode("utf-8", errors="replace"))
            pos -= partial_bytes
        else:
            # ends with newline; drop the empty trailing element
            lines.pop()
        for ln in lines:
            on_line(ln)

    def _ensure_file_watch(notifier: pyinotify.Notifier) -> None:
        nonlocal file_wd
        if file_wd is not None:
            try:
                wm.rm_watch(file_wd)
            except Exception:
                pass
            file_wd = None
        if path.exists():
            file_wd = wm.add_watch(str(path), mask, quiet=False)

    class _Handler(pyinotify.ProcessEvent):
        def process_IN_MODIFY(self, event):  # noqa: N802
            if str(event.pathname) == str(path):
                _drain()

        def process_IN_CLOSE_WRITE(self, event):  # noqa: N802
            if str(event.pathname) == str(path):
                _drain()

        def process_IN_MOVE_SELF(self, event):  # noqa: N802
            if on_rotation is not None:
                on_rotation()
            # the wd is now invalid
            try:
                if file_wd is not None:
                    wm.rm_watch(file_wd)
            except Exception:
                pass
            file_wd_locals["wd"] = None  # type: ignore[name-defined]

        def process_IN_DELETE_SELF(self, event):  # noqa: N802
            if on_rotation is not None:
                on_rotation()
            try:
                if file_wd is not None:
                    wm.rm_watch(file_wd)
            except Exception:
                pass
            file_wd_locals["wd"] = None  # type: ignore[name-defined]

        def process_IN_CREATE(self, event):  # noqa: N802
            # Recreated by some external actor; re-attach.
            if str(event.pathname) == str(path):
                _ensure_file_watch(notifier)
                _drain()

    file_wd_locals: dict[str, Optional[int]] = {"wd": None}

    handler = _Handler()
    notifier = pyinotify.Notifier(wm, handler, timeout=1000)  # 1s tick
    _ensure_file_watch(notifier)
    # Drain any pre-existing tail once on start (so a new subscriber sees
    # recent history if the caller wants it; callers that don't want this
    # can seek to the end themselves before calling).
    # NB: inotify_follow by default DOES emit pre-existing tail; the
    # ``--backfill`` flag in the monitor script controls how much of it.
    _drain()

    try:
        while True:
            if stop is not None and stop():
                break
            notifier.check_events(timeout=1000)
            notifier.read_events()
            notifier.process_events()
    except KeyboardInterrupt:
        pass
