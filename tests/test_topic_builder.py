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
