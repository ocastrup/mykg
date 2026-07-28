# Wiki Frontmatter Enrichment + Source Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the Obsidian wiki vault with resolvable source-document notes, wikilinked `source_files`, an Obsidian `tags` property from the entity type, and a Dataview-queryable `neighbors` list carrying first-hop edge confidence.

**Architecture:** All changes are confined to the wiki subsystem. A shared path-normalization helper lives in `src/mykg/wiki/loader.py`. Frontmatter rendering (`src/mykg/wiki/page_builder.py`) gains `tags`, wikilink `source_files`, and `neighbors`. A new `wiki_sources` pipeline step (`src/mykg/wiki_pipeline.py`) materializes each corpus file from `intermediate/file_manifest.json` into `sources/<basename>.md`, tracked by a dedicated manifest in `src/mykg/wiki/manifest.py` for incremental rebuild and cleanup.

**Tech Stack:** Python 3, Pydantic, PyYAML, pytest. Package manager: `uv`.

**Spec:** `docs/superpowers/specs/2026-07-28-wiki-frontmatter-source-notes-design.md`

---

## File Structure

- `src/mykg/wiki/loader.py` — add `source_note_name(raw_path) -> str` helper (single source of truth for corpus-path → note-name).
- `src/mykg/wiki/page_builder.py` — enrich `_frontmatter`; thread `neighbors` through `render_entity_page` / `render_stub_page` / `generate_entity_page`; add `render_source_page`.
- `src/mykg/wiki/manifest.py` — add `load_source_manifest` / `save_source_manifest`.
- `src/mykg/wiki_pipeline.py` — add `run_wiki_sources` step; register in `WIKI_STEPS`.
- `README.md` — short Obsidian-Groups usage tip.
- Tests: `tests/test_wiki_loader.py`, `tests/test_wiki_page_builder.py`, `tests/test_wiki_pipeline.py`.

Run all tests with: `uv run pytest -q`. Run a single test with `uv run pytest tests/FILE::TEST -v`.

---

### Task 1: Path normalization helper `source_note_name`

**Files:**
- Modify: `src/mykg/wiki/loader.py`
- Test: `tests/test_wiki_loader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_loader.py`:

```python
from mykg.wiki.loader import source_note_name


def test_source_note_name_strips_dirs_and_extension():
    assert source_note_name("doc.md") == "doc"
    assert source_note_name("_preprocessed\\Future Yard Architecture.md") == "Future Yard Architecture"
    assert source_note_name("nested/sub/Report.md") == "Report"
    assert source_note_name("NoExtension") == "NoExtension"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_loader.py::test_source_note_name_strips_dirs_and_extension -v`
Expected: FAIL with `ImportError: cannot import name 'source_note_name'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/mykg/wiki/loader.py` (below the imports, before `class WikiNode`):

```python
def source_note_name(raw_path: str) -> str:
    """Corpus file path -> flat vault note name (drop dir prefix and .md)."""
    base = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith(".md"):
        base = base[:-3]
    return base
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_wiki_loader.py::test_source_note_name_strips_dirs_and_extension -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/loader.py tests/test_wiki_loader.py
git commit -m "feat(wiki): add source_note_name path helper"
```

---

### Task 2: Enrich entity frontmatter (`tags`, wikilink `source_files`, `neighbors`)

**Files:**
- Modify: `src/mykg/wiki/page_builder.py`
- Test: `tests/test_wiki_page_builder.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_wiki_page_builder.py` (top-level, after the existing imports; note the imports already include `Neighbor`, `render_entity_page`, `render_stub_page`):

```python
def test_frontmatter_has_tags_wikilinks_and_neighbors():
    node = WikiNode(
        id="person-alice", type="Software Engineer", name="Alice",
        attributes={"name": {"value": "Alice", "confidence": 0.9}},
        source_files=["doc.md", "_preprocessed\\Future Yard Architecture.md"],
        grounded_chunk_keys=["doc.md::1"],
        grounded_chunks=["Alice works at Acme."], grounded=True)
    nb = [Neighbor(id="org-acme", name="Acme", type="Organization",
                   relationship="works_at", confidence=0.91)]
    page = render_entity_page(node, "## Alice\n\nbody", nb)
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["type"] == "Software Engineer"
    assert fm["tags"] == ["Software_Engineer"]        # sanitized to valid tag
    assert fm["source_files"] == [
        "[[doc]]", "[[Future Yard Architecture]]"]     # wikilinked, flattened
    assert fm["neighbors"] == [{"link": "[[org-acme|Acme]]", "confidence": 0.91}]


def test_frontmatter_neighbors_empty_when_none():
    node = WikiNode(
        id="person-bob", type="Person", name="Bob",
        attributes={}, source_files=["doc.md"],
        grounded_chunk_keys=[], grounded_chunks=[], grounded=False)
    page = render_entity_page(node, "body", [])
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["neighbors"] == []
    assert fm["tags"] == ["Person"]
    assert fm["source_files"] == ["[[doc]]"]
```

