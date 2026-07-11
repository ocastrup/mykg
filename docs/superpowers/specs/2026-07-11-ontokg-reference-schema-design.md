# OntoKG Reference Schema for mykg — Design

**Date:** 2026-07-11
**Status:** Approved design, pending implementation plan
**Scope:** One deliverable data artifact (`ontokg-base.ttl`) plus a companion mapping doc and a round-trip check script. **No pipeline code changes.**

## 1. Motivation

The paper *OntoKG: Ontology-Oriented Knowledge Graph Construction with Intrinsic-Relational Routing* (Li, Liu, Pandey, Srikanth — ProRata.ai, arXiv:2604.02618, 3 Apr 2026) presents a **declarative schema** whose central idea is **intrinsic-relational routing**: every property is either *intrinsic* (a node attribute for lookup, e.g. birth date) or *relational* (a traversable graph edge, e.g. employer). The schema is deliberately **not** a formal OWL/RDF ontology; it is a reusable, backend-portable classification schema instantiated on Wikidata as **8 categories / 94 modules (56 intrinsic, 38 relational)**.

We want to reuse OntoKG's **category + module vocabulary** as a **reference (seed) schema** for the mykg extraction pipeline, so that mykg graphs are typed against a principled, published ontology instead of a purely per-corpus induced one.

### What we are and are not doing

- **We are:** importing OntoKG's *vocabulary* (category names, module names, and the intrinsic/relational typing) as a mykg base schema.
- **We are not:** importing OntoKG's Wikidata mechanics (QID gate values, PID value-property routing, the Rust classifier). Those are Wikidata-specific and irrelevant to mykg's free-text LLM extraction.
- **We are not** freezing the vocabulary. Per decision in §3, this is **seed + extend**: OntoKG's vocabulary is locked, but mykg Pass-1 induction may still add corpus-specific subclasses and edges.

## 2. Key facts that shaped this design

1. **mykg already has the hook.** `mykg extract-graph <dir> --base-schema <file.ttl>` (`src/mykg/cli.py:567`, "Locked TBox TTL") parses an RDFS Turtle file via `base_schema.py:parse_base_schema` into `locked_classes` + `locked_properties`, and `steps/step_pass1.py:37-48` injects them into the Pass-1 induction prompt as *"EXISTING SCHEMA (DO NOT RENAME, REMOVE, OR DUPLICATE THESE)… You may add new subclasses, new properties, or new root classes."* Importing a reference schema therefore requires **only a data file** — no code.

2. **`parse_base_schema` semantics** (defines what the TTL must contain):
   - `?c a rdfs:Class` → a locked concept; `rdfs:subClassOf` sets its `parent`.
   - `?p a rdf:Property` with `rdfs:range rdfs:Literal` → becomes a **datatype attribute** appended to each declared `rdfs:domain` class.
   - `?p a rdf:Property` with a **class** range → becomes a locked **object property** (edge); note it records only the **first** `rdfs:domain` for its internal entry (multi-domain is truncated in the locked-properties dict, but all domains still render in the TTL and the Pass-1 prompt lists property names regardless).

