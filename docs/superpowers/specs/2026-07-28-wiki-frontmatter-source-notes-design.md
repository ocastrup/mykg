# Wiki Frontmatter Enrichment + Source Notes — Design

Date: 2026-07-28
Status: Approved (design)

## Summary

Enrich the Obsidian vault produced by the `build-wiki` pipeline so that:

1. Source documents are materialized as real vault notes, making `source_files`
   resolvable wikilinks (with working backlinks and search).
2. `source_files` in entity frontmatter become `[[wikilinks]]`.
3. An Obsidian-native `tags` property is added, populated from the entity type.
4. First-hop edges (neighbors) are exposed in frontmatter with their confidence,
   in a Dataview-queryable shape.

These changes are scoped to the wiki subsystem
(`src/mykg/wiki/` + `src/mykg/wiki_pipeline.py`). No change to graph extraction,
`nodes.jsonl`, `edges.jsonl`, or other outputs.

## Motivation

Current entity frontmatter (example):

```yaml
---
mykg_id: document-ccs-digital-shipyards-and-ai-advanced-search
type: Document
aliases:
- CCS Digital Shipyards and AI (Advanced Search)
source_files:
- CCS Digital Shipyards and AI (Advanced Search).md
- _preprocessed\Future Yard Architecture.md
grounded: true
grounded_chunks:
- CCS Digital Shipyards and AI (Advanced Search).md::1
---
```

Problems:
- `source_files` are inert filenames — not clickable, no backlinks, and the
  documents themselves are not present in the vault.
- No Obsidian-native `tags`, so Graph-view Groups and tag queries can't target
  entity types cleanly.
- Edge confidence (a core signal of the graph) is invisible from a note and not
  queryable via Dataview.

## Design

### 1. Source documents as vault notes (`sources/`)

- New pipeline step **`wiki_sources`** in `src/mykg/wiki_pipeline.py`.
- Reads source text from `intermediate/file_manifest.json` (already loaded by the
  wiki loader; each entry has a `content` field).
- For each source file, writes `sources/<basename>.md` where `<basename>` is the
  file name with any directory prefix (e.g. `_preprocessed\`) and the `.md`
  extension removed. Example:
  `_preprocessed\Future Yard Architecture.md` → `sources/Future Yard Architecture.md`.
- Note body = the **full source text**.
- Note frontmatter (minimal), so sources are groupable/queryable:
  ```yaml
  ---
  type: Source
  tags:
  - Source
  source_file: "_preprocessed\\Future Yard Architecture.md"
  ---
  ```
  `source_file` preserves the original relative path for provenance.
- **Basename collisions:** if two source files flatten to the same basename, the
  first wins and a warning is logged (`wiki: source basename collision ...`).
- **Incremental rebuild + cleanup:** tracked in a manifest analogous to the
  entity-page manifest, so unchanged sources are skipped and sources removed from
  the corpus are deleted from `sources/`. Hash = hash of the source content.

### 2. `source_files` become wikilinks

In `_frontmatter()` (`src/mykg/wiki/page_builder.py`), map each raw source path to
its flattened basename and emit a wikilink string:

```yaml
source_files:
- "[[CCS Digital Shipyards and AI (Advanced Search)]]"
- "[[Future Yard Architecture]]"
```

A single shared helper computes the flattened basename so entity frontmatter and
the `wiki_sources` step agree on note names. This helper is the single source of
truth for path → note-name normalization.

### 3. `tags` property from type

- Add a `tags` list containing the entity's type, alongside the existing `type`
  field (kept for current consumers).
- Sanitize the type into a valid Obsidian tag: replace whitespace and disallowed
  characters with `_` (e.g. `Software Engineer` → `Software_Engineer`).
- Applied to entity notes, hub relevance is via type; source notes use `Source`.

### 4. `neighbors` property with confidence

- Pass the node's first-hop neighbors (already computed via
  `graph.neighbors(nid, WIKI_MIN_EDGE_CONFIDENCE, WIKI_NEIGHBORS_MAX)`) into the
  frontmatter builder.
- Emit a list of objects:
  ```yaml
  neighbors:
  - link: "[[org-classnk|ClassNK]]"
    confidence: 0.91
  ```
- Same confidence threshold and max-count already used for the body Connections
  section — no new config.
- Dataview can read `file.frontmatter.neighbors` as a list of `{link, confidence}`;
  the `[[...]]` inside creates graph backlinks.

### Resulting entity frontmatter

```yaml
---
mykg_id: document-ccs-digital-shipyards-and-ai-advanced-search
type: Document
tags:
- Document
aliases:
- CCS Digital Shipyards and AI (Advanced Search)
source_files:
- "[[CCS Digital Shipyards and AI (Advanced Search)]]"
- "[[Future Yard Architecture]]"
neighbors:
- link: "[[org-classnk|ClassNK]]"
  confidence: 0.91
grounded: true
grounded_chunks:
- CCS Digital Shipyards and AI (Advanced Search).md::1
---
```

## Signature / data-flow changes

- `_frontmatter(node)` → `_frontmatter(node, neighbors)`; `render_entity_page`
  and `generate_entity_page` / `render_stub_page` thread the `neighbors` list
  (already available in `run_wiki_pages`) into the frontmatter builder.
- New normalization helper (e.g. `source_note_name(raw_path) -> str`) in the wiki
  package, used by both `page_builder` and the `wiki_sources` step.
- New step registered in `WIKI_STEPS`; ordering: `wiki_sources` can run alongside
  `wiki_pages` (independent), before/around `wiki_index`. It writes a
  `wiki_sources.done` marker.
- New source manifest file under the vault (name mirrors existing wiki manifest).

## Obsidian Groups (usage guidance, not code)

Graph-view Groups recolor nodes matching a search query; they do not alter graph
topology. With the new `tags`, hubs/types can be highlighted via queries such as
`tag:#Document`, and source notes via `path:sources/` or `tag:#Source`. This will
be documented as a tip (README / SKILL), not implemented in code.

## Non-goals

- No change to extraction, `nodes.jsonl`, `edges.jsonl`, TTL, or Neo4j export.
- No new configuration keys.
- No LLM prompt changes.

## Testing

- Unit: `source_note_name` normalization (prefixes, extension, collisions).
- Unit: `_frontmatter` emits `tags`, wikilink `source_files`, and `neighbors`
  with confidence (extend `tests/test_wiki_page_builder.py`).
- Pipeline: `wiki_sources` writes `sources/*.md` with full text + frontmatter,
  handles collisions, and cleans up removed sources
  (extend `tests/test_wiki_pipeline.py`).
- Manifest/incremental: unchanged source is skipped; changed source is rewritten.
