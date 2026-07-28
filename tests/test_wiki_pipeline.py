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
    run_wiki_sources,
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


def test_full_pipeline_writes_vault(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
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


def test_incremental_second_run_regenerates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    root = _session(tmp_path)
    ctx = _ctx(root)
    run_wiki_load(ctx)
    run_wiki_pages(ctx)
    before = (vault_dir(ctx) / "entities" / "person-alice.md").stat().st_mtime_ns
    run_wiki_load(ctx)
    run_wiki_pages(ctx)   # manifest unchanged -> page kept, not rewritten
    after = (vault_dir(ctx) / "entities" / "person-alice.md").stat().st_mtime_ns
    assert before == after


def test_wiki_sources_writes_full_text_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("mykg.config.WIKI_ROOT", str(tmp_path / "wiki"))
    root = _session(tmp_path)
    ctx = _ctx(root)
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
    run_wiki_sources(ctx)
    note_path = vault_dir(ctx) / "sources" / "doc.md"
    before = note_path.stat().st_mtime_ns
    run_wiki_sources(ctx)                       # unchanged -> not rewritten
    assert note_path.stat().st_mtime_ns == before
    import json
    fm_path = root / "intermediate" / "file_manifest.json"
    fm_path.write_text(json.dumps({}))
    run_wiki_sources(ctx)
    assert not note_path.exists()


def test_wiki_steps_include_sources_after_load():
    assert [s.name for s in WIKI_STEPS] == [
        "wiki_load", "wiki_sources", "wiki_pages", "wiki_hubs", "wiki_index"]
