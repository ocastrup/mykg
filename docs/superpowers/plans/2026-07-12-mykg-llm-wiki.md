# mykg LLM Wiki (`build-wiki`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `mykg build-wiki <session>` command that turns a completed mykg session's graph into a graph-grounded, LLM-authored Obsidian prose vault.

**Architecture:** A new pipeline module `wiki_pipeline.py` with an ordered `STEPS` list, driven by the *existing* `orchestrator.run()`. The wiki reads a finished session read-only (`output/nodes.jsonl`, `output/edges.jsonl`, `intermediate/{edge_metadata,chunk_node_index,file_manifest,schema}.json`) and writes markdown into a vault it solely owns. Entity pages are LLM-generated and grounded in the exact source chunks each node came from; **every `[[wikilink]]` is validated against the graph's real edges in code** (invented links are stripped). Hub and home pages are deterministic. Per-page grounding hashes in a manifest make rebuilds incremental. The orchestrator's state/sentinels live in a dedicated `session/wiki/` dir so `build-wiki` never clobbers the extract session's `intermediate/pipeline_state.json`.

**Tech Stack:** Python 3.12, pydantic (types), PyYAML (config + frontmatter), tiktoken via existing `chunker.py`, `ThreadPoolExecutor` (parallelism), click (CLI), pytest.

## Global Constraints

- All LLM calls go through `ctx.adapter.complete(system, user, context_label="", max_tokens=None, timeout=None) -> str`. Never import a specific adapter.
- All stages over independent items (nodes) MUST use `ThreadPoolExecutor`; worker count from `mykg_config.yaml` (`wiki.max_workers`). Serial loops over nodes are a bug.
- No hardcoded config in code paths that have a config key; read via `mykg.config` constants. Optional keys use `_get_opt(section, key, default)` (same pattern as `OBSIDIAN_ENABLED`).
- `mykg_config.yaml` (repo root) and `src/mykg/data/mykg_config.yaml` (packaged) must stay in sync; a parity test enforces it.
- `chunk_node_index.json` keys are **1-based** (`filename -> {"<chunk_index+1>": [node_id, ...]}`). Chunk text is reconstructed with `chunker.chunk_file(name, content)` and indexed at `chunk_index == key - 1`.
- Tests: use `tmp_path`; stub `adapter.complete()` with a small fake returning canned strings; mark real-network tests `@pytest.mark.live`.
- Ruff clean: `uv run ruff check src/ tests/` and `uv run ruff format src/ tests/`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `mykg_config.yaml` | Modify | Add `wiki:` block under each profile's `pipeline:` |
| `src/mykg/data/mykg_config.yaml` | Modify | Mirror the identical `wiki:` block (parity) |
| `src/mykg/config.py` | Modify | Expose `WIKI_*` constants |
| `src/mykg/wiki/__init__.py` | Create | Package marker |
| `src/mykg/wiki/loader.py` | Create | Read the session contract into typed `WikiGraph` (nodes, edges, per-node grounding) |
| `src/mykg/wiki/page_builder.py` | Create | Pure page rendering: link validator, entity prompt, entity/stub/hub/home rendering, LLM entity generation |
| `src/mykg/wiki/manifest.py` | Create | Grounding-hash manifest: load, plan incremental rebuild, save |
| `src/mykg/wiki_pipeline.py` | Create | The 4 step functions + `WIKI_STEPS` list + path helpers |
| `src/mykg/cli.py` | Modify | Add `build-wiki` subcommand |
| `tests/test_wiki_*.py` | Create | One test module per task |

Data types (defined in `loader.py`, consumed everywhere):

```python
class WikiNode(BaseModel):
    id: str
    type: str
    name: str                          # attributes["name"]["value"] or humanized id
    attributes: dict[str, dict]        # {attr: {"value": Any, "confidence": float}}
    source_files: list[str]
    grounded_chunk_keys: list[str]     # ["file.md::3", ...] (1-based, from chunk_node_index)
    grounded_chunks: list[str]         # reconstructed chunk texts, same order as keys
    grounded: bool                     # bool(grounded_chunks)

class WikiEdge(BaseModel):
    id: str
    type: str
    from_id: str
    to_id: str
    confidence: float

class Neighbor(BaseModel):
    id: str
    name: str
    type: str
    relationship: str                  # edge.type
    confidence: float

class WikiGraph(BaseModel):
    nodes: dict[str, WikiNode]         # keyed by node id
    edges: list[WikiEdge]
    types: list[str]                   # concept type names from schema.json, sorted
    def neighbors(self, node_id: str, min_confidence: float, max_n: int) -> list[Neighbor]: ...
```

---

### Task 1: Config — `wiki:` block, constants, parity test

**Files:**
- Create: `tests/test_wiki_config.py`
- Modify: `mykg_config.yaml`
- Modify: `src/mykg/data/mykg_config.yaml`
- Modify: `src/mykg/config.py`

**Interfaces:**
- Produces: `mykg.config.WIKI_VAULT_DIR: str`, `WIKI_MAX_WORKERS: int`, `WIKI_MIN_ATTR_CONFIDENCE: float`, `WIKI_MIN_EDGE_CONFIDENCE: float`, `WIKI_MAX_GROUNDING_TOKENS: int`, `WIKI_NEIGHBORS_MAX: int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_config.py`:

```python
"""Tests for the wiki config block, constants, and root/packaged parity."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
WIKI_KEYS = {
    "vault_dir",
    "max_workers",
    "min_attr_confidence",
    "min_edge_confidence",
    "max_grounding_tokens",
    "neighbors_max",
}


def _profiles(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())["profiles"]


def test_every_pipeline_profile_has_wiki_block():
    for path in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        for name, prof in _profiles(path).items():
            if "pipeline" not in prof:
                continue
            assert "wiki" in prof["pipeline"], f"{path}:{name} missing pipeline.wiki"
            assert set(prof["pipeline"]["wiki"].keys()) == WIKI_KEYS, f"{path}:{name}"


def test_root_and_packaged_wiki_blocks_match():
    root = _profiles("mykg_config.yaml")
    pkg = _profiles("src/mykg/data/mykg_config.yaml")
    for name in root:
        if "pipeline" in root[name] and "wiki" in root[name]["pipeline"]:
            assert root[name]["pipeline"]["wiki"] == pkg[name]["pipeline"]["wiki"], name


def test_config_exposes_wiki_constants():
    import mykg.config as c

    assert isinstance(c.WIKI_VAULT_DIR, str)
    assert isinstance(c.WIKI_MAX_WORKERS, int)
    assert isinstance(c.WIKI_MIN_ATTR_CONFIDENCE, float)
    assert isinstance(c.WIKI_MIN_EDGE_CONFIDENCE, float)
    assert isinstance(c.WIKI_MAX_GROUNDING_TOKENS, int)
    assert isinstance(c.WIKI_NEIGHBORS_MAX, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_config.py -v`
Expected: FAIL — `pipeline.wiki` missing and `AttributeError: WIKI_VAULT_DIR`.

- [ ] **Step 3: Add `wiki:` block to every profile's `pipeline:` in `mykg_config.yaml`**

For **each** profile block, inside its `pipeline:` mapping, add this block (indent so `wiki:` aligns with sibling sections like `export:` / `ingest:`, children two spaces deeper):

