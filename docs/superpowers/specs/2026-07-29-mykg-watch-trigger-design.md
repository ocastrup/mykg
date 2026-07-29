# mykg Watch-Folder Trigger — Design Spec

**Date:** 2026-07-29
**Status:** Approved for planning
**Author:** brainstormed with Copilot CLI

## 1. Summary

Add a per-session **watch-folder trigger** to mykg. A new `mykg watch` daemon
polls one or more configured folders for new/modified Markdown files and, after a
debounce quiet-period, enqueues a JSON **extraction-request** into a durable
global queue. A running host coding agent (`/mykg watch` skill loop) drains the
queue and executes `mykg extract-graph --append --session <name>` end-to-end —
including draining the LLM inbox/outbox that agent-mode requires — then moves the
processed request to an audit folder.

Detection and execution are deliberately **split**: the daemon only detects and
enqueues; the host agent executes and answers LLM calls. This keeps agent-mode's
LLM-answering on the host-agent side and lets requests accumulate durably on disk
when no agent is running.

## 2. Goals & Non-Goals

### Goals
- Configure multiple `folder -> session` watch entries in `mykg_config.yaml`.
- Detect new/modified `.md` / `.markdown` files with a polling + state-manifest
  approach (no new dependencies; robust on OneDrive/network-synced folders).
