"""Unit tests for mykg.watcher."""
from __future__ import annotations

from pathlib import Path

import pytest

from mykg import watcher


def test_load_watch_config_applies_defaults(tmp_path):
    raw = {"watch": {"entries": [{"session": "S", "folder": str(tmp_path / "f")}]}}
    cfg = watcher.load_watch_config(raw, sessions_root=tmp_path / "sessions")
    assert cfg.poll_interval_seconds == 300
    assert cfg.debounce_seconds == 600
    assert cfg.autopilot is False
    # Relative queue_dir resolves under sessions_root.
    assert cfg.queue_dir == tmp_path / "sessions" / "_watch_queue"
    assert len(cfg.entries) == 1
    e = cfg.entries[0]
    assert e.session == "S"
    assert e.enabled is True
    assert e.base_schema is None


def test_load_watch_config_absolute_queue_dir(tmp_path):
    q = tmp_path / "abs_queue"
    raw = {"watch": {"queue_dir": str(q), "entries": []}}
    cfg = watcher.load_watch_config(raw, sessions_root=tmp_path / "sessions")
    assert cfg.queue_dir == q


def test_load_watch_config_missing_block_raises(tmp_path):
    with pytest.raises(KeyError):
        watcher.load_watch_config({}, sessions_root=tmp_path)


def test_load_watch_config_entry_missing_session_raises(tmp_path):
    raw = {"watch": {"entries": [{"folder": "x"}]}}
    with pytest.raises(ValueError):
        watcher.load_watch_config(raw, sessions_root=tmp_path)
