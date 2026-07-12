# mykg + LLM Wiki — Design Spec

**Date:** 2026-07-12
**Status:** Approved (design), pending implementation plan
**Author:** Ole Christian Astrup (with Claude)

## Goal

Combine mykg (structured knowledge-graph extraction) with a Karpathy-style
**LLM wiki** (LLM-authored, interlinked prose articles), so each system does
what it is best at:

- **mykg** — structure and grounding: entities, typed edges, deterministic IDs,
  dedup, per-attribute confidence, provenance back to source chunks.
- **LLM wiki** — readable synthesis: prose articles a human reads in Obsidian.

The wiki is **graph-grounded**: it consumes mykg's output and turns it into a
prose vault whose link structure is 100% derived from the graph's edges.

## Non-goals

- Re-ingesting or re-extracting clippings in the wiki (single extraction path
  stays in mykg).
- Modifying the user's raw Obsidian clippings.
- Cross-entity synthesized "topic essays" from graph communities. Deferred as a
  possible phase 2; this spec covers entity pages + type hubs + home only.
- Removing mykg's existing Obsidian exporter. It stays in the codebase for users
  not adopting the wiki; it is simply turned off (`export.obsidian_enabled: false`)
  for this workflow.

## Architecture overview

Two planes, one direction of flow. Clippings enter the system exactly once.

```
Obsidian clippings/  (raw web clips — never modified)
        │
        ▼
  mykg extract-graph          ← DATA PLANE (unchanged, minus obsidian export)
        │   emits: nodes.jsonl, edges.jsonl, edge_metadata.json,
        │          knowledge_graph.ttl, chunk_node_index.json, file_manifest.json
        ▼
  mykg build-wiki <session>   ← PRESENTATION PLANE (new)
        │   reads the graph + provenance, synthesizes prose
        ▼
  wiki_vault/   →  opened in Obsidian as the reading view
```

### Responsibilities

| Concern | Owner | Rationale |
|---|---|---|
| Ingest clippings, chunk, extract | **mykg** | Already implemented; deterministic IDs, dedup, confidence |
| Entities, typed edges, provenance, TTL | **mykg** | The structural backbone |
| Prose synthesis, page layout, wikilinks | **wiki** | Narrative is the wiki's strength |
| The Obsidian markdown vault | **wiki (sole writer)** | One authority for markdown |
| Raw clippings | **neither writes** | Read-only source of truth |

### Decisions this resolves

- **Clippings are ingested only by mykg.** The wiki consumes mykg's output, so
  there is a single extraction path and nothing to drift out of sync.
- **mykg does not write to Obsidian.** Set `export.obsidian_enabled: false` in
  the active profile. The wiki owns the vault; mykg emits data only.
- **The wiki is a standalone, re-runnable command** (`mykg build-wiki <session>`),
  decoupled from extraction so the vault can be rebuilt without re-extracting.

## Data contract (what `build-wiki` reads)

The wiki treats a completed session as **read-only input**. It reads only files
mykg already produces:

| File | Wiki uses it for |
|---|---|
| `output/nodes.jsonl` | Page inventory — one page per node. `id`, `type`, `attributes` (per-value confidence), `source_files` |
| `output/edges.jsonl` | Link graph — `from`, `to`, relationship `type`. **The only wikilinks allowed on a page.** |
| `intermediate/edge_metadata.json` | Per-edge confidence/role/dates — annotate/rank links, drop low-confidence links |
| `intermediate/chunk_node_index.json` | Node → exact `filename::chunk_idx` list that produced it — the grounding key |
| `intermediate/file_manifest.json` | Actual chunk text fed to the LLM as grounding evidence |
| `intermediate/schema.json` | Type names + attribute definitions — drives hub pages and page structure |

### The grounding rule (anti-hallucination contract)

A page for node *N* is generated from exactly three inputs and nothing else:

1. N's own attributes (from `nodes.jsonl`).
2. The **verbatim source chunks** N is grounded in
   (via `chunk_node_index` → `file_manifest`).