Update the existing `test_render_entity_page_has_valid_frontmatter` to pass neighbors and assert new keys:

```python
def test_render_entity_page_has_valid_frontmatter():
    page = render_entity_page(_node(), "## Alice\n\nAlice works at [[org-acme|Acme]].", [])
    assert page.startswith("---\n")
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["mykg_id"] == "person-alice"
    assert fm["type"] == "Person"
    assert fm["tags"] == ["Person"]
    assert fm["source_files"] == ["[[doc]]"]
    assert fm["neighbors"] == []
    assert fm["grounded"] is True
    assert fm["grounded_chunks"] == ["doc.md::1"]
    assert "Alice works at [[org-acme|Acme]]." in page
```

Update the existing `test_stub_page_flags_ungrounded` to assert the neighbor appears in frontmatter too:

```python
def test_stub_page_flags_ungrounded():
    page = render_stub_page(_node(grounded=False), [Neighbor(
        id="org-acme", name="Acme", type="Organization",
        relationship="works_at", confidence=0.7)])
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is False
    assert fm["neighbors"] == [{"link": "[[org-acme|Acme]]", "confidence": 0.7}]
    assert "[[org-acme|Acme]]" in page
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wiki_page_builder.py -k "frontmatter or stub_page_flags" -v`
Expected: FAIL — `render_entity_page()` takes 2 positional args / missing `tags` key.

- [ ] **Step 3: Write the implementation**

In `src/mykg/wiki/page_builder.py`, add the import and a tag helper near the top (after existing imports):

```python
from mykg.wiki.loader import Neighbor, WikiGraph, WikiNode, source_note_name

_TAG_INVALID = re.compile(r"[^A-Za-z0-9_/-]+")


def _type_tag(type_name: str) -> str:
    return _TAG_INVALID.sub("_", type_name.strip())
```

(The existing `from mykg.wiki.loader import Neighbor, WikiGraph, WikiNode` line is replaced by the one above — adding `source_note_name`.)

Replace `_frontmatter` and `render_entity_page`:

```python
def _frontmatter(node: WikiNode, neighbors: list[Neighbor]) -> str:
    data = {
        "mykg_id": node.id,
        "type": node.type,
        "tags": [_type_tag(node.type)],
        "aliases": [node.name],
        "source_files": [f"[[{source_note_name(s)}]]" for s in node.source_files],
        "neighbors": [{"link": f"[[{n.id}|{n.name}]]", "confidence": n.confidence}
                      for n in neighbors],
        "grounded": node.grounded,
        "grounded_chunks": node.grounded_chunk_keys,
    }
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n"


def render_entity_page(node: WikiNode, body_markdown: str,
                       neighbors: list[Neighbor]) -> str:
    """Wrap already-validated body markdown with YAML frontmatter."""
    return _frontmatter(node, neighbors) + body_markdown.strip() + "\n"
```

Update `render_stub_page` to forward its neighbors to `render_entity_page` (change only the final return):

```python
    return render_entity_page(node, "\n".join(lines), neighbors)
```

Update the two `render_entity_page(...)` calls inside `generate_entity_page`:
- The ungrounded early return already calls `render_stub_page(node, neighbors)` — unchanged.
- Change the final success return to pass neighbors:

```python
    return render_entity_page(node, cleaned, neighbors), True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wiki_page_builder.py -v`
Expected: PASS (all tests in the file, including the updated ones).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/page_builder.py tests/test_wiki_page_builder.py
git commit -m "feat(wiki): add tags, wikilinked source_files, and neighbors to frontmatter"
```

---

### Task 3: `render_source_page` for source-document notes

**Files:**
- Modify: `src/mykg/wiki/page_builder.py`
- Test: `tests/test_wiki_page_builder.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_wiki_page_builder.py`:

```python
def test_render_source_page_has_frontmatter_and_full_body():
    from mykg.wiki.page_builder import render_source_page
    page = render_source_page("_preprocessed\\Future Yard Architecture.md",
                              "# Heading\n\nFull body text.")
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["type"] == "Source"
    assert fm["tags"] == ["Source"]
    assert fm["source_file"] == "_preprocessed\\Future Yard Architecture.md"
    assert "# Heading\n\nFull body text." in page
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_page_builder.py::test_render_source_page_has_frontmatter_and_full_body -v`
Expected: FAIL with `ImportError: cannot import name 'render_source_page'`.

- [ ] **Step 3: Write the implementation**

Add to `src/mykg/wiki/page_builder.py` (near the other render functions):

```python
def render_source_page(raw_path: str, content: str) -> str:
    """Render a corpus document as a vault note: minimal frontmatter + full text."""
    data = {"type": "Source", "tags": ["Source"], "source_file": raw_path}
    fm = "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n"
    return fm + content.strip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_wiki_page_builder.py::test_render_source_page_has_frontmatter_and_full_body -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/page_builder.py tests/test_wiki_page_builder.py
