# Design: KG Synthesis Wiki Skill

**Date:** 2026-07-28
**Status:** Approved (design) — pending implementation plan
**Author:** brainstorming session

## Summary

A new **agent skill** that maintains an LLM-authored wiki *grounded in the mykg
knowledge graphs*. The skill answers the user's competence questions by reading
**only the KGs** (across all domains), synthesizing the answer, and persisting it
as a markdown report — with wiki backlinks and charts — into a **separate
synthesis folder** inside the existing Obsidian vault.

It is the "synthesis/compile" layer that sits beside the existing per-domain
KG-generated wiki. It never reads source documents and never modifies the
KG-generated wiki pages.

## Purpose & boundaries

**Reads (only):**
- `kg_sessions/<Domain>/output/nodes.jsonl`
- `kg_sessions/<Domain>/output/edges.jsonl`
- `kg_wiki/<Domain>/.wiki_manifest.json` (id→path index, for backlink validation only)

**Never reads:** `raw/` source documents.

**Never writes / modifies:** the KG-generated domain wikis (`kg_wiki/Research/`,
`kg_wiki/Yard/`, and any future domain folder). "Never touches" = never writes;
read-only access to a domain's `.wiki_manifest.json` for link validation is
permitted.

**Writes (only):** `kg_wiki/Synthesis/`.

The graph is the ground truth. The skill answers from what the KG contains, not
from model training data. If the KG does not contain the answer, it says so
rather than fabricating.

## Environment layout (from the reference vault)

Reference/fixture vault: `C:\Users\oca\DNV\Yards - Documents\test-wiki`.

```
test-wiki/
├── raw/                              source documents — skill NEVER reads
├── kg_sessions/
│   ├── Research/output/{nodes,edges}.jsonl, knowledge_graph.ttl, networkx_output/
│   └── Yard/output/{nodes,edges}.jsonl, ...
└── kg_wiki/                        ONE Obsidian vault (top-level .obsidian/)
    ├── Research/                     KG-generated wiki — skill NEVER writes
    │   ├── entities/  hubs/  sources/  Home.md  .wiki_manifest.json
    ├── Yard/                         KG-generated wiki — skill NEVER writes
    │   ├── entities/  hubs/  Home.md  .wiki_manifest.json
    └── Synthesis/                    NEW — skill owns this fully
```

- **Domains are named session folders** (`Research`, `Yard`), one per seed schema —
  not timestamped. The skill discovers domains by listing `kg_sessions/`.
- The whole `kg_wiki/` is a **single Obsidian vault**, so `[[wikilinks]]` resolve
  vault-wide across domain folders and `Synthesis/`.

### KG data formats (observed)

`nodes.jsonl` — one JSON object per line:
```json
{"id":"person-alice-chen","type":"Person","confidence":0.98,
 "attributes":{"name":{"value":"Alice Chen","confidence":0.98}, ...},
 "source_files":["team.md"]}
```

`edges.jsonl` — one JSON object per line:
```json
{"id":"edge-0adce0","type":"works_at","from":"person-alice-chen",
 "to":"organization-acme-corp","confidence":0.97,
 "attributes":{...},"method":"llm_extraction","source_files":["team.md"]}
```

### KG-wiki wikilink convention (must be matched)

The KG-generated entity notes use **id-based links with a display alias**:
- Entity note filename = `<mykg_id>.md` (e.g. `entities/benchmark-mmlu.md`).
- Links target the id, alias is the display name: `[[benchmark-mmlu|MMLU]]`.
- Hub links: `[[hubs/AICapability|AICapability]]`.

Synthesized reports **must use the same `[[<mykg_id>|<display>]]` form** so
backlinks resolve to the existing entity notes.

## Synthesis folder layout

The skill owns `kg_wiki/Synthesis/` completely:

```
Synthesis/
├── index.md            one row per report, grouped by theme, with link + summary + Updated
├── log.md              append-only operation log
├── reports/
│   └── <slug>.md       one synthesized answer per file
└── assets/
    └── <slug>-NN.png   generated PNG charts embedded by reports
```

- `index.md` — heading `# Synthesis Index`, entries grouped by theme, each row:
  link to the report + one-line summary + Updated date.
- `log.md` — heading `# Synthesis Log`, append-only.
- Report filenames: kebab-case slug from the question topic, max 60 chars, numeric
  suffix on collision.

### Initialization

On first Synthesize/Query, create only what is missing (never overwrite):
`Synthesis/`, `Synthesis/reports/`, `Synthesis/assets/`, `Synthesis/index.md`
(empty body), `Synthesis/log.md` (empty body). If Lint runs before any synthesis
exists, tell the user to synthesize first; do not auto-create.

## Discovery & grounding

1. List `kg_sessions/` → domain names.
2. For each domain, load `output/nodes.jsonl` + `output/edges.jsonl`.
3. Build an in-context **entity table**: `id → {display, type, domain}` where
   `display = attributes.name.value` if present, else a humanized form of the id.
4. For backlink validation, load each domain's
   `kg_wiki/<Domain>/.wiki_manifest.json` → set of valid page ids and their
   `<Domain>/entities/<id>` paths. Note where the same id appears in more than one
   domain (collision set).

Corpus is small (hundreds of nodes/edges per domain), so direct in-context reads
are acceptable; no precomputed cross-domain index is built or persisted.

## Operations (verbs)

