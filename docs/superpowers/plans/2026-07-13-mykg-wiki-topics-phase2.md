# mykg Wiki Phase 2 — Synthesized Topic Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mykg build-topics <session>`, a separate opt-in pipeline that clusters the graph into communities, has the LLM write one cross-entity thematic article per community, and emits propose-only, human-gated schema improvement suggestions.

**Architecture:** A second orchestrator-driven `STEPS` pipeline parallel to `build-wiki`, with its own state dir (`<session>/topics_state/`). It reuses the Phase 1 `WikiGraph` loader, wikilink validator, grounding-token cap, and per-node grounding hash. It writes a disjoint set of vault files (`topics/`, `Topics.md`, `schema_proposals.md`, `.topics_manifest.json`) and never mutates the extract session. Community detection is deterministic (confidence-weighted greedy modularity); topic articles and proposals are the only LLM steps and rebuild incrementally by grounding hash.

**Tech Stack:** Python, Click, Pydantic, networkx (`networkx.algorithms.community.greedy_modularity_communities`), the existing `LLMAdapter`, `ThreadPoolExecutor`.

## Global Constraints

- **Base branch:** Implement on top of `refactor/top-level-paths-config` (or after it merges to `main`). This plan's code calls `mykg.wiki_pipeline.vault_dir`, which depends on `cfg.WIKI_ROOT` and the `<wiki_root>/<session>/` vault layout introduced by that refactor. Do **not** base on plain `main` (it still uses `<session>/wiki_vault/` and lacks `WIKI_ROOT`).
- **Spec:** `docs/superpowers/specs/2026-07-13-mykg-wiki-topics-phase2-design.md` is authoritative.
- **Isolation invariant:** build-topics writes only under `<session>/topics_state/` (state) and `<wiki_root>/<session>/` (vault). It **never** writes under the extract session's `output/` or `intermediate/`. Reading those is allowed.
- **Writer disjointness:** build-topics owns `topics/`, `Topics.md`, `schema_proposals.md`, `.topics_manifest.json`. It must never write `Home.md`, `entities/`, `hubs/`, or `.wiki_manifest.json`.
- **Determinism:** clustering must be byte-for-byte reproducible across reruns of an unchanged graph. Sort node ids before graph construction and sort communities by `(-size, first_member_id)`.
- **Parallelism:** all per-item LLM loops (topic pages, proposals) use `ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS)`.
- **Config:** `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml` must stay in sync (a parity test enforces it). No hardcoded defaults in pipeline code — read from `cfg.*`.
- **Commands:** dev uses `uv run pytest -m "not live"`, `uv run ruff check src/ tests/`.

---

### Task 1: Config — `topics:` block and constants

**Files:**
- Modify: `mykg_config.yaml` (add a `topics:` block under `pipeline:` in every profile that has a `wiki:` block)
- Modify: `src/mykg/data/mykg_config.yaml` (same edit, kept identical)
- Modify: `src/mykg/config.py` (add constants after the wiki constants, ~line 150)
- Test: `tests/test_topics_config.py`

**Interfaces:**
- Produces: `cfg.TOPICS_RESOLUTION: float`, `cfg.TOPICS_MIN_SIZE: int`, `cfg.TOPICS_MEMBERS_MAX: int`, `cfg.TOPICS_ENABLED: bool`.

- [ ] **Step 1: Write the failing test**

`tests/test_topics_config.py`:
```python
"""Tests for the topics config block, constants, and root/packaged parity."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
TOPICS_KEYS = {"resolution", "min_size", "members_max", "enabled"}


def _profiles(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())["profiles"]


def test_every_pipeline_profile_has_topics_block():
    for path in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        for name, prof in _profiles(path).items():
            pipe = prof.get("pipeline")
            if not pipe or "wiki" not in pipe:
                continue
            assert "topics" in pipe, f"{path}:{name} missing pipeline.topics"
            assert set(pipe["topics"].keys()) == TOPICS_KEYS, f"{path}:{name}"


def test_root_and_packaged_topics_blocks_match():
    root = _profiles("mykg_config.yaml")
    pkg = _profiles("src/mykg/data/mykg_config.yaml")
    for name in root:
        rp = root[name].get("pipeline", {})
        if "topics" in rp:
            assert rp["topics"] == pkg[name]["pipeline"]["topics"], name


def test_config_exposes_topics_constants():
    import mykg.config as c

    assert isinstance(c.TOPICS_RESOLUTION, float)
    assert isinstance(c.TOPICS_MIN_SIZE, int)
    assert isinstance(c.TOPICS_MEMBERS_MAX, int)
    assert isinstance(c.TOPICS_ENABLED, bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topics_config.py -q --no-cov`
Expected: FAIL — `pipeline.topics` missing / `AttributeError: TOPICS_RESOLUTION`.

- [ ] **Step 3: Add the `topics:` block to both YAML files**

In **each** profile of `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml`, immediately after the profile's `wiki:` block, insert (matching the surrounding indentation — the `wiki:` block sits at 6 spaces under `pipeline:`):
```yaml
      topics:
        resolution: 1.0     # greedy-modularity resolution (higher -> more, smaller communities)
        min_size: 3         # communities smaller than this get no topic page
        members_max: 25     # max members grounded into a topic prompt
        enabled: true       # reserved gate; build-topics is already opt-in via the command
```
Apply to every profile that has a `wiki:` block (both files have the same profile set). Keep the two files byte-identical in this block.

- [ ] **Step 4: Add constants to `src/mykg/config.py`**

After the wiki constants block (the `WIKI_NEIGHBORS_MAX` line, ~line 150), add:
```python
# Topics (build-topics command) — optional; defaults apply when a profile omits `topics:`
TOPICS_RESOLUTION: float = float(_get_opt("topics", "resolution", 1.0))
TOPICS_MIN_SIZE: int = int(_get_opt("topics", "min_size", 3))
TOPICS_MEMBERS_MAX: int = int(_get_opt("topics", "members_max", 25))
TOPICS_ENABLED: bool = bool(_get_opt("topics", "enabled", True))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_topics_config.py -q --no-cov`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add mykg_config.yaml src/mykg/data/mykg_config.yaml src/mykg/config.py tests/test_topics_config.py
git commit -m "feat(topics): add topics config block and constants"
```

---

### Task 2: Deterministic community detection

**Files:**
- Create: `src/mykg/wiki/clustering.py`
- Test: `tests/test_topics_clustering.py`

**Interfaces:**
- Consumes: `mykg.wiki.loader.WikiGraph`.
- Produces:
  - `Community(BaseModel)` with `topic_id: str`, `member_ids: list[str]`
  - `SkippedGroup(BaseModel)` with `member_ids: list[str]`, `reason: str`
  - `Communities(BaseModel)` with `resolution: float`, `communities: list[Community]`, `skipped: list[SkippedGroup]`
  - `build_communities(graph: WikiGraph, min_edge_confidence: float, resolution: float, min_size: int) -> Communities`

- [ ] **Step 1: Write the failing test**

`tests/test_topics_clustering.py`:
```python
from __future__ import annotations

