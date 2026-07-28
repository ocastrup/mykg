"""build-wiki pipeline: render a graph-grounded Obsidian vault from a session."""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import mykg.config as cfg
from mykg.orchestrator import PipelineContext, Step
from mykg.wiki.loader import WikiGraph, load_wiki_graph, source_note_name
from mykg.wiki.manifest import (
    grounding_hash,
    load_manifest,
    load_source_manifest,
    plan_rebuild,
    save_manifest,
    save_source_manifest,
)
from mykg.wiki.page_builder import (
    extract_lead,
    generate_entity_page,
    render_home_page,
    render_hub_page,
    render_source_page,
)

log = logging.getLogger(__name__)


def session_root(ctx: PipelineContext) -> Path:
    return ctx.output_dir.parent


def vault_dir(ctx: PipelineContext) -> Path:
    # Each session's wiki lives under the top-level wiki root, keyed by session
    # name: <wiki_root>/<session-name>/. A relative wiki_root resolves from cwd.
    return Path(cfg.WIKI_ROOT) / session_root(ctx).name


def _graph_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "wiki_graph.json"


def _load_cached_graph(ctx: PipelineContext) -> WikiGraph:
    return WikiGraph.model_validate_json(_graph_path(ctx).read_text(encoding="utf-8"))


def run_wiki_load(ctx: PipelineContext) -> None:
    graph = load_wiki_graph(session_root(ctx))
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    _graph_path(ctx).write_text(graph.model_dump_json(), encoding="utf-8")
    log.info("wiki_load — %d nodes, %d edges", len(graph.nodes), len(graph.edges))


def run_wiki_sources(ctx: PipelineContext) -> None:
    manifest_path = session_root(ctx) / "intermediate" / "file_manifest.json"
    corpus = json.loads(manifest_path.read_text(encoding="utf-8"))
    vault = vault_dir(ctx)
    sources = vault / "sources"
    sources.mkdir(parents=True, exist_ok=True)

    prior = load_source_manifest(vault).get("sources", {})
    hashes: dict[str, str] = {}
    seen: dict[str, str] = {}
    for raw_path, meta in corpus.items():
        name = source_note_name(raw_path)
        if name in seen:
            log.warning("wiki_sources — basename collision %r vs %r -> %s.md (first wins)",
                        seen[name], raw_path, name)
            continue
        seen[name] = raw_path
        content = (meta or {}).get("content", "")
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        hashes[name] = h
        if prior.get(name, {}).get("hash") != h:
            (sources / f"{name}.md").write_text(
                render_source_page(raw_path, content), encoding="utf-8")

    for name in prior:
        if name not in hashes:
            (sources / f"{name}.md").unlink(missing_ok=True)

    save_source_manifest(vault, hashes)
    (ctx.intermediate_dir / "wiki_sources.done").write_text("ok")
    log.info("wiki_sources — %d source notes", len(hashes))


def run_wiki_pages(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    entities = vault / "entities"
    entities.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(vault)
    plan = plan_rebuild(graph, manifest, cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX)
    log.info("wiki_pages — generate=%d keep=%d delete=%d",
             len(plan.to_generate), len(plan.to_keep), len(plan.to_delete))

    for nid in plan.to_delete:
        (entities / f"{nid}.md").unlink(missing_ok=True)

    def _one(nid: str) -> tuple[str, bool]:
        node = graph.nodes[nid]
        nb = graph.neighbors(nid, cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX)
        page, ok = generate_entity_page(node, nb, ctx.adapter,
                                        cfg.WIKI_MIN_ATTR_CONFIDENCE, cfg.WIKI_MAX_GROUNDING_TOKENS)
        (entities / f"{nid}.md").write_text(page, encoding="utf-8")
        return nid, ok

    failed: set[str] = set()
    if plan.to_generate:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            for nid, ok in pool.map(_one, plan.to_generate):
                if not ok:
                    failed.add(nid)

    hashes = {
        nid: grounding_hash(graph.nodes[nid],
                            graph.neighbors(nid, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                                            cfg.WIKI_NEIGHBORS_MAX))
        for nid in graph.nodes if nid not in failed
    }
    save_manifest(vault, hashes)
    (ctx.intermediate_dir / "wiki_pages.done").write_text("ok")


def run_wiki_hubs(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    hubs = vault / "hubs"
    hubs.mkdir(parents=True, exist_ok=True)
    entities = vault / "entities"

    leads: dict[str, str] = {}
    for nid in graph.nodes:
        page = entities / f"{nid}.md"
        if page.exists():
            leads[nid] = extract_lead(page.read_text(encoding="utf-8"))

    by_type: dict[str, list] = {t: [] for t in graph.types}
    for node in graph.nodes.values():
        by_type.setdefault(node.type, []).append(node)
    for type_name, nodes in by_type.items():
        (hubs / f"{type_name}.md").write_text(
            render_hub_page(type_name, nodes, leads), encoding="utf-8")
    (ctx.intermediate_dir / "wiki_hubs.done").write_text("ok")


def run_wiki_index(ctx: PipelineContext) -> None:
    graph = _load_cached_graph(ctx)
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (vault / "Home.md").write_text(
        render_home_page(graph, session_root(ctx).name, now), encoding="utf-8")
    (ctx.intermediate_dir / "wiki_index.done").write_text("ok")


WIKI_STEPS: list[Step] = [
    Step(name="wiki_load", fn=run_wiki_load, outputs=["wiki_graph.json"]),
    Step(name="wiki_sources", fn=run_wiki_sources, outputs=["wiki_sources.done"]),
    Step(name="wiki_pages", fn=run_wiki_pages, outputs=["wiki_pages.done"], is_llm_step=True),
    Step(name="wiki_hubs", fn=run_wiki_hubs, outputs=["wiki_hubs.done"]),
    Step(name="wiki_index", fn=run_wiki_index, outputs=["wiki_index.done"]),
]
