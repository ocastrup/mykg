# mykg Wiki Phase 2 — Synthesized Topic Pages — Design

**Date:** 2026-07-13
**Status:** Draft (design), pending user review
**Builds on:** `2026-07-12-mykg-llm-wiki-design.md` (Phase 1, shipped)

## Purpose

Phase 1 (`mykg build-wiki`) renders one grounded prose page per graph entity
plus deterministic type hubs and a Home index. Phase 2 adds the most
distinctively "Karpathy wiki" layer: **synthesized topic pages** — cross-entity
thematic articles, one per graph community, that read across many entities
instead of describing one. As a byproduct, topic synthesis surfaces
**human-gated schema improvement proposals**: recurring patterns the clusters
evidence that the extraction schema never captured.

Phase 2 ships as a **separate command**, `mykg build-topics`, so the expensive,
non-deterministic LLM synthesis is opt-in and never slows the deterministic
Phase 1 build.

## Non-goals

- Modifying the graph, the schema, or the extract session. Proposals are
  **propose-only** — the human reads and applies them manually.
- Rewriting any Phase 1 output file (`Home.md`, `entities/`, `hubs/`).
- Edge/relationship synthesis beyond what community structure already implies.
- Automatic re-extraction. (The extract pipeline's `SchemaUpdatedError` →
  targeted re-extraction machinery exists, but is deliberately *not* wired to
  build-topics; see "Feedback loop", below.)

## Command & architecture

`mykg build-topics <session> [--rebuild]` is a second, independent pipeline
parallel to `build-wiki`, driven by the same `orchestrator.py`:

- **Own `STEPS` list** in a new module `src/mykg/topics_pipeline.py`.
- **Own orchestrator state** at `<session>/topics_state/` (build-wiki uses
  `<session>/wiki/`). It **never touches the extract session's
  `intermediate/`** — the Phase 1 isolation invariant is preserved verbatim.
- **Shares the vault** `<wiki_root>/<session>/` but writes only a **disjoint set
  of files it exclusively owns**:
  - `topics/<topic-slug>.md` — one article per qualifying community
  - `Topics.md` — topics index at the vault root
  - `.topics_manifest.json` — incremental-rebuild manifest
  - `schema_proposals.md` — human-readable schema proposals
- It **re-loads the session graph itself** via `load_wiki_graph(session_root)`,
  reusing `<session>/topics_state/wiki_graph.json` if a prior step wrote it.
  Topic pages wikilink to entity pages (`entities/<id>.md`); if `entities/` is
  absent (build-wiki not yet run), build-topics logs a warning and still
  produces topic pages — the links resolve once build-wiki runs.

### Writer disjointness (invariant)

`build-wiki` owns: `entities/`, `hubs/`, `Home.md`, `.wiki_manifest.json`.
`build-topics` owns: `topics/`, `Topics.md`, `schema_proposals.md`,
`.topics_manifest.json`. Neither command writes the other's files. `Home.md`
does **not** link to topics; discovery is via `Topics.md`. This keeps each file
single-writer and lets the two commands run in any order or independently.

## Steps

Ordered `STEPS` (each writes a `.done` sentinel under
`<session>/topics_state/`, exactly like Phase 1):

| Step | Kind | Output |
|---|---|---|
| `topics_load` | deterministic | `wiki_graph.json` (reused from Phase 1 shape) |
| `topics_cluster` | deterministic | `communities.json` |
| `topics_pages` | LLM, parallel | `topics/<slug>.md`, updates `.topics_manifest.json` |
| `topics_proposals` | LLM, parallel | `schema_proposals.md` |
| `topics_index` | deterministic | `Topics.md` |

### `topics_cluster` — deterministic community detection

- Project `WikiGraph` to an **undirected weighted** graph: one node per graph
  node; for each edge with `confidence >= WIKI_MIN_EDGE_CONFIDENCE` (the Phase 1
  threshold, reused), add/accumulate an undirected edge weighted by confidence.
  Sub-threshold edges are dropped.
- `networkx.greedy_modularity_communities(G, weight="weight",
  resolution=cfg.TOPICS_RESOLUTION)`. This is deterministic given the graph;
  membership is stabilized by sorting node ids before construction and sorting
  communities by `(-size, first_member_id)`.
- **Min community size** `cfg.TOPICS_MIN_SIZE` (default 3): communities smaller
  than this get **no** topic page (a single entity or a pair is already covered
  by its entity pages). Isolated nodes and sub-min communities are recorded in
  `communities.json` under `skipped` but not synthesized.
- Output `communities.json`:
  ```json
  {
    "resolution": 1.0,
    "communities": [
      {"topic_id": "t0001", "member_ids": ["org-acme", "person-alice", "..."]}
    ],
    "skipped": [{"member_ids": ["..."], "reason": "below_min_size"}]
  }
  ```
  `topic_id` is a stable ordinal (`t0001`, `t0002`, …) assigned in the sorted
  order above; it anchors the manifest across reruns.

### `topics_pages` — LLM synthesis (parallel, incremental)

For each qualifying community:

- **Member selection for grounding.** All members are listed in the article,
  but the LLM prompt grounds on at most `cfg.TOPICS_MEMBERS_MAX` members
  (default 25), chosen by `degree × mean-edge-confidence` (most central first),
  to bound prompt size. Each selected member contributes its Phase 1 grounded
  source chunks, truncated to a combined `cfg.WIKI_MAX_GROUNDING_TOKENS` budget.