3. A **1-hop neighbor list**: names + types + relationship of nodes N has edges
   to — so the LLM knows what it may link.

Prose is free-form; **link structure is 100% derived from the graph.** Obsidian's
graph view of the wiki is therefore topologically identical to mykg's edge set.

### What the wiki writes (never back into the session)

```
wiki_vault/
  Home.md                    # index: counts, links to each type hub
  hubs/People.md             # one MOC per concept type, lists its entity pages
  hubs/Concept.md
  entities/<node-id>.md      # prose page; frontmatter carries mykg_id + provenance
  .wiki_manifest.json        # content-hash per page for incremental rebuilds
```

Each entity page's frontmatter records `mykg_id`, `type`, `source_files`, and a
`grounded_chunks` list — so any page traces straight back to the clippings and
Obsidian sees clean YAML.

## Page model & generation

Three page kinds. Only entity pages call the LLM; hubs and home are
deterministic assembly.

### Entity page (LLM-generated, one per node)

- **LLM input:** node attributes, verbatim grounded chunks, 1-hop neighbor list
  `[(name, type, relationship), …]`.
- **Output structure (enforced by prompt, not left to the model):**
  - *Lead* — 1–2 sentence definition of the entity.
  - *Body* — prose synthesis of the grounded chunks.
  - *Connections* — narrative mentioning neighbors, each as `[[neighbor-id|Neighbor Name]]`.
- **Link mechanics:** the LLM receives the exact neighbor set and links only
  those. A **post-validator** parses every `[[…]]` in the output and drops/flags
  any wikilink whose target is not a real neighbor edge. Invented links never
  reach disk. Hard code gate, not a prompt hope.
- **Confidence handling:** attributes/edges below a configurable threshold are
  omitted from the LLM input entirely; null-valued attributes are not passed.
- **Empty-grounding guard:** a node with no resolvable chunks produces a minimal
  stub (name, type, links) with frontmatter `grounded: false` — never fabricated
  prose.

### Hub page (deterministic, one per concept type from `schema.json`)

No LLM. Lists every entity of that type as wikilinks, optionally grouped/sorted
by edge-degree. A one-line description per entry is pulled from the entity page's
cached lead, so hubs stay cheap and consistent with the entities.

### Home page (deterministic)

Node/edge counts, links to each type hub, generation timestamp and source-session
path. Pure assembly.

**Why the split:** the expensive, non-deterministic work (prose) is isolated to
entity pages and made verifiable by the link post-validator; everything
navigational is deterministic and free. Regenerating a page changes only that
one entity's prose; hubs/home recompute mechanically.

## Command architecture

`build-wiki` mirrors `merge_graphs`: its own pipeline module driven by the
existing `orchestrator.py`, scoped to the session, all LLM calls through
`LLMAdapter`. No new orchestration machinery.

### New/changed files

| File | Action | Responsibility |
|---|---|---|
| `src/mykg/wiki_pipeline.py` | create | Ordered `STEPS: list[Step]` for the wiki build |
| `src/mykg/wiki/loader.py` | create | Read-only load of the session contract into typed objects |
| `src/mykg/wiki/page_builder.py` | create | Prompt assembly, link post-validator, page rendering |
| `src/mykg/wiki/manifest.py` | create | Content-hash manifest for incremental rebuilds |
| `src/mykg/cli.py` | modify | Add `mykg build-wiki <session>` subcommand |
| `mykg_config.yaml` + packaged twin | modify | Add a `wiki:` config block (parity-tested) |

### STEPS list

Each step writes a sentinel, so a failed run resumes via `--from-step`, exactly
like extract.

| Step | Output |
|---|---|
| `wiki_load` | Validated in-memory graph + provenance; fails fast if session incomplete |
| `wiki_pages` | `entities/*.md` — **parallel** over nodes via `ThreadPoolExecutor` (`wiki.max_workers`); each worker one LLM call, one page |
| `wiki_hubs` | `hubs/*.md` — deterministic |
| `wiki_index` | `Home.md` + `.wiki_manifest.json` |

