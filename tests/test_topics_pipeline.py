from __future__ import annotations

import json
from pathlib import Path

from mykg.orchestrator import PipelineContext, run
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
    run(TOPIC_STEPS, ctx)
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
