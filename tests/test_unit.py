"""
Unit tests for simple_agent_room_lib — all in-process, no subprocesses.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

import simple_agent_room_lib as lib


# ---------------------------------------------------------------------------
# format / parse roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("msg", [
    "plain",
    "has\nnewline",
    "has\ttab",
    "has\\backslash",
    "has\nmixed\ttab\\and-back",
    "unicode: \u00e9\u00f6 \u4e2d\u6587 \U0001F600",
    "  leading and trailing  ",
    "x" * 1000,
])
def test_format_parse_roundtrip(msg: str) -> None:
    line = lib.format_record("alice", msg)
    assert "\n" not in line  # one line, no embedded literal newline
    rec = lib.parse_record(line)
    assert rec is not None
    assert rec["msg"] == msg
    assert rec["agent"] == "alice"
    assert rec["kind"] == "msg"
    assert isinstance(rec["id"], str) and len(rec["id"]) == 32  # uuid4 hex
    assert isinstance(rec["ts"], str)


def test_format_record_kind() -> None:
    for kind in ("msg", "system", "meta"):
        rec = lib.parse_record(lib.format_record("alice", "x", kind=kind))
        assert rec["kind"] == kind


def test_format_record_invalid_kind_defaults_to_msg() -> None:
    rec = lib.parse_record(lib.format_record("alice", "x", kind="bogus"))
    assert rec["kind"] == "msg"


def test_format_record_explicit_id_ts_seq() -> None:
    line = lib.format_record(
        "alice", "x", kind="msg", seq=42,
        record_id="deadbeef", ts="2026-01-01T00:00:00Z",
    )
    rec = lib.parse_record(line)
    assert rec["id"] == "deadbeef"
    assert rec["ts"] == "2026-01-01T00:00:00Z"
    assert rec["seq"] == 42


def test_format_record_rejects_invalid_agent() -> None:
    for bad in ("", "has space", "x" * 65, "weird!char", "../etc"):
        with pytest.raises(ValueError):
            lib.format_record(bad, "x")


# ---------------------------------------------------------------------------
# parse_record edge cases
# ---------------------------------------------------------------------------


def test_parse_record_blank() -> None:
    assert lib.parse_record("") is None
    assert lib.parse_record("\n") is None
    assert lib.parse_record("   \n") is None


def test_parse_record_comment() -> None:
    assert lib.parse_record("# a header\n") is None
    assert lib.parse_record("#{" ) is None  # even if it looks like JSON


def test_parse_record_malformed() -> None:
    assert lib.parse_record("not json") is None
    assert lib.parse_record("{") is None
    assert lib.parse_record("[1, 2]") is None  # not a dict


def test_parse_record_crlf() -> None:
    rec = lib.parse_record('{"id":"a","ts":"2026-01-01T00:00:00Z","agent":"a","msg":"m","kind":"msg"}\r\n')
    assert rec is not None
    assert rec["agent"] == "a"


# ---------------------------------------------------------------------------
# room_path / room_dir
# ---------------------------------------------------------------------------


def test_room_path_default_creates_dir(room_dir: Path) -> None:
    p = lib.room_path("kitchen")
    assert p == room_dir / "kitchen.log"
    assert p.parent == room_dir
    assert p.parent.is_dir()


def test_room_path_rejects_invalid_name(room_dir: Path) -> None:
    for bad in ("", "has space", "x" * 65, "../etc", "weird!char"):
        with pytest.raises(ValueError):
            lib.room_path(bad)


def test_room_path_env_override(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "other"
    monkeypatch.setenv("SIMPLE_AGENT_ROOM_DIR", str(other))
    p = lib.room_path("x")
    assert p == other / "x.log"
    assert other.is_dir()


# ---------------------------------------------------------------------------
# default_agent
# ---------------------------------------------------------------------------


def test_default_agent_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_AGENT_ID", "alice")
    monkeypatch.delenv("USER", raising=False)
    assert lib.default_agent() == "alice"


def test_default_agent_env_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLE_AGENT_ID", "has space")
    monkeypatch.setenv("USER", "bob")
    monkeypatch.setenv("HOSTNAME", "")
    # Falls back to $USER-<pid>; the env value is rejected.
    a = lib.default_agent()
    assert "has space" not in a
    assert a.startswith("bob-")
    assert str(os.getpid()) in a


def test_default_agent_user_host_pid(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLE_AGENT_ID", raising=False)
    monkeypatch.setenv("USER", "u")
    monkeypatch.setenv("HOSTNAME", "h1")
    a = lib.default_agent()
    assert a == f"u-h1-{os.getpid()}"


# ---------------------------------------------------------------------------
# iter_records / record_count / active_agents / latest_seq_for
# ---------------------------------------------------------------------------


def test_iter_records_skips_blank_and_bad(room_dir: Path) -> None:
    p = lib.room_path("kitchen")
    p.write_text(
        "\n"
        "# header\n"
        'not json\n'
        '{\n'  # malformed
        '{"id":"a","ts":"2026-01-01T00:00:00Z","agent":"x","msg":"ok","kind":"msg"}\n'
        "\n"
    )
    recs = list(lib.iter_records(p))
    assert len(recs) == 1
    assert recs[0]["agent"] == "x"


def test_record_count_matches_iter(room_dir: Path) -> None:
    p = lib.room_path("kitchen")
    for i in range(7):
        lib.append_record(p, lib.format_record(f"a{i}", f"m{i}"))
    assert lib.record_count(p) == 7
    # Mixed in blank + comment + malformed lines.
    # (blank and '#' lines are ignored; malformed non-blank lines are counted
    # by record_count's simple line-counter, but iter_records skips them).
    with p.open("a") as f:
        f.write("\n# comment\nnot json\n")
    assert lib.record_count(p) == 8  # 7 valid + 1 malformed
    assert sum(1 for _ in lib.iter_records(p)) == 7


def test_active_agents_window(room_dir: Path) -> None:
    p = lib.room_path("kitchen")
    lib.append_record(p, lib.format_record("alice", "old", ts="2020-01-01T00:00:00Z"))
    lib.append_record(p, lib.format_record("bob", "new", ts=lib.now_iso()))
    active = lib.active_agents(p, window_seconds=60)
    assert "bob" in active
    assert "alice" not in active


def test_latest_seq_for(room_dir: Path) -> None:
    p = lib.room_path("kitchen")
    for s in (3, 7, 1, 9, 4):
        lib.append_record(p, lib.format_record("alice", "x", seq=s))
    lib.append_record(p, lib.format_record("bob", "y", seq=100))
    assert lib.latest_seq_for("alice", p) == 9
    assert lib.latest_seq_for("bob", p) == 100
    assert lib.latest_seq_for("nobody", p) == 0


# ---------------------------------------------------------------------------
# append_record (concurrent)
# ---------------------------------------------------------------------------


def test_concurrent_append_no_torn_lines(room_dir: Path) -> None:
    """50 concurrent appenders should produce 50 valid JSON records."""
    import concurrent.futures as cf
    import subprocess

    p = lib.room_path("kitchen")
    n = 50
    SCR = str(Path(__file__).resolve().parent.parent / "scripts")
    env = os.environ.copy()
    env["SIMPLE_AGENT_ROOM_DIR"] = str(room_dir)

    def send(i: int) -> None:
        subprocess.run(
            [sys.executable, f"{SCR}/simple_room_send.py",
             "kitchen", "-a", f"w{i:02d}", "-m", f"m{i}"],
            check=True, env=env, capture_output=True,
        )

    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(send, range(n)))

    assert lib.record_count(p) == n
    recs = list(lib.iter_records(p))
    assert len(recs) == n
    # Every agent shows up exactly once
    agents = sorted(r["agent"] for r in recs)
    assert agents == sorted(f"w{i:02d}" for i in range(n))
    # Every message body is intact
    msgs = sorted(r["msg"] for r in recs)
    assert msgs == sorted(f"m{i}" for i in range(n))


# ---------------------------------------------------------------------------
# inotify_follow (in-process, single process — we just write+read)
# ---------------------------------------------------------------------------


def test_inotify_follow_sees_new_lines(room_dir: Path) -> None:
    """Start a follower in a background thread, write, observe."""
    import threading

    p = lib.room_path("kitchen")
    p.touch()  # exists before we start following
    seen: list[str] = []
    stop_flag = [False]

    def follow() -> None:
        lib.inotify_follow(
            p,
            on_line=lambda ln: seen.append(ln),
            stop=lambda: stop_flag[0],
        )

    t = threading.Thread(target=follow, daemon=True)
    t.start()
    time.sleep(0.2)  # let inotify attach

    lib.append_record(p, lib.format_record("alice", "first"))
    lib.append_record(p, lib.format_record("bob", "second"))
    # Append a partial line — must not be emitted yet.
    with p.open("a") as f:
        f.write('{"id":"c","ts":"2026-01-01T00:00:00Z","agent":"x","msg":"part')
    time.sleep(0.4)

    stop_flag[0] = True
    t.join(timeout=2.0)

    assert any('"first"' in ln for ln in seen), seen
    assert any('"second"' in ln for ln in seen), seen
    assert not any('"part' in ln for ln in seen), seen

    # Finish the partial line; follower would pick it up if still running.
    with p.open("a") as f:
        f.write('ial","kind":"msg"}\n')
    # (we don't re-attach here; covered by the next test)
