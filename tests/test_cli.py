"""
Integration tests for the three simple-room-* CLI entry points.

These drive the actual scripts as subprocesses (one Python invocation per
CLI call), so we catch argparse / shebang / PYTHONPATH regressions that
in-process tests would miss.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN = REPO_ROOT / "skills" / "simple-agent-room" / "bin"
SCRIPTS = BIN  # legacy name kept to minimise diff churn


# ---------------------------------------------------------------------------
# simple-room-send
# ---------------------------------------------------------------------------


def test_send_writes_a_record(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "-m", "hi")
    assert rc == 0
    assert "sent id=" in err  # the confirmation goes to stderr
    # The file should have exactly one record.
    p = room_dir / "kitchen.log"
    assert p.exists()
    lines = [ln for ln in p.read_text().splitlines() if ln and not ln.startswith("#")]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["agent"] == "alice"
    assert rec["msg"] == "hi"


def test_send_accepts_positional_message(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "stove is on", "-a", "alice")
    assert rc == 0
    rec = json.loads((room_dir / "kitchen.log").read_text().strip())
    assert rec["msg"] == "stove is on"


def test_send_creates_schema_version(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "-m", "hi")
    assert rc == 0
    assert (room_dir / ".version").read_text() == "1\n"


def test_send_stdin(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "--stdin", stdin=b"from-stdin\n")
    assert rc == 0
    p = room_dir / "kitchen.log"
    recs = [json.loads(ln) for ln in p.read_text().splitlines() if ln]
    assert recs[0]["msg"] == "from-stdin"


def test_send_rejects_empty(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "-m", "")
    assert rc != 0
    assert "refusing to send empty message" in err


def test_send_rejects_invalid_agent(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "has space", "-m", "x")
    assert rc != 0
    assert "invalid agent" in err


def test_send_long_message(room_dir: Path, run_cli) -> None:
    msg = "x" * 3500  # close to but under PIPE_BUF
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "-m", msg)
    assert rc == 0
    rec = json.loads((room_dir / "kitchen.log").read_text().strip())
    assert rec["msg"] == msg


def test_send_with_seq(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("send", "kitchen", "-a", "alice", "-m", "x", "--seq", "17")
    assert rc == 0
    rec = json.loads((room_dir / "kitchen.log").read_text().strip())
    assert rec["seq"] == 17


# ---------------------------------------------------------------------------
# simple-room-scan
# ---------------------------------------------------------------------------


def test_scan_count_empty(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("scan", "kitchen", "count")
    assert rc == 0
    assert out.strip() == "0"
    assert (room_dir / ".version").read_text() == "1\n"


def test_scan_count_after_sends(room_dir: Path, run_cli) -> None:
    for i in range(3):
        run_cli("send", "kitchen", "-a", f"a{i}", "-m", f"m{i}")
    rc, out, err = run_cli("scan", "kitchen", "count")
    assert rc == 0
    assert out.strip() == "3"


def test_scan_tail_n(room_dir: Path, run_cli) -> None:
    for i in range(5):
        run_cli("send", "kitchen", "-a", "a", "-m", f"m{i}")
    rc, out, err = run_cli("scan", "kitchen", "tail", "-n", "2")
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert len(lines) == 2
    assert "m3" in lines[0]
    assert "m4" in lines[1]


def test_scan_tail_json(room_dir: Path, run_cli) -> None:
    run_cli("send", "kitchen", "-a", "alice", "-m", "x")
    rc, out, err = run_cli("scan", "kitchen", "tail", "-n", "1", "--json")
    assert rc == 0
    rec = json.loads(out.strip())
    assert rec["msg"] == "x"
    assert rec["agent"] == "alice"


def test_scan_ids(room_dir: Path, run_cli) -> None:
    for a in ("bob", "alice", "carol"):
        run_cli("send", "kitchen", "-a", a, "-m", "x")
    rc, out, err = run_cli("scan", "kitchen", "ids")
    assert rc == 0
    assert out.splitlines() == ["alice", "bob", "carol"]  # sorted


def test_scan_path(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("scan", "kitchen", "path")
    assert rc == 0
    assert Path(out.strip()) == room_dir / "kitchen.log"


def test_scan_active_with_window(room_dir: Path, run_cli) -> None:
    run_cli("send", "kitchen", "-a", "alice", "-m", "x", "--ts", "2020-01-01T00:00:00Z")
    run_cli("send", "kitchen", "-a", "bob", "-m", "y")  # uses now
    rc, out, err = run_cli("scan", "kitchen", "active", "--window", "60")
    assert rc == 0
    lines = out.splitlines()
    agents = {ln.split("\t", 1)[0] for ln in lines}
    assert agents == {"bob"}


def test_scan_grep(room_dir: Path, run_cli) -> None:
    for msg in ("hello world", "goodbye world", "hello there"):
        run_cli("send", "kitchen", "-a", "a", "-m", msg)
    rc, out, err = run_cli("scan", "kitchen", "grep", "hello")
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert len(lines) == 2
    assert all("hello" in ln for ln in lines)


def test_scan_grep_is_case_insensitive_literal_substring(room_dir: Path, run_cli) -> None:
    for msg in ("Hello world", "literal.dot", "another line"):
        run_cli("send", "kitchen", "-a", "a", "-m", msg)
    rc, out, err = run_cli("scan", "kitchen", "grep", "hello")
    assert rc == 0
    assert "Hello world" in out

    rc, out, err = run_cli("scan", "kitchen", "grep", ".")
    assert rc == 0
    assert "literal.dot" in out
    assert "Hello world" not in out
    assert "another line" not in out


def test_scan_grep_count_flag(room_dir: Path, run_cli) -> None:
    for i in range(4):
        run_cli("send", "kitchen", "-a", "a", "-m", f"x{i}")
    rc, out, err = run_cli("scan", "kitchen", "grep", "x", "-c")
    assert rc == 0
    assert "4" in err  # count to stderr


def test_monitor_backfill_all_cap(room_dir: Path) -> None:
    """--backfill -1 must cap at SOFT_CAP (50_000) and warn on stderr."""
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    # Seed just 5 records; the cap should NOT trigger.
    for i in range(5):
        subprocess.run(
            [sys.executable, str(BIN / "simple-room-send"),
             "kitchen", "-a", "alice", "-m", f"m{i}"],
            check=True, env=env,
        )
    proc = _start_monitor(
        room_dir, "kitchen", "--backfill", "-1",
        "--no-exclude-self", agent="alice",
    )
    try:
        out = _drain(proc, timeout=2.0)
        err = b""
        try:
            proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            err = proc.stderr.read() if proc.stderr else b""
    finally:
        _stop(proc)
    assert "m0" in out and "m4" in out
    # No cap warning when under SOFT_CAP.
    assert "capped" not in out
    assert b"capped" not in err


def test_scan_unknown_subcommand(room_dir: Path, run_cli) -> None:
    rc, out, err = run_cli("scan", "kitchen", "bogus")
    assert rc == 2
    assert "unknown subcommand" in err


# ---------------------------------------------------------------------------
# simple-room-monitor
# ---------------------------------------------------------------------------


def _start_monitor(room_dir: Path, *args: str, agent: str | None = None,
                   ) -> subprocess.Popen:
    cmd = [sys.executable, str(BIN / "simple-room-monitor"), *args]
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    if agent is not None:
        env["SIMPLE_AGENT_ID"] = agent
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _drain(proc: subprocess.Popen, timeout: float = 1.5) -> str:
    """Read whatever the subprocess has emitted within `timeout` seconds.

    A reader thread blocks on ``read1`` and accumulates chunks; the main
    thread waits up to ``timeout`` (or until a newline arrives) and then
    returns what we have.  This avoids the ``select`` /
    ``BufferedReader`` fd ownership dance.
    """
    chunks: list[bytes] = []
    saw_newline = threading.Event()

    def reader() -> None:
        try:
            while True:
                c = proc.stdout.read1(4096)
                if not c:
                    break
                chunks.append(c)
                if b"\n" in c:
                    saw_newline.set()
        except (ValueError, OSError):
            pass
        finally:
            saw_newline.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    saw_newline.wait(timeout=timeout)
    if saw_newline.is_set():
        # Give the pipe a brief moment for any trailing data
        time.sleep(0.1)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _stop(proc: subprocess.Popen) -> None:
    """Kill a monitor subprocess (no graceful TERM) and drain its pipe.

    pyinotify's notifier loop often swallows SIGTERM, so we go straight
    to SIGKILL and then ``communicate()`` to read the remainder of the
    pipe in one shot.  This function is safe to call multiple times.
    """
    if proc.poll() is not None:
        try:
            proc.stdout.close()
        except Exception:
            pass
        return
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        # Last resort: leave the pipe, the OS will reap on exit.
        try:
            proc.stdout.close()
        except Exception:
            pass


def test_monitor_exclude_self_default(room_dir: Path) -> None:
    # Seed two records, one from alice, one from bob.
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    subprocess.run([sys.executable, str(BIN / "simple-room-send"),
                    "kitchen", "-a", "alice", "-m", "self-msg"],
                   check=True, env=env)
    subprocess.run([sys.executable, str(BIN / "simple-room-send"),
                    "kitchen", "-a", "bob", "-m", "other-msg"],
                   check=True, env=env)
    proc = _start_monitor(room_dir, "kitchen", "--backfill", "2", agent="alice")
    try:
        out = _drain(proc, timeout=2.0)
    finally:
        _stop(proc)
    # Alice's self-msg must be filtered; bob's must be present.
    assert "other-msg" in out
    assert "self-msg" not in out


def test_monitor_no_exclude_self(room_dir: Path) -> None:
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    for who, msg in (("alice", "first"), ("bob", "second")):
        subprocess.run([sys.executable, str(BIN / "simple-room-send"),
                        "kitchen", "-a", who, "-m", msg],
                       check=True, env=env)
    proc = _start_monitor(room_dir, "kitchen", "--backfill", "2",
                          "--no-exclude-self", "--json", agent="alice")
    try:
        out = _drain(proc, timeout=2.0)
    finally:
        _stop(proc)
    assert "first" in out and "second" in out


def test_monitor_live_event(room_dir: Path) -> None:
    """After backfill, a NEW write must appear within ~1s (inotify, not poll)."""
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    proc = _start_monitor(room_dir, "kitchen", "--backfill", "0", agent="watcher")
    try:
        time.sleep(0.3)  # let inotify attach
        t0 = time.time()
        subprocess.run([sys.executable, str(BIN / "simple-room-send"),
                        "kitchen", "-a", "writer", "-m", "ping"],
                       check=True, env=env)
        out = _drain(proc, timeout=2.0).encode("utf-8")
    finally:
        _stop(proc)
    dt = time.time() - t0
    assert b"ping" in out, f"live event not seen in {dt:.2f}s"
    # Sanity: should be well under 1 second.
    assert dt < 1.5, f"inotify latency too high: {dt:.2f}s"


def test_monitor_creates_schema_version(room_dir: Path) -> None:
    proc = _start_monitor(room_dir, "kitchen", "--backfill", "0", agent="watcher")
    try:
        deadline = time.time() + 2.0
        version = room_dir / ".version"
        while time.time() < deadline and not version.exists():
            time.sleep(0.05)
        assert version.read_text() == "1\n"
    finally:
        _stop(proc)


def test_monitor_grep(room_dir: Path) -> None:
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)
    for m in ("apple", "banana", "apricot"):
        subprocess.run([sys.executable, str(BIN / "simple-room-send"),
                        "kitchen", "-a", "alice", "-m", m],
                       check=True, env=env)
    # Monitor as "watcher" (a different agent) so self-filter doesn't
    # drop alice's messages.  Grep is a substring match against the
    # rendered (human or JSON) line, so we match on the unique word.
    proc = _start_monitor(room_dir, "kitchen", "--backfill", "3", "--grep", "ap", agent="watcher")
    try:
        out = _drain(proc, timeout=2.0)
    finally:
        _stop(proc)
    lines = [ln for ln in out.splitlines() if ln]
    assert len(lines) == 2
    assert all("apple" in ln or "apricot" in ln for ln in lines)
    assert all("banana" not in ln for ln in lines)
