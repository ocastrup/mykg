"""Load a completed mykg session (read-only) into a typed WikiGraph."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from mykg.chunker import chunk_file


class WikiNode(BaseModel):
    id: str
    type: str
    name: str
    attributes: dict[str, dict]
    source_files: list[str]
    grounded_chunk_keys: list[str]
    grounded_chunks: list[str]
    grounded: bool


class WikiEdge(BaseModel):
    id: str
    type: str
    from_id: str
    to_id: str
    confidence: float


class Neighbor(BaseModel):
    id: str
    name: str
    type: str
    relationship: str
    confidence: float


class WikiGraph(BaseModel):
    nodes: dict[str, WikiNode]
    edges: list[WikiEdge]
    types: list[str]

    def neighbors(self, node_id: str, min_confidence: float, max_n: int) -> list[Neighbor]:
        best: dict[str, Neighbor] = {}
        for e in self.edges:
            if e.confidence < min_confidence:
                continue
            other = e.to_id if e.from_id == node_id else e.from_id if e.to_id == node_id else None
            if other is None or other not in self.nodes:
                continue
            n = self.nodes[other]
            cand = Neighbor(id=other, name=n.name, type=n.type,
                            relationship=e.type, confidence=e.confidence)
            if other not in best or cand.confidence > best[other].confidence:
                best[other] = cand
        ordered = sorted(best.values(), key=lambda n: (-n.confidence, n.id))
        return ordered[:max_n]


def _require(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Session incomplete — missing {path.name}: {path}")
    return path.read_text(encoding="utf-8")


def _read_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _humanize(node_id: str) -> str:
    return node_id.split("-", 1)[-1].replace("-", " ").title()


def _node_name(raw: dict) -> str:
    val = (raw.get("attributes", {}).get("name", {}) or {}).get("value")
    return val if isinstance(val, str) and val.strip() else _humanize(raw["id"])


def load_wiki_graph(session_root: Path) -> WikiGraph:
    out = session_root / "output"
    inter = session_root / "intermediate"

    raw_nodes = _read_jsonl(_require(out / "nodes.jsonl"))
    raw_edges = _read_jsonl(_require(out / "edges.jsonl"))
    chunk_index = json.loads(_require(inter / "chunk_node_index.json"))
    manifest = json.loads(_require(inter / "file_manifest.json"))
    schema = json.loads(_require(inter / "schema.json"))

    # node_id -> [(filename, chunk_idx_1based)]
    node_to_chunks: dict[str, list[tuple[str, int]]] = {}
    for fname, chunks in chunk_index.items():
        for idx_str, ids in chunks.items():
            for nid in ids:
                node_to_chunks.setdefault(nid, []).append((fname, int(idx_str)))

    # Reconstruct chunk text lazily per file (chunk_index is 0-based; keys are 1-based).
    chunk_text_cache: dict[str, dict[int, str]] = {}

    def _chunk_text(fname: str, idx_1based: int) -> str | None:
        if fname not in chunk_text_cache:
            content = (manifest.get(fname) or {}).get("content", "")
            chunk_text_cache[fname] = {c.chunk_index: c.text for c in chunk_file(fname, content)}
        return chunk_text_cache[fname].get(idx_1based - 1)

    nodes: dict[str, WikiNode] = {}
    for raw in raw_nodes:
        keys: list[str] = []
        texts: list[str] = []
        for fname, idx in sorted(node_to_chunks.get(raw["id"], [])):
            txt = _chunk_text(fname, idx)
            if txt:
                keys.append(f"{fname}::{idx}")
                texts.append(txt)
        nodes[raw["id"]] = WikiNode(
            id=raw["id"], type=raw["type"], name=_node_name(raw),
            attributes=raw.get("attributes", {}), source_files=raw.get("source_files", []),
            grounded_chunk_keys=keys, grounded_chunks=texts, grounded=bool(texts))

    edges = [WikiEdge(id=e["id"], type=e["type"], from_id=e["from"],
                      to_id=e["to"], confidence=float(e.get("confidence", 0.0)))
             for e in raw_edges]
    types = sorted(c["type"] for c in schema.get("concepts", []))
    return WikiGraph(nodes=nodes, edges=edges, types=types)
