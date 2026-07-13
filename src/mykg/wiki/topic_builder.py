"""LLM synthesis of cross-entity topic articles from a community."""
from __future__ import annotations

import logging
import re

import yaml

from mykg.llm.adapter import LLMAdapter
from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.page_builder import _capped_grounding, strip_invalid_wikilinks

log = logging.getLogger(__name__)

_TOPIC_SYSTEM = (
    "You write a synthesized topic article for a personal knowledge base, weaving "
    "several related entities into one coherent theme. Use ONLY the provided source "
    "excerpts and entity list — never invent facts. Output Markdown: the FIRST line "
    "must be an H1 naming the theme ('# <theme>'), followed by a synthesizing article. "
    "Reference entities ONLY using the exact [[id|Name]] links listed under 'Member "
    "entities'. Do not create any other [[...]] links."
)


def slugify(theme: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", theme.lower()).strip("-")
    return s or "topic"


def select_members(graph: WikiGraph, member_ids: list[str], members_max: int) -> list[str]:
    member_set = set(member_ids)
    degree: dict[str, float] = {m: 0.0 for m in member_ids}
    for e in graph.edges:
        if e.from_id in member_set and e.to_id in member_set:
            degree[e.from_id] = degree.get(e.from_id, 0.0) + e.confidence
            degree[e.to_id] = degree.get(e.to_id, 0.0) + e.confidence
    ordered = sorted(member_ids, key=lambda m: (-degree.get(m, 0.0), m))
    return ordered[:members_max]


def _build_prompt(graph: WikiGraph, selected: list[str], all_members: list[str],
                  max_grounding_tokens: int) -> tuple[str, str]:
    members_block = "\n".join(
        f"- [[{m}|{graph.nodes[m].name}]] — {graph.nodes[m].type}"
        for m in all_members if m in graph.nodes) or "(none)"
    chunks: list[str] = []
    for m in selected:
        if m in graph.nodes:
            chunks.extend(graph.nodes[m].grounded_chunks)
    grounding = _capped_grounding(chunks, max_grounding_tokens)
    user = f"# Member entities\n{members_block}\n\n# Source excerpts\n{grounding}\n"
    return _TOPIC_SYSTEM, user


def _extract_theme(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _render(community: Community, theme: str, body: str) -> str:
    fm = {"topic_id": community.topic_id, "theme": theme,
          "members": [f"[[{m}]]" for m in community.member_ids]}
    return ("---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
            + "---\n\n" + body.strip() + "\n")


def generate_topic_page(community: Community, graph: WikiGraph, adapter: LLMAdapter,
                        members_max: int, max_grounding_tokens: int) -> tuple[str, str, bool]:
    selected = select_members(graph, community.member_ids, members_max)
    system, user = _build_prompt(graph, selected, community.member_ids, max_grounding_tokens)
    try:
        raw = adapter.complete(system, user, context_label=f"topic:{community.topic_id}")
    except Exception:
        log.warning("topics: generation failed for %s", community.topic_id, exc_info=True)
        return "", "", False
    body = LLMAdapter.strip_code_fences(raw).strip() if raw else ""
    if not body:
        log.warning("topics: blank reply for %s", community.topic_id)
        return "", "", False
    theme = _extract_theme(body) or community.topic_id
    cleaned, _dropped = strip_invalid_wikilinks(body, set(graph.nodes))
    return slugify(theme), _render(community, theme, cleaned), True
