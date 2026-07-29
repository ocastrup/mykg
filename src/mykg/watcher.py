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


def scan_markdown(folder: Path) -> dict[str, dict]:
    """Return {relpath: {mtime, size}} for all Markdown files under folder."""
    state: dict[str, dict] = {}
    if not folder.exists():
        return state
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in MARKDOWN_SUFFIXES:
            st = p.stat()
            state[str(p.relative_to(folder))] = {"mtime": st.st_mtime, "size": st.st_size}
    return state


def read_state(state_path: Path) -> dict[str, dict]:
    """Return the persisted {relpath: {mtime, size}} map, or {} if absent."""
    if not state_path.exists():
        return {}
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return data.get("files", {})


def write_state(state_path: Path, session: str, files: dict[str, dict], now: datetime) -> None:
    """Atomically persist the enqueued snapshot for a session."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session": session,
        "last_enqueued": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(state_path)


def changed_set(current: dict[str, dict], previous: dict[str, dict]) -> set[str]:
    """Return relpaths that are new or whose (mtime, size) differs."""
    changed: set[str] = set()
    for rel, meta in current.items():
        prev = previous.get(rel)
        if prev is None or prev.get("mtime") != meta["mtime"] or prev.get("size") != meta["size"]:
            changed.add(rel)
    return changed


def request_id(session: str, now: datetime) -> str:
    """Sortable timestamp + session, e.g. 20260729T132000Z__Research."""
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}__{session}"


def build_request(
    entry: WatchEntry, changed_files: list[str], autopilot: bool, now: datetime
) -> dict:
    """Build the extraction-request envelope for one session."""
    command: dict = {"subcommand": "extract-graph", "append": True}
    if entry.base_schema:
        command["base_schema"] = entry.base_schema
    command["obsidian_vault"] = entry.obsidian_vault
    return {
        "request_id": request_id(entry.session, now),
        "session": entry.session,
        "folder": str(entry.folder),
        "changed_files": sorted(changed_files),
        "command": command,
        "execution": {
            "mode": "autopilot" if autopilot else "supervised",
            "on_error": "quarantine",
        },
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": CREATED_BY,
    }


def write_request(queue_dir: Path, request: dict) -> Path:
    """Atomically write a request to the queue top-level. Returns the path."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{request['request_id']}.request.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(request, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def pending_request_exists(queue_dir: Path, session: str) -> bool:
    """True if an unprocessed request for this session sits at the queue top-level."""
    if not queue_dir.exists():
        return False
    suffix = f"__{session}.request.json"
    return any(p.name.endswith(suffix) for p in queue_dir.glob("*.request.json"))



@dataclass
class DebounceState:
    last_snapshot: dict[str, dict] = field(default_factory=dict)
    last_change_at: float | None = None


def poll_once(
    cfg: WatchConfig,
    sessions_root: Path,
    *,
    now_wall: datetime,
    now_mono: float,
    trackers: dict[str, "DebounceState"],
    skip_debounce: bool = False,
) -> list[str]:
    """Run one scan/enqueue cycle across all entries. Returns enqueued session names.

    ``now_wall`` is a timezone-aware datetime for request/state stamps.
    ``now_mono`` is a monotonic seconds value for debounce math.
    ``trackers`` is mutated in place to carry debounce state across cycles.
    ``skip_debounce`` fires immediately on any change (used by ``--once``).
    """
    enqueued: list[str] = []
    state_dir = cfg.queue_dir / "_state"
    for entry in cfg.entries:
        if not entry.enabled:
            continue
        if not (sessions_root / entry.session).exists():
            log.warning(
                "watch: session '%s' not found under %s — skipping (create it first)",
                entry.session, sessions_root,
            )
            continue
        if not entry.folder.exists():
            log.warning(
                "watch: folder %s for session '%s' not found — skipping",
                entry.folder, entry.session,
            )
            continue

        current = scan_markdown(entry.folder)
        state_path = state_dir / f"{entry.session}.state.json"
        previous = read_state(state_path)
        changed = changed_set(current, previous)
        tracker = trackers.setdefault(entry.session, DebounceState())

        if not changed:
            tracker.last_snapshot = current
            tracker.last_change_at = None
            continue

        # (Re)start the debounce timer whenever the changed snapshot moves.
        if current != tracker.last_snapshot:
            tracker.last_snapshot = current
            tracker.last_change_at = now_mono

        quiet_ok = skip_debounce or (
            tracker.last_change_at is not None
            and (now_mono - tracker.last_change_at) >= cfg.debounce_seconds
        )
        if not quiet_ok:
            continue

        if pending_request_exists(cfg.queue_dir, entry.session):
            log.info("watch: session '%s' already pending — coalescing", entry.session)
            continue

        request = build_request(entry, sorted(changed), cfg.autopilot, now_wall)
        write_request(cfg.queue_dir, request)
        write_state(state_path, entry.session, current, now_wall)
        tracker.last_change_at = None
        enqueued.append(entry.session)
        log.info(
            "watch: enqueued request for session '%s' (%d changed file(s))",
            entry.session, len(changed),
        )
    return enqueued
