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
