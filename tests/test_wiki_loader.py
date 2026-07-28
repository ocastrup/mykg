"""Tests for wiki.loader — reading a session contract into a WikiGraph."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.wiki.loader import WikiGraph, load_wiki_graph, source_note_name


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


def test_source_note_name_strips_dirs_and_extension():
    assert source_note_name("doc.md") == "doc"
    assert source_note_name("_preprocessed\\Future Yard Architecture.md") == "Future Yard Architecture"
    assert source_note_name("nested/sub/Report.md") == "Report"
    assert source_note_name("NoExtension") == "NoExtension"