### Query / Synthesize
Trigger: any competence question ("what does the KG say about X", "compare A and B
across domains", "summarize everything about Y").

1. Select relevant nodes/edges across **all** domains using the entity table +
   edge scan.
2. Synthesize an answer grounded strictly in those nodes/edges. Prefer KG content
   over training knowledge. When a fact spans domains, say so and attribute the
   domain.
3. Write the answer to `reports/<slug>.md`:
   - YAML frontmatter: `title`, `created`, `updated`, `domains` (list),
     `entities` (list of cited ids), `theme`.
   - Body prose with entity references as `[[<mykg_id>|<display>]]`.
   - Charts as specified below.
4. Update `index.md` (add/update the report's row under its theme) and append to
   `log.md`.

Plain conversational answers that the user does **not** ask to persist are printed
in-conversation only and write no files. Persisting is explicit.

### Chart
Charts are a required capability. Two mechanisms:
- **Mermaid, inline** — for relationship subgraphs, flows, hierarchies, and simple
  distributions. Rendered natively by Obsidian; no dependencies; git-diffable.
  Use entity display names as node labels.
- **PNG, via `scripts/chart.py`** — for genuine quantitative charts (bar / line /
  scatter / histogram: e.g. confidence distributions, node-degree rankings, per-
  type counts across domains). Saved to `assets/<slug>-NN.png` and embedded with
  `![[assets/<slug>-NN.png]]`. `chart.py` reads the relevant jsonl (or receives a
  small data file/args) and uses matplotlib; it writes only under
  `Synthesis/assets/`.

Choice rule: relationship/topology or trivial counts → Mermaid; multi-value
quantitative comparison or distribution → PNG.

### Lint
Trigger: occasional maintenance ("lint the synthesis wiki", "check backlinks").
Operates over **only** `Synthesis/` files (`scripts/lint_backlinks.py`):

Deterministic (auto-fix):
- **Backlink existence** — every `[[id|...]]` (and `[[id]]`) target in `Synthesis/`
  must be a known page id in some domain manifest. Unknown → report as dangling
  (do not delete; user decides).
- **Collision qualification** — if a linked id exists in more than one domain,
  rewrite that link to path-qualified form `[[<Domain>/entities/<id>|<display>]]`
  to remove Obsidian's shortest-path ambiguity. Requires the report frontmatter /
  context to know the intended domain; if intent is ambiguous, report instead of
  guessing.
- **Index consistency** — `index.md` rows vs actual `reports/*.md`: missing file →
  mark `[MISSING]` (don't delete); file with no row → add row with `(no summary)`.

Heuristic (report only): reports whose cited entities have materially changed,
orphan reports with no inbound links, duplicate/near-duplicate reports.

Lint **never** writes outside `Synthesis/`. It reads domain manifests read-only.
Appends a summary line to `log.md`.

## Backlink correctness (primary risk)

Obsidian resolves `[[id]]` by filename across the whole vault. If the same
`mykg_id` exists in both `Research/entities/` and `Yard/entities/`, a short link is
ambiguous and may resolve to the wrong domain. Mitigations:

- At synthesis time, when a cited id is in the discovery collision set, emit the
  path-qualified link `[[<Domain>/entities/<id>|<display>]]` directly.
- Lint re-checks and qualifies any short collision links that slipped through.
- Non-colliding ids keep the short `[[id|display]]` form.

## Error handling

- No `kg_sessions/` or empty `output/` for a domain → tell the user to run
  extraction first; never fabricate an answer.
- Entity named in the answer but absent from every KG → do **not** invent a
  backlink; render as plain text and note that it is not in the graph.
- Stale backlink (KG regenerated, id removed) → lint flags as dangling; never
  silently deletes.
- Partial write / crash mid-report → `index.md`/`log.md` are updated only after the
  report file is written, so a missing report is detectable by lint (index
  `[MISSING]`), not a corrupt half-state.

## Testing

Fixture: the `test-wiki` vault (`Research` + `Yard`). Verify:
1. Discovery reads both domains' `nodes.jsonl` + `edges.jsonl`.
2. Synthesis writes only under `Synthesis/` (assert no mtime change under
   `Research/`, `Yard/`).
3. Backlinks in a report resolve to existing entity notes.
4. Collision detection: an id present in both domains is rewritten to
   path-qualified form.
5. Lint modifies nothing outside `Synthesis/` and flags a deliberately dangling
   link.
6. `chart.py` produces a PNG under `assets/` and the report embeds it.

## Deliverables

Authored with the **writing-skills** superpower; planned via **writing-plans**.

- `SKILL.md` — schema + workflow layer (this design, operationalized).
- `references/` — `report-template.md`, `index-template.md`, `log-format.md`.
- `scripts/lint_backlinks.py` — deterministic backlink/index lint over `Synthesis/`.
- `scripts/chart.py` — matplotlib PNG chart generator writing to `Synthesis/assets/`.

## Conventions

- Standard markdown; `[[<mykg_id>|<display>]]` for entity backlinks, matching the
  KG-wiki style.
- `Synthesis/` is the only write target. Domain wikis are read-only (manifests) or
  untouched (everything else). `raw/` is never accessed.
- Today's date for `log.md` entries and `created`; `updated` reflects last content
  change.
- Query/Synthesize updates `index.md` + `log.md`. Lint updates `log.md` (and
  `index.md` only when auto-fixing rows). Plain in-conversation answers write
  nothing.

## Out of scope (YAGNI)

- No changes to the mykg pipeline, CLI, or the KG-wiki generator.
- No persisted cross-domain index/database (corpus is small).
- No editing/regeneration of KG entity notes.
- No source-document access.
