---
name: mykg-synthesis-wiki
description: "Use to answer competence questions from the mykg knowledge graphs and maintain an LLM-authored synthesis wiki. Triggers: 'synthesize ...', 'what does the KG/graph say about X', 'add to the synthesis wiki', 'write a synthesis report on ...', 'compare A and B across domains', 'lint the synthesis wiki', 'check synthesis backlinks'. Reads ONLY the knowledge graphs (kg_sessions/*/output/nodes.jsonl + edges.jsonl, all domains); never reads source documents; never modifies the KG-generated domain wikis. Writes only to kg_wiki/Synthesis/."
---

# mykg Synthesis Wiki

Answer the user's competence questions **grounded only in the mykg knowledge
graphs**, and persist the answers as an LLM-authored synthesis wiki. This is the
synthesis layer beside the KG-generated per-domain wikis — it reads the graphs,
never the sources, and writes only to its own folder.

## Boundaries (hard rules)

- **Read only the KGs.** Load `kg_sessions/<Domain>/output/nodes.jsonl` and
  `edges.jsonl` for every domain. Never read `raw/` or any source document.
- **Never modify the domain wikis.** `kg_wiki/<Domain>/` (e.g. `Research/`,
  `Yard/`) is read-only. You may read a domain's `.wiki_manifest.json` for link
  validation, nothing else there.
- **Write only to `kg_wiki/Synthesis/`.** All reports, charts, index, and log
  live there.
- **Never fabricate.** If the graphs do not contain the answer, say so. Never
  invent a backlink to an entity that is not in the KG.

## Locate the vault root

The vault root is the folder that contains both `kg_sessions/` and
`kg_wiki/`. Resolve in this order and confirm with the user if unsure:
1. A path the user gave in the request.
2. The `kg_wiki_ROOT` environment variable, if set.
3. The current directory, if it contains both `kg_sessions/` and `kg_wiki/`.
4. Otherwise, ask the user for the path.

Reference/fixture root for testing:
`C:\Users\oca\DNV\Yards - Documents\test-wiki`.

## Discover domains and load the KGs

1. List subfolders of `<root>/kg_sessions/` → domain names (e.g. `Research`,
   `Yard`).
2. For each, read `output/nodes.jsonl` and `output/edges.jsonl`.
3. Build an in-context entity table: `id -> {display, type, domain}` where
   `display = attributes.name.value` if present, else the id humanized
   (split on `-`, drop the leading type token when it duplicates `type`,
   title-case). Note any id that appears in more than one domain (collision set).

## Verbs

### Synthesize / answer a competence question
Triggers: "synthesize …", "what does the KG say about X", "write a synthesis
report on …", "compare A and B across domains", "add to the synthesis wiki".

1. Select the relevant nodes/edges across **all** domains.
2. Write the answer grounded strictly in them. Prefer KG content over training
   knowledge; attribute the domain when a fact spans domains.
3. Initialize `Synthesis/` if missing: create `Synthesis/`, `reports/`,
   `assets/`, `index.md` (heading `# Synthesis Index`, empty body), `log.md`
   (heading `# Synthesis Log`, empty body). Never overwrite existing files.
4. Write `reports/<slug>.md` following `references/report-template.md`. Slug =
   kebab-case of the topic, max 60 chars, numeric suffix on collision.
5. Reference entities as `[[<mykg_id>|<display>]]`. If the id is in the collision
   set, write it path-qualified: `[[<Domain>/entities/<id>|<display>]]`.
6. Update `index.md` (add/update the report's row under its theme; see
   `references/index-template.md`) and append a `synthesize` block to `log.md`
   (see `references/log-format.md`).

A plain conversational answer the user does **not** ask to persist writes no
files — answer in the conversation and, if the discipline block applies, log a
`query | in-conversation only` line only when they asked to record it.

### Chart
Charts are required. Choose the mechanism:
- **Mermaid inline** for relationships/flow/hierarchy or trivial counts. Embed a
  fenced ```mermaid block in the report. Use entity display names as labels.
- **PNG via scripts/chart.py** for quantitative charts (bar/line/hist:
  confidence distributions, node-degree rankings, per-type counts). Compute the
  data yourself from the loaded jsonl, then render:

  ```bash
  uv run python "<skill_dir>/scripts/chart.py" --kind bar --data data.json \
    --out "<root>/kg_wiki/Synthesis/assets/<slug>-01.png" --title "…"
  ```

  Or count a field directly from a domain's nodes:

  ```bash
  uv run python "<skill_dir>/scripts/chart.py" \
    --from-jsonl "<root>/kg_sessions/<Domain>/output/nodes.jsonl" \
    --count-by type --out "<root>/kg_wiki/Synthesis/assets/<slug>-01.png" \
    --title "<Domain> nodes by type"
  ```

  Embed in the report with `![[assets/<slug>-01.png]]`. If chart.py exits 2,
  matplotlib is missing — tell the user to run `pip install 'mykg[wiki]'`.

### Lint
Triggers: "lint the synthesis wiki", "check synthesis backlinks". Two parts:

1. **Backlinks (script).** Run over the synthesis folder only:

   ```bash
   uv run python "<skill_dir>/scripts/lint_backlinks.py" \
     --vault "<root>/kg_wiki" --fix
   ```

   It validates every `[[…]]` target against the domain wikis, auto-qualifies
   collisions using each report's `domains:` frontmatter, and reports dangling
   links (it never deletes them and never writes outside `Synthesis/`). Add
   `--json` for machine-readable output. Report the dangling/ambiguous items to
   the user for a decision.

2. **Index consistency (you).** Compare `index.md` rows against `reports/*.md`:
   a report with no row → add a row with `(no summary)`; a row pointing at a
   missing report → mark it `[MISSING]` (do not delete). Append a `lint` block to
   `log.md`.

## Wikilink rules

- Entity backlink: `[[<mykg_id>|<display>]]` (matches the KG wiki's own style).
- Collision id (present in >1 domain): `[[<Domain>/entities/<id>|<display>]]`.
- Never link an id that is absent from every KG — render it as plain text and
  note that it is not in the graph.

## Error handling

- No `kg_sessions/` or an empty `output/` for a domain → tell the user to run
  extraction first; do not fabricate.
- KG regenerated and an id disappeared → lint flags the backlink as dangling;
  never silently delete.
- Write `index.md`/`log.md` only after the report file is written, so a crash
  leaves a detectable missing report (lint `[MISSING]`), not a corrupt half-state.
