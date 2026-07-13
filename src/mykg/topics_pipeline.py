"""build-topics pipeline: cluster the graph and synthesize cross-entity topic pages."""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import mykg.config as cfg
from mykg.orchestrator import PipelineContext, Step
from mykg.schema_flattener import flatten_schema
from mykg.wiki.clustering import Communities, build_communities
from mykg.wiki.loader import WikiGraph, load_wiki_graph
from mykg.wiki.proposals import aggregate_proposals, extract_proposals, render_proposals_md
from mykg.wiki.topic_builder import generate_topic_page
from mykg.wiki.topic_manifest import (
    community_fingerprint,
    load_topic_manifest,
    plan_topic_rebuild,
    save_topic_manifest,
    topic_grounding_hash,
)
from mykg.wiki_pipeline import session_root, vault_dir

log = logging.getLogger(__name__)


def _graph_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "wiki_graph.json"


def _communities_path(ctx: PipelineContext) -> Path:
    return ctx.intermediate_dir / "communities.json"


def _load_graph(ctx: PipelineContext) -> WikiGraph:
    return WikiGraph.model_validate_json(_graph_path(ctx).read_text(encoding="utf-8"))


def _load_communities(ctx: PipelineContext) -> Communities:
    return Communities.model_validate_json(_communities_path(ctx).read_text(encoding="utf-8"))


def _schema_sig(ctx: PipelineContext) -> str:
    path = session_root(ctx) / "intermediate" / "schema.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _flattened_schema(ctx: PipelineContext) -> dict:
    path = session_root(ctx) / "intermediate" / "schema.json"
    if not path.exists():
        return {}
    return flatten_schema(json.loads(path.read_text(encoding="utf-8")))


def run_topics_load(ctx: PipelineContext) -> None:
    graph = load_wiki_graph(session_root(ctx))
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    _graph_path(ctx).write_text(graph.model_dump_json(), encoding="utf-8")
    if not (vault_dir(ctx) / "entities").is_dir():
        log.warning("topics: entities/ not found in vault — run build-wiki so topic "
                    "wikilinks resolve to entity pages")
    log.info("topics_load — %d nodes, %d edges", len(graph.nodes), len(graph.edges))


def run_topics_cluster(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = build_communities(graph, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                              cfg.TOPICS_RESOLUTION, cfg.TOPICS_MIN_SIZE)
    _communities_path(ctx).write_text(comms.model_dump_json(indent=2), encoding="utf-8")
    log.info("topics_cluster — %d communities, %d skipped",
             len(comms.communities), len(comms.skipped))


def run_topics_pages(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = _load_communities(ctx)
    vault = vault_dir(ctx)
    topics = vault / "topics"
    topics.mkdir(parents=True, exist_ok=True)

    schema_sig = _schema_sig(ctx)
    by_fp = {community_fingerprint(c): c for c in comms.communities}
    manifest = load_topic_manifest(vault)
    plan = plan_topic_rebuild(comms.communities, graph, manifest,
                              cfg.WIKI_MIN_EDGE_CONFIDENCE, cfg.WIKI_NEIGHBORS_MAX,
                              comms.resolution, schema_sig)
    prior = manifest.get("topics", {})
    log.info("topics_pages — generate=%d keep=%d delete=%d",
             len(plan.to_generate), len(plan.to_keep), len(plan.to_delete))

    for fp in plan.to_delete:
        slug = prior.get(fp, {}).get("slug")
        if slug:
            (topics / f"{slug}.md").unlink(missing_ok=True)

    entries: dict[str, dict] = {fp: dict(prior[fp]) for fp in plan.to_keep if fp in prior}
    used_slugs = {e["slug"] for e in entries.values()}

    def _one(fp: str):
        comm = by_fp[fp]
        slug, page, ok = generate_topic_page(comm, graph, ctx.adapter,
                                             cfg.TOPICS_MEMBERS_MAX, cfg.WIKI_MAX_GROUNDING_TOKENS)
        return fp, comm, slug, page, ok

    if plan.to_generate:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            results = list(pool.map(_one, plan.to_generate))
        for fp, comm, slug, page, ok in results:
            if not ok:
                continue
            unique = slug
            n = 2
            while unique in used_slugs:
                unique = f"{slug}-{n}"
                n += 1
            used_slugs.add(unique)
            (topics / f"{unique}.md").write_text(page, encoding="utf-8")
            entries[fp] = {
                "hash": topic_grounding_hash(comm, graph, cfg.WIKI_MIN_EDGE_CONFIDENCE,
                                             cfg.WIKI_NEIGHBORS_MAX, comms.resolution, schema_sig),
                "slug": unique,
                "topic_id": comm.topic_id,
            }

    save_topic_manifest(vault, entries)
    (ctx.intermediate_dir / "topics_pages.done").write_text("ok")


def run_topics_proposals(ctx: PipelineContext) -> None:
    graph = _load_graph(ctx)
    comms = _load_communities(ctx)
    flattened = _flattened_schema(ctx)

    def _one(comm):
        return extract_proposals(comm, graph, flattened, ctx.adapter, cfg.WIKI_MAX_GROUNDING_TOKENS)

    collected: list = []
    if comms.communities:
        with ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS) as pool:
            for props in pool.map(_one, comms.communities):
                collected.extend(props)

    ranked = aggregate_proposals(collected)
    now = datetime.now(timezone.utc).isoformat()
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "schema_proposals.md").write_text(
        render_proposals_md(ranked, session_root(ctx).name, now), encoding="utf-8")
    (ctx.intermediate_dir / "topics_proposals.done").write_text("ok")


def run_topics_index(ctx: PipelineContext) -> None:
    comms = _load_communities(ctx)
    vault = vault_dir(ctx)
    vault.mkdir(parents=True, exist_ok=True)
    manifest = load_topic_manifest(vault)
    entries = manifest.get("topics", {})
    now = datetime.now(timezone.utc).isoformat()
    lines = ["# Topics", "",
             f"- Source session: `{session_root(ctx).name}`",
             f"- Topics: {len(comms.communities)}",
             f"- Generated: {now}", ""]
    for c in comms.communities:
        slug = entries.get(community_fingerprint(c), {}).get("slug")
        if not slug:
            continue
        theme = slug.replace("-", " ").title()
        lines.append(f"- [[topics/{slug}|{theme}]] — {len(c.member_ids)} entities")
    (vault / "Topics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ctx.intermediate_dir / "topics_index.done").write_text("ok")


TOPIC_STEPS: list[Step] = [
    Step(name="topics_load", fn=run_topics_load, outputs=["wiki_graph.json"]),
    Step(name="topics_cluster", fn=run_topics_cluster, outputs=["communities.json"]),
    Step(name="topics_pages", fn=run_topics_pages, outputs=["topics_pages.done"], is_llm_step=True),
    Step(name="topics_proposals", fn=run_topics_proposals,
         outputs=["topics_proposals.done"], is_llm_step=True),
    Step(name="topics_index", fn=run_topics_index, outputs=["topics_index.done"]),
]
