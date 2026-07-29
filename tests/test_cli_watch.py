from __future__ import annotations

import json
from pathlib import Path

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
