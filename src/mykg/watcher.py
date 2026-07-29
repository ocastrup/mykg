"""Watch-folder trigger for mykg.

A polling daemon that diffs a per-session Markdown state manifest, debounces,
and enqueues JSON extraction-requests into a durable global queue. A host coding
agent (/mykg watch) drains the queue and runs `extract-graph --append`.

All file I/O uses UTF-8 explicitly. Pure functions take explicit paths/clocks so
they are deterministically testable; only `run_daemon` reads global config.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from mykg.logging import get

log = get("mykg.watcher")

MARKDOWN_SUFFIXES = {".md", ".markdown"}
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_DEBOUNCE_SECONDS = 600
DEFAULT_QUEUE_DIR = "_watch_queue"
CREATED_BY = "mykg-watch/1.0"


@dataclass(frozen=True)
class WatchEntry:
    session: str
    folder: Path
    base_schema: str | None = None
    obsidian_vault: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class WatchConfig:
    poll_interval_seconds: int
    debounce_seconds: int
    queue_dir: Path
    autopilot: bool
    entries: list[WatchEntry]


def load_watch_config(raw: dict, sessions_root: Path) -> WatchConfig:
    """Build a validated WatchConfig from the raw YAML dict."""
    block = raw.get("watch")
    if block is None:
        raise KeyError("mykg_config.yaml has no top-level 'watch:' block")
    if not isinstance(block, dict):
        raise ValueError("'watch:' must be a mapping")

    poll = int(block.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS))
    debounce = int(block.get("debounce_seconds", DEFAULT_DEBOUNCE_SECONDS))
    autopilot = bool(block.get("autopilot", False))

    queue_path = Path(str(block.get("queue_dir", DEFAULT_QUEUE_DIR)))
    if not queue_path.is_absolute():
        queue_path = sessions_root / queue_path

    entries_raw = block.get("entries", []) or []
    if not isinstance(entries_raw, list):
        raise ValueError("'watch.entries' must be a list")

    entries: list[WatchEntry] = []
    for i, e in enumerate(entries_raw):
        if not isinstance(e, dict):
            raise ValueError(f"watch.entries[{i}] must be a mapping")
        if not e.get("session"):
            raise ValueError(f"watch.entries[{i}] missing required 'session'")
        if not e.get("folder"):
            raise ValueError(f"watch.entries[{i}] missing required 'folder'")
        entries.append(
            WatchEntry(
                session=str(e["session"]),
                folder=Path(str(e["folder"])),
                base_schema=str(e["base_schema"]) if e.get("base_schema") else None,
                obsidian_vault=bool(e.get("obsidian_vault", False)),
                enabled=bool(e.get("enabled", True)),
            )
        )
    return WatchConfig(
        poll_interval_seconds=poll,
        debounce_seconds=debounce,
        queue_dir=queue_path,
        autopilot=autopilot,
        entries=entries,
    )
