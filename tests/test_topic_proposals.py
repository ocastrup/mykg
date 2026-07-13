from __future__ import annotations

import json

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph, WikiNode
from mykg.wiki.proposals import (
    Proposal,
    aggregate_proposals,
    extract_proposals,
    render_proposals_md,
)


class _StubAdapter:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return self.reply

    def endpoint_label(self):
        return "stub"


def _graph():
    nodes = {"o": WikiNode(id="o", type="Organization", name="Acme", attributes={},
                           source_files=[], grounded_chunk_keys=["a.md::1"],
                           grounded_chunks=["Acme, founded in 1998."], grounded=True)}
    return WikiGraph(nodes=nodes, edges=[], types=["Organization"])


def test_extract_proposals_parses_grounded_json():
    reply = json.dumps([
        {"kind": "add_attribute", "target": "Organization.founded_year",
         "rationale": "founding year stated", "quote": "founded in 1998"},
        {"kind": "bogus", "target": "x", "quote": "q"},           # wrong kind -> dropped
        {"kind": "add_attribute", "target": "Organization.ceo"},  # no quote -> dropped
    ])
    comm = Community(topic_id="t0001", member_ids=["o"])
    props = extract_proposals(comm, _graph(), {"Organization": ["name"]},
                              _StubAdapter(reply), max_grounding_tokens=4000)
    assert len(props) == 1
    assert props[0].target == "Organization.founded_year"


def test_aggregate_dedupes_and_counts():
    a = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="x", quotes=["q1"])
    b = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="y", quotes=["q2"])
    out = aggregate_proposals([a, b])
    assert len(out) == 1
    assert out[0].evidence_count == 2
    assert set(out[0].quotes) == {"q1", "q2"}


def test_render_proposals_md_is_grounded():
    p = Proposal(kind="add_attribute", target="Organization.founded_year",
                 rationale="founding year stated", quotes=["founded in 1998"], evidence_count=3)
    md = render_proposals_md([p], "sess1", "2026-07-13T00:00:00Z")
    assert "Organization.founded_year" in md
    assert "founded in 1998" in md
    assert "sess1" in md
    assert "Propose-only" in md


def test_extract_proposals_malformed_json_returns_empty():
    """extract_proposals returns [] when LLM returns invalid JSON or non-array."""
    comm = Community(topic_id="t0001", member_ids=["o"])

    # Test non-JSON string
    props = extract_proposals(comm, _graph(), {"Organization": ["name"]},
                              _StubAdapter("not valid json at all"), max_grounding_tokens=4000)
    assert props == []

    # Test valid JSON but not an array (object instead)
    props = extract_proposals(comm, _graph(), {"Organization": ["name"]},
                              _StubAdapter('{"kind": "add_attribute"}'), max_grounding_tokens=4000)
    assert props == []


class _ErrorAdapter:
    """Adapter that raises an exception on complete()."""
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        raise RuntimeError("adapter error")

    def endpoint_label(self):
        return "error"


def test_extract_proposals_adapter_raises_returns_empty():
    """extract_proposals returns [] and does not raise when adapter fails."""
    comm = Community(topic_id="t0001", member_ids=["o"])
    props = extract_proposals(comm, _graph(), {"Organization": ["name"]},
                              _ErrorAdapter(), max_grounding_tokens=4000)
    assert props == []