3. **The OntoKG repo is dark.** `github.com/Prorata-ai/OntoKG` (the paper's stated code/schema location) returns 404 for every case variant, via web and `gh`. The authoritative 8 YAML files (with QID gates and per-module value-properties) are **not obtainable**. Therefore the vocabulary is reconstructed from the **paper's Appendix B**, which is OntoKG's own "LLM-guided extraction using the schema as prompt instructions" (Application 5.5) — the category taxonomy and per-category module tag lists, already de-coupled from Wikidata. This is the most faithful available source and matches mykg's use case exactly.

## 3. Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Module → mykg mapping | **Hybrid** | Categories → concepts; intrinsic modules → subclasses; relational modules → edges. Faithful to both OntoKG's routing and mykg's property-graph model. |
| Strictness | **Seed + extend** | Use existing `--base-schema` behavior. Zero new pipeline code. Induction may extend beyond OntoKG's 8/94. |
| Relational-edge range | **`:Entity`** | OntoKG defines relational modules as entity→entity connections, so `:Entity` is *true*, not fabricated, and satisfies `parse_base_schema`'s requirement that object properties carry a class range. |

## 4. Mapping rules

Given the OntoKG vocabulary, produce `ontokg-base.ttl`:

| OntoKG element | mykg TTL representation | Naming |
|---|---|---|
| 8 categories | `rdfs:Class`, each `rdfs:subClassOf :Entity` | PascalCase: `Person`, `Organization`, `Work`, `Place`, `Science`, `Event`, `Knowledge`, `Product` |
| `:Entity` | one synthetic root `rdfs:Class` | — |
| Intrinsic module | `rdfs:Class`, `rdfs:subClassOf <its category>`, **no attributes** | PascalCase: `Corporation ⊑ Organization`, `River ⊑ Place`, `Film ⊑ Work` |
| Relational module | `rdf:Property`, `rdfs:domain` = spanning categories, `rdfs:range :Entity` | snake_case: `affiliation`, `military`, `finance` |

Worked fragment:
```turtle
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix :     <http://mykg.local/ontokg#> .

:Entity        a rdfs:Class .
:Organization  a rdfs:Class ; rdfs:subClassOf :Entity .
:Person        a rdfs:Class ; rdfs:subClassOf :Entity .
:Place         a rdfs:Class ; rdfs:subClassOf :Entity .

:Corporation   a rdfs:Class ; rdfs:subClassOf :Organization .   # intrinsic module
:River         a rdfs:Class ; rdfs:subClassOf :Place .          # intrinsic module

:affiliation   a rdf:Property ; rdfs:domain :Organization, :Person ; rdfs:range :Entity .
:military      a rdf:Property ; rdfs:domain :Person, :Organization, :Place, :Work, :Event, :Product ; rdfs:range :Entity .
```

### Intrinsic vs relational typing — authority

The intrinsic/relational split is **authoritative for the relational modules named in the paper** and **inferred for the rest**. Every entry in the companion doc (§6, deliverable 2) MUST be marked `A` (authoritative) or `I` (inferred).

- **Authoritative relational modules** (paper Figure 2 — cross-category span ≥ 2): `affiliation`, `authorship`, `award`, `culture`, `education`, `entertainment`, `finance`, `food`, `government`, `healthcare`, `hierarchy`, `legal`, `location`, `military`, `politics`, `religion`, `society`, `sports`, `technology`, `transportation`. Paper-named single-category relational examples: `family` (Person), `genomics` (Science). These are **always edges**.
- **Inference heuristic for all other Appendix-B tags:**
  - If the tag names a **kind of the parent entity** (a noun the entity *is-a*: `corporation`, `film`, `river`, `element`, `compound`, `protein`, `gene`, `disease`, `aircraft`, `software`, `theorem`, …) → **intrinsic subclass**.
  - If the tag names a **cross-cutting domain, scope, or connection** (`crime`, `creativity`, `international`, `revenue`, `violence`, `position`, `field`, `jurisdiction`, `astronomy`, …) → **relational edge**.
  - Ambiguous cases are marked `I` and default to the reading in the companion table; **induction can override any inferred choice**, so an imperfect call is low-cost.

## 5. Source vocabulary (verbatim from Appendix B)

**Categories** (with entity-type examples):
- `Person` — human (real, living or historical)
- `Organization` — business, company, university, government agency
- `Work` — book, film, television series, fictional character
- `Place` — street, river, human settlement, lake
- `Science` — planet, asteroid, chemical element, disease, gene
- `Event` — war, battle, election, conference, natural disaster
- `Knowledge` — scholarly article, theorem, algorithm, law
- `Product` — software, aircraft, vehicle, video game

**Per-category module (tag) vocabulary:**
- **Person:** entertainment, creativity, education, politics, sports, religion, finance, military, society, crime, family, award, healthcare, legal, culture, government, technology, food
- **Organization:** location, affiliation, education, international, government, corporation, culture, religion, politics, sports, broadcast, finance, society, healthcare, military, legal, transportation, entertainment, award, food
- **Work:** literature, film, television, art, comics, periodical, revenue, museum, music, sports, military, religion, character, culture, award, authorship, location
- **Place:** dwelling, commercial, culture, religion, infrastructure, transportation, government, administration, sports, heritage, education, nature, finance, military, entertainment, healthcare, affiliation, architecture, food
- **Science:** element, compound, mineral, geology, disease, gene, biofunction, protein, pharmaceutical, anatomy, organism, botany, astronomy, clinical, healthcare, education, biosystem, clinical_trial, cell_lineage, genomics
- **Event:** military, conference, exhibition, disaster, violence, politics, award, sports, society, legal, entertainment, education, religion, transportation
- **Knowledge:** language, theorem, algorithm, specification, abstract, position, law, unit, field, phenomenon, publication, reference, name, religion, jurisdiction
- **Product:** cloud, aircraft, vehicle, computer, software, game, device, military, food, tool, currency, fiction, material, artifact, brand, entertainment, transportation, technology, award

A module name that appears under multiple categories becomes **one** TTL entry whose `rdfs:domain` lists all categories it appears in (relational) or, for intrinsic modules that are genuinely category-specific, a subclass under each relevant category.

## 6. Deliverables

1. **`ontokg-base.ttl`** — the reference schema. Location: `docs/examples/ontokg/ontokg-base.ttl` (data/example, not packaged source). Valid RDFS Turtle parseable by `parse_base_schema`.
2. **`ontokg-mapping.md`** (companion) — a table: `module | category(ies) | intrinsic|relational | A|I | mykg representation`, covering every distinct tag in §5. This is the human-auditable record of the typing judgments.
3. **`check_ontokg_base.py`** — a standalone script (not a pipeline change) that runs `parse_base_schema(ontokg-base.ttl)` and asserts: all 8 categories present as locked classes under `:Entity`; every intrinsic module present as a locked subclass of a category; every relational module present as a locked object property with range `:Entity`; counts reported.

## 7. Validation

1. **Round-trip:** `check_ontokg_base.py` passes — confirms the TTL loads and every intended class/property survives `parse_base_schema`.
2. **Smoke run:** one live `mykg extract-graph <existing example corpus> --base-schema ontokg-base.ttl` on a small corpus (e.g. `docs/examples/blog_demo_run` inputs or the `live_corpus` fixture). Confirm: (a) the Pass-1 prompt's locked block lists the OntoKG classes/properties; (b) the resulting `schema.json` contains the OntoKG concepts/properties **plus** any induced additions, with **no duplication or renaming** of locked names.

## 8. Limitations (carried into implementation)

1. **Typing authority is partial.** Only the ~20 cross-category relational modules (plus 2 named single-category ones) are paper-authoritative. The remaining relational + all 56 intrinsic modules are inferred (§4) and marked `I`. Because this is seed + extend, every inferred call is a starting point induction can revise.
2. **No module attributes.** OntoKG's per-module Wikidata value-properties are not in the paper, so intrinsic subclasses ship with empty attribute lists; mykg induces attributes per corpus.
3. **`hierarchy` module** is an authoritative relational module (Figure 2) but does not appear as an extraction tag in Appendix B; it is included as a relational edge for completeness and noted as such.
4. **Multi-domain truncation** in `parse_base_schema`'s internal `locked_properties` entry (first domain only) is cosmetic for seeding — the Pass-1 prompt lists property names regardless, and the full domain set is preserved in the TTL. No workaround needed.
5. **Reconstruction, not the original artifact.** This schema is derived from the paper, not the (inaccessible) OntoKG repo. If the repo becomes available, the authoritative YAML should supersede the inferred typings.

## 9. Out of scope

- A frozen / induction-suppressing mode (`--frozen-schema`). Considered and rejected for this iteration (seed + extend chosen).
- Importing QID gate values or PID value-property routing.
- Any change to `parse_base_schema`, Pass 1, Pass 2, or the CLI.
