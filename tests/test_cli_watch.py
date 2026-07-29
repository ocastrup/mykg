from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


def test_watch_once_enqueues_request(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions = tmp_path / "sessions"
    (sessions / "Research").mkdir(parents=True)
    folder = tmp_path / "watch"
    folder.mkdir()
    (folder / "a.md").write_text("# hi", encoding="utf-8")

    raw = {
        "watch": {
            "poll_interval_seconds": 300,
            "debounce_seconds": 600,
            "queue_dir": "_watch_queue",
            "autopilot": False,
            "entries": [{"session": "Research", "folder": str(folder), "enabled": True}],
        }
    }
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions))
    monkeypatch.setattr(cfg_mod, "RAW", raw)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["watch", "--once"])
    assert result.exit_code == 0, (result.output, result.exception)

    queue = sessions / "_watch_queue"
    reqs = list(queue.glob("*.request.json"))
    assert len(reqs) == 1
    doc = json.loads(reqs[0].read_text(encoding="utf-8"))
    assert doc["session"] == "Research"
    assert doc["command"]["append"] is True
    # State manifest written.
    assert (queue / "_state" / "Research.state.json").exists()


def test_watch_once_missing_session_no_request(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    folder = tmp_path / "watch"
    folder.mkdir()
    (folder / "a.md").write_text("# hi", encoding="utf-8")

    raw = {"watch": {"entries": [{"session": "Ghost", "folder": str(folder)}]}}
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions))
    monkeypatch.setattr(cfg_mod, "RAW", raw)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["watch", "--once"])
    assert result.exit_code == 0
    queue = sessions / "_watch_queue"
    if queue.exists():
        assert list(queue.glob("*.request.json")) == []


class _StopLoop(Exception):
    """Sentinel used to break run_daemon's infinite loop after one iteration."""


def test_run_daemon_survives_malformed_yaml_reload(tmp_path, monkeypatch):
    """A malformed/half-saved config mid-run must not crash the daemon.

    The reload raises yaml.YAMLError; run_daemon should log and keep the previous
    config, reaching poll_once and the sleep (which we hijack to stop the loop).
    """
    import mykg.config as cfg_mod
    from mykg import watcher

    sessions = tmp_path / "sessions"
    (sessions / "Research").mkdir(parents=True)
    folder = tmp_path / "watch"
    folder.mkdir()

    raw = {"watch": {"entries": [{"session": "Research", "folder": str(folder)}]}}
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions))
    monkeypatch.setattr(cfg_mod, "RAW", raw)

    def _boom():
        raise yaml.YAMLError("while scanning: broken config")

    monkeypatch.setattr(watcher, "_reload_raw", _boom)

    calls = {"n": 0}

    def _fake_sleep(_seconds):
        calls["n"] += 1
        raise _StopLoop()

    monkeypatch.setattr(watcher.time, "sleep", _fake_sleep)

    # Must not raise yaml.YAMLError; the loop reaches the (hijacked) sleep exactly once.
    with pytest.raises(_StopLoop):
        watcher.run_daemon(once=False)
    assert calls["n"] == 1
