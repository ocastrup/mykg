"""Tests for the incremental-rebuild manifest."""
from __future__ import annotations

from mykg.wiki.loader import WikiGraph, WikiNode
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


def test_grounding_hash_changes_with_neighbor_confidence_and_name():
    from mykg.wiki.loader import Neighbor
    node = WikiNode(
        id="person-alice", type="Person", name="Alice",
        attributes={}, source_files=["doc.md"],
        grounded_chunk_keys=["doc.md::1"], grounded_chunks=["text"], grounded=True)
    base_nb = [Neighbor(id="org-acme", name="Acme", type="Organization",
                        relationship="works_at", confidence=0.70)]
    changed_conf = [Neighbor(id="org-acme", name="Acme", type="Organization",
                             relationship="works_at", confidence=0.95)]
    changed_name = [Neighbor(id="org-acme", name="Acme Corp", type="Organization",
                             relationship="works_at", confidence=0.70)]
    h0 = grounding_hash(node, base_nb)
    assert grounding_hash(node, changed_conf) != h0
    assert grounding_hash(node, changed_name) != h0


def test_source_manifest_roundtrip(tmp_path):
    from mykg.wiki.manifest import load_source_manifest, save_source_manifest
    assert load_source_manifest(tmp_path) == {"sources": {}}
    save_source_manifest(tmp_path, {"doc": "hash123"})
    loaded = load_source_manifest(tmp_path)
    assert loaded["sources"]["doc"]["hash"] == "hash123"
    assert loaded["sources"]["doc"]["path"] == "sources/doc.md"
