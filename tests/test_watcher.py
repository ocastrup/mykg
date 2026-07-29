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


def _entry(tmp_path, **kw):
    defaults = dict(session="Research", folder=tmp_path / "f")
    defaults.update(kw)
    return watcher.WatchEntry(**defaults)


def test_build_request_shape(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 7, 29, 13, 20, 0, tzinfo=timezone.utc)
    entry = _entry(tmp_path, base_schema="schema.ttl", obsidian_vault=True)
    req = watcher.build_request(entry, ["b.md", "a.md"], autopilot=True, now=now)
    assert req["request_id"] == "20260729T132000Z__Research"
    assert req["session"] == "Research"
    assert req["changed_files"] == ["a.md", "b.md"]  # sorted
    assert req["command"] == {
        "subcommand": "extract-graph",
        "append": True,
        "base_schema": "schema.ttl",
        "obsidian_vault": True,
    }
    assert req["execution"] == {"mode": "autopilot", "on_error": "quarantine"}
    assert req["created_by"] == "mykg-watch/1.0"


def test_build_request_supervised_when_not_autopilot(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    req = watcher.build_request(_entry(tmp_path), [], autopilot=False, now=now)
    assert req["execution"]["mode"] == "supervised"
    assert "base_schema" not in req["command"]


def test_write_request_atomic_and_pending_dedupe(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 7, 29, 13, 20, 0, tzinfo=timezone.utc)
    q = tmp_path / "queue"
    req = watcher.build_request(_entry(tmp_path), ["a.md"], autopilot=False, now=now)
    assert watcher.pending_request_exists(q, "Research") is False
    path = watcher.write_request(q, req)
    assert path.name == "20260729T132000Z__Research.request.json"
    assert watcher.pending_request_exists(q, "Research") is True
    # A different session is not seen as pending.
    assert watcher.pending_request_exists(q, "Other") is False
    # Content is valid UTF-8 JSON.
    import json as _json
    assert _json.loads(path.read_text(encoding="utf-8"))["session"] == "Research"


from datetime import datetime, timezone


def _cfg(tmp_path, entries, debounce=600, autopilot=False):
    return watcher.WatchConfig(
        poll_interval_seconds=300,
        debounce_seconds=debounce,
        queue_dir=tmp_path / "queue",
        autopilot=autopilot,
        entries=entries,
    )


def _make_session(sessions_root: Path, name: str) -> None:
    (sessions_root / name).mkdir(parents=True, exist_ok=True)


def test_poll_once_skips_missing_session(tmp_path):
    sessions = tmp_path / "sessions"
    folder = tmp_path / "watch"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path, [watcher.WatchEntry(session="Ghost", folder=folder)])
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime.now(timezone.utc), now_mono=100.0,
        trackers={}, skip_debounce=True,
    )
    assert enq == []  # session dir does not exist


def test_poll_once_enqueues_when_debounce_skipped(tmp_path):
    sessions = tmp_path / "sessions"
    _make_session(sessions, "Research")
    folder = tmp_path / "watch"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path, [watcher.WatchEntry(session="Research", folder=folder)])
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime(2026, 7, 29, tzinfo=timezone.utc),
        now_mono=100.0, trackers={}, skip_debounce=True,
    )
    assert enq == ["Research"]
    assert watcher.pending_request_exists(cfg.queue_dir, "Research")
    # State written so a second identical scan enqueues nothing.
    enq2 = watcher.poll_once(
        cfg, sessions, now_wall=datetime(2026, 7, 29, tzinfo=timezone.utc),
        now_mono=200.0, trackers={}, skip_debounce=True,
    )
    assert enq2 == []


def test_poll_once_debounce_waits_for_quiet(tmp_path):
    sessions = tmp_path / "sessions"
    _make_session(sessions, "Research")
    folder = tmp_path / "watch"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path, [watcher.WatchEntry(session="Research", folder=folder)], debounce=600)
    trackers: dict = {}
    # First cycle: change seen, timer starts, debounce not satisfied.
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime.now(timezone.utc), now_mono=1000.0,
        trackers=trackers, skip_debounce=False,
    )
    assert enq == []
    # Second cycle within debounce window: still waiting.
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime.now(timezone.utc), now_mono=1300.0,
        trackers=trackers, skip_debounce=False,
    )
    assert enq == []
    # Third cycle after quiet period elapsed: fires.
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime.now(timezone.utc), now_mono=1601.0,
        trackers=trackers, skip_debounce=False,
    )
    assert enq == ["Research"]


def test_poll_once_coalesces_when_pending(tmp_path):
    sessions = tmp_path / "sessions"
    _make_session(sessions, "Research")
    folder = tmp_path / "watch"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path, [watcher.WatchEntry(session="Research", folder=folder)])
    # Pre-seed a pending request.
    watcher.write_request(cfg.queue_dir, watcher.build_request(
        watcher.WatchEntry(session="Research", folder=folder), ["a.md"],
        autopilot=False, now=datetime(2026, 7, 28, tzinfo=timezone.utc)))
    enq = watcher.poll_once(
        cfg, sessions, now_wall=datetime.now(timezone.utc), now_mono=100.0,
        trackers={}, skip_debounce=True,
    )
    assert enq == []  # coalesced: did not enqueue a second request
