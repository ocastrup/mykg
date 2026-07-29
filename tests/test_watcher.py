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


def test_scan_markdown_finds_md_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "sub" / "b.markdown").write_text("y", encoding="utf-8")
    (tmp_path / "c.txt").write_text("z", encoding="utf-8")
    state = watcher.scan_markdown(tmp_path)
    assert set(state) == {"a.md", str(Path("sub") / "b.markdown")}
    assert set(state["a.md"]) == {"mtime", "size"}


def test_scan_markdown_missing_folder_returns_empty(tmp_path):
    assert watcher.scan_markdown(tmp_path / "nope") == {}


def test_changed_set_detects_new_and_modified():
    prev = {"a.md": {"mtime": 1.0, "size": 10}, "b.md": {"mtime": 2.0, "size": 20}}
    cur = {
        "a.md": {"mtime": 1.0, "size": 10},   # unchanged
        "b.md": {"mtime": 2.0, "size": 21},   # size changed
        "c.md": {"mtime": 3.0, "size": 30},   # new
    }
    assert watcher.changed_set(cur, prev) == {"b.md", "c.md"}


def test_state_roundtrip(tmp_path):
    from datetime import datetime, timezone

    sp = tmp_path / "_state" / "S.state.json"
    files = {"a.md": {"mtime": 1.0, "size": 10}}
    watcher.write_state(sp, "S", files, datetime(2026, 7, 29, tzinfo=timezone.utc))
    assert watcher.read_state(sp) == files


def test_read_state_missing_returns_empty(tmp_path):
    assert watcher.read_state(tmp_path / "missing.json") == {}
