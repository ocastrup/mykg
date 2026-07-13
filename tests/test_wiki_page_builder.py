"""Tests for the pure page-rendering primitives (link validator, frontmatter)."""
from __future__ import annotations

import yaml

from mykg.wiki.loader import Neighbor, WikiGraph, WikiNode
from mykg.wiki.page_builder import (
    build_entity_prompt,
    extract_lead,
    generate_entity_page,
    render_entity_page,
    render_home_page,
    render_hub_page,
    render_stub_page,
    strip_invalid_wikilinks,
)


def _node(grounded: bool = True) -> WikiNode:
    return WikiNode(
        id="person-alice", type="Person", name="Alice",
        attributes={"name": {"value": "Alice", "confidence": 0.9}},
        source_files=["doc.md"],
        grounded_chunk_keys=["doc.md::1"] if grounded else [],
        grounded_chunks=["Alice works at Acme."] if grounded else [],
        grounded=grounded)


def test_valid_link_survives_invented_link_stripped():
    md = "Alice joined [[org-acme|Acme]] and knows [[person-ghost|Ghost]]."
    cleaned, dropped = strip_invalid_wikilinks(md, {"org-acme"})
    assert "[[org-acme|Acme]]" in cleaned
    assert "[[person-ghost" not in cleaned
    assert "Ghost" in cleaned          # label preserved as plain text
    assert dropped == ["person-ghost"]


def test_bare_invented_link_stripped_to_text():
    cleaned, dropped = strip_invalid_wikilinks("See [[unknown-id]].", set())
    assert cleaned == "See unknown-id."
    assert dropped == ["unknown-id"]


def test_render_entity_page_has_valid_frontmatter():
    page = render_entity_page(_node(), "## Alice\n\nAlice works at [[org-acme|Acme]].")
    assert page.startswith("---\n")
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["mykg_id"] == "person-alice"
    assert fm["type"] == "Person"
    assert fm["grounded"] is True
    assert fm["grounded_chunks"] == ["doc.md::1"]
    assert "Alice works at [[org-acme|Acme]]." in page


def test_nested_smuggled_wikilink_is_fully_stripped():
    md = "reports to [[bad-wrapper|[[secret-invented-id]]]] ok"
    cleaned, dropped = strip_invalid_wikilinks(md, set())
    # No live wikilink of any kind survives -- the invariant under test.
    # (The bare id may remain as inert plain text, same as any other
    # invalid target with no label; that is not a link.)
    assert "[[" not in cleaned
    assert "[[secret-invented-id" not in cleaned
    assert "bad-wrapper" in dropped
    assert "secret-invented-id" in dropped


def test_empty_label_wikilink_is_stripped():
    md = "See [[unknown-id|]] here."
    cleaned, dropped = strip_invalid_wikilinks(md, set())
    assert "[[" not in cleaned
    assert "unknown-id" in dropped


def test_wikilink_with_bracket_in_label_is_stripped():
    md = "see [[unknown|La]bel]] end"
    cleaned, dropped = strip_invalid_wikilinks(md, set())
    assert "[[unknown" not in cleaned
    assert "unknown" in dropped


def test_stub_page_flags_ungrounded():
    page = render_stub_page(_node(grounded=False), [Neighbor(
        id="org-acme", name="Acme", type="Organization",
        relationship="works_at", confidence=0.7)])
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is False
    assert "[[org-acme|Acme]]" in page


class _StubAdapter:
    def __init__(self, reply: str):
        self.reply, self.calls = reply, []

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        self.calls.append(user)
        return self.reply


def _alice_and_neighbor():
    node = WikiNode(
        id="person-alice", type="Person", name="Alice",
        attributes={"name": {"value": "Alice", "confidence": 0.9},
                    "affiliation": {"value": "Acme", "confidence": 0.1}},
        source_files=["doc.md"], grounded_chunk_keys=["doc.md::1"],
        grounded_chunks=["Alice works at Acme."], grounded=True)
    nb = [Neighbor(id="org-acme", name="Acme", type="Organization",
                   relationship="works_at", confidence=0.7)]
    return node, nb


def test_prompt_drops_low_confidence_attributes():
    node, nb = _alice_and_neighbor()
    _system, user = build_entity_prompt(node, nb, min_attr_confidence=0.3,
                                        max_grounding_tokens=4000)
    assert "Alice works at Acme." in user     # grounding included
    assert "org-acme" in user                 # neighbor offered for linking
    assert "affiliation" not in user          # 0.1 < 0.3 filtered out


def test_generate_strips_invented_links_and_wraps():
    node, nb = _alice_and_neighbor()
    reply = "## Alice\n\nWorks at [[org-acme|Acme]] with [[person-ghost|Ghost]]."
    page, ok = generate_entity_page(node, nb, _StubAdapter(reply),
                                    min_attr_confidence=0.3, max_grounding_tokens=4000)
    assert ok is True
    assert "[[org-acme|Acme]]" in page
    assert "person-ghost" not in page
    assert page.startswith("---\n")


def test_blank_reply_falls_back_to_stub():
    node, nb = _alice_and_neighbor()
    page, ok = generate_entity_page(node, nb, _StubAdapter("   "),
                                    min_attr_confidence=0.3, max_grounding_tokens=4000)
    assert ok is False
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is True             # node had grounding...
    assert fm["mykg_id"] == "person-alice"
    assert "## Connections" in page
    assert "[[org-acme|Acme]] (works_at)" in page
    assert "Automated summary generation failed" in page
    assert "No source text was available to summarize" not in page


class _RaisingAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        raise RuntimeError("adapter unavailable")


def test_adapter_exception_falls_back_to_stub_and_does_not_propagate():
    node, nb = _alice_and_neighbor()
    page, ok = generate_entity_page(node, nb, _RaisingAdapter(),
                                    min_attr_confidence=0.3, max_grounding_tokens=4000)
    assert ok is False
    fm = yaml.safe_load(page.split("---\n")[1])
    assert fm["grounded"] is True
    assert fm["mykg_id"] == "person-alice"
    assert "Automated summary generation failed" in page
    assert "[[org-acme|Acme]] (works_at)" in page


def test_extract_lead_skips_frontmatter_and_heading():
    page = "---\nmykg_id: x\n---\n\n## Alice\n\nAlice works at Acme.\n\nMore text."
    assert extract_lead(page) == "Alice works at Acme."


def test_hub_lists_every_entity_of_type():
    nodes = [_node()]  # from earlier in this file (person-alice)
    hub = render_hub_page("Person", nodes, {"person-alice": "Alice works at Acme."})
    assert "# Person" in hub
    assert "[[person-alice|Alice]]" in hub
    assert "Alice works at Acme." in hub


def test_home_links_every_type_hub():
    g = WikiGraph(nodes={"person-alice": _node()}, edges=[], types=["Person", "Organization"])
    home = render_home_page(g, "2026-07-05T08-41-11", "2026-07-12T10:00:00Z")
    assert "[[hubs/Person|Person]]" in home
    assert "[[hubs/Organization|Organization]]" in home
    assert "1" in home  # node count