```yaml
      wiki:
        vault_dir: wiki_vault       # relative to session root, or absolute
        max_workers: 4
        min_attr_confidence: 0.3    # drop attributes below this from the LLM prompt
        min_edge_confidence: 0.3    # drop links (and neighbor context) below this
        max_grounding_tokens: 4000  # cap source-chunk text fed per page
        neighbors_max: 25           # cap 1-hop neighbor list per page
```

- [ ] **Step 4: Mirror the identical block into `src/mykg/data/mykg_config.yaml`**

Apply the exact same edit to every profile's `pipeline:` in the packaged template.

- [ ] **Step 5: Add constants to `src/mykg/config.py`**

After the existing `OBSIDIAN_*` / `NEO4J_*` lines (near line 143), add:

```python
# Wiki (build-wiki command) — optional; defaults apply when a profile omits `wiki:`
WIKI_VAULT_DIR: str = _get_opt("wiki", "vault_dir", "wiki_vault")
WIKI_MAX_WORKERS: int = int(_get_opt("wiki", "max_workers", 4))
WIKI_MIN_ATTR_CONFIDENCE: float = float(_get_opt("wiki", "min_attr_confidence", 0.3))
WIKI_MIN_EDGE_CONFIDENCE: float = float(_get_opt("wiki", "min_edge_confidence", 0.3))
WIKI_MAX_GROUNDING_TOKENS: int = int(_get_opt("wiki", "max_grounding_tokens", 4000))
WIKI_NEIGHBORS_MAX: int = int(_get_opt("wiki", "neighbors_max", 25))
```

- [ ] **Step 6: Run tests and lint**

Run: `uv run pytest tests/test_wiki_config.py -v && uv run ruff check src/ tests/`
Expected: 3 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add mykg_config.yaml src/mykg/data/mykg_config.yaml src/mykg/config.py tests/test_wiki_config.py
git commit -m "feat(wiki): add wiki config block, constants, and parity test"
```

---

### Task 2: `wiki/loader.py` — session contract → `WikiGraph`

**Files:**
- Create: `src/mykg/wiki/__init__.py` (empty)
- Create: `src/mykg/wiki/loader.py`
- Create: `tests/test_wiki_loader.py`

**Interfaces:**
- Consumes: `chunker.chunk_file(source_file: str, content: str) -> list[Chunk]` where `Chunk` has `.chunk_index` (0-based) and `.text`.
- Produces: `WikiNode`, `WikiEdge`, `Neighbor`, `WikiGraph` (see File Structure); `load_wiki_graph(session_root: Path) -> WikiGraph`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_loader.py`:

```python
"""Tests for wiki.loader — reading a session contract into a WikiGraph."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.wiki.loader import WikiGraph, load_wiki_graph


def _write_session(root: Path) -> Path:
    out = root / "output"
    inter = root / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    nodes = [
        {"id": "person-alice", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "Alice", "confidence": 0.9},
                        "affiliation": {"value": "Acme", "confidence": 0.2}},
         "source_files": ["doc.md"]},
        {"id": "org-acme", "type": "Organization", "confidence": 0.8,
         "attributes": {"name": {"value": "Acme", "confidence": 0.8}},
         "source_files": ["doc.md"]},
    ]
    (out / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    edges = [{"id": "edge-1", "type": "works_at", "from": "person-alice",
              "to": "org-acme", "confidence": 0.7, "attributes": {}}]
    (out / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    (inter / "edge_metadata.json").write_text(json.dumps({"edge-1": edges[0]}))
    (inter / "chunk_node_index.json").write_text(json.dumps(
        {"doc.md": {"1": ["person-alice"], "2": ["org-acme"]}}))
    # Two chunks worth of content so chunk_file yields >=2 chunks deterministically.
    content = "Alice works at Acme. " * 400 + "\n\n" + "Acme is a company. " * 400
    (inter / "file_manifest.json").write_text(json.dumps(
        {"doc.md": {"content": content, "sha256": "x", "token_count": 10}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]},
                      {"type": "Organization", "parent": None, "attributes": ["name"]}],
         "properties": []}))
    return root


def test_load_returns_nodes_edges_types(tmp_path):
    g = load_wiki_graph(_write_session(tmp_path))
    assert isinstance(g, WikiGraph)
    assert set(g.nodes) == {"person-alice", "org-acme"}
    assert g.nodes["person-alice"].name == "Alice"
    assert g.types == ["Organization", "Person"]
    assert len(g.edges) == 1 and g.edges[0].from_id == "person-alice"


def test_node_grounding_resolves_chunk_text(tmp_path):
    g = load_wiki_graph(_write_session(tmp_path))
    alice = g.nodes["person-alice"]
    assert alice.grounded is True
    assert alice.grounded_chunk_keys == ["doc.md::1"]
    assert "Alice" in alice.grounded_chunks[0]


def test_neighbors_filters_by_confidence_and_caps(tmp_path):
    g = load_wiki_graph(_write_session(tmp_path))
    nb = g.neighbors("person-alice", min_confidence=0.3, max_n=25)
    assert [n.id for n in nb] == ["org-acme"]
    assert nb[0].relationship == "works_at" and nb[0].name == "Acme"
    assert g.neighbors("person-alice", min_confidence=0.8, max_n=25) == []


def test_missing_file_fails_fast(tmp_path):
    root = _write_session(tmp_path)
    (root / "output" / "nodes.jsonl").unlink()
    with pytest.raises(FileNotFoundError, match="nodes.jsonl"):
        load_wiki_graph(root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.loader`.

- [ ] **Step 3: Create the package marker**

Create `src/mykg/wiki/__init__.py` (empty file).

- [ ] **Step 4: Implement the loader**

Create `src/mykg/wiki/loader.py`:

