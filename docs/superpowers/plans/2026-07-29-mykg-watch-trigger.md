# mykg Watch-Folder Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `mykg watch` daemon that polls per-session folders for new/modified Markdown and enqueues JSON extraction-requests, plus a `/mykg watch` host-agent skill mode that drains the queue and runs `extract-graph --append`.

**Architecture:** A polling daemon (no new deps) diffs a per-session state manifest, debounces, and writes atomic JSON requests to a durable global queue (`pending -> done\/failed\`). A host coding agent consumes the oldest request, runs the CLI, drains the LLM inbox/outbox, and moves the request to an audit folder. Detection and execution are split so agent-mode LLM answering stays on the host-agent side.

**Tech Stack:** Python 3.11+, Click (CLI), PyYAML (config), pytest (tests). Windows-first paths. Spec: `docs/superpowers/specs/2026-07-29-mykg-watch-trigger-design.md`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/mykg/watcher.py` | **New.** Data models (`WatchEntry`, `WatchConfig`), config loader/validator, markdown scan, state manifest I/O, change diff, request build/write, dedupe, `poll_once` cycle, `run_daemon` loop. |
| `src/mykg/config.py` | **Modify.** Expose top-level `WATCH_*` constants + `WATCH_ENTRIES` from the `watch:` block with defaults. |
| `mykg_config.yaml` | **Modify.** Add documented top-level `watch:` block. |
| `src/mykg/data/mykg_config.yaml` | **Modify.** Add identical `watch:` block (packaged template; parity-tested). |
| `src/mykg/cli.py` | **Modify.** Add `@cli.command("watch")` (`--once`, `--verbose`). |
| `src/mykg/data/skills/mykg/SKILL.md` | **Modify.** Add `/mykg watch` consumer mode + queue contract. |
| `docs/agent-mode.md` | **Modify.** Cross-reference the watch trigger + queue protocol. |
| `tests/test_watcher.py` | **New.** Unit tests for watcher pure functions + `poll_once`. |
| `tests/test_watch_config.py` | **New.** Config block parity + constant exposure + validation. |
| `tests/test_cli_watch.py` | **New.** CLI `watch --once` wiring test. |

**Design note (testability):** all watcher logic is pure functions that take explicit paths/timestamps; `run_daemon` is the only part that reads globals. Tests call the pure functions with `tmp_path` and injected clocks — no live LLM, no sleeping.

---

## Task 1: Config block + constants

**Files:**
- Modify: `mykg_config.yaml` (add top-level `watch:` block)
- Modify: `src/mykg/data/mykg_config.yaml` (identical block)
- Modify: `src/mykg/config.py` (expose constants)
- Test: `tests/test_watch_config.py`

- [ ] **Step 1: Add the `watch:` block to `mykg_config.yaml`**

Insert immediately after the top-level `paths:` block (before `profiles:`), matching the existing indentation style:

```yaml
# ---------------------------------------------------------------------------
# Watch — per-session folder triggers. Top-level (profile-independent).
# `mykg watch` polls each folder, debounces, and enqueues a JSON extraction-
# request into <sessions_root>\<queue_dir>\; a /mykg watch host-agent loop runs
# extract-graph --append for the request. See docs/superpowers/specs/
# 2026-07-29-mykg-watch-trigger-design.md.
# ---------------------------------------------------------------------------
watch:
  poll_interval_seconds: 300     # daemon folder-scan cadence
  debounce_seconds: 600          # quiet period before firing a request
  queue_dir: _watch_queue        # relative to sessions_root, or an absolute path
  autopilot: false               # true => /mykg watch runs unsupervised
  entries:
    - session: Research
      folder: 'C:\Users\oca\Documents\Obsidian Vault\Research'
      base_schema: '.\src\mykg\data\ontokg-shipai.ttl'
      obsidian_vault: false
      enabled: false
```

(`enabled: false` in the shipped example so no one accidentally triggers a run.)

- [ ] **Step 2: Add the identical block to `src/mykg/data/mykg_config.yaml`**

Copy the exact same `watch:` block into the packaged template at the same position (after its top-level `paths:` block). The two files must match (Step 6 test enforces parity).

- [ ] **Step 3: Write the failing config test**

Create `tests/test_watch_config.py`:

```python
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
    # Compare everything except the example entries (which may hold user paths).
    for key in ("poll_interval_seconds", "debounce_seconds", "queue_dir", "autopilot"):
        assert root[key] == pkg[key], key


def test_config_exposes_watch_constants():
    import mykg.config as c

    assert isinstance(c.WATCH_POLL_INTERVAL_SECONDS, int)
    assert isinstance(c.WATCH_DEBOUNCE_SECONDS, int)
    assert isinstance(c.WATCH_QUEUE_DIR, str) and c.WATCH_QUEUE_DIR
    assert isinstance(c.WATCH_AUTOPILOT, bool)
    assert isinstance(c.WATCH_ENTRIES, list)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_watch_config.py -v`
Expected: `test_config_exposes_watch_constants` FAILS with `AttributeError: module 'mykg.config' has no attribute 'WATCH_POLL_INTERVAL_SECONDS'` (the YAML-only tests should already pass after Steps 1-2).

- [ ] **Step 5: Expose constants in `src/mykg/config.py`**

Add this block right after the `WIKI_ROOT` line (`WIKI_ROOT: str = _user_paths["wiki_root"]`):

```python
# ---------------------------------------------------------------------------
# Watch — top-level `watch:` block (profile-independent). Defaults applied here
# so the block's optional keys can be omitted.
# ---------------------------------------------------------------------------
_watch = RAW.get("watch", {}) or {}
WATCH_POLL_INTERVAL_SECONDS: int = int(_watch.get("poll_interval_seconds", 300))
WATCH_DEBOUNCE_SECONDS: int = int(_watch.get("debounce_seconds", 600))
WATCH_QUEUE_DIR: str = str(_watch.get("queue_dir", "_watch_queue"))
WATCH_AUTOPILOT: bool = bool(_watch.get("autopilot", False))
WATCH_ENTRIES: list = list(_watch.get("entries", []) or [])
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_watch_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add mykg_config.yaml src/mykg/data/mykg_config.yaml src/mykg/config.py tests/test_watch_config.py
git commit -m "feat(watch): add top-level watch config block and constants"
```

---

## Task 2: Watcher data models + config loader

**Files:**
- Create: `src/mykg/watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_watcher.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mykg.watcher'`.

- [ ] **Step 3: Create `src/mykg/watcher.py` with models + loader**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/watcher.py tests/test_watcher.py
git commit -m "feat(watch): watcher data models and config loader"
```

---

## Task 3: Markdown scan + state manifest + change diff

**Files:**
- Modify: `src/mykg/watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watcher.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -k "scan or changed or state" -v`
Expected: FAIL with `AttributeError: module 'mykg.watcher' has no attribute 'scan_markdown'`.

- [ ] **Step 3: Add scan/state/diff functions to `src/mykg/watcher.py`**

Append after `load_watch_config`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_watcher.py -k "scan or changed or state" -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/watcher.py tests/test_watcher.py
git commit -m "feat(watch): markdown scan, state manifest, and change diff"
```

---

## Task 4: Request build + atomic queue write + dedupe

**Files:**
- Modify: `src/mykg/watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watcher.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -k "build_request or write_request or dedupe" -v`
Expected: FAIL with `AttributeError: module 'mykg.watcher' has no attribute 'build_request'`.

- [ ] **Step 3: Add request/queue functions to `src/mykg/watcher.py`**

Append after `changed_set`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_watcher.py -k "build_request or write_request or dedupe" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/watcher.py tests/test_watcher.py
git commit -m "feat(watch): request envelope, atomic queue write, and dedupe"
```

---

## Task 5: `poll_once` scan cycle with debounce + coalesce

**Files:**
- Modify: `src/mykg/watcher.py`
- Test: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watcher.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_watcher.py -k poll_once -v`
Expected: FAIL with `AttributeError: module 'mykg.watcher' has no attribute 'poll_once'`.

- [ ] **Step 3: Add `DebounceState` + `poll_once` to `src/mykg/watcher.py`**

Append after `pending_request_exists`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_watcher.py -k poll_once -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the whole watcher suite**

Run: `uv run pytest tests/test_watcher.py -v`
Expected: PASS (all tests from Tasks 2-5).

- [ ] **Step 6: Commit**

```bash
git add src/mykg/watcher.py tests/test_watcher.py
git commit -m "feat(watch): poll_once cycle with debounce and coalesce"
```

---

## Task 6: `run_daemon` + `mykg watch` CLI command

**Files:**
- Modify: `src/mykg/watcher.py`
- Modify: `src/mykg/cli.py`
- Test: `tests/test_cli_watch.py`

- [ ] **Step 1: Write the failing CLI test**

Create `tests/test_cli_watch.py`:

```python
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
    assert list((sessions / "_watch_queue").glob("*.request.json")) == [] \
        if (sessions / "_watch_queue").exists() else True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_watch.py -v`
Expected: FAIL — `watch` is not a command (`No such command 'watch'`), so `exit_code != 0`.

- [ ] **Step 3: Add `run_daemon` to `src/mykg/watcher.py`**

Append at the end of `src/mykg/watcher.py`:

```python
def _reload_raw() -> dict:
    """Re-read the raw YAML so the daemon picks up edits between cycles.

    The `watch:` block is top-level (profile-independent), so raw YAML is enough.
    """
    import yaml

    from mykg import config as cfg_mod

    return yaml.safe_load(Path(cfg_mod.CONFIG_PATH).read_text(encoding="utf-8"))


def run_daemon(*, once: bool = False) -> None:
    """Entry point for `mykg watch`. Reads global config and runs the loop."""
    from mykg import config as cfg_mod

    sessions_root = Path(cfg_mod.SESSIONS_DIR)
    cfg = load_watch_config(cfg_mod.RAW, sessions_root)
    for sub in ("done", "failed", "_state"):
        (cfg.queue_dir / sub).mkdir(parents=True, exist_ok=True)

    trackers: dict[str, DebounceState] = {}
    log.info(
        "watch: %d entr(ies) poll=%ds debounce=%ds queue=%s autopilot=%s",
        len(cfg.entries), cfg.poll_interval_seconds, cfg.debounce_seconds,
        cfg.queue_dir, cfg.autopilot,
    )

    if once:
        poll_once(
            cfg, sessions_root,
            now_wall=datetime.now(timezone.utc), now_mono=time.monotonic(),
            trackers=trackers, skip_debounce=True,
        )
        return

    while True:
        try:
            cfg = load_watch_config(_reload_raw(), sessions_root)
        except (KeyError, ValueError) as exc:
            log.error("watch: config reload failed (%s) — keeping previous config", exc)
        poll_once(
            cfg, sessions_root,
            now_wall=datetime.now(timezone.utc), now_mono=time.monotonic(),
            trackers=trackers, skip_debounce=False,
        )
        time.sleep(cfg.poll_interval_seconds)
```

- [ ] **Step 4: Add the `watch` command to `src/mykg/cli.py`**

Insert this command definition immediately after the `extract_graph` function (before the `build-wiki` command, near line 755):

```python
@cli.command("watch")
@click.option(
    "--once",
    is_flag=True,
    help="Run a single scan/enqueue cycle and exit (skips debounce; good for cron/tests).",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging")
def watch(once, verbose):
    """Watch configured folders and enqueue extract-graph --append requests."""
    from mykg.logging import setup
    from mykg.watcher import run_daemon

    setup(verbose=verbose)
    run_daemon(once=once)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_watch.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Verify the command is registered**

Run: `uv run mykg watch --help`
Expected: usage text showing `--once` and `--verbose` options.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/watcher.py src/mykg/cli.py tests/test_cli_watch.py
git commit -m "feat(watch): run_daemon and mykg watch CLI command"
```

---

## Task 7: `/mykg watch` host-agent consumer (skill docs)

**Files:**
- Modify: `src/mykg/data/skills/mykg/SKILL.md`
- Modify: `docs/agent-mode.md`

This task is documentation-only (the consumer runs inside the host coding agent). No code test; verify by reading.

- [ ] **Step 1: Add the `/mykg watch` consumer section to `SKILL.md`**

Append a new top-level section to `src/mykg/data/skills/mykg/SKILL.md`:

````markdown
## Stage 4e — watch-queue consumer (`/mykg watch`)

`/mykg watch` drains the watch-folder request queue produced by the `mykg watch`
daemon. Read `sessions_root` from `mykg_config.yaml` (`paths.sessions_root`) and
the queue dir from `watch.queue_dir` (default `_watch_queue`, relative to
`sessions_root` unless absolute).

Queue layout:

```
<queue_dir>\
  <ts>__<session>.request.json     # pending
  done\    ...                      # processed OK (audit)
  failed\  ...                      # errored (audit)
  _state\  <session>.state.json     # daemon manifests (do not touch)
```

Loop (bounded to 20 waves, then print a re-invoke hint):

1. List pending `*.request.json` at the queue top-level; sort oldest-first by
   filename (timestamps sort lexicographically).
2. Take the oldest. Enforce serialize-per-session: never run two extractions for
   the same session concurrently within this loop.
3. Read the request JSON. Fields: `request_id`, `session`, `folder`,
   `changed_files` (advisory), `command`, `execution`.
4. If `execution.mode == "supervised"`: restate the resolved command and ask the
   user to confirm (as in Stage 2). If `"autopilot"`: proceed without asking.
5. Validate the session exists under `sessions_root`. If missing, move the request
   to `failed\` and continue.
6. Resolve `command` into a CLI call, validating flags against live
   `uv run mykg extract-graph --help`:
   `uv run mykg extract-graph "<folder>" --append --session <session>`
   plus `--base-schema <path>` if `command.base_schema` is set and
   `--obsidian-vault` if `command.obsidian_vault` is true.
7. Launch it and drain the LLM inbox/outbox exactly as in Stage 4a (parallel
   subagents per wave).
8. On success: move the request file to `done\`. On error (`on_error:
   "quarantine"`): move it to `failed\` and continue to the next request. Never
   delete requests.
9. After processing all currently-pending requests, exit. With
   `/mykg watch --follow`, keep polling until the 20-wave budget is spent, then
   print: "Watch budget exhausted — re-invoke /mykg watch to keep draining."

Autopilot is advisory to this skill only; it cannot override the host CLI's own
tool-approval settings. Always keep run logs; failures are quarantined for audit
and manual re-queue (move the file from `failed\` back to the top level).
````

- [ ] **Step 2: Cross-reference from `docs/agent-mode.md`**

Append to `docs/agent-mode.md`:

```markdown
## Watch-folder trigger

The `mykg watch` daemon (see `src/mykg/watcher.py` and
`docs/superpowers/specs/2026-07-29-mykg-watch-trigger-design.md`) polls
per-session folders configured in the top-level `watch:` block of
`mykg_config.yaml` and enqueues JSON extraction-requests into
`<sessions_root>\<queue_dir>\`. The `/mykg watch` skill mode drains that queue,
runs `extract-graph --append` for each request, and answers the resulting LLM
inbox/outbox tasks — the same contract described above, one level up.
```

- [ ] **Step 3: Verify docs render and reference real paths**

Run: `uv run python -c "from pathlib import Path; print(Path('src/mykg/data/skills/mykg/SKILL.md').read_text(encoding='utf-8').count('Stage 4e'))"`
Expected: prints `1`.

- [ ] **Step 4: Commit**

```bash
git add src/mykg/data/skills/mykg/SKILL.md docs/agent-mode.md
git commit -m "docs(watch): /mykg watch consumer contract and agent-mode cross-ref"
```

---

## Task 8: Full-suite regression + final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the watch-related tests together**

Run: `uv run pytest tests/test_watcher.py tests/test_watch_config.py tests/test_cli_watch.py -v`
Expected: PASS (all).

- [ ] **Step 2: Run the full test suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: the full suite passes (same baseline as before this change; the new tests are additive).

- [ ] **Step 3: Smoke-test the daemon end-to-end with `--once`**

Run (PowerShell, from repo root — uses the real config; safe because the shipped entry is `enabled: false`):
```
uv run mykg watch --once --verbose
```
Expected: logs the entry count and, because the example entry is disabled, enqueues nothing and exits cleanly.

- [ ] **Step 4: Final commit (if any docs/config tweaks remain)**

```bash
git add -A
git commit -m "test(watch): full-suite regression pass for watch trigger" --allow-empty
```

---

## Notes for the implementer

- **Windows paths:** the shipped example entry uses backslash paths in single quotes — keep single quotes in YAML so backslashes stay literal (double quotes trigger YAML escape parsing, the bug fixed in `step_validate_graph.py`).
- **UTF-8 everywhere:** every `read_text`/`write_text` in `watcher.py` passes `encoding="utf-8"`. Do not drop it.
- **No sleeping in tests:** debounce is tested by injecting `now_mono`, never by real time. `--once` uses `skip_debounce=True` so it is deterministic.
- **Coalesce invariant:** the state manifest is only written when a request is enqueued, so changes that arrive while a request is pending remain "changed" and fold into the next request after the current one is processed.