git commit -m "feat(wiki): render source-document notes"
```

---

### Task 4: Source manifest load/save

**Files:**
- Modify: `src/mykg/wiki/manifest.py`
- Test: `tests/test_wiki_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_wiki_manifest.py`:

```python
def test_source_manifest_roundtrip(tmp_path):
    from mykg.wiki.manifest import load_source_manifest, save_source_manifest
    assert load_source_manifest(tmp_path) == {"sources": {}}
    save_source_manifest(tmp_path, {"doc": "hash123"})
    loaded = load_source_manifest(tmp_path)
    assert loaded["sources"]["doc"]["hash"] == "hash123"
    assert loaded["sources"]["doc"]["path"] == "sources/doc.md"
```

If `tests/test_wiki_manifest.py` has no imports yet, this test is self-contained (imports inline).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_manifest.py::test_source_manifest_roundtrip -v`
Expected: FAIL with `ImportError: cannot import name 'load_source_manifest'`.

- [ ] **Step 3: Write the implementation**

Add to `src/mykg/wiki/manifest.py` (after the existing `_MANIFEST_NAME` constant and `save_manifest`):

```python
_SOURCE_MANIFEST_NAME = ".wiki_sources_manifest.json"


def load_source_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _SOURCE_MANIFEST_NAME
    if not path.exists():
        return {"sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_source_manifest(vault_dir: Path, hashes: dict[str, str]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    sources = {name: {"hash": h, "path": f"sources/{name}.md"}
               for name, h in hashes.items()}
    (vault_dir / _SOURCE_MANIFEST_NAME).write_text(
        json.dumps({"sources": sources}, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_wiki_manifest.py::test_source_manifest_roundtrip -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki/manifest.py tests/test_wiki_manifest.py
git commit -m "feat(wiki): source-note manifest load/save"
```

---

### Task 5: `wiki_sources` pipeline step (materialize, dedupe, cleanup, incremental)

**Files:**
- Modify: `src/mykg/wiki_pipeline.py`
- Test: `tests/test_wiki_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_wiki_pipeline.py` (the module already imports from `mykg.wiki_pipeline` and defines `_session` / `_ctx`; extend the import line to include `run_wiki_sources`):

```python
def test_wiki_sources_writes_full_text_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    root = _session(tmp_path)
    ctx = _ctx(root)
    from mykg.wiki_pipeline import run_wiki_sources
    run_wiki_sources(ctx)
    note = (vault_dir(ctx) / "sources" / "doc.md").read_text()
    import yaml
    fm = yaml.safe_load(note.split("---\n")[1])
    assert fm["type"] == "Source"
    assert fm["tags"] == ["Source"]
    assert "Alice works at Acme." in note
    assert (vault_dir(ctx) / ".wiki_sources_manifest.json").exists()


def test_wiki_sources_cleans_up_removed_and_is_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    root = _session(tmp_path)
    ctx = _ctx(root)
    from mykg.wiki_pipeline import run_wiki_sources
    run_wiki_sources(ctx)
    note_path = vault_dir(ctx) / "sources" / "doc.md"
    before = note_path.stat().st_mtime_ns
    run_wiki_sources(ctx)                       # unchanged -> not rewritten
    assert note_path.stat().st_mtime_ns == before
    # Remove the source from the corpus manifest; note should be deleted.
    import json
    fm_path = root / "intermediate" / "file_manifest.json"
    fm_path.write_text(json.dumps({}))
    run_wiki_sources(ctx)
    assert not note_path.exists()


def test_wiki_steps_include_sources_after_load():
    assert [s.name for s in WIKI_STEPS] == [
        "wiki_load", "wiki_sources", "wiki_pages", "wiki_hubs", "wiki_index"]
```

