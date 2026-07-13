"""Fingerprint-keyed grounding manifest driving incremental topic rebuilds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from mykg.wiki.clustering import Community
from mykg.wiki.loader import WikiGraph
from mykg.wiki.manifest import grounding_hash

_MANIFEST_NAME = ".topics_manifest.json"


class TopicRebuildPlan(BaseModel):
    to_generate: list[str]
    to_keep: list[str]
    to_delete: list[str]


def community_fingerprint(community: Community) -> str:
    blob = json.dumps(sorted(community.member_ids), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def topic_grounding_hash(community: Community, graph: WikiGraph, min_edge_confidence: float,
                         neighbors_max: int, resolution: float, schema_sig: str) -> str:
    members = sorted(community.member_ids)
    member_hashes = [
        grounding_hash(graph.nodes[m], graph.neighbors(m, min_edge_confidence, neighbors_max))
        for m in members if m in graph.nodes
    ]
    payload = {"members": members, "member_hashes": member_hashes,
               "resolution": resolution, "schema_sig": schema_sig}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def plan_topic_rebuild(communities: list[Community], graph: WikiGraph, manifest: dict,
                       min_edge_confidence: float, neighbors_max: int, resolution: float,
                       schema_sig: str, force: bool = False) -> TopicRebuildPlan:
    prior = manifest.get("topics", {})
    current_fps: set[str] = set()
    to_generate, to_keep = [], []
    for comm in communities:
        fp = community_fingerprint(comm)
        current_fps.add(fp)
        h = topic_grounding_hash(comm, graph, min_edge_confidence, neighbors_max,
                                 resolution, schema_sig)
        if not force and prior.get(fp, {}).get("hash") == h:
            to_keep.append(fp)
        else:
            to_generate.append(fp)
    to_delete = [fp for fp in prior if fp not in current_fps]
    return TopicRebuildPlan(to_generate=sorted(to_generate), to_keep=sorted(to_keep),
                            to_delete=sorted(to_delete))


def load_topic_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _MANIFEST_NAME
    if not path.exists():
        return {"topics": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_topic_manifest(vault_dir: Path, entries: dict[str, dict]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / _MANIFEST_NAME).write_text(
        json.dumps({"topics": entries}, indent=2, sort_keys=True), encoding="utf-8")
