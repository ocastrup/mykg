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


def test_parallel_edges_collapse_to_max_confidence():
    # Graph with two edges on the same node pair (a-b) with different confidences.
    # The lower-confidence edge is below threshold; the higher-confidence edge is above.
    # When both are in the edge list, max() collapse keeps the higher confidence,
    # so the pair stays connected despite the low-confidence edge.
    ids = ["a", "b", "c"]
    nodes = {i: _node(i) for i in ids}
    edges = [
        WikiEdge(id="low", type="rel", from_id="a", to_id="b", confidence=0.2),
        WikiEdge(id="high", type="rel", from_id="a", to_id="b", confidence=0.8),
        WikiEdge(id="e2", type="rel", from_id="b", to_id="c", confidence=0.9),
    ]
    g = WikiGraph(nodes=nodes, edges=edges, types=["Thing"])

    # With min_edge_confidence=0.5:
    # - low edge (0.2) is dropped by threshold filter
    # - high edge (0.8) is kept, creating a-b with weight 0.8
    # - e2 (0.9) is kept, creating b-c with weight 0.9
    # Result: a-b-c form one connected component
    comms = build_communities(g, min_edge_confidence=0.5, resolution=1.0, min_size=2)

    members = [set(c.member_ids) for c in comms.communities]
    # All three nodes should be in the same community (connected via max-collapsed edge)
    assert {"a", "b", "c"} in members
    assert len(comms.communities) == 1


def test_all_edges_below_threshold_yields_all_singletons():
    # Graph where every edge has confidence strictly below the threshold.
    # All edges are dropped by the threshold filter, leaving only isolated nodes.
    # With min_size=1, each node becomes its own singleton community.
    ids = ["a", "b", "c", "d"]
    nodes = {i: _node(i) for i in ids}
    edges = [
        WikiEdge(id="e1", type="rel", from_id="a", to_id="b", confidence=0.1),
        WikiEdge(id="e2", type="rel", from_id="b", to_id="c", confidence=0.1),
        WikiEdge(id="e3", type="rel", from_id="c", to_id="d", confidence=0.1),
    ]
    g = WikiGraph(nodes=nodes, edges=edges, types=["Thing"])

    # With min_edge_confidence=0.5, all edges (confidence 0.1) are dropped.
    # No edges remain -> each node is isolated.
    # With min_size=1, all 4 singleton communities are kept.
    comms = build_communities(g, min_edge_confidence=0.5, resolution=1.0, min_size=1)

    assert len(comms.communities) == 4
    # Each community should have exactly one member (the isolated node itself)
    for comm in comms.communities:
        assert len(comm.member_ids) == 1