from mykg.wiki.clustering import build_communities
from mykg.wiki.loader import WikiEdge, WikiGraph, WikiNode


def _node(nid: str) -> WikiNode:
    return WikiNode(id=nid, type="Thing", name=nid, attributes={},
                    source_files=[], grounded_chunk_keys=[], grounded_chunks=[], grounded=False)


def _graph() -> WikiGraph:
    # Two clear triangles a-b-c and x-y-z, linked by no edges; plus a loner 'q'.
    ids = ["a", "b", "c", "x", "y", "z", "q"]
    nodes = {i: _node(i) for i in ids}
    def e(i, f, t):
        return WikiEdge(id=i, type="rel", from_id=f, to_id=t, confidence=0.9)
    edges = [e("1", "a", "b"), e("2", "b", "c"), e("3", "a", "c"),
             e("4", "x", "y"), e("5", "y", "z"), e("6", "x", "z")]
    return WikiGraph(nodes=nodes, edges=edges, types=["Thing"])


def test_two_communities_min_size_3():
    comms = build_communities(_graph(), min_edge_confidence=0.3, resolution=1.0, min_size=3)
    members = [set(c.member_ids) for c in comms.communities]
    assert {"a", "b", "c"} in members
    assert {"x", "y", "z"} in members
    assert len(comms.communities) == 2
    # 'q' is isolated (size 1) -> skipped
    assert any(g.member_ids == ["q"] and g.reason == "below_min_size" for g in comms.skipped)


def test_topic_ids_are_stable_ordinals():
    comms = build_communities(_graph(), 0.3, 1.0, 3)
    assert [c.topic_id for c in comms.communities] == ["t0001", "t0002"]


def test_deterministic_across_runs():
    a = build_communities(_graph(), 0.3, 1.0, 3).model_dump()
    b = build_communities(_graph(), 0.3, 1.0, 3).model_dump()
    assert a == b


def test_subthreshold_edges_dropped():
    g = _graph()
    g.edges.append(WikiEdge(id="w", type="rel", from_id="c", to_id="x", confidence=0.1))
    comms = build_communities(g, min_edge_confidence=0.3, resolution=1.0, min_size=3)
    # low-confidence bridge ignored -> still two separate triangles
    assert len(comms.communities) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topics_clustering.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.clustering`.

- [ ] **Step 3: Write the implementation**

`src/mykg/wiki/clustering.py`:
```python
"""Deterministic graph community detection for synthesized topic pages."""
from __future__ import annotations

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities
from pydantic import BaseModel

from mykg.wiki.loader import WikiGraph


class Community(BaseModel):
    topic_id: str
    member_ids: list[str]


class SkippedGroup(BaseModel):
    member_ids: list[str]
    reason: str


class Communities(BaseModel):
    resolution: float
    communities: list[Community]
    skipped: list[SkippedGroup]


