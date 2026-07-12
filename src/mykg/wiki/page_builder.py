"""Pure rendering primitives for wiki pages: link validation + markdown assembly."""
from __future__ import annotations

import re

import yaml

from mykg.wiki.loader import Neighbor, WikiNode

_WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")


def strip_invalid_wikilinks(markdown: str, allowed_ids: set[str]) -> tuple[str, list[str]]:
    """Keep only [[id]] / [[id|label]] whose id is in allowed_ids; others become plain text.

    Returns (cleaned_markdown, dropped_ids_in_order).
    """
    dropped: list[str] = []

    def _sub(m: re.Match) -> str:
        target, label = m.group(1).strip(), m.group(2)
        if target in allowed_ids:
            return m.group(0)
        dropped.append(target)
        return (label or target).strip()

    return _WIKILINK.sub(_sub, markdown), dropped


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
