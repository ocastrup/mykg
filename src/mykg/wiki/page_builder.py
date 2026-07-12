"""Pure rendering primitives for wiki pages: link validation + markdown assembly."""
from __future__ import annotations

import re

import yaml

from mykg.chunker import count_tokens
from mykg.llm.adapter import LLMAdapter
from mykg.wiki.loader import Neighbor, WikiNode

_WIKILINK = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)


def strip_invalid_wikilinks(markdown: str, allowed_ids: set[str]) -> tuple[str, list[str]]:
    """Keep only [[id]] / [[id|label]] whose id is in allowed_ids; others become plain text.

    Runs to a fixed point so an invalid link whose label contains nested
    bracket syntax cannot reconstruct a live wikilink after one pass.
    Returns (cleaned_markdown, dropped_ids_in_order).
    """
    dropped: list[str] = []

    def _sub(m: re.Match) -> str:
        target, sep, label = m.group(1).partition("|")
        target = target.strip()
        if target in allowed_ids:
            return m.group(0)
        dropped.append(target)
        return (label if sep else target).strip()

    text, prev = markdown, None
    while prev != text:
        prev = text
        text = _WIKILINK.sub(_sub, text)
    return text, dropped


def _frontmatter(node: WikiNode) -> str:
    data = {
        "mykg_id": node.id,
        "type": node.type,
        "aliases": [node.name],
        "source_files": node.source_files,
        "grounded": node.grounded,
        "grounded_chunks": node.grounded_chunk_keys,
    }
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n"


def render_entity_page(node: WikiNode, body_markdown: str) -> str:
    """Wrap already-validated body markdown with YAML frontmatter."""
    return _frontmatter(node) + body_markdown.strip() + "\n"


def render_stub_page(node: WikiNode, neighbors: list[Neighbor]) -> str:
    """Minimal, never-fabricated page for nodes with no resolvable grounding."""
    lines = [f"# {node.name}", "", f"*{node.type}. No source text was available to summarize.*"]
    if neighbors:
        lines += ["", "## Connections", ""]
        lines += [f"- [[{n.id}|{n.name}]] ({n.relationship})" for n in neighbors]
    return render_entity_page(node, "\n".join(lines))


_SYSTEM = (
    "You write concise, factual wiki articles for a personal knowledge base. "
    "Use ONLY the provided source excerpts and attributes — never invent facts. "
    "Write in Markdown: a one-sentence lead defining the subject, a short body "
    "synthesizing the excerpts, then a '## Connections' section. In Connections, "
    "reference related entities ONLY using the exact [[id|Name]] links listed under "
    "'Allowed links'. Do not create any other [[...]] links."
)


def _visible_attributes(node: WikiNode, min_conf: float) -> dict[str, object]:
    out: dict[str, object] = {}
    for name, cell in node.attributes.items():
        if not isinstance(cell, dict):
            continue
        val, conf = cell.get("value"), cell.get("confidence", 0.0)
        if val not in (None, "") and float(conf) >= min_conf:
            out[name] = val
    return out


def _capped_grounding(chunks: list[str], max_tokens: int) -> str:
    kept, total = [], 0
    for c in chunks:
        t = count_tokens(c)
        if total + t > max_tokens and kept:
            break
        kept.append(c)
        total += t
    return "\n\n---\n\n".join(kept)


def build_entity_prompt(node: WikiNode, neighbors: list[Neighbor],
                        min_attr_confidence: float, max_grounding_tokens: int) -> tuple[str, str]:
    attrs = _visible_attributes(node, min_attr_confidence)
    links = "\n".join(f"- [[{n.id}|{n.name}]] — {n.type}, relationship: {n.relationship}"
                      for n in neighbors) or "(none)"
    grounding = _capped_grounding(node.grounded_chunks, max_grounding_tokens)
    user = (
        f"# Subject\nName: {node.name}\nType: {node.type}\n"
        f"Attributes: {attrs}\n\n"
        f"# Allowed links (use these exact wikilinks, and only these)\n{links}\n\n"
        f"# Source excerpts\n{grounding}\n"
    )
    return _SYSTEM, user


def generate_entity_page(node: WikiNode, neighbors: list[Neighbor], adapter: LLMAdapter,
                         min_attr_confidence: float, max_grounding_tokens: int) -> str:
    if not node.grounded:
        return render_stub_page(node, neighbors)
    system, user = build_entity_prompt(node, neighbors, min_attr_confidence, max_grounding_tokens)
    try:
        raw = adapter.complete(system, user, context_label=f"wiki:{node.id}")
    except Exception:
        return render_stub_page(node, neighbors)
    body = LLMAdapter.strip_code_fences(raw).strip() if raw else ""
    if not body:
        return render_stub_page(node, neighbors)
    allowed = {n.id for n in neighbors}
    cleaned, _dropped = strip_invalid_wikilinks(body, allowed)
    return render_entity_page(node, cleaned)