- **Prompt** asks the LLM to (a) name the theme in a few words and (b) write a
  cross-entity narrative that synthesizes how the members relate, citing
  entities as `[[<node-id>|<name>]]` wikilinks. The theme name → filename slug.
- **Wikilink validation** reuses the Phase 1 validator: every `[[…]]` is checked
  against real graph node ids; invented links are stripped. (Refactor the
  validator out of `page_builder.py` into a shared helper if not already
  importable.)
- Written to `topics/<slug>.md` with YAML front matter: `topic_id`, `theme`,
  `members` (all member ids, as wikilinks in the body too).
- Parallelized with `ThreadPoolExecutor(max_workers=cfg.WIKI_MAX_WORKERS)`.
- **Transient-failure handling** follows Phase 1: a generation failure is
  retried and, on persistent failure, the topic is left out of the manifest so
  the next run retries it (no stub is cached as "done").

### `topics_proposals` — human-gated schema feedback (propose-only)

- A dedicated LLM pass per community asks: *what recurring attribute, relationship
  type, or concept type does this cluster evidence that the current schema does
  not capture?* The community's grounded chunks and the flattened schema for its
  members' types are provided as context.
- Each proposal must be **grounded in a short source quote** and typed as one of:
  `add_attribute` (type + attribute name), `add_relationship_type`, or
  `add_concept_type`.
- Proposals are aggregated across communities, deduped, and ranked by how many
  communities/entities evidence them, then written to
  **`<wiki_root>/<session>/schema_proposals.md`**:
  ```markdown
  # Schema proposals — <session>
  Generated <ISO-8601>. Propose-only: review and apply manually.

  ## add_attribute — Organization.founded_year   (evidence: 4 communities)
  Multiple organizations state a founding year the schema omits.
  > "...Acme, founded in 1998, ..."  — acme.md::3
  > "...established 2004..."  — beta.md::1

  **To apply:** add `founded_year` to `Organization` in
  `<session>/intermediate/schema.json`, then
  `mykg extract-graph --from-step pass2 --session <session>`.
  ```
- build-topics writes **nothing** into the session. Applying a proposal is a
  manual human action; this is the same "recommend; you decide" contract as the
  attribute-completeness-eval spec, and composes with it.

### `topics_index` — deterministic

Writes `Topics.md`: session name, generation timestamp, and a list of topics
(`[[topics/<slug>|<theme>]]`, member count, top members). Deterministic given
`communities.json` + the generated topic files.

## Incremental rebuild

`.topics_manifest.json` maps `topic_id → grounding_hash`, where
`grounding_hash = sha256(sorted member_ids + each member's Phase-1 grounding
hash + resolution + schema.json signature)`. On each run, `topics_pages`:

- regenerates only topics whose hash changed or are new;
- keeps byte-identical topics whose hash is unchanged;
- deletes `topics/*.md` whose `topic_id` no longer exists.

`--rebuild` forces regeneration of every topic (clears the manifest first),
mirroring `build-wiki --rebuild`. Because clustering is deterministic, an
unchanged graph produces an unchanged manifest and zero LLM calls on rerun.

## Configuration

A **new `topics:` block** per profile in both `mykg_config.yaml` and
`src/mykg/data/mykg_config.yaml` (kept in sync; covered by a config-parity test
mirroring the existing wiki-parity test):

```yaml
pipeline:
  topics:
    resolution: 1.0     # greedy-modularity resolution (higher -> more, smaller communities)
    min_size: 3         # communities smaller than this get no topic page
    members_max: 25     # max members grounded into a topic prompt
    enabled: true       # reserved gate; build-topics is already opt-in via the command
```

Exposed in `src/mykg/config.py` as `TOPICS_RESOLUTION`, `TOPICS_MIN_SIZE`,
`TOPICS_MEMBERS_MAX`, `TOPICS_ENABLED`. `max_workers` and the confidence /
grounding-token thresholds are reused from the existing `wiki:` constants
(`WIKI_MAX_WORKERS`, `WIKI_MIN_EDGE_CONFIDENCE`, `WIKI_MAX_GROUNDING_TOKENS`).

## Testing

Unit (all with stub adapter + `tmp_path`, `WIKI_ROOT` patched under `tmp_path`):

- **cluster determinism** — same fixture graph clustered twice yields identical
  `communities.json`; sub-min communities land in `skipped`.
- **topic page** — wikilinks validated against real node ids; invented link
  stripped; theme → slug; front matter present.
- **incremental** — change one member's attributes → exactly one topic
  regenerates, others byte-identical; removed community's file deleted.
- **proposals** — a cluster whose chunks evidence an off-schema attribute yields
  a grounded `schema_proposals.md` entry; no session file is written.
- **writer disjointness** — after `build-topics`, `Home.md` and `entities/*.md`
  are byte-identical to their pre-topics state.
- **config parity** — the `topics:` block exists and matches between root and
  packaged config.
- **cli** — `mykg build-topics <session>` wiring; missing-session error path.
- **live** *(marked)* — end-to-end small-corpus build against a real adapter.

## Open questions / future (Phase 3+)

- **Gated apply.** A future command could let the human approve proposals in a
  gate file and auto-apply + re-extract, reusing the `SchemaUpdatedError` path.
  Deferred to keep build-topics read-only over the session.
- **Home discoverability.** If topic pages prove central, revisit whether
  `build-wiki` should conditionally link `Topics.md` from `Home.md`.
- **Topic-to-topic links.** Communities that share boundary edges could
  cross-link; not in this phase.