def build_communities(graph: WikiGraph, min_edge_confidence: float,
                      resolution: float, min_size: int) -> Communities:
    g = nx.Graph()
    g.add_nodes_from(sorted(graph.nodes))
    for e in graph.edges:
        if e.confidence < min_edge_confidence:
            continue
        if e.from_id not in graph.nodes or e.to_id not in graph.nodes:
            continue
        a, b = sorted((e.from_id, e.to_id))
        if a == b:
            continue
        if g.has_edge(a, b):
            g[a][b]["weight"] = max(g[a][b]["weight"], e.confidence)
        else:
            g.add_edge(a, b, weight=e.confidence)

    if g.number_of_edges() == 0:
        raw = [[n] for n in sorted(g.nodes)]
    else:
        raw = [sorted(c) for c in
               greedy_modularity_communities(g, weight="weight", resolution=resolution)]
    raw.sort(key=lambda m: (-len(m), m[0] if m else ""))

    communities: list[Community] = []
    skipped: list[SkippedGroup] = []
    idx = 1
    for members in raw:
        if len(members) >= min_size:
            communities.append(Community(topic_id=f"t{idx:04d}", member_ids=members))
            idx += 1
        else:
            skipped.append(SkippedGroup(member_ids=members, reason="below_min_size"))
    return Communities(resolution=resolution, communities=communities, skipped=skipped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topics_clustering.py -q --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/clustering.py tests/test_topics_clustering.py
git commit -m "feat(topics): deterministic confidence-weighted community detection"
```

---

### Task 3: Topic rebuild manifest

**Files:**
- Create: `src/mykg/wiki/topic_manifest.py`
- Test: `tests/test_topic_manifest.py`

**Interfaces:**
- Consumes: `Community` (Task 2), `WikiGraph`, `mykg.wiki.manifest.grounding_hash`.
- Produces:
  - `community_fingerprint(community: Community) -> str` — sha256 of sorted member ids (identity key, stable under community reordering).
  - `topic_grounding_hash(community, graph, min_edge_confidence, neighbors_max, resolution, schema_sig) -> str`
  - `TopicRebuildPlan(BaseModel)` with `to_generate: list[str]`, `to_keep: list[str]`, `to_delete: list[str]` (values are fingerprints).
  - `plan_topic_rebuild(communities: list[Community], graph, manifest: dict, min_edge_confidence, neighbors_max, resolution, schema_sig, force=False) -> TopicRebuildPlan`
  - `load_topic_manifest(vault_dir: Path) -> dict` (shape `{"topics": {fingerprint: {"hash", "slug", "topic_id"}}}`)
  - `save_topic_manifest(vault_dir: Path, entries: dict[str, dict]) -> None`

**Note (design refinement):** the manifest keys on a **member-set fingerprint**, not `topic_id`. `topic_id` is a display ordinal that can shift when the graph changes; fingerprint keying keeps incremental rebuild correct across reorderings. `topic_id`/`slug` are stored as values for filenames.

- [ ] **Step 1: Write the failing test**

`tests/test_topic_manifest.py`:
```python
from __future__ import annotations

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiEdge, WikiGraph, WikiNode
from mykg.wiki.topic_manifest import (
    community_fingerprint,
    load_topic_manifest,
    plan_topic_rebuild,
    save_topic_manifest,
    topic_grounding_hash,
)


def _node(nid: str, attrs=None) -> WikiNode:
    return WikiNode(id=nid, type="Thing", name=nid, attributes=attrs or {},
                    source_files=[], grounded_chunk_keys=[], grounded_chunks=["text"], grounded=True)


def _graph(attrs=None) -> WikiGraph:
    nodes = {i: _node(i, attrs) for i in ("a", "b", "c")}
    edges = [WikiEdge(id="1", type="rel", from_id="a", to_id="b", confidence=0.9)]
    return WikiGraph(nodes=nodes, edges=edges, types=["Thing"])


def test_fingerprint_is_order_independent():
    c1 = Community(topic_id="t0001", member_ids=["a", "b", "c"])
    c2 = Community(topic_id="t0009", member_ids=["c", "b", "a"])
    assert community_fingerprint(c1) == community_fingerprint(c2)


def test_plan_generates_when_absent_then_keeps(tmp_path):
    comm = Community(topic_id="t0001", member_ids=["a", "b", "c"])
    g = _graph()
    fp = community_fingerprint(comm)
    plan = plan_topic_rebuild([comm], g, {"topics": {}}, 0.3, 25, 1.0, "sig")
    assert plan.to_generate == [fp] and plan.to_keep == []

    h = topic_grounding_hash(comm, g, 0.3, 25, 1.0, "sig")
    save_topic_manifest(tmp_path, {fp: {"hash": h, "slug": "theme", "topic_id": "t0001"}})
    manifest = load_topic_manifest(tmp_path)
    plan2 = plan_topic_rebuild([comm], g, manifest, 0.3, 25, 1.0, "sig")
    assert plan2.to_keep == [fp] and plan2.to_generate == []


def test_plan_regenerates_on_attribute_change(tmp_path):
    comm = Community(topic_id="t0001", member_ids=["a", "b", "c"])
    fp = community_fingerprint(comm)
    g0 = _graph()
    h0 = topic_grounding_hash(comm, g0, 0.3, 25, 1.0, "sig")
    save_topic_manifest(tmp_path, {fp: {"hash": h0, "slug": "theme", "topic_id": "t0001"}})
    g1 = _graph(attrs={"note": {"value": "changed", "confidence": 0.9}})
    plan = plan_topic_rebuild([comm], g1, load_topic_manifest(tmp_path), 0.3, 25, 1.0, "sig")
    assert plan.to_generate == [fp]


def test_plan_deletes_missing(tmp_path):
    old_fp = "deadbeef"
    save_topic_manifest(tmp_path, {old_fp: {"hash": "x", "slug": "gone", "topic_id": "t0001"}})
    plan = plan_topic_rebuild([], _graph(), load_topic_manifest(tmp_path), 0.3, 25, 1.0, "sig")
    assert plan.to_delete == [old_fp]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topic_manifest.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.topic_manifest`.

- [ ] **Step 3: Write the implementation**

`src/mykg/wiki/topic_manifest.py`:
```python
"""Fingerprint-keyed grounding manifest driving incremental topic rebuilds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.manifest import grounding_hash

_MANIFEST_NAME = ".topics_manifest.json"


class TopicRebuildPlan(BaseModel):
    to_generate: list[str]
    to_keep: list[str]
    to_delete: list[str]


def community_fingerprint(community: Community) -> str:
    blob = json.dumps(sorted(community.member_ids), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def topic_grounding_hash(community: Community, graph: WikiGraph, min_edge_confidence: float,
                         neighbors_max: int, resolution: float, schema_sig: str) -> str:
    members = sorted(community.member_ids)
    member_hashes = [
        grounding_hash(graph.nodes[m], graph.neighbors(m, min_edge_confidence, neighbors_max))
        for m in members if m in graph.nodes
    ]
    payload = {"members": members, "member_hashes": member_hashes,
               "resolution": resolution, "schema_sig": schema_sig}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def plan_topic_rebuild(communities: list[Community], graph: WikiGraph, manifest: dict,
                       min_edge_confidence: float, neighbors_max: int, resolution: float,
                       schema_sig: str, force: bool = False) -> TopicRebuildPlan:
    prior = manifest.get("topics", {})
    current_fps: set[str] = set()
    to_generate, to_keep = [], []
    for comm in communities:
        fp = community_fingerprint(comm)
        current_fps.add(fp)
        h = topic_grounding_hash(comm, graph, min_edge_confidence, neighbors_max,
                                 resolution, schema_sig)
        if not force and prior.get(fp, {}).get("hash") == h:
            to_keep.append(fp)
        else:
            to_generate.append(fp)
    to_delete = [fp for fp in prior if fp not in current_fps]
    return TopicRebuildPlan(to_generate=sorted(to_generate), to_keep=sorted(to_keep),
                            to_delete=sorted(to_delete))


def load_topic_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _MANIFEST_NAME
    if not path.exists():
        return {"topics": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_topic_manifest(vault_dir: Path, entries: dict[str, dict]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / _MANIFEST_NAME).write_text(
        json.dumps({"topics": entries}, indent=2, sort_keys=True), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topic_manifest.py -q --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/topic_manifest.py tests/test_topic_manifest.py
git commit -m "feat(topics): fingerprint-keyed incremental rebuild manifest"
```

---

### Task 4: Topic page synthesis

**Files:**
- Create: `src/mykg/wiki/topic_builder.py`
- Test: `tests/test_topic_builder.py`

**Interfaces:**
- Consumes: `Community` (Task 2), `WikiGraph`, `mykg.wiki.page_builder.strip_invalid_wikilinks` and `_capped_grounding`, `mykg.llm.adapter.LLMAdapter`.
- Produces:
  - `slugify(theme: str) -> str`
  - `select_members(graph: WikiGraph, member_ids: list[str], members_max: int) -> list[str]`
  - `generate_topic_page(community: Community, graph: WikiGraph, adapter: LLMAdapter, members_max: int, max_grounding_tokens: int) -> tuple[str, str, bool]` returning `(slug, page_markdown, ok)`; `ok=False` marks a transient failure (retryable, not persisted).

- [ ] **Step 1: Write the failing test**

`tests/test_topic_builder.py`:
```python
from __future__ import annotations

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiEdge, WikiGraph, WikiNode
from mykg.wiki.topic_builder import generate_topic_page, select_members, slugify


class _StubAdapter:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return self.reply

    def endpoint_label(self):
        return "stub"


def _node(nid: str) -> WikiNode:
    return WikiNode(id=nid, type="Thing", name=nid.title(), attributes={},
                    source_files=[], grounded_chunk_keys=[f"{nid}.md::1"],
                    grounded_chunks=[f"{nid} does things."], grounded=True)


def _graph():
    nodes = {i: _node(i) for i in ("a", "b", "c")}
    edges = [WikiEdge(id="1", type="rel", from_id="a", to_id="b", confidence=0.9),
             WikiEdge(id="2", type="rel", from_id="b", to_id="c", confidence=0.8)]
    return WikiGraph(nodes=nodes, edges=edges, types=["Thing"])


def test_slugify():
    assert slugify("The Acme Alliance!") == "the-acme-alliance"
    assert slugify("") == "topic"


def test_select_members_caps_and_orders_by_degree():
    g = _graph()
    comm = ["a", "b", "c"]
    # b has degree 2 (highest), so first; cap to 2
    assert select_members(g, comm, members_max=2)[0] == "b"
    assert len(select_members(g, comm, 2)) == 2


def test_generate_topic_page_strips_invalid_links_and_extracts_theme():
    comm = Community(topic_id="t0001", member_ids=["a", "b", "c"])
    reply = "# Acme Alliance\n\nThey collaborate: [[a|A]], [[nope|Ghost]]."
    slug, page, ok = generate_topic_page(comm, _graph(), _StubAdapter(reply),
                                         members_max=25, max_grounding_tokens=4000)
    assert ok is True
    assert slug == "acme-alliance"
    assert "[[a|A]]" in page          # valid link kept
    assert "[[nope|Ghost]]" not in page  # invalid link stripped
    assert "Ghost" in page            # label preserved as plain text
    assert "topic_id: t0001" in page  # frontmatter present


def test_generate_topic_page_blank_reply_is_transient_failure():
    comm = Community(topic_id="t0001", member_ids=["a", "b", "c"])
    slug, page, ok = generate_topic_page(comm, _graph(), _StubAdapter(""),
                                         members_max=25, max_grounding_tokens=4000)
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topic_builder.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.topic_builder`.

- [ ] **Step 3: Write the implementation**

`src/mykg/wiki/topic_builder.py`:
```python
"""LLM synthesis of cross-entity topic articles from a community."""
from __future__ import annotations

import logging
import re

import yaml

from mykg.llm.adapter import LLMAdapter
from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.page_builder import _capped_grounding, strip_invalid_wikilinks

log = logging.getLogger(__name__)

_TOPIC_SYSTEM = (
    "You write a synthesized topic article for a personal knowledge base, weaving "
    "several related entities into one coherent theme. Use ONLY the provided source "
    "excerpts and entity list — never invent facts. Output Markdown: the FIRST line "
    "must be an H1 naming the theme ('# <theme>'), followed by a synthesizing article. "
    "Reference entities ONLY using the exact [[id|Name]] links listed under 'Member "
    "entities'. Do not create any other [[...]] links."
)


def slugify(theme: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", theme.lower()).strip("-")
    return s or "topic"


def select_members(graph: WikiGraph, member_ids: list[str], members_max: int) -> list[str]:
    member_set = set(member_ids)
    degree: dict[str, float] = {m: 0.0 for m in member_ids}
    for e in graph.edges:
        if e.from_id in member_set and e.to_id in member_set:
            degree[e.from_id] = degree.get(e.from_id, 0.0) + e.confidence
            degree[e.to_id] = degree.get(e.to_id, 0.0) + e.confidence
    ordered = sorted(member_ids, key=lambda m: (-degree.get(m, 0.0), m))
    return ordered[:members_max]


def _build_prompt(graph: WikiGraph, selected: list[str], all_members: list[str],
                  max_grounding_tokens: int) -> tuple[str, str]:
    members_block = "\n".join(
        f"- [[{m}|{graph.nodes[m].name}]] — {graph.nodes[m].type}"
        for m in all_members if m in graph.nodes) or "(none)"
    chunks: list[str] = []
    for m in selected:
        if m in graph.nodes:
            chunks.extend(graph.nodes[m].grounded_chunks)
    grounding = _capped_grounding(chunks, max_grounding_tokens)
    user = f"# Member entities\n{members_block}\n\n# Source excerpts\n{grounding}\n"
    return _TOPIC_SYSTEM, user


def _extract_theme(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _render(community: Community, theme: str, body: str) -> str:
    fm = {"topic_id": community.topic_id, "theme": theme,
          "members": [f"[[{m}]]" for m in community.member_ids]}
    return ("---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
            + "---\n\n" + body.strip() + "\n")


def generate_topic_page(community: Community, graph: WikiGraph, adapter: LLMAdapter,
                        members_max: int, max_grounding_tokens: int) -> tuple[str, str, bool]:
    selected = select_members(graph, community.member_ids, members_max)
    system, user = _build_prompt(graph, selected, community.member_ids, max_grounding_tokens)
    try:
        raw = adapter.complete(system, user, context_label=f"topic:{community.topic_id}")
    except Exception:
        log.warning("topics: generation failed for %s", community.topic_id, exc_info=True)
        return "", "", False
    body = LLMAdapter.strip_code_fences(raw).strip() if raw else ""
    if not body:
        log.warning("topics: blank reply for %s", community.topic_id)
        return "", "", False
    theme = _extract_theme(body) or community.topic_id
    cleaned, _dropped = strip_invalid_wikilinks(body, set(graph.nodes))
    return slugify(theme), _render(community, theme, cleaned), True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topic_builder.py -q --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/topic_builder.py tests/test_topic_builder.py
git commit -m "feat(topics): LLM cross-entity topic article synthesis"
```

---

### Task 5: Schema proposals (propose-only)

**Files:**
- Create: `src/mykg/wiki/proposals.py`
- Test: `tests/test_topic_proposals.py`

**Interfaces:**
- Consumes: `Community` (Task 2), `WikiGraph`, `LLMAdapter`, `_capped_grounding`.
- Produces:
  - `Proposal(BaseModel)` with `kind: str`, `target: str`, `rationale: str`, `quotes: list[str]`, `evidence_count: int = 1`
  - `extract_proposals(community, graph, flattened_schema: dict, adapter, max_grounding_tokens) -> list[Proposal]`
  - `aggregate_proposals(items: list[Proposal]) -> list[Proposal]`
  - `render_proposals_md(proposals: list[Proposal], session_name: str, generated_at: str) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_topic_proposals.py`:
```python
from __future__ import annotations

import json

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph, WikiNode
from mykg.wiki.proposals import (
    Proposal,
    aggregate_proposals,
    extract_proposals,
    render_proposals_md,
)


class _StubAdapter:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return self.reply

    def endpoint_label(self):
        return "stub"


def _graph():
    nodes = {"o": WikiNode(id="o", type="Organization", name="Acme", attributes={},
                           source_files=[], grounded_chunk_keys=["a.md::1"],
                           grounded_chunks=["Acme, founded in 1998."], grounded=True)}
    return WikiGraph(nodes=nodes, edges=[], types=["Organization"])


def test_extract_proposals_parses_grounded_json():
    reply = json.dumps([
        {"kind": "add_attribute", "target": "Organization.founded_year",
         "rationale": "founding year stated", "quote": "founded in 1998"},
        {"kind": "bogus", "target": "x", "quote": "q"},           # wrong kind -> dropped
        {"kind": "add_attribute", "target": "Organization.ceo"},  # no quote -> dropped
    ])
    comm = Community(topic_id="t0001", member_ids=["o"])
    props = extract_proposals(comm, _graph(), {"Organization": ["name"]},
                              _StubAdapter(reply), max_grounding_tokens=4000)
    assert len(props) == 1
    assert props[0].target == "Organization.founded_year"


def test_aggregate_dedupes_and_counts():
    a = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="x", quotes=["q1"])
    b = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="y", quotes=["q2"])
    out = aggregate_proposals([a, b])
    assert len(out) == 1
    assert out[0].evidence_count == 2
    assert set(out[0].quotes) == {"q1", "q2"}


def test_render_proposals_md_is_grounded():
    p = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="founding year stated", quotes=["founded in 1998"], evidence_count=3)
    md = render_proposals_md([p], "sess1", "2026-07-13T00:00:00Z")
    assert "Organization.founded_year" in md
    assert "founded in 1998" in md
    assert "sess1" in md
    assert "Propose-only" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topic_proposals.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: mykg.wiki.proposals`.

- [ ] **Step 3: Write the implementation**

`src/mykg/wiki/proposals.py`:
```python
"""Propose-only, human-gated schema improvement suggestions from communities."""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from mykg.llm.adapter import LLMAdapter
from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.page_builder import _capped_grounding

log = logging.getLogger(__name__)

_KINDS = {"add_attribute", "add_relationship_type", "add_concept_type"}

_PROPOSAL_SYSTEM = (
    "You analyze a cluster of related entities and their source text to find schema "
    "gaps: recurring attributes, relationship types, or entity types the current schema "
    "does not capture but the text clearly supports. Output ONLY a JSON array; each item: "
    '{"kind": "add_attribute"|"add_relationship_type"|"add_concept_type", '
    '"target": "<Type.attr | RelType | ConceptType>", "rationale": "<short>", '
    '"quote": "<verbatim source snippet>"}. Only include proposals grounded in a quote '
    "from the excerpts. If none, output []."
)


class Proposal(BaseModel):
    kind: str
    target: str
    rationale: str = ""
    quotes: list[str] = []
    evidence_count: int = 1


def _parse_array(raw: str | None) -> list:
    txt = LLMAdapter.strip_code_fences(raw or "").strip()
    try:
        val = json.loads(txt)
    except Exception:
        return []
    return val if isinstance(val, list) else []


def extract_proposals(community: Community, graph: WikiGraph, flattened_schema: dict,
                      adapter: LLMAdapter, max_grounding_tokens: int) -> list[Proposal]:
    types = sorted({graph.nodes[m].type for m in community.member_ids if m in graph.nodes})
    schema_block = "\n".join(f"{t}: {flattened_schema.get(t, [])}" for t in types) or "(none)"
    chunks: list[str] = []
    for m in community.member_ids:
        if m in graph.nodes:
            chunks.extend(graph.nodes[m].grounded_chunks)
    grounding = _capped_grounding(chunks, max_grounding_tokens)
    user = (f"# Current schema for these types\n{schema_block}\n\n"
            f"# Source excerpts\n{grounding}\n")
    try:
        raw = adapter.complete(_PROPOSAL_SYSTEM, user,
                               context_label=f"topic-proposals:{community.topic_id}")
    except Exception:
        log.warning("topics: proposal pass failed for %s", community.topic_id, exc_info=True)
        return []
    out: list[Proposal] = []
    for item in _parse_array(raw):
        if not isinstance(item, dict):
            continue
        kind, target, quote = item.get("kind"), item.get("target"), item.get("quote")
        if kind in _KINDS and target and quote:
            out.append(Proposal(kind=kind, target=str(target),
                                rationale=str(item.get("rationale", "")), quotes=[str(quote)]))
    return out


def aggregate_proposals(items: list[Proposal]) -> list[Proposal]:
    by_key: dict[tuple[str, str], Proposal] = {}
    for p in items:
        key = (p.kind, p.target)
        if key in by_key:
            e = by_key[key]
            e.quotes.extend(q for q in p.quotes if q not in e.quotes)
            e.evidence_count += 1
        else:
            by_key[key] = Proposal(kind=p.kind, target=p.target, rationale=p.rationale,
                                   quotes=list(p.quotes), evidence_count=1)
    return sorted(by_key.values(), key=lambda p: (-p.evidence_count, p.kind, p.target))


def render_proposals_md(proposals: list[Proposal], session_name: str, generated_at: str) -> str:
    lines = [f"# Schema proposals — {session_name}", "",
             f"Generated {generated_at}. Propose-only: review and apply manually.", ""]
    if not proposals:
        lines += ["_No schema gaps proposed for this session._", ""]
        return "\n".join(lines)
    for p in proposals:
        lines.append(f"## {p.kind} — {p.target}   (evidence: {p.evidence_count})")
        if p.rationale:
            lines.append(p.rationale)
        for q in p.quotes:
            lines.append(f"> {q}")
        lines += [
            "",
            f"**To apply:** update `intermediate/schema.json` for this "
            f"session, then `mykg extract-graph --from-step pass2 --session {session_name}`.",
            "",
        ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topic_proposals.py -q --no-cov`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/proposals.py tests/test_topic_proposals.py
git commit -m "feat(topics): propose-only schema gap suggestions from communities"
```

---

### Task 6: Topics pipeline (steps + orchestration)

**Files:**
- Create: `src/mykg/topics_pipeline.py`
- Test: `tests/test_topics_pipeline.py`

**Interfaces:**
- Consumes: `mykg.wiki_pipeline.session_root`, `mykg.wiki_pipeline.vault_dir`; `mykg.wiki.loader.load_wiki_graph`; Tasks 2–5; `mykg.schema_flattener.flatten_schema`; `cfg.*`; `mykg.orchestrator.PipelineContext, Step`.
- Produces:
  - `run_topics_load(ctx)`, `run_topics_cluster(ctx)`, `run_topics_pages(ctx)`, `run_topics_proposals(ctx)`, `run_topics_index(ctx)`
  - `TOPIC_STEPS: list[Step]` in order `topics_load → topics_cluster → topics_pages → topics_proposals → topics_index`.

- [ ] **Step 1: Write the failing test**

`tests/test_topics_pipeline.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from mykg.orchestrator import PipelineContext
from mykg.topics_pipeline import (
    TOPIC_STEPS,
    run_topics_cluster,
    run_topics_index,
    run_topics_load,
    run_topics_pages,
    run_topics_proposals,
)
from mykg.wiki_pipeline import vault_dir


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        if context_label.startswith("topic-proposals:"):
            return json.dumps([{"kind": "add_attribute", "target": "Person.role",
                                "rationale": "role stated", "quote": "Alice is the lead"}])
        return "# Team Acme\n\n[[person-alice|Alice]] and [[org-acme|Acme]] work together."

    def endpoint_label(self):
        return "stub"


def _session(tmp_path: Path) -> Path:
    root = tmp_path / "sess"
    out, inter = root / "output", root / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    nodes = [
        {"id": "person-alice", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "Alice", "confidence": 0.9}}, "source_files": ["doc.md"]},
        {"id": "org-acme", "type": "Organization", "confidence": 0.8,
         "attributes": {"name": {"value": "Acme", "confidence": 0.8}}, "source_files": ["doc.md"]},
        {"id": "proj-x", "type": "Project", "confidence": 0.8,
         "attributes": {"name": {"value": "X", "confidence": 0.8}}, "source_files": ["doc.md"]},
    ]
    (out / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    edges = [
        {"id": "e1", "type": "works_at", "from": "person-alice", "to": "org-acme",
         "confidence": 0.9, "attributes": {}},
        {"id": "e2", "type": "runs", "from": "org-acme", "to": "proj-x",
         "confidence": 0.8, "attributes": {}},
    ]
    (out / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    (inter / "edge_metadata.json").write_text(json.dumps({e["id"]: e for e in edges}))
    (inter / "chunk_node_index.json").write_text(json.dumps(
        {"doc.md": {"1": ["person-alice", "org-acme", "proj-x"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"doc.md": {"content": "Alice is the lead at Acme which runs X. " * 30,
                    "sha256": "x", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]},
                      {"type": "Organization", "parent": None, "attributes": ["name"]},
                      {"type": "Project", "parent": None, "attributes": ["name"]}],
         "properties": []}))
    return root


def _ctx(root: Path) -> PipelineContext:
    state = root / "topics_state"
    state.mkdir(parents=True, exist_ok=True)
    return PipelineContext(input_dir=root / "input", output_dir=root / "output",
                           intermediate_dir=state, adapter=_StubAdapter())


def test_full_topics_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    monkeypatch.setattr("mykg.config.TOPICS_MIN_SIZE", 3)
    root = _session(tmp_path)
    ctx = _ctx(root)
    for step in (run_topics_load, run_topics_cluster, run_topics_pages,
                 run_topics_proposals, run_topics_index):
        step(ctx)
    vault = vault_dir(ctx)
    topics = list((vault / "topics").glob("*.md"))
    assert topics, "expected at least one topic page"
    body = topics[0].read_text()
    assert "[[person-alice|Alice]]" in body
    assert (vault / "Topics.md").exists()
    proposals = (vault / "schema_proposals.md").read_text()
    assert "Person.role" in proposals
    assert (vault / ".topics_manifest.json").exists()
    # Isolation: extract session state untouched.
    assert not (root / "intermediate" / "pipeline_state.json").exists()
    assert (root / "topics_state" / "pipeline_state.json").exists()


def test_writer_disjointness(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    monkeypatch.setattr("mykg.config.TOPICS_MIN_SIZE", 3)
    root = _session(tmp_path)
    ctx = _ctx(root)
    vault = vault_dir(ctx)
    (vault).mkdir(parents=True, exist_ok=True)
    (vault / "Home.md").write_text("SENTINEL HOME")
    (vault / "entities").mkdir()
    (vault / "entities" / "person-alice.md").write_text("SENTINEL ENTITY")
    for step in (run_topics_load, run_topics_cluster, run_topics_pages,
                 run_topics_proposals, run_topics_index):
        step(ctx)
    assert (vault / "Home.md").read_text() == "SENTINEL HOME"
    assert (vault / "entities" / "person-alice.md").read_text() == "SENTINEL ENTITY"


def test_topic_steps_names_and_order():
    assert [s.name for s in TOPIC_STEPS] == [
        "topics_load", "topics_cluster", "topics_pages", "topics_proposals", "topics_index"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topics_pipeline.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: mykg.topics_pipeline`.

- [ ] **Step 3: Write the implementation**

`src/mykg/topics_pipeline.py`:
```python
"""build-topics pipeline: cluster the graph and synthesize cross-entity topic pages."""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import mykg.config as cfg
from mykg.orchestrator import PipelineContext, Step
from mykg.schema_flattener import flatten_schema
from mykg.wiki.clustering import Communities, build_communities
from mykg.wiki.loader import WikiGraph, load_wiki_graph
from mykg.wiki.proposals import aggregate_proposals, extract_proposals, render_proposals_md
from mykg.wiki.topic_builder import generate_topic_page
from mykg.wiki.topic_manifest import (
    community_fingerprint,
    load_topic_manifest,
    plan_topic_rebuild,
    save_topic_manifest,
    topic_grounding_hash,
)
from mykg.wiki_pipeline import session_root, vault_dir

log = logging.getLogger(__name__)


def _graph_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "wiki_graph.json"


def _communities_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "communities.json"


def _load_graph(ctx: PipelineContext) -> WikiGraph:
    return WikiGraph.model_validate_json(_graph_path(ctx).read_text(encoding="utf-8"))


def _load_communities(ctx: PipelineContext) -> Communities:
    return Communities.model_validate_json(_communities_path(ctx).read_text(encoding="utf-8"))


def _schema_sig(ctx: PipelineContext) -> str:
    path = session_root(ctx) / "intermediate" / "schema.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _flattened_schema(ctx: PipelineContext) -> dict:
    path = session_root(ctx) / "intermediate" / "schema.json"
    if not path.exists():
        return {}
    return flatten_schema(json.loads(path.read_text(encoding="utf-8")))


def run_topics_load(ctx: PipelineContext) -> None:
    graph = load_wiki_graph(session_root(ctx))
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    _graph_path(ctx).write_text(graph.model_dump_json(), encoding="utf-8")
    if not (vault_dir(ctx) / "entities").is_dir():
        log.warning("topics: entities/ not found in vault — run build-wiki so topic "
                    "wikilinks resolve to entity pages")
    log.info("topics_load — %d nodes, %d edges", len(graph.nodes), len(graph.edges))


def run_topics_cluster(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = build_communities(graph, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                              cfg.TOPICS_RESOLUTION, cfg.TOPICS_MIN_SIZE)
    _communities_path(ctx).write_text(comms.model_dump_json(indent=2), encoding="utf-8")
    log.info("topics_cluster — %d communities, %d skipped",
             len(comms.communities), len(comms.skipped))


def run_topics_pages(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = _load_communities(ctx)
    vault = vault_dir(ctx)
    topics = vault / "topics"
    topics.mkdir(parents=True, exist_ok=True)

    schema_sig = _schema_sig(ctx)
    by_fp = {community_fingerprint(c): c for c in comms.communities}
    manifest = load_topic_manifest(vault)
    plan = plan_topic_rebuild(comms.communities, graph, manifest,
                              cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX,
                              comms.resolution, schema_sig)
    prior = manifest.get("topics", {})
    log.info("topics_pages — generate=%d keep=%d delete=%d",
             len(plan.to_generate), len(plan.to_keep), len(plan.to_delete))

    for fp in plan.to_delete:
        slug = prior.get(fp, {}).get("slug")
        if slug:
            (topics / f"{slug}.md").unlink(missing_ok=True)

    entries: dict[str, dict] = {fp: dict(prior[fp]) for fp in plan.to_keep if fp in prior}
    used_slugs = {e["slug"] for e in entries.values()}

    def _one(fp: str):
        comm = by_fp[fp]
        slug, page, ok = generate_topic_page(comm, graph, ctx.adapter,
                                             cfg.TOPICS_MEMBERS_MAX, cfg.WIKI_MAX_GROUNDING_TOKENS)
        return fp, comm, slug, page, ok

    if plan.to_generate:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            results = list(pool.map(_one, plan.to_generate))
        for fp, comm, slug, page, ok in results:
            if not ok:
                continue
            unique = slug
            n = 2
            while unique in used_slugs:
                unique = f"{slug}-{n}"
                n += 1
            used_slugs.add(unique)
            (topics / f"{unique}.md").write_text(page, encoding="utf-8")
            entries[fp] = {
                "hash": topic_grounding_hash(comm, graph, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                                             cfg.WIKI_NEIGHBORS_MAX, comms.resolution, schema_sig),
                "slug": unique,
                "topic_id": comm.topic_id,
            }

    save_topic_manifest(vault, entries)
    (ctx.intermediate_dir / "topics_pages.done").write_text("ok")


def run_topics_proposals(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = _load_communities(ctx)
    flattened = _flattened_schema(ctx)

    def _one(comm):
        return extract_proposals(comm, graph, flattened, ctx.adapter, cfg.WIKI_MAX_GROUNDING_TOKENS)

    collected: list = []
    if comms.communities:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            for props in pool.map(_one, comms.communities):
                collected.extend(props)

    ranked = aggregate_proposals(collected)
    now = datetime.now(timezone.utc).isoformat()
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "schema_proposals.md").write_text(
        render_proposals_md(ranked, session_root(ctx).name, now), encoding="utf-8")
    (ctx.intermediate_dir / "topics_proposals.done").write_text("ok")


def run_topics_index(ctx: PipelineContext) -> None:
    comms = _load_communities(ctx)
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    manifest = load_topic_manifest(vault)
    entries = manifest.get("topics", {})
    now = datetime.now(timezone.utc).isoformat()
    lines = ["# Topics", "",
             f"- Source session: `{session_root(ctx).name}`",
             f"- Topics: {len(comms.communities)}",
             f"- Generated: {now}", ""]
    for c in comms.communities:
        slug = entries.get(community_fingerprint(c), {}).get("slug")
        if not slug:
            continue
        theme = slug.replace("-", " ").title()
        lines.append(f"- [[topics/{slug}|{theme}]] — {len(c.member_ids)} entities")
    (vault / "Topics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ctx.intermediate_dir / "topics_index.done").write_text("ok")


TOPIC_STEPS: list[Step] = [
    Step(name="topics_load", fn=run_topics_load, outputs=["wiki_graph.json"]),
    Step(name="topics_cluster", fn=run_topics_cluster, outputs=["communities.json"]),
    Step(name="topics_pages", fn=run_topics_pages, outputs=["topics_pages.done"], is_llm_step=True),
    Step(name="topics_proposals", fn=run_topics_proposals,
         outputs=["topics_proposals.done"], is_llm_step=True),
    Step(name="topics_index", fn=run_topics_index, outputs=["topics_index.done"]),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topics_pipeline.py -q --no-cov`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full non-live suite to check for regressions**

Run: `uv run pytest -m "not live" -q --no-cov`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add src/mykg/topics_pipeline.py tests/test_topics_pipeline.py
git commit -m "feat(topics): topics pipeline steps and orchestration"
```

---

### Task 7: CLI command `build-topics`

**Files:**
- Modify: `src/mykg/cli.py` (add a `build-topics` command after `build-wiki`, ~line 811)
- Test: `tests/test_topics_cli.py`

**Interfaces:**
- Consumes: `TOPIC_STEPS`, `vault_dir` from `mykg.topics_pipeline`; `mykg.orchestrator.run`, `PipelineContext`; `_sessions_root`.
- Produces: `mykg build-topics <session> [--rebuild] [--from-step] [--log-file] [--verbose]`.

- [ ] **Step 1: Write the failing test**

`tests/test_topics_cli.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import cli


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        if context_label.startswith("topic-proposals:"):
            return "[]"
        return "# Theme\n\n[[person-x|X]] links [[org-y|Y]]."

    def endpoint_label(self):
        return "stub"


def _session(sessions_root: Path, name: str) -> None:
    out, inter = sessions_root / name / "output", sessions_root / name / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    nodes = [
        {"id": "person-x", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "X", "confidence": 0.9}}, "source_files": ["d.md"]},
        {"id": "org-y", "type": "Organization", "confidence": 0.9,
         "attributes": {"name": {"value": "Y", "confidence": 0.9}}, "source_files": ["d.md"]},
        {"id": "proj-z", "type": "Project", "confidence": 0.9,
         "attributes": {"name": {"value": "Z", "confidence": 0.9}}, "source_files": ["d.md"]},
    ]
    (out / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    edges = [
        {"id": "e1", "type": "at", "from": "person-x", "to": "org-y", "confidence": 0.9, "attributes": {}},
        {"id": "e2", "type": "runs", "from": "org-y", "to": "proj-z", "confidence": 0.9, "attributes": {}},
    ]
    (out / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    (inter / "edge_metadata.json").write_text(json.dumps({e["id"]: e for e in edges}))
    (inter / "chunk_node_index.json").write_text(json.dumps(
        {"d.md": {"1": ["person-x", "org-y", "proj-z"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"d.md": {"content": "X at Y runs Z. " * 40, "sha256": "s", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]},
                      {"type": "Organization", "parent": None, "attributes": ["name"]},
                      {"type": "Project", "parent": None, "attributes": ["name"]}],
         "properties": []}))


def test_build_topics_missing_session_errors(tmp_path):
    with patch("mykg.cli._sessions_root", return_value=tmp_path):
        res = CliRunner().invoke(cli, ["build-topics", "nope"])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()


def test_build_topics_writes_topics(tmp_path):
    _session(tmp_path, "sess1")
    with patch("mykg.cli._sessions_root", return_value=tmp_path), \
         patch("mykg.config.WIKI_ROOT", str(tmp_path / "wiki")), \
         patch("mykg.config.TOPICS_MIN_SIZE", 3), \
         patch("mykg.llm.config.load_adapter", return_value=_StubAdapter()):
        res = CliRunner().invoke(cli, ["build-topics", "sess1"])
    assert res.exit_code == 0, res.output
    vault = tmp_path / "wiki" / "sess1"
    assert (vault / "Topics.md").exists()
    assert list((vault / "topics").glob("*.md"))
    assert (vault / "schema_proposals.md").exists()
    # Extract session state untouched by the topics run.
    assert not (tmp_path / "sess1" / "intermediate" / "pipeline_state.json").exists()
    assert (tmp_path / "sess1" / "topics_state" / "pipeline_state.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_topics_cli.py -q --no-cov`
Expected: FAIL — no such command `build-topics`.

- [ ] **Step 3: Add the command to `src/mykg/cli.py`**

Insert immediately after the `build_wiki` function (after its `click.echo(...)`, ~line 811):
```python
@cli.command("build-topics")
@click.argument("session")
@click.option("--rebuild", is_flag=True, help="Force-regenerate every topic page (ignore manifest)")
@click.option("--from-step", default=None, help="Resume from a topics step (topics_cluster, ...)")
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def build_topics(session, rebuild, from_step, log_file, verbose):
    """Cluster a finished session's graph and synthesize cross-entity topic pages."""
    from mykg.llm.config import load_adapter
    from mykg.logging import setup
    from mykg.orchestrator import PipelineContext, run
    from mykg.topics_pipeline import TOPIC_STEPS, vault_dir

    session_root = _sessions_root() / session
    if not session_root.is_dir():
        raise click.ClickException(f"Session '{session}' not found at {session_root}.")
    if not (session_root / "output" / "nodes.jsonl").exists():
        raise click.ClickException(
            f"Session '{session}' has no output/nodes.jsonl — run extract-graph first."
        )

    topics_state = session_root / "topics_state"
    topics_state.mkdir(parents=True, exist_ok=True)
    if log_file is None:
        log_file = session_root / "topics.log"
    setup(log_file=log_file, verbose=verbose)
    logging.getLogger(__name__).info("Command: %s", " ".join(sys.argv))

    step_names = [s.name for s in TOPIC_STEPS]
    if from_step:
        if from_step not in step_names:
            raise click.ClickException(
                f"--from-step must be one of {step_names}, got '{from_step}'."
            )
        start = step_names.index(from_step)
        for name in step_names[start:]:
            (topics_state / f"{name}.done").unlink(missing_ok=True)
        if from_step == "topics_load":
            (topics_state / "wiki_graph.json").unlink(missing_ok=True)
    else:
        for name in step_names:
            (topics_state / f"{name}.done").unlink(missing_ok=True)
        (topics_state / "wiki_graph.json").unlink(missing_ok=True)

    adapter = load_adapter(intermediate_dir=topics_state)
    ctx = PipelineContext(
        input_dir=session_root / "input",
        output_dir=session_root / "output",
        intermediate_dir=topics_state,
        adapter=adapter,
    )
    if rebuild:
        (vault_dir(ctx) / ".topics_manifest.json").unlink(missing_ok=True)

    run(TOPIC_STEPS, ctx)
    click.echo(f"Topics written to {vault_dir(ctx)}")
```
Note: `vault_dir` is re-exported from `topics_pipeline` (it imports it from `wiki_pipeline`), so the import above resolves.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_topics_cli.py -q --no-cov`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/ tests/`
Expected: no errors in the new/modified files.

- [ ] **Step 6: Commit**

```bash
git add src/mykg/cli.py tests/test_topics_cli.py
git commit -m "feat(topics): add build-topics CLI command"
```

---

### Task 8: Live end-to-end smoke test

**Files:**
- Create: `tests/test_topics_live.py`

**Interfaces:**
- Consumes: the `live_corpus` fixture (`tests/conftest.py`), the real active adapter, `mykg build-topics`.

- [ ] **Step 1: Write the live test**

`tests/test_topics_live.py`:
```python
"""Live end-to-end build-topics smoke test against the active LLM provider."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_build_topics_live(live_corpus, tmp_path):
    # 1. Extract a small graph.
    session = "topics-live"
    extract = subprocess.run(
        ["uv", "run", "mykg", "extract-graph", str(live_corpus),
         "--session", session, "--obsidian-vault"],
        capture_output=True, text=True)
    assert extract.returncode == 0, extract.stderr

    # 2. Build the entity wiki first so topic wikilinks resolve.
    subprocess.run(["uv", "run", "mykg", "build-wiki", session], check=True)

    # 3. Build topics.
    topics = subprocess.run(["uv", "run", "mykg", "build-topics", session],
                            capture_output=True, text=True)
    assert topics.returncode == 0, topics.stderr

    # 4. Assert outputs exist and never touched the extract session's intermediate state.
    import mykg.config as cfg
    vault = Path(cfg.WIKI_ROOT) / session
    assert (vault / "Topics.md").exists()
    assert (vault / "schema_proposals.md").exists()
    sess = Path(cfg.SESSIONS_DIR) / session
    assert not (sess / "intermediate" / "topics_pages.done").exists()
    assert (sess / "topics_state" / "topics_index.done").exists()
```

- [ ] **Step 2: Run it (only if a live provider is configured)**

Run: `uv run pytest tests/test_topics_live.py -q -m live --no-cov`
Expected: PASS when a provider is configured; otherwise skip/deselect. Do **not** block the plan on this if no live provider is available — note it and move on.

- [ ] **Step 3: Commit**

```bash
git add tests/test_topics_live.py
git commit -m "test(topics): live end-to-end build-topics smoke test"
```

---

## Final verification

- [ ] Run `uv run pytest -m "not live" -q --no-cov` — all pass.
- [ ] Run `uv run ruff check src/ tests/` — no new errors.
- [ ] Confirm no stray files written outside `tmp_path` during the run (`git status` clean apart from intended changes).
- [ ] Update `CLAUDE.md`'s wiki section to add a short `build-topics` paragraph (owned files, opt-in, propose-only proposals). *(CLAUDE.md is gitignored in this repo — this is a local doc edit, not committed.)*

## Self-review notes (author)

- **Spec coverage:** §1 command/architecture → Tasks 6–7; §2 clustering → Task 2; §3 topic pages → Task 4; §4 incremental → Task 3 + Task 6 `run_topics_pages`; §5 proposals → Task 5 + Task 6 `run_topics_proposals`; §6 steps/config → Tasks 1, 6; §7 testing → every task's tests + Task 8. Writer-disjointness + isolation invariants asserted in Task 6 tests.
- **Design refinement recorded:** the manifest keys on `community_fingerprint` (member-set hash), not the display ordinal `topic_id`, so incremental rebuild stays correct when community ordering shifts. Noted in Task 3.
- **Reuse:** `strip_invalid_wikilinks`, `_capped_grounding`, `grounding_hash`, `load_wiki_graph`, `session_root`, `vault_dir`, `flatten_schema` are all imported, not reimplemented.
