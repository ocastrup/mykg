"""Tests for the top-level watch config block and exposed constants."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
WATCH_KEYS = {"poll_interval_seconds", "debounce_seconds", "queue_dir", "autopilot", "entries"}


def _raw(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def test_watch_block_present_in_both_configs():
    for rel in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        raw = _raw(rel)
        assert "watch" in raw, f"{rel}: missing top-level watch block"
        assert WATCH_KEYS <= set(raw["watch"]), f"{rel}: watch keys {set(raw['watch'])}"


def test_watch_defaults_are_300_and_600():
    raw = _raw("mykg_config.yaml")
    assert raw["watch"]["poll_interval_seconds"] == 300
    assert raw["watch"]["debounce_seconds"] == 600
    assert raw["watch"]["autopilot"] is False


def test_root_and_packaged_watch_blocks_match():
    root = _raw("mykg_config.yaml")["watch"]
    pkg = _raw("src/mykg/data/mykg_config.yaml")["watch"]
    for key in ("poll_interval_seconds", "debounce_seconds", "queue_dir", "autopilot"):
        assert root[key] == pkg[key], key


def test_config_exposes_watch_constants():
    import mykg.config as c

    assert isinstance(c.WATCH_POLL_INTERVAL_SECONDS, int)
    assert isinstance(c.WATCH_DEBOUNCE_SECONDS, int)
    assert isinstance(c.WATCH_QUEUE_DIR, str) and c.WATCH_QUEUE_DIR
    assert isinstance(c.WATCH_AUTOPILOT, bool)
    assert isinstance(c.WATCH_ENTRIES, list)
