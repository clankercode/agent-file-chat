"""
Shared pytest fixtures for the simple-agent-room test suite.

Every test that touches the on-disk format must use the `room_dir` fixture
so it runs in a clean tmp dir and never pollutes the real
~/.cache/simple-agent-room.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make the scripts package importable from this tests/ dir.
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture()
def room_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated SIMPLE_AGENT_ROOM_DIR for one test."""
    d = tmp_path / "rooms"
    d.mkdir()
    monkeypatch.setenv("SIMPLE_AGENT_ROOM_DIR", str(d))
    # Clear any $SIMPLE_AGENT_ID so each test uses the default-agent logic.
    monkeypatch.delenv("SIMPLE_AGENT_ID", raising=False)
    return d


@pytest.fixture()
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture()
def run_cli():
    """Run a simple-room-* CLI as a subprocess and capture (rc, out, err)."""
    def _run(*args: str, stdin: bytes | None = None,
             env_extra: dict | None = None) -> tuple[int, str, str]:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / f"simple_room_{args[0]}.py"),
             *args[1:]],
            input=stdin,
            capture_output=True,
            env=env,
            timeout=15,
        )
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")
    return _run