```python
"""Load a completed mykg session (read-only) into a typed WikiGraph."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from mykg.chunker import chunk_file


class WikiNode(BaseModel):
    id: str
    type: str
    name: str
    attributes: dict[str, dict]
    source_files: list[str]
    grounded_chunk_keys: list[str]
    grounded_chunks: list[str]
    grounded: bool


class WikiEdge(BaseModel):
    id: str
    type: str
    from_id: str
    to_id: str
    confidence: float


class Neighbor(BaseModel):
    id: str
    name: str
    type: str
    relationship: str
    confidence: float


class WikiGraph(BaseModel):
    nodes: dict[str, WikiNode]
    edges: list[WikiEdge]
    types: list[str]

    def neighbors(self, node_id: str, min_confidence: float, max_n: int) -> list[Neighbor]:
        best: dict[str, Neighbor] = {}
        for e in self.edges:
            if e.confidence < min_confidence:
                continue
            other = e.to_id if e.from_id == node_id else e.from_id if e.to_id == node_id else None
            if other is None or other not in self.nodes:
                continue
            n = self.nodes[other]
            cand = Neighbor(id=other, name=n.name, type=n.type,
                            relationship=e.type, confidence=e.confidence)
            if other not in best or cand.confidence > best[other].confidence:
                best[other] = cand
        ordered = sorted(best.values(), key=lambda n: (-n.confidence, n.id))
        return ordered[:max_n]


def _require(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Session incomplete — missing {path.name}: {path}")
    return path.read_text(encoding="utf-8")


def _read_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _humanize(node_id: str) -> str:
    return node_id.split("-", 1)[-1].replace("-", " ").title()


def _node_name(raw: dict) -> str:
    val = (raw.get("attributes", {}).get("name", {}) or {}).get("value")
    return val if isinstance(val, str) and val.strip() else _humanize(raw["id"])


def load_wiki_graph(session_root: Path) -> WikiGraph:
    out = session_root / "output"
    inter = session_root / "intermediate"

    raw_nodes = _read_jsonl(_require(out / "nodes.jsonl"))
    raw_edges = _read_jsonl(_require(out / "edges.jsonl"))
    chunk_index = json.loads(_require(inter / "chunk_node_index.json"))
    manifest = json.loads(_require(inter / "file_manifest.json"))
    schema = json.loads(_require(inter / "schema.json"))

    # node_id -> [(filename, chunk_idx_1based)]
    node_to_chunks: dict[str, list[tuple[str, int]]] = {}
    for fname, chunks in chunk_index.items():
        for idx_str, ids in chunks.items():
            for nid in ids:
                node_to_chunks.setdefault(nid, []).append((fname, int(idx_str)))

    # Reconstruct chunk text lazily per file (chunk_index is 0-based; keys are 1-based).
    chunk_text_cache: dict[str, dict[int, str]] = {}

    def _chunk_text(fname: str, idx_1based: int) -> str | None:
        if fname not in chunk_text_cache:
            content = (manifest.get(fname) or {}).get("content", "")
            chunk_text_cache[fname] = {c.chunk_index: c.text for c in chunk_file(fname, content)}
        return chunk_text_cache[fname].get(idx_1based - 1)

    nodes: dict[str, WikiNode] = {}
    for raw in raw_nodes:
        keys: list[str] = []
        texts: list[str] = []
        for fname, idx in sorted(node_to_chunks.get(raw["id"], [])):
            txt = _chunk_text(fname, idx)
            if txt:
                keys.append(f"{fname}::{idx}")
                texts.append(txt)
        nodes[raw["id"]] = WikiNode(
            id=raw["id"], type=raw["type"], name=_node_name(raw),
            attributes=raw.get("attributes", {}), source_files=raw.get("source_files", []),
            grounded_chunk_keys=keys, grounded_chunks=texts, grounded=bool(texts))

    edges = [WikiEdge(id=e["id"], type=e["type"], from_id=e["from"],
                      to_id=e["to"], confidence=float(e.get("confidence", 0.0)))
             for e in raw_edges]
    types = sorted(c["type"] for c in schema.get("concepts", []))
    return WikiGraph(nodes=nodes, edges=edges, types=types)
```

- [ ] **Step 5: Run tests and lint**

Run: `uv run pytest tests/test_wiki_loader.py -v && uv run ruff check src/mykg/wiki tests/test_wiki_loader.py`
Expected: 4 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mykg/wiki/__init__.py src/mykg/wiki/loader.py tests/test_wiki_loader.py
git commit -m "feat(wiki): add loader building WikiGraph with chunk-grounded nodes"
```

---

### Task 3: `wiki/page_builder.py` — link validator + page rendering (pure)

**Files:**
- Create: `src/mykg/wiki/page_builder.py`
- Create: `tests/test_wiki_page_builder.py`

**Interfaces:**
- Consumes: `WikiNode`, `Neighbor` from `wiki.loader`.
- Produces:
  - `strip_invalid_wikilinks(markdown: str, allowed_ids: set[str]) -> tuple[str, list[str]]`
  - `render_entity_page(node: WikiNode, body_markdown: str) -> str`
  - `render_stub_page(node: WikiNode, neighbors: list[Neighbor]) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_page_builder.py`:

```python
"""Tests for the pure page-rendering primitives (link validator, frontmatter)."""
from __future__ import annotations

import yaml

from mykg.wiki.loader import Neighbor, WikiNode
from mykg.wiki.page_builder import (
    render_entity_page,
    render_stub_page,
    strip_invalid_wikilinks,
)


def _node(grounded: bool = True) -> WikiNode:
    return WikiNode(
        id="person-alice", type="Person", name="Alice",
        attributes={"name": {"value": "Alice", "confidence": 0.9}},
        source_files=["doc.md"],
        grounded_chunk_keys=["doc.md::1"] if grounded else [],
        grounded_chunks=["Alice works at Acme."] if grounded else [],
        grounded=grounded)


def test_valid_link_survives_invented_link_stripped():
    md = "Alice joined [[org-acme|Acme]] and knows [[person-ghost|Ghost]]."
    cleaned, dropped = strip_invalid_wikilinks(md, {"org-acme"})
    assert "[[org-acme|Acme]]" in cleaned
    assert "[[person-ghost" not in cleaned
    assert "Ghost" in cleaned          # label preserved as plain text
    assert dropped == ["person-ghost"]


def test_bare_invented_link_stripped_to_text():
    cleaned, dropped = strip_invalid_wikilinks("See [[unknown-id]].", set())
    assert cleaned == "See unknown-id."
    assert dropped == ["unknown-id"]


def test_render_entity_page_has_valid_frontmatter():
    page = render_entity_page(_node(), "## Alice\n\nAlice works at [[org-acme|Acme]].")
    assert page.startswith("---\n")
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["mykg_id"] == "person-alice"
    assert fm["type"] == "Person"
    assert fm["grounded"] is True
    assert fm["grounded_chunks"] == ["doc.md::1"]
    assert "Alice works at [[org-acme|Acme]]." in page


def test_stub_page_flags_ungrounded():
    page = render_stub_page(_node(grounded=False), [Neighbor(
        id="org-acme", name="Acme", type="Organization",
        relationship="works_at", confidence=0.7)])
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is False
    assert "[[org-acme|Acme]]" in page
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_page_builder.py -v`
Expected: FAIL — `ImportError` (functions not defined).

- [ ] **Step 3: Implement the pure primitives**

Create `src/mykg/wiki/page_builder.py`:

```python
"""Pure rendering primitives for wiki pages: link validation + markdown assembly."""
from __future__ import annotations

import re

import yaml

from mykg.wiki.loader import Neighbor, WikiNode

_WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")


def strip_invalid_wikilinks(markdown: str, allowed_ids: set[str]) -> tuple[str, list[str]]:
    """Keep only [[id]] / [[id|label]] whose id is in allowed_ids; others become plain text.

    Returns (cleaned_markdown, dropped_ids_in_order).
    """
    dropped: list[str] = []

    def _sub(m: re.Match) -> str:
        target, label = m.group(1).strip(), m.group(2)
        if target in allowed_ids:
            return m.group(0)
        dropped.append(target)
        return (label or target).strip()

    return _WIKILINK.sub(_sub, markdown), dropped


def _frontmatter(node: WikiNode) -> str:
    data = {
        "mykg_id": node.id,
        "type": node.type,
        "aliases": [node.name],
        "source_files": node.source_files,
        "grounded": node.grounded,
        "grounded_chunks": node.grounded_chunk_keys,
    }
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n"


def render_entity_page(node: WikiNode, body_markdown: str) -> str:
    """Wrap already-validated body markdown with YAML frontmatter."""
    return _frontmatter(node) + body_markdown.strip() + "\n"


