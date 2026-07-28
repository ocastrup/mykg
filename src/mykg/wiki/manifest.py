"""Per-page grounding-hash manifest driving incremental wiki rebuilds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from mykg.wiki.loader import Neighbor, WikiGraph, WikiNode

_MANIFEST_NAME = ".wiki_manifest.json"


class RebuildPlan(BaseModel):
    to_generate: list[str]
    to_keep: list[str]
    to_delete: list[str]


def grounding_hash(node: WikiNode, neighbors: list[Neighbor]) -> str:
    payload = {
        "attributes": {k: node.attributes[k] for k in sorted(node.attributes)},
        "chunks": node.grounded_chunks,
        "neighbors": sorted((n.id, n.name, n.relationship, n.confidence) for n in neighbors),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def plan_rebuild(graph: WikiGraph, manifest: dict, min_edge_confidence: float,
                 neighbors_max: int, force: bool = False) -> RebuildPlan:
    prior = manifest.get("pages", {})
    to_generate, to_keep = [], []
    for nid, node in graph.nodes.items():
        nb = graph.neighbors(nid, min_edge_confidence, neighbors_max)
        current = grounding_hash(node, nb)
        if not force and prior.get(nid, {}).get("hash") == current:
            to_keep.append(nid)
        else:
            to_generate.append(nid)
    to_delete = [nid for nid in prior if nid not in graph.nodes]
    return RebuildPlan(to_generate=sorted(to_generate), to_keep=sorted(to_keep),
                       to_delete=sorted(to_delete))


def load_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _MANIFEST_NAME
    if not path.exists():
        return {"pages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(vault_dir: Path, hashes: dict[str, str]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    pages = {nid: {"hash": h, "path": f"entities/{nid}.md"} for nid, h in hashes.items()}
    (vault_dir / _MANIFEST_NAME).write_text(
        json.dumps({"pages": pages}, indent=2), encoding="utf-8")


_SOURCE_MANIFEST_NAME = ".wiki_sources_manifest.json"


def load_source_manifest(vault_dir: Path) -> dict:
    path = vault_dir / _SOURCE_MANIFEST_NAME
    if not path.exists():
        return {"sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_source_manifest(vault_dir: Path, hashes: dict[str, str]) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    sources = {name: {"hash": h, "path": f"sources/{name}.md"}
               for name, h in hashes.items()}
    (vault_dir / _SOURCE_MANIFEST_NAME).write_text(
        json.dumps({"sources": sources}, indent=2), encoding="utf-8")
