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