def render_stub_page(node: WikiNode, neighbors: list[Neighbor]) -> str:
    """Minimal, never-fabricated page for nodes with no resolvable grounding."""
    lines = [f"# {node.name}", "", f"*{node.type}. No source text was available to summarize.*"]
    if neighbors:
        lines += ["", "## Connections", ""]
        lines += [f"- [[{n.id}|{n.name}]] ({n.relationship})" for n in neighbors]
    return render_entity_page(node, "\n".join(lines))
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_wiki_page_builder.py -v && uv run ruff check src/mykg/wiki`
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/page_builder.py tests/test_wiki_page_builder.py
git commit -m "feat(wiki): add link post-validator and page rendering primitives"
```

---

### Task 4: LLM entity-page generation (prompt, confidence filter, stub fallback)

**Files:**
- Modify: `src/mykg/wiki/page_builder.py`
- Modify: `tests/test_wiki_page_builder.py`

**Interfaces:**
- Consumes: `strip_invalid_wikilinks`, `render_entity_page`, `render_stub_page`; `ctx.adapter.complete(...)`; `chunker.count_tokens`.
- Produces:
  - `build_entity_prompt(node, neighbors, min_attr_confidence, max_grounding_tokens) -> tuple[str, str]`
  - `generate_entity_page(node, neighbors, adapter, min_attr_confidence, max_grounding_tokens) -> str`

- [ ] **Step 1: Write the failing test (append to `tests/test_wiki_page_builder.py`)**

```python
from mykg.wiki.page_builder import build_entity_prompt, generate_entity_page


class _StubAdapter:
    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        self.calls.append(user)
        return self.reply


def _alice_and_neighbor():
    node = WikiNode(
        id="person-alice", type="Person", name="Alice",
        attributes={"name": {"value": "Alice", "confidence": 0.9},
                    "affiliation": {"value": "Acme", "confidence": 0.1}},
        source_files=["doc.md"], grounded_chunk_keys=["doc.md::1"],
        grounded_chunks=["Alice works at Acme."], grounded=True)
    nb = [Neighbor(id="org-acme", name="Acme", type="Organization",
                   relationship="works_at", confidence=0.7)]
    return node, nb


def test_prompt_drops_low_confidence_attributes():
    node, nb = _alice_and_neighbor()
    _system, user = build_entity_prompt(node, nb, min_attr_confidence=0.3,
                                        max_grounding_tokens=4000)
    assert "Alice works at Acme." in user     # grounding included
    assert "org-acme" in user                 # neighbor offered for linking
    assert "affiliation" not in user          # 0.1 < 0.3 filtered out


def test_generate_strips_invented_links_and_wraps():
    node, nb = _alice_and_neighbor()
    reply = "## Alice\n\nWorks at [[org-acme|Acme]] with [[person-ghost|Ghost]]."
    page = generate_entity_page(node, nb, _StubAdapter(reply),
                                min_attr_confidence=0.3, max_grounding_tokens=4000)
    assert "[[org-acme|Acme]]" in page
    assert "person-ghost" not in page
    assert page.startswith("---\n")


def test_blank_reply_falls_back_to_stub():
    node, nb = _alice_and_neighbor()
    page = generate_entity_page(node, nb, _StubAdapter("   "),
                                min_attr_confidence=0.3, max_grounding_tokens=4000)
    import yaml as _y
    fm = _y.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is True             # node had grounding...
    assert "No source text" not in page or "Connections" in page  # stub shape
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_page_builder.py -k "prompt or generate or blank" -v`
Expected: FAIL — `ImportError` for `build_entity_prompt` / `generate_entity_page`.

- [ ] **Step 3: Implement generation (append to `src/mykg/wiki/page_builder.py`)**

Add imports at top (`from mykg.chunker import count_tokens`) and this code:

```python
from mykg.llm.adapter import LLMAdapter

_SYSTEM = (
    "You write concise, factual wiki articles for a personal knowledge base. "
    "Use ONLY the provided source excerpts and attributes — never invent facts. "
    "Write in Markdown: a one-sentence lead defining the subject, a short body "
    "synthesizing the excerpts, then a '## Connections' section. In Connections, "
    "reference related entities ONLY using the exact [[id|Name]] links listed under "
    "'Allowed links'. Do not create any other [[...]] links."
)


def _visible_attributes(node: WikiNode, min_conf: float) -> dict[str, object]:
    out: dict[str, object] = {}
    for name, cell in node.attributes.items():
        if not isinstance(cell, dict):
            continue
        val, conf = cell.get("value"), cell.get("confidence", 0.0)
        if val not in (None, "") and float(conf) >= min_conf:
            out[name] = val
    return out


def _capped_grounding(chunks: list[str], max_tokens: int) -> str:
    kept, total = [], 0
    for c in chunks:
        t = count_tokens(c)
        if total + t > max_tokens and kept:
            break
        kept.append(c)
        total += t
    return "\n\n---\n\n".join(kept)


def build_entity_prompt(node: WikiNode, neighbors: list[Neighbor],
                        min_attr_confidence: float, max_grounding_tokens: int) -> tuple[str, str]:
    attrs = _visible_attributes(node, min_attr_confidence)
    links = "\n".join(f"- [[{n.id}|{n.name}]] — {n.type}, relationship: {n.relationship}"
                      for n in neighbors) or "(none)"
    grounding = _capped_grounding(node.grounded_chunks, max_grounding_tokens)
    user = (
        f"# Subject\nName: {node.name}\nType: {node.type}\n"
        f"Attributes: {attrs}\n\n"
        f"# Allowed links (use these exact wikilinks, and only these)\n{links}\n\n"
        f"# Source excerpts\n{grounding}\n"
    )
    return _SYSTEM, user


def generate_entity_page(node: WikiNode, neighbors: list[Neighbor], adapter: LLMAdapter,
                         min_attr_confidence: float, max_grounding_tokens: int) -> str:
    if not node.grounded:
        return render_stub_page(node, neighbors)
    system, user = build_entity_prompt(node, neighbors, min_attr_confidence, max_grounding_tokens)
    try:
        raw = adapter.complete(system, user, context_label=f"wiki:{node.id}")
    except Exception:
        return render_stub_page(node, neighbors)
    body = LLMAdapter.strip_code_fences(raw).strip() if raw else ""
    if not body:
        return render_stub_page(node, neighbors)
    allowed = {n.id for n in neighbors}
    cleaned, _dropped = strip_invalid_wikilinks(body, allowed)
    return render_entity_page(node, cleaned)
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_wiki_page_builder.py -v && uv run ruff check src/mykg/wiki`
Expected: all passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/page_builder.py tests/test_wiki_page_builder.py
git commit -m "feat(wiki): add grounded entity-page generation with stub fallback"
```

---

### Task 5: `wiki/manifest.py` — grounding hash + incremental rebuild plan

**Files:**
- Create: `src/mykg/wiki/manifest.py`
- Create: `tests/test_wiki_manifest.py`

**Interfaces:**
- Consumes: `WikiGraph`, `WikiNode`, `Neighbor` from `wiki.loader`.
- Produces:
  - `grounding_hash(node: WikiNode, neighbors: list[Neighbor]) -> str`
  - `class RebuildPlan(BaseModel)`: `to_generate: list[str]`, `to_keep: list[str]`, `to_delete: list[str]`
  - `plan_rebuild(graph, manifest: dict, min_edge_confidence: float, neighbors_max: int, force: bool = False) -> RebuildPlan`
  - `load_manifest(vault_dir: Path) -> dict`
  - `save_manifest(vault_dir: Path, hashes: dict[str, str]) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_manifest.py`:

```python
"""Tests for the incremental-rebuild manifest."""
from __future__ import annotations