### Config block

New `wiki:` key, tunable per profile (so the `mlx-local` profile can run the
wiki on the local model too). Added to both the repo-root `mykg_config.yaml` and
the packaged `src/mykg/data/mykg_config.yaml`, with a parity test per repo
convention.

```yaml
wiki:
  vault_dir: wiki_vault          # relative to session, or absolute
  max_workers: 4
  min_attr_confidence: 0.3       # drop attributes below this from LLM input
  min_edge_confidence: 0.3       # drop links below this
  max_grounding_tokens: 4000     # cap chunk text per page
  neighbors_max: 25              # cap 1-hop list size for hub-like nodes
```

### Incremental rebuilds

The user adds clippings and re-runs mykg often; regenerating every page each time
is wasteful and non-deterministic. Each page records a **grounding hash** =
`hash(node attributes + grounded chunk text + neighbor set)` in
`.wiki_manifest.json`. On the next `build-wiki`:

- hash unchanged → **skip** (keep existing prose — stable across runs),
- hash changed → **regenerate** that page,
- node gone → **delete** its page,
- new node → **generate**.

Hubs/home always recompute (cheap). A run after adding two clippings touches only
the pages whose grounding actually moved. A `--rebuild` flag forces full
regeneration.

## Error handling

The wiki is a pure read→synthesize→write stage, so failure modes are narrower
than extraction, but the graph-grounding contract is enforced in code, not
trusted to the model.

| Situation | Behavior |
|---|---|
| Session incomplete (missing `nodes.jsonl` / intermediate file) | `wiki_load` fails fast naming the missing file; no partial vault written |
| LLM returns invented `[[wikilinks]]` | Post-validator strips them; a page with zero valid links still ships |
| LLM call fails / returns blank for a page | Orchestrator retry→correction path applies; on final failure that page becomes a `grounded: true` stub and the run continues — one bad page never fails the build |
| Node with no resolvable chunks | Deterministic stub, `grounded: false` — never fabricated |
| Vault write collision (page exists from prior run) | Manifest decides skip/regenerate; `--rebuild` overwrites |
| Malformed model output (bad frontmatter, stray code fences) | Renderer owns frontmatter/layout; model output fills only the prose body, so it cannot corrupt YAML |

## Testing

Follows repo conventions — `tmp_path` fixtures, stubbed `LLMAdapter.complete()`
returning canned strings, `live` marker for anything real.

- **loader** — reads a fixture session; asserts typed graph + node→chunk grounding
  resolves; fails fast on a missing file.
- **link post-validator** — model output with one valid + one invented `[[link]]`;
  assert only the real edge survives. *(Core anti-hallucination guarantee —
  highest-value test.)*
- **page_builder** — stubbed LLM; assert entity page has lead/body/connections,
  valid frontmatter with `mykg_id` + `grounded_chunks`, and confidence filtering
  (below-threshold attrs absent from the prompt).
- **hubs/home** — deterministic; assert every node appears under exactly one type
  hub and Home links every hub.
- **manifest / incremental** — build once; rebuild with one node's attributes
  changed; assert exactly one page regenerated, unchanged pages byte-identical,
  removed node's page deleted.
- **config parity** — the `wiki:` block exists and matches between root and
  packaged `mykg_config.yaml`.
- **cli** — `mykg build-wiki <session>` wiring; missing-session error path.
- **live** *(marked)* — end-to-end small-corpus build against a real adapter.

## Open questions / future

- **Phase 2 — synthesized topic pages:** cluster the graph (communities) and have
  the LLM write cross-entity thematic articles per cluster. This is the most
  distinctively "Karpathy wiki" value but adds LLM cost and non-determinism;
  deferred out of the MVP.
- **Hub description caching** relies on parsing the entity page lead; if page
  layout changes, the extraction selector must move with it.