- Fire **one debounced, coalesced** append-request per session after a quiet period.
- Provide a durable, auditable JSON queue (`pending` -> `done\` / `failed\`).
- Provide a host-agent consumer (`/mykg watch` skill loop) that executes requests
  end-to-end and drains the LLM inbox/outbox.
- Support a **global autopilot** flag to run unsupervised (no per-run confirmation).

### Non-Goals (v1, explicitly deferred)
- Non-Markdown conversion (PDF/Office via `parse-docs`).
- Per-entry autopilot (v1 is a single global flag).
- Auto-bootstrapping a not-yet-created session (v1 requires the session to exist).
- `watchdog`/event-based detection (polling only in v1).
- Cross-machine / distributed queue coordination.

## 3. Execution Model

Chosen model: **watcher emits request; host agent executes end-to-end.**

```
mykg_config.yaml (watch: block)
        |
        v
mykg watch  (daemon: polling + state manifest)        <sessions_root>\_watch_queue\
  per entry: scan folder -> diff state --debounce-->  <ts>__<session>.request.json
                                                             |
                                                             v
                                          /mykg watch  (host-agent skill loop)
                                            poll queue -> extract-graph --append
                                            -> drain LLM inbox/outbox
                                            -> move request to done\ (or failed\)
```

Rationale: in the `agent-claude-code` profile the pipeline is a subprocess whose
LLM calls are answered by a host coding agent draining `agent_inbox`/`agent_outbox`.
A standalone daemon cannot answer those calls, so the daemon is restricted to
detection + enqueue, and the host agent owns execution.

## 4. Configuration

New **top-level** `watch:` block in `mykg_config.yaml` (sibling of `paths:`,
provider-independent — not part of any profile). Loaded by `config.py` into a
`WATCH` dict, mirroring how `paths:` is loaded.

```yaml
watch:
  poll_interval_seconds: 300     # daemon folder-scan cadence (default 300)
  debounce_seconds: 600          # quiet period before firing (default 600)
  queue_dir: _watch_queue        # relative to sessions_root, or an absolute path
  autopilot: false               # global: true => skill runs unsupervised
  entries:
    - session: Research
      folder: 'C:\Users\oca\Documents\Obsidian Vault\Research'
      base_schema: '.\src\mykg\data\ontokg-shipai.ttl'   # optional
      obsidian_vault: false                               # optional
      enabled: true
```

### Config semantics
- `poll_interval_seconds` (default **300**) and `debounce_seconds` (default **600**)
  are read from the `watch:` block; defaults apply when omitted.
- `queue_dir` resolves relative to `paths.sessions_root` unless absolute.
- `autopilot` (default **false**) is global and stamped into every request.
- `entries[].session` must reference an existing session under `sessions_root`.
- `entries[].folder` is the watched directory (scanned recursively).
- Optional per-entry flags (`base_schema`, `obsidian_vault`, ...) are forwarded
  into the request's `command` block.
- `entries[].enabled: false` skips the entry.

### Config validation
- Malformed `watch:` block (missing required keys, wrong types) -> daemon fails
  fast at startup with a clear message, before any polling.

## 5. The `mykg watch` Daemon

New Click command `mykg watch [--once] [--verbose]`; logic in a new module
`src/mykg/watcher.py`.

### Per-cycle loop (every `poll_interval_seconds`)
1. Reload `watch.entries` from config (pick up edits between cycles); skip
   `enabled: false`.
2. For each entry, verify the target session exists under `sessions_root`.
   Missing -> log `WARN`, skip (no bootstrap).
3. Scan `folder` recursively for `*.md` / `*.markdown`; build current state map
   `{relpath: {mtime, size}}`.
4. Diff against persisted `<queue_dir>\_state\<session>.state.json`; the
   **changed set** = paths that are new or whose `(mtime, size)` differs from the
   last *enqueued* snapshot.
5. Debounce: track `last_change_at` per entry (updated whenever the changed set is
   non-empty and differs from the previous cycle). Fire only when the changed set
   is non-empty **and** `now - last_change_at >= debounce_seconds`.
6. Dedupe: do **not** enqueue if a top-level `*.request.json` for that session is
   already pending in the queue.
7. On fire -> write one request (Section 6) atomically, then update the state
   file to the just-enqueued snapshot so the same files do not re-fire.

### State manifest — `<queue_dir>\_state\<session>.state.json`
```json
{
  "session": "Research",
  "last_enqueued": "2026-07-29T13:20:00Z",
  "files": { "notes\\a.md": { "mtime": 1730200000.0, "size": 4096 } }
}
```
Persisted so restarts do not re-fire already-processed files. All file I/O uses
`encoding="utf-8"`.

### `--once`
Runs a single scan/enqueue cycle and exits (testing / cron). Default runs forever
until interrupted.

## 6. Request JSON & Queue Contract

### Queue layout (under `sessions_root`, or absolute `queue_dir`)
```
_watch_queue\
  <ts>__<session>.request.json      # pending
  done\    <ts>__<session>.request.json   # processed OK (audit)
  failed\  <ts>__<session>.request.json   # errored (audit + retry source)
  _state\  <session>.state.json           # daemon manifests
  watch.log                                # daemon log
```
Filename example: `20260729T132000Z__Research.request.json` (sortable timestamp +
session for triage).

### Request envelope (written atomically: `.tmp` -> `replace`, UTF-8)
```json
{
  "request_id": "20260729T132000Z__Research",
  "session": "Research",
  "folder": "C:\\Users\\oca\\Documents\\Obsidian Vault\\Research",
  "changed_files": ["notes\\a.md", "notes\\b.md"],
  "command": {
    "subcommand": "extract-graph",
    "append": true,
    "base_schema": ".\\src\\mykg\\data\\ontokg-shipai.ttl",
    "obsidian_vault": false
  },
  "execution": { "mode": "autopilot", "on_error": "quarantine" },
  "created_at": "2026-07-29T13:20:00Z",
  "created_by": "mykg-watch/1.0"
}
```

- `changed_files` is **advisory** (logging/audit only). `extract-graph --append`
  re-derives new/modified files from the session manifest and is authoritative.
- `command` is stored **structured** (not a shell string) to avoid quoting bugs
  and let the agent validate flags against live `--help`.
- `execution.mode` is `"autopilot"` or `"supervised"`, taken from global
  `watch.autopilot`. `on_error` is `"quarantine"` in v1.

### Processing contract
- The agent picks the **oldest** pending request, executes it, then moves the file
  to `done\` on success or `failed\` on error. Requests are never deleted (audit).
- "In progress" is represented by the request remaining at top-level; it is only
  moved when finished. A crash mid-run leaves it pending -> retried next loop.

## 7. Host-Agent Consumer (`/mykg watch` skill loop)

A new mode in the existing `mykg` skill, invoked as `/mykg watch`
(one-shot) or `/mykg watch --follow` (keeps polling within a bounded wave budget).

### Loop
1. List pending `*.request.json` at queue top-level, sorted oldest-first.
2. Take the oldest. Enforce **serialize-per-session**: if that session already has
   a run in progress (in-loop state), skip to the next session's request.
3. Read `execution.mode`:
   - `supervised` -> restate the resolved command and ask the user to confirm
     (`ask_user`), as in manual runs.
   - `autopilot` -> proceed without asking.
4. Validate the session exists; resolve `command` into
   `uv run mykg extract-graph <folder> --append --session <s> [flags]`, validating
   flags against live `--help`.
5. Launch it, then **drain the LLM inbox/outbox** with parallel subagents (the
   existing wave mechanism).
6. On success -> move request to `done\`. On error (`on_error: quarantine`) ->
   move to `failed\`, record the reason, continue to the next request.
7. Coalesce: after a run finishes, the daemon's next scan folds newer changes into
   a fresh request that the loop then picks up.

### Termination
- `/mykg watch`: process all currently-pending requests, then exit.
- `/mykg watch --follow`: keep polling for a bounded number of waves
  (mirrors the existing 20-wave budget) with a re-invoke hint on exhaustion.

### Autopilot caveats
- The flag is **advisory to the skill**: it governs the skill's own confirmation
  logic only. It cannot override the host CLI's tool-approval/permission settings.
- Unsupervised runs still log every action and quarantine failures for audit and
  re-run.

## 8. Error Handling

| Condition | Behavior |
| --- | --- |
| Missing session (daemon) | `WARN`, skip entry, no enqueue |
| Missing/invalid `folder` | `WARN`, skip entry, other entries keep running |
| Malformed `watch:` config | Daemon fails fast at startup with a clear message |
| Bad flags in `command` | Agent validates vs. live `--help`, moves request to `failed\` with reason |
| Crash mid-run | Request stays pending, retried next loop; `--append` is idempotent |
| Encoding | All file writes use `encoding="utf-8"` (avoids the cp1252 corruption class) |

## 9. Observability

- Daemon logs to stdout and `<queue_dir>\watch.log`: each scan, changed-file
  counts, debounce timers, and enqueues.
- Every request is a durable artifact; `done\` and `failed\` form the audit trail.
- Optional (nice-to-have): a per-request `result.json` written next to the moved
  request in `done\`/`failed\` (exit status, node/edge deltas, duration).

## 10. Testing

pytest, matching the existing suite style. No live LLM calls.

- **Unit:** state-diff detection (new / modified / unchanged), debounce gating,
  dedupe (no second request while one is pending), request-envelope serialization,
  config loading + defaults (300 / 600, autopilot false), config validation errors.
- **Filesystem:** `tmp_path` fake folders; `--once` runs a full scan/enqueue cycle
  deterministically and asserts queue contents.
- **Agent-side:** exercised via `--once` + asserting queue/state, not by running
  the LLM pipeline.

## 11. Affected Code

- `src/mykg/watcher.py` — new: daemon loop, state manifest, request emission.
- `src/mykg/cli.py` — new `watch` Click command.
- `src/mykg/config.py` — load top-level `WATCH` dict with defaults + validation.
- `mykg_config.yaml` — new `watch:` block (documented, `enabled` example).
- `src/mykg/data/skills/mykg/SKILL.md` — new `/mykg watch` consumer mode + queue
  contract.
- `docs/agent-mode.md` — cross-reference the watch trigger and queue protocol.
- `tests/` — new tests per Section 10.

## 12. Open Questions / Future Work

- Per-entry autopilot and per-entry poll/debounce overrides.
- Auto-bootstrap of missing sessions (first non-append run).
- Non-Markdown ingestion via `parse-docs` pre-step.
- `watchdog` event-based detection as an opt-in for local (non-synced) folders.
- Retry policy for `failed\` requests (currently manual re-queue).