from mykg.wiki.loader import Neighbor, WikiEdge, WikiGraph, WikiNode
from mykg.wiki.manifest import (
    grounding_hash,
    load_manifest,
    plan_rebuild,
    save_manifest,
)


def _node(nid="person-alice", chunks=("Alice works at Acme.",)) -> WikiNode:
    return WikiNode(id=nid, type="Person", name="Alice",
                    attributes={"name": {"value": "Alice", "confidence": 0.9}},
                    source_files=["doc.md"], grounded_chunk_keys=["doc.md::1"],
                    grounded_chunks=list(chunks), grounded=bool(chunks))


def _graph(node) -> WikiGraph:
    return WikiGraph(nodes={node.id: node}, edges=[], types=["Person"])


def test_hash_changes_when_chunk_text_changes():
    a = grounding_hash(_node(chunks=("Alice works at Acme.",)), [])
    b = grounding_hash(_node(chunks=("Alice moved to Globex.",)), [])
    assert a != b


def test_hash_stable_for_identical_inputs():
    assert grounding_hash(_node(), []) == grounding_hash(_node(), [])


def test_plan_keeps_unchanged_generates_changed_deletes_removed():
    node = _node()
    manifest = {"pages": {node.id: {"hash": grounding_hash(node, []),
                                    "path": f"entities/{node.id}.md"},
                          "ghost-id": {"hash": "old", "path": "entities/ghost-id.md"}}}
    plan = plan_rebuild(_graph(node), manifest, min_edge_confidence=0.3, neighbors_max=25)
    assert plan.to_keep == [node.id]
    assert plan.to_generate == []
    assert plan.to_delete == ["ghost-id"]


def test_changed_node_is_regenerated():
    manifest = {"pages": {"person-alice": {"hash": "stale",
                                           "path": "entities/person-alice.md"}}}
    plan = plan_rebuild(_graph(_node()), manifest, min_edge_confidence=0.3, neighbors_max=25)
    assert plan.to_generate == ["person-alice"]


def test_force_regenerates_everything():
    node = _node()
    manifest = {"pages": {node.id: {"hash": grounding_hash(node, []),
                                    "path": f"entities/{node.id}.md"}}}
    plan = plan_rebuild(_graph(node), manifest, min_edge_confidence=0.3,
                        neighbors_max=25, force=True)
    assert plan.to_generate == [node.id] and plan.to_keep == []


def test_manifest_roundtrip(tmp_path):
    assert load_manifest(tmp_path) == {"pages": {}}
    save_manifest(tmp_path, {"person-alice": "abc"})
    assert load_manifest(tmp_path)["pages"]["person-alice"]["hash"] == "abc"
    assert load_manifest(tmp_path)["pages"]["person-alice"]["path"] == "entities/person-alice.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.manifest`.

- [ ] **Step 3: Implement the manifest**

Create `src/mykg/wiki/manifest.py`:

```python
"""Per-page grounding-hash manifest driving incremental wiki rebuilds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from mykg.wiki.loader import Neighbor, WikiGraph, WikiNode

_MANIFEST_NAME = ".wiki_manifest.json"


class RebuildPlan(BaseModel):
    to_generate: list[str]
    to_keep: list[str]
    to_delete: list[str]


def grounding_hash(node: WikiNode, neighbors: list[Neighbor]) -> str:
    payload = {
        "attributes": {k: node.attributes[k] for k in sorted(node.attributes)},
        "chunks": node.grounded_chunks,
        "neighbors": sorted((n.id, n.relationship) for n in neighbors),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def plan_rebuild(graph: WikiGraph, manifest: dict, min_edge_confidence: float,
                 neighbors_max: int, force: bool = False) -> RebuildPlan:
    prior = manifest.get("pages", {})
    to_generate, to_keep = [], []
    for nid, node in graph.nodes.items():
        nb = graph.neighbors(nid, min_edge_confidence, neighbors_max)
        current = grounding_hash(node, nb)
        if not force and prior.get(nid, {}).get("hash") == current:
            to_keep.append(nid)
        else:
            to_generate.append(nid)
    to_delete = [nid for nid in prior if nid not in graph.nodes]
    return RebuildPlan(to_generate=sorted(to_generate), to_keep=sorted(to_keep),
                       to_delete=sorted(to_delete))


def load_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _MANIFEST_NAME
    if not path.exists():
        return {"pages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(vault_dir: Path, hashes: dict[str, str]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    pages = {nid: {"hash": h, "path": f"entities/{nid}.md"} for nid, h in hashes.items()}
    (vault_dir / _MANIFEST_NAME).write_text(
        json.dumps({"pages": pages}, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_wiki_manifest.py -v && uv run ruff check src/mykg/wiki`
Expected: 6 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/manifest.py tests/test_wiki_manifest.py
git commit -m "feat(wiki): add grounding-hash manifest for incremental rebuilds"
```

---

### Task 6: Hub + home rendering (deterministic)

**Files:**
- Modify: `src/mykg/wiki/page_builder.py`
- Modify: `tests/test_wiki_page_builder.py`

**Interfaces:**
- Consumes: `WikiGraph`, `WikiNode`.
- Produces:
  - `extract_lead(page_markdown: str) -> str` (first non-heading, non-frontmatter paragraph)
  - `render_hub_page(type_name: str, nodes: list[WikiNode], leads: dict[str, str]) -> str`
  - `render_home_page(graph: WikiGraph, session_name: str, generated_at: str) -> str`

- [ ] **Step 1: Write the failing test (append to `tests/test_wiki_page_builder.py`)**

```python
from mykg.wiki.loader import WikiGraph
from mykg.wiki.page_builder import extract_lead, render_home_page, render_hub_page


def test_extract_lead_skips_frontmatter_and_heading():
    page = "---\nmykg_id: x\n---\n\n## Alice\n\nAlice works at Acme.\n\nMore text."
    assert extract_lead(page) == "Alice works at Acme."


def test_hub_lists_every_entity_of_type():
    nodes = [_node()]  # from earlier in this file (person-alice)
    hub = render_hub_page("Person", nodes, {"person-alice": "Alice works at Acme."})
    assert "# Person" in hub
    assert "[[person-alice|Alice]]" in hub
    assert "Alice works at Acme." in hub


def test_home_links_every_type_hub():
    g = WikiGraph(nodes={"person-alice": _node()}, edges=[], types=["Person", "Organization"])
    home = render_home_page(g, "2026-07-05T08-41-11", "2026-07-12T10:00:00Z")
    assert "[[hubs/Person|Person]]" in home
    assert "[[hubs/Organization|Organization]]" in home
    assert "1" in home  # node count
```

(Note: `_node()` is the helper defined earlier in Task 3's test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_page_builder.py -k "lead or hub or home" -v`
Expected: FAIL — `ImportError` for the new functions.

- [ ] **Step 3: Implement (append to `src/mykg/wiki/page_builder.py`)**

Add `from mykg.wiki.loader import WikiGraph` to the imports, then:

```python
def extract_lead(page_markdown: str) -> str:
    body = page_markdown
    if body.startswith("---\n"):
        body = body.split("---\n", 2)[-1]
    for para in (p.strip() for p in body.split("\n\n")):
        if para and not para.startswith("#") and not para.startswith("*"):
            return " ".join(para.split())
    return ""


def render_hub_page(type_name: str, nodes: list["WikiNode"], leads: dict[str, str]) -> str:
    lines = [f"# {type_name}", "", f"{len(nodes)} ent"
             f"{'ry' if len(nodes) == 1 else 'ries'}.", ""]
    for n in sorted(nodes, key=lambda n: n.name.lower()):
        lead = leads.get(n.id, "")
        suffix = f" — {lead}" if lead else ""
        lines.append(f"- [[{n.id}|{n.name}]]{suffix}")
    return "\n".join(lines) + "\n"


def render_home_page(graph: WikiGraph, session_name: str, generated_at: str) -> str:
    lines = [
        "# Wiki Home", "",
        f"- Entities: {len(graph.nodes)}",
        f"- Relationships: {len(graph.edges)}",
        f"- Source session: `{session_name}`",
        f"- Generated: {generated_at}", "",
        "## Type hubs", "",
    ]
    lines += [f"- [[hubs/{t}|{t}]]" for t in graph.types]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_wiki_page_builder.py -v && uv run ruff check src/mykg/wiki`
Expected: all passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/page_builder.py tests/test_wiki_page_builder.py
git commit -m "feat(wiki): add deterministic hub and home page rendering"
```

---

### Task 7: `wiki_pipeline.py` — steps + `WIKI_STEPS`

**Files:**
- Create: `src/mykg/wiki_pipeline.py`
- Create: `tests/test_wiki_pipeline.py`

**Interfaces:**
- Consumes: `orchestrator.Step`, `orchestrator.PipelineContext`; everything from `wiki.loader`, `wiki.page_builder`, `wiki.manifest`; `mykg.config` constants.
- Produces: `WIKI_STEPS: list[Step]`; `run_wiki_load`, `run_wiki_pages`, `run_wiki_hubs`, `run_wiki_index` (each `(ctx) -> None`); `vault_dir(ctx) -> Path`, `session_root(ctx) -> Path`.

**Background:** the wiki loads once in `wiki_load`, persisting `wiki_graph.json` into `session/wiki/`; later steps reload it (cheap, no re-chunking). `session_root(ctx)` is `ctx.output_dir.parent`; the loader reads the real `session/output` + `session/intermediate`. Sentinels/state live under `ctx.intermediate_dir`, which the CLI (Task 8) sets to `session/wiki/` — never the extract session's `intermediate/`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_pipeline.py`:

```python
"""End-to-end wiki pipeline over a tiny fixture session with a stub adapter."""
from __future__ import annotations

import json
from pathlib import Path

from mykg.orchestrator import PipelineContext
from mykg.wiki_pipeline import (
    WIKI_STEPS,
    run_wiki_hubs,
    run_wiki_index,
    run_wiki_load,
    run_wiki_pages,
    vault_dir,
)


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return "## Alice\n\nAlice works at [[org-acme|Acme]]."

    def endpoint_label(self):
        return "stub"


def _session(tmp_path: Path) -> Path:
    root = tmp_path / "sess"
    out, inter = root / "output", root / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    nodes = [
        {"id": "person-alice", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
         "source_files": ["doc.md"]},
        {"id": "org-acme", "type": "Organization", "confidence": 0.8,
         "attributes": {"name": {"value": "Acme", "confidence": 0.8}},
         "source_files": ["doc.md"]},
    ]
    (out / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    edges = [{"id": "edge-1", "type": "works_at", "from": "person-alice",
              "to": "org-acme", "confidence": 0.7, "attributes": {}}]
    (out / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    (inter / "edge_metadata.json").write_text(json.dumps({"edge-1": edges[0]}))
    (inter / "chunk_node_index.json").write_text(json.dumps(
        {"doc.md": {"1": ["person-alice", "org-acme"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"doc.md": {"content": "Alice works at Acme. " * 50, "sha256": "x", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]},
                      {"type": "Organization", "parent": None, "attributes": ["name"]}],
         "properties": []}))
    return root


def _ctx(root: Path) -> PipelineContext:
    wiki_state = root / "wiki"
    wiki_state.mkdir(parents=True, exist_ok=True)
    return PipelineContext(input_dir=root / "input", output_dir=root / "output",
                           intermediate_dir=wiki_state, adapter=_StubAdapter())


def test_full_pipeline_writes_vault(tmp_path):
    root = _session(tmp_path)
    ctx = _ctx(root)
    for step in (run_wiki_load, run_wiki_pages, run_wiki_hubs, run_wiki_index):
        step(ctx)
    vault = vault_dir(ctx)
    alice = (vault / "entities" / "person-alice.md").read_text()
    assert "[[org-acme|Acme]]" in alice
    assert (vault / "hubs" / "Person.md").exists()
    assert (vault / "hubs" / "Organization.md").exists()
    home = (vault / "Home.md").read_text()
    assert "Entities: 2" in home
    assert (vault / ".wiki_manifest.json").exists()


def test_incremental_second_run_regenerates_nothing(tmp_path):
    root = _session(tmp_path)
    ctx = _ctx(root)
    run_wiki_load(ctx)
    run_wiki_pages(ctx)
    before = (vault_dir(ctx) / "entities" / "person-alice.md").stat().st_mtime_ns
    run_wiki_load(ctx)
    run_wiki_pages(ctx)   # manifest unchanged -> page kept, not rewritten
    after = (vault_dir(ctx) / "entities" / "person-alice.md").stat().st_mtime_ns
    assert before == after


def test_wiki_steps_list_names_and_order():
    assert [s.name for s in WIKI_STEPS] == ["wiki_load", "wiki_pages", "wiki_hubs", "wiki_index"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki_pipeline`.

- [ ] **Step 3: Implement the pipeline**

Create `src/mykg/wiki_pipeline.py`:

```python
"""build-wiki pipeline: render a graph-grounded Obsidian vault from a session."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import mykg.config as cfg
from mykg.orchestrator import PipelineContext, Step
from mykg.wiki.loader import WikiGraph, load_wiki_graph
from mykg.wiki.manifest import grounding_hash, load_manifest, plan_rebuild, save_manifest
from mykg.wiki.page_builder import (
    extract_lead,
    generate_entity_page,
    render_home_page,
    render_hub_page,
)

log = logging.getLogger(__name__)


def session_root(ctx: PipelineContext) -> Path:
    return ctx.output_dir.parent


def vault_dir(ctx: PipelineContext) -> Path:
    configured = Path(cfg.WIKI_VAULT_DIR)
    return configured if configured.is_absolute() else session_root(ctx) / configured


def _graph_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "wiki_graph.json"


def _load_cached_graph(ctx: PipelineContext) -> WikiGraph:
    return WikiGraph.model_validate_json(_graph_path(ctx).read_text(encoding="utf-8"))


def run_wiki_load(ctx: PipelineContext) -> None:
    graph = load_wiki_graph(session_root(ctx))
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    _graph_path(ctx).write_text(graph.model_dump_json(), encoding="utf-8")
    log.info("wiki_load — %d nodes, %d edges", len(graph.nodes), len(graph.edges))


def run_wiki_pages(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    entities = vault / "entities"
    entities.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(vault)
    plan = plan_rebuild(graph, manifest, cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX)
    log.info("wiki_pages — generate=%d keep=%d delete=%d",
             len(plan.to_generate), len(plan.to_keep), len(plan.to_delete))

    for nid in plan.to_delete:
        (entities / f"{nid}.md").unlink(missing_ok=True)

    def _one(nid: str) -> None:
        node = graph.nodes[nid]
        nb = graph.neighbors(nid, cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX)
        page = generate_entity_page(node, nb, ctx.adapter,
                                    cfg.WIKI_MIN_ATTR_CONFIDENCE, cfg.WIKI_MAX_GROUNDING_TOKENS)
        (entities / f"{nid}.md").write_text(page, encoding="utf-8")

    if plan.to_generate:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            list(pool.map(_one, plan.to_generate))

    hashes = {
        nid: grounding_hash(graph.nodes[nid],
                            graph.neighbors(nid, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                                            cfg.WIKI_NEIGHBORS_MAX))
        for nid in graph.nodes
    }
    save_manifest(vault, hashes)


def run_wiki_hubs(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    hubs = vault / "hubs"
    hubs.mkdir(parents=True, exist_ok=True)
    entities = vault / "entities"

    leads: dict[str, str] = {}
    for nid in graph.nodes:
        page = entities / f"{nid}.md"
        if page.exists():
            leads[nid] = extract_lead(page.read_text(encoding="utf-8"))

    by_type: dict[str, list] = {t: [] for t in graph.types}
    for node in graph.nodes.values():
        by_type.setdefault(node.type, []).append(node)
    for type_name, nodes in by_type.items():
        (hubs / f"{type_name}.md").write_text(
            render_hub_page(type_name, nodes, leads), encoding="utf-8")


def run_wiki_index(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (vault / "Home.md").write_text(
        render_home_page(graph, session_root(ctx).name, now), encoding="utf-8")


WIKI_STEPS: list[Step] = [
    Step(name="wiki_load", fn=run_wiki_load, outputs=["wiki_graph.json"]),
    Step(name="wiki_pages", fn=run_wiki_pages, outputs=["wiki_pages.done"], is_llm_step=True),
    Step(name="wiki_hubs", fn=run_wiki_hubs, outputs=["wiki_hubs.done"]),
    Step(name="wiki_index", fn=run_wiki_index, outputs=["wiki_index.done"]),
]
```

Note: `wiki_pages`, `wiki_hubs`, `wiki_index` declare `.done` sentinels as `outputs`, but the step functions write pages to the vault, not the sentinel. Add sentinel writes at the end of each of those three functions so the orchestrator's `_is_done` works within a single invocation:

```python
    (ctx.intermediate_dir / "wiki_pages.done").write_text("ok")   # end of run_wiki_pages
    (ctx.intermediate_dir / "wiki_hubs.done").write_text("ok")    # end of run_wiki_hubs
    (ctx.intermediate_dir / "wiki_index.done").write_text("ok")   # end of run_wiki_index
```

- [ ] **Step 4: Add the sentinel writes**

Append the matching sentinel line to the end of each of `run_wiki_pages`, `run_wiki_hubs`, and `run_wiki_index` as shown above.

- [ ] **Step 5: Run tests and lint**

Run: `uv run pytest tests/test_wiki_pipeline.py -v && uv run ruff check src/mykg/wiki_pipeline.py tests/test_wiki_pipeline.py`
Expected: 3 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mykg/wiki_pipeline.py tests/test_wiki_pipeline.py
git commit -m "feat(wiki): add build-wiki pipeline steps (load, pages, hubs, index)"
```

---

### Task 8: CLI `build-wiki` command + `--rebuild` + docs

**Files:**
- Modify: `src/mykg/cli.py`
- Create: `tests/test_wiki_cli.py`

**Interfaces:**
- Consumes: `WIKI_STEPS`, `vault_dir` from `mykg.wiki_pipeline`; `_sessions_root()`, `load_adapter`, `orchestrator.run`, `PipelineContext`.
- Produces: `mykg build-wiki <session> [--rebuild] [--from-step NAME] [--log-file P] [-v]`.

**Behavior:**
- Resolve `session_root = _sessions_root() / session`; error if missing or `output/nodes.jsonl` absent.
- Orchestrator state/sentinels live in `session_root / "wiki"` (never the extract `intermediate/`).
- On a normal run, delete stale `wiki_*.done` sentinels so every step re-runs (page-level incrementality is handled by the manifest). With `--from-step`, keep sentinels and delete from that step onward. With `--rebuild`, also delete `<vault>/.wiki_manifest.json` so every page regenerates.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_cli.py`:

```python
"""CLI wiring for build-wiki."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import cli


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return "## X\n\nBody."

    def endpoint_label(self):
        return "stub"


def _session(sessions_root: Path, name: str) -> None:
    out, inter = sessions_root / name / "output", sessions_root / name / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    (out / "nodes.jsonl").write_text(json.dumps(
        {"id": "person-x", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "X", "confidence": 0.9}},
         "source_files": ["d.md"]}))
    (out / "edges.jsonl").write_text("")
    (inter / "edge_metadata.json").write_text("{}")
    (inter / "chunk_node_index.json").write_text(json.dumps({"d.md": {"1": ["person-x"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"d.md": {"content": "X is a person. " * 40, "sha256": "s", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
         "properties": []}))


def test_build_wiki_missing_session_errors(tmp_path):
    with patch("mykg.cli._sessions_root", return_value=tmp_path):
        res = CliRunner().invoke(cli, ["build-wiki", "nope"])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()


def test_build_wiki_writes_vault(tmp_path):
    _session(tmp_path, "sess1")
    with patch("mykg.cli._sessions_root", return_value=tmp_path), \
         patch("mykg.llm.config.load_adapter", return_value=_StubAdapter()):
        res = CliRunner().invoke(cli, ["build-wiki", "sess1"])
    assert res.exit_code == 0, res.output
    vault = tmp_path / "sess1" / "wiki_vault"
    assert (vault / "entities" / "person-x.md").exists()
    assert (vault / "Home.md").exists()
    # Extract session state must be untouched by the wiki run.
    assert not (tmp_path / "sess1" / "intermediate" / "pipeline_state.json").exists()
    assert (tmp_path / "sess1" / "wiki" / "pipeline_state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_cli.py -v`
Expected: FAIL — no such command `build-wiki`.

- [ ] **Step 3: Implement the command in `src/mykg/cli.py`**

Add after the `merge-graphs` command (near the other `@cli.command` blocks):

