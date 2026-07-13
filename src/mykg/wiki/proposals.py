"""Propose-only, human-gated schema improvement suggestions from communities."""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from mykg.llm.adapter import LLMAdapter
from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.page_builder import _capped_grounding

log = logging.getLogger(__name__)

_KINDS = {"add_attribute", "add_relationship_type", "add_concept_type"}

_PROPOSAL_SYSTEM = (
    "You analyze a cluster of related entities and their source text to find schema "
    "gaps: recurring attributes, relationship types, or entity types the current schema "
    "does not capture but the text clearly supports. Output ONLY a JSON array; each item: "
    '{"kind": "add_attribute"|"add_relationship_type"|"add_concept_type", '
    '"target": "<Type.attr | RelType | ConceptType>", "rationale": "<short>", '
    '"quote": "<verbatim source snippet>"}. Only include proposals grounded in a quote '
    "from the excerpts. If none, output []."
)


class Proposal(BaseModel):
    kind: str
    target: str
    rationale: str = ""
    quotes: list[str] = []
    evidence_count: int = 1


def _parse_array(raw: str | None) -> list:
    txt = LLMAdapter.strip_code_fences(raw or "").strip()
    try:
        val = json.loads(txt)
    except Exception:
        return []
    return val if isinstance(val, list) else []


def extract_proposals(community: Community, graph: WikiGraph, flattened_schema: dict,
                      adapter: LLMAdapter, max_grounding_tokens: int) -> list[Proposal]:
    types = sorted({graph.nodes[m].type for m in community.member_ids if m in graph.nodes})
    schema_block = "\n".join(f"{t}: {flattened_schema.get(t, [])}" for t in types) or "(none)"
    chunks: list[str] = []
    for m in community.member_ids:
        if m in graph.nodes:
            chunks.extend(graph.nodes[m].grounded_chunks)
    grounding = _capped_grounding(chunks, max_grounding_tokens)
    user = (f"# Current schema for these types\n{schema_block}\n\n"
            f"# Source excerpts\n{grounding}\n")
    try:
        raw = adapter.complete(_PROPOSAL_SYSTEM, user,
                               context_label=f"topic-proposals:{community.topic_id}")
    except Exception:
        log.warning("topics: proposal pass failed for %s", community.topic_id, exc_info=True)
        return []
    out: list[Proposal] = []
    for item in _parse_array(raw):
        if not isinstance(item, dict):
            continue
        kind, target, quote = item.get("kind"), item.get("target"), item.get("quote")
        if kind in _KINDS and target and quote:
            out.append(Proposal(kind=kind, target=str(target),
                                rationale=str(item.get("rationale", "")), quotes=[str(quote)]))
    return out


def aggregate_proposals(items: list[Proposal]) -> list[Proposal]:
    by_key: dict[tuple[str, str], Proposal] = {}
    for p in items:
        key = (p.kind, p.target)
        if key in by_key:
            e = by_key[key]
            e.quotes.extend(q for q in p.quotes if q not in e.quotes)
            e.evidence_count += 1
        else:
            by_key[key] = Proposal(kind=p.kind, target=p.target, rationale=p.rationale,
                                   quotes=list(p.quotes), evidence_count=1)
    return sorted(by_key.values(), key=lambda p: (-p.evidence_count, p.kind, p.target))


def render_proposals_md(proposals: list[Proposal], session_name: str, generated_at: str) -> str:
    lines = [f"# Schema proposals — {session_name}", "",
             f"Generated {generated_at}. Propose-only: review and apply manually.", ""]
    if not proposals:
        lines += ["_No schema gaps proposed for this session._", ""]
        return "\n".join(lines)
    for p in proposals:
        lines.append(f"## {p.kind} — {p.target}   (evidence: {p.evidence_count})")
        if p.rationale:
            lines.append(p.rationale)
        for q in p.quotes:
            lines.append(f"> {q}")
        lines += [
            "",
            f"**To apply:** update `intermediate/schema.json` for this "
            f"session, then `mykg extract-graph --from-step pass2 --session {session_name}`.",
            "",
        ]
    return "\n".join(lines)