Delete the old `test_wiki_steps_list_names_and_order` test (the new `test_wiki_steps_include_sources_after_load` replaces it).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wiki_pipeline.py -k "sources or steps_include" -v`
Expected: FAIL with `ImportError: cannot import name 'run_wiki_sources'`.

- [ ] **Step 3: Write the implementation**

In `src/mykg/wiki_pipeline.py`, add imports at the top of the file (alongside existing imports):

```python
import hashlib
import json
```

Extend the manifest import:

```python
from mykg.wiki.manifest import (
    grounding_hash,
    load_manifest,
    load_source_manifest,
    plan_rebuild,
    save_manifest,
    save_source_manifest,
)
```

Extend the page_builder import to include `render_source_page`, and the loader import to include `source_note_name`:

```python
from mykg.wiki.loader import WikiGraph, load_wiki_graph, source_note_name
from mykg.wiki.page_builder import (
    extract_lead,
    generate_entity_page,
    render_home_page,
    render_hub_page,
    render_source_page,
)
```

Add the step function (place it after `run_wiki_load`):

```python
def run_wiki_sources(ctx: PipelineContext) -> None:
    manifest_path = session_root(ctx) / "intermediate" / "file_manifest.json"
    corpus = json.loads(manifest_path.read_text(encoding="utf-8"))
    vault = vault_dir(ctx)
    sources = vault / "sources"
    sources.mkdir(parents=True, exist_ok=True)

    prior = load_source_manifest(vault).get("sources", {})
    hashes: dict[str, str] = {}
    seen: dict[str, str] = {}
    for raw_path, meta in corpus.items():
        name = source_note_name(raw_path)
        if name in seen:
            log.warning("wiki_sources — basename collision %r vs %r -> %s.md (first wins)",
                        seen[name], raw_path, name)
            continue
        seen[name] = raw_path
        content = (meta or {}).get("content", "")
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        hashes[name] = h
        if prior.get(name, {}).get("hash") != h:
            (sources / f"{name}.md").write_text(
                render_source_page(raw_path, content), encoding="utf-8")

    for name in prior:
        if name not in hashes:
            (sources / f"{name}.md").unlink(missing_ok=True)

    save_source_manifest(vault, hashes)
    (ctx.intermediate_dir / "wiki_sources.done").write_text("ok")
    log.info("wiki_sources — %d source notes", len(hashes))
```

Register the step in `WIKI_STEPS` (insert after `wiki_load`):

```python
WIKI_STEPS: list[Step] = [
    Step(name="wiki_load", fn=run_wiki_load, outputs=["wiki_graph.json"]),
    Step(name="wiki_sources", fn=run_wiki_sources, outputs=["wiki_sources.done"]),
    Step(name="wiki_pages", fn=run_wiki_pages, outputs=["wiki_pages.done"], is_llm_step=True),
    Step(name="wiki_hubs", fn=run_wiki_hubs, outputs=["wiki_hubs.done"]),
    Step(name="wiki_index", fn=run_wiki_index, outputs=["wiki_index.done"]),
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wiki_pipeline.py -v`
Expected: PASS (including the existing end-to-end tests).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/wiki_pipeline.py tests/test_wiki_pipeline.py
git commit -m "feat(wiki): wiki_sources step materializing corpus notes"
```

---

### Task 6: Document the Obsidian Groups usage tip

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the tip**

Append this section to `README.md`:

```markdown
## Obsidian vault tips

Each entity note carries a `tags` property set from its type (e.g. `#Person`,
`#Document`), and source documents are notes under `sources/` tagged `#Source`.
Use Obsidian **Graph view → Groups** to recolor these: add a group with query
`tag:#Document` to highlight one entity type, or `path:sources/` to highlight
source documents. Groups only recolor nodes — they do not change graph topology.
The `neighbors` frontmatter list (each `{link, confidence}`) is queryable with
Dataview, e.g. to surface an entity's strongest first-hop connections.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: Obsidian Groups + tags/neighbors usage tip"
```

---

### Task 7: Full-suite verification

- [ ] **Step 1: Run the whole test suite**

Run: `uv run pytest -q`
Expected: PASS — no regressions in wiki or other modules.

- [ ] **Step 2: If green, no commit needed**

If any unrelated test fails, investigate whether the frontmatter/signature changes touched a shared consumer (search for `render_entity_page`, `_frontmatter`, `source_files` usages) and fix forward with a focused commit.

---

## Self-Review Notes

- **Spec coverage:** source notes (Tasks 3–5), wikilink `source_files` (Task 2), `tags` (Task 2), `neighbors` with confidence (Task 2), incremental + cleanup (Tasks 4–5), Groups doc (Task 6). All spec sections mapped.
- **Type consistency:** `source_note_name` (Task 1) is reused verbatim in Tasks 2 and 5. `render_entity_page(node, body, neighbors)` signature is consistent across Tasks 2 and 5. `render_source_page(raw_path, content)` consistent across Tasks 3 and 5. `neighbors` frontmatter shape `{"link", "confidence"}` identical in Task 2 tests and impl.
- **No placeholders:** every code and test step is complete.
