"""Deterministic graph community detection for synthesized topic pages."""
from __future__ import annotations

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities
from pydantic import BaseModel

from mykg.wiki.loader import WikiGraph


class Community(BaseModel):
    topic_id: str
    member_ids: list[str]


class SkippedGroup(BaseModel):
    member_ids: list[str]
    reason: str


class Communities(BaseModel):
    resolution: float
    communities: list[Community]
    skipped: list[SkippedGroup]


def build_communities(graph: WikiGraph, min_edge_confidence: float,
                      resolution: float, min_size: int) -> Communities:
    g = nx.Graph()
    g.add_nodes_from(sorted(graph.nodes))
    for e in graph.edges:
        if e.confidence < min_edge_confidence:
            continue
        if e.from_id not in graph.nodes or e.to_id not in graph.nodes:
            continue
        a, b = sorted((e.from_id, e.to_id))
        if a == b:
            continue
        if g.has_edge(a, b):
            g[a][b]["weight"] = max(g[a][b]["weight"], e.confidence)
        else:
            g.add_edge(a, b, weight=e.confidence)

    if g.number_of_edges() == 0:
        raw = [[n] for n in sorted(g.nodes)]
    else:
        raw = [sorted(c) for c in
               greedy_modularity_communities(g, weight="weight", resolution=resolution)]
    raw.sort(key=lambda m: (-len(m), m[0] if m else ""))

    communities: list[Community] = []
    skipped: list[SkippedGroup] = []
    idx = 1
    for members in raw:
        if len(members) >= min_size:
            communities.append(Community(topic_id=f"t{idx:04d}", member_ids=members))
            idx += 1
        else:
            skipped.append(SkippedGroup(member_ids=members, reason="below_min_size"))
    return Communities(resolution=resolution, communities=communities, skipped=skipped)
