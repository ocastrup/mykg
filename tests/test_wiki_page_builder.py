"""Tests for the pure page-rendering primitives (link validator, frontmatter)."""
from __future__ import annotations

import yaml

from mykg.wiki.loader import Neighbor, WikiNode
from mykg.wiki.page_builder import (
    render_entity_page,
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