```python
@cli.command("build-wiki")
@click.argument("session")
@click.option("--rebuild", is_flag=True, help="Force-regenerate every page (ignore manifest)")
@click.option("--from-step", default=None, help="Resume from a wiki step (wiki_pages, ...)")
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def build_wiki(session, rebuild, from_step, log_file, verbose):
    """Render a graph-grounded Obsidian prose vault from a finished session."""
    from mykg.llm.config import load_adapter
    from mykg.logging import setup
    from mykg.orchestrator import PipelineContext, run
    from mykg.wiki_pipeline import WIKI_STEPS, vault_dir

    session_root = _sessions_root() / session
    if not session_root.is_dir():
        raise click.ClickException(f"Session '{session}' not found at {session_root}.")
    if not (session_root / "output" / "nodes.jsonl").exists():
        raise click.ClickException(
            f"Session '{session}' has no output/nodes.jsonl — run extract-graph first.")

    wiki_state = session_root / "wiki"
    wiki_state.mkdir(parents=True, exist_ok=True)
    if log_file is None:
        log_file = session_root / "wiki.log"
    setup(log_file=log_file, verbose=verbose)
    logging.getLogger(__name__).info("Command: %s", " ".join(sys.argv))

    wiki_step_names = [s.name for s in WIKI_STEPS]
    if from_step:
        if from_step not in wiki_step_names:
            raise click.ClickException(
                f"--from-step must be one of {wiki_step_names}, got '{from_step}'.")
        start = wiki_step_names.index(from_step)
        for name in wiki_step_names[start:]:
            (wiki_state / f"{name}.done").unlink(missing_ok=True)
        (wiki_state / "wiki_graph.json").unlink(missing_ok=True) if from_step == "wiki_load" else None
    else:
        for name in wiki_step_names:
            (wiki_state / f"{name}.done").unlink(missing_ok=True)
        (wiki_state / "wiki_graph.json").unlink(missing_ok=True)

    adapter = load_adapter(intermediate_dir=wiki_state)
    ctx = PipelineContext(
        input_dir=session_root / "input",
        output_dir=session_root / "output",
        intermediate_dir=wiki_state,
        adapter=adapter,
    )
    if rebuild:
        (vault_dir(ctx) / ".wiki_manifest.json").unlink(missing_ok=True)

    run(WIKI_STEPS, ctx)
    click.echo(f"Wiki written to {vault_dir(ctx)}")
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest tests/test_wiki_cli.py -v && uv run ruff check src/mykg/cli.py tests/test_wiki_cli.py`
Expected: 2 passed, ruff clean.

- [ ] **Step 5: Full suite regression check**

Run: `uv run pytest -m "not live" -q`
Expected: previous pass count + the new wiki tests, 0 failures.

- [ ] **Step 6: Document the command + Obsidian handoff in `CLAUDE.md`**

Under the `## Commands` section add:

```bash
uv run mykg build-wiki <session>            # render graph-grounded Obsidian vault
uv run mykg build-wiki <session> --rebuild  # force-regenerate every page
```

And add a short note under the mykg knowledge-graph section:

> The `build-wiki` command owns the `wiki_vault/` under a session and is the sole
> writer of that Obsidian vault. To stop mykg's own stub Obsidian export from
> competing, set `export.obsidian_enabled: false` in your active profile (the
> wiki replaces it). Point Obsidian at `<session>/wiki_vault/`.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/cli.py tests/test_wiki_cli.py CLAUDE.md
git commit -m "feat(wiki): add build-wiki CLI command with incremental + rebuild"
```

---

### Task 9: Live end-to-end smoke test (marked)

**Files:**
- Create: `tests/test_wiki_live.py`

**Interfaces:**
- Consumes: the full `build-wiki` command against a real adapter (active profile).

- [ ] **Step 1: Write the live test**

Create `tests/test_wiki_live.py`:

```python
"""Live end-to-end build-wiki smoke test (real adapter)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_build_wiki_on_latest_session():
    sessions = sorted(Path("mykg_sessions").glob("*/output/nodes.jsonl"))
    if not sessions:
        pytest.skip("no completed session available")
    session = sessions[-1].parent.parent.name
    res = subprocess.run(["uv", "run", "mykg", "build-wiki", session],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    vault = Path("mykg_sessions") / session / "wiki_vault"
    assert (vault / "Home.md").exists()
    assert any((vault / "entities").glob("*.md"))
    # Every wikilink target in every entity page must be a real file in the vault.
    import re
    ids = {p.stem for p in (vault / "entities").glob("*.md")}
    for page in (vault / "entities").glob("*.md"):
        for target in re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", page.read_text()):
            target = target.split("/")[-1]
            assert target in ids or target in {"Person", "Organization"} or \
                (vault / "hubs" / f"{target}.md").exists(), f"dangling link {target} in {page.name}"
```

- [ ] **Step 2: Run the live test (requires a configured provider + a session)**

Run: `uv run pytest tests/test_wiki_live.py -v -m live`
Expected: PASS (or SKIP if no session). Confirm the vault opens cleanly in Obsidian.

- [ ] **Step 3: Verify the excluded-live suite is unaffected**

Run: `uv run pytest -m "not live" -q`
Expected: all pass; the live test is not collected.

- [ ] **Step 4: Commit**

```bash
git add tests/test_wiki_live.py
git commit -m "test(wiki): add live end-to-end build-wiki smoke test"
```

---

## Self-Review

**Spec coverage:**
- ✅ Clippings ingested once by mykg; wiki reads its output — Tasks 2, 7 (no ingest path in wiki).
- ✅ mykg does not write Obsidian; wiki sole vault writer — Task 8 doc + `export.obsidian_enabled: false` note.
- ✅ Standalone re-runnable command — Task 8 (`build-wiki`), decoupled from extract.
- ✅ Data contract (nodes/edges/edge_metadata/chunk_node_index/file_manifest/schema) — Task 2 loader.
- ✅ Grounding rule: attributes + verbatim chunks + 1-hop neighbors only — Tasks 2, 4.
- ✅ Anti-hallucination link post-validator (hard code gate) — Task 3 `strip_invalid_wikilinks`, tested Tasks 3, 4, 9.
- ✅ Confidence filtering of attributes and edges/links — Task 4 (`_visible_attributes`), Task 2 (`neighbors` min_confidence).
- ✅ Empty-grounding stub, `grounded: false`, never fabricated — Tasks 3, 4.
- ✅ Entity pages (LLM) + type hubs + home (deterministic) — Tasks 4, 6, 7.
- ✅ Frontmatter carries `mykg_id`, `type`, `source_files`, `grounded_chunks` — Task 3.
- ✅ Pipeline module driven by existing orchestrator; parallel over nodes — Task 7.
- ✅ Per-page failure → stub, one bad page never fails the build — Task 4 (`try/except` → stub).
- ✅ Incremental rebuilds via grounding hash; skip/regenerate/delete; `--rebuild` — Tasks 5, 7, 8.
- ✅ Config block + parity, tunable per profile — Task 1.
- ✅ State isolation (no clobber of extract `pipeline_state.json`) — Task 7/8 (`session/wiki/` state dir), tested Task 8.
- ✅ Tests: loader, validator, page_builder, hubs/home, manifest/incremental, config parity, cli, live — Tasks 1–9.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output.

**Type consistency:** `WikiNode`/`WikiEdge`/`Neighbor`/`WikiGraph` defined in Task 2 and used unchanged in Tasks 3–7. `strip_invalid_wikilinks`, `render_entity_page`, `render_stub_page`, `build_entity_prompt`, `generate_entity_page`, `extract_lead`, `render_hub_page`, `render_home_page` names are identical across definition (Tasks 3, 4, 6) and use (Task 7). `plan_rebuild`/`grounding_hash`/`load_manifest`/`save_manifest` signatures match between Task 5 and Task 7. `WIKI_STEPS` step names (`wiki_load`, `wiki_pages`, `wiki_hubs`, `wiki_index`) consistent between Task 7 and Task 8. `vault_dir`/`session_root` consistent Task 7 → Task 8.
