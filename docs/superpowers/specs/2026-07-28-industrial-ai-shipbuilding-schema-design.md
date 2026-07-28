# Design: OntoKG schema for Industrial AI in Shipbuilding (design & manufacturing)

**Date:** 2026-07-28
**Status:** Approved design — ready for implementation planning
**Artifact:** a standalone mykg base-schema TTL, e.g. `src/mykg/data/ontokg-shipai.ttl`

## 1. Purpose & scope

A standalone, locked-TBox schema for a `mykg` knowledge graph that maps the
**research landscape of industrial AI in shipbuilding**. Primary job: track
**who is developing what AI capability, its maturity, and the direction of
travel**, and how those capabilities become **solutions** applied to
shipbuilding **design and manufacturing** — including the **digital thread**
and **interoperability** between stakeholders (shipyard, owner, classification
society, manufacturers), governed by **normative** standards and rules.

**In scope (lifecycle):** design, manufacturing, and assembly stages.
**Out of scope:** ship operations, in-service/voyage, and crewing.

### Design goals

- Explicit subclasses for the named AI areas so queries can target them
  directly (foundation models, spatial AI, robotics, digital twins,
  simulation).
- First-class **Standard/Norm** entities for the normative dimension.
- **Trends and maturity are emergent**, not modeled as classes: momentum,
  maturity/TRL, adoption level, and model openness (frontier vs open-weight)
  are captured as **induced attributes** (mykg Pass-1 adds attributes at
  bootstrap; the TBox declares classes and relations only).
- Digital-thread and interoperability semantics carried by **relations**, not
  by a monolithic class.

## 2. Conventions & compatibility

- Namespace/prefix: default `:` = `<http://mykg.local/ontokg#>`, root class
  `:Entity`, matching `ontokg-strategy.ttl`. The `mykg` base-schema parser
  (`src/mykg/base_schema.py`) is namespace-agnostic (localname split on
  `#`/`/`); keeping the `ontokg#` prefix and `:Entity` root keeps the schema
  consistent with existing pipeline behaviour.
- Classes carry **no attributes** in the TTL (Pass-1 induction adds them).
  Object properties use `rdfs:domain` / `rdfs:range`; `range :Entity` is used
  where the target is intentionally open.
- This is a **separate** schema from `ontokg-strategy.ttl` (user chose
  standalone). Usage:

  ```
  mykg extract-graph <dir> --base-schema src/mykg/data/ontokg-shipai.ttl
  mykg extract-graph <dir> --append --session <name> \
      --base-schema src/mykg/data/ontokg-shipai.ttl --obsidian-vault
  ```

## 3. Class hierarchy

Root: `:Entity`.

### Actors

- `:Organization` ⊂ `:Entity`
  - `:Shipyard`
  - `:ShipOwner`
  - `:ClassificationSociety`
  - `:Manufacturer` — equipment/component supplier
  - `:ResearchOrg` — labs, academia, research institutes
  - `:TechVendor` — AI/software solution providers
  - `:RegulatoryBody`
  - `:StandardsBody`
- `:Person` ⊂ `:Entity` — researchers, authors, decision makers

### AI capabilities — "what AI can do"

- `:AICapability` ⊂ `:Entity`
  - `:FoundationModel` — large models; frontier vs open-weight distinguished by
    induced attributes (openness, scale, license)
  - `:SpatialAI` — 3D perception, SLAM, world models for robotics
  - `:RoboticSystem` — robots / autonomous manufacturing & assembly systems
  - `:DigitalTwin` — **live, synchronized** virtual replica of a real
    asset/process
  - `:Simulation` — **predictive/offline** virtual execution of behaviour
    (may exist before any physical asset)
  - `:GenerativeDesign` — generative/optimization AI for design
  - `:AIMethod` — general fallback for methods/techniques

### Applied solutions

- `:Solution` ⊂ `:Entity` — a deployed system applying one or more
  capabilities to a shipbuilding process ("solution for use of industrial AI").

### Software-defined assets

- `:SoftwareDefinedAsset` ⊂ `:Entity` — a physical asset, equipment, ship
  block, or manufacturing cell represented and controllable in software; the
  subject that digital twins and simulations mirror. "Software-defined
  *processes*" are `:Process` nodes flagged by an induced attribute
  (e.g. `software_defined`), not a separate class.

### Shipbuilding processes & digital thread

- `:Process` ⊂ `:Entity`
  - `:DesignProcess`
  - `:ManufacturingProcess`
  - `:AssemblyProcess`
- `:DigitalThread` ⊂ `:Entity` — the integration backbone linking processes,
  assets, actors, and standards across the lifecycle.

### Normative — standards & rules

- `:Standard` ⊂ `:Entity`
  - `:ClassRule` — classification-society rules
  - `:Regulation` — statutory/regulatory instruments
  - `:ReferenceArchitecture`
  - `:TechnicalStandard` — ISO and other technical standards

### Supporting

- `:Document` ⊂ `:Entity`
  - `:ResearchPaper`
  - `:Report`
  - `:Whitepaper`
- `:Benchmark` ⊂ `:Entity` — evaluation benchmark (maturity evidence)
- `:Dataset` ⊂ `:Entity`
- `:Deliverable` ⊂ `:Entity` — a process output / work product
- `:Concept` ⊂ `:Entity` — theme / approach / strategy
- `:Event` ⊂ `:Entity` — release, milestone, conference (direction of travel
  over time)
- `:Place` ⊂ `:Entity` — location / geography

## 4. Relations (object properties)

### Research landscape / development

| Property | Domain | Range |
| --- | --- | --- |
| `:develops` | `:Organization`, `:Person` | `:AICapability`, `:Solution` |
| `:researches` | `:Organization`, `:Person` | `:AICapability`, `:Concept` |
| `:builds_on` | `:AICapability` | `:AICapability` |
| `:supersedes` | `:AICapability`, `:Solution`, `:Standard` | `:Entity` |
| `:trained_on` | `:FoundationModel` | `:Dataset` |
| `:benchmarked_on` | `:AICapability`, `:Solution` | `:Benchmark` |

### Applied solutions / usage

| Property | Domain | Range |
| --- | --- | --- |
| `:applies` | `:Solution` | `:AICapability` |
| `:applied_in` | `:Solution`, `:AICapability` | `:Process` |
| `:automates` | `:AICapability`, `:Solution` | `:Process` |
| `:simulates` | `:Simulation`, `:DigitalTwin` | `:SoftwareDefinedAsset`, `:Process` |
| `:twin_of` | `:DigitalTwin` | `:SoftwareDefinedAsset`, `:Process` |
| `:validates` | `:Simulation` | `:DesignProcess`, `:ManufacturingProcess`, `:Deliverable` |

### Process / digital thread / interoperability

| Property | Domain | Range |
| --- | --- | --- |
| `:precedes` | `:Process` | `:Process` |
| `:produces` | `:Process` | `:Deliverable`, `:SoftwareDefinedAsset` |
| `:integrates_with` | `:Solution`, `:Process`, `:DigitalThread` | `:Entity` |
| `:data_exchanged_with` | `:Process`, `:Organization`, `:DigitalThread` | `:Entity` |
| `:interoperates_with` | `:Organization` | `:Organization` |
| `:links` | `:DigitalThread` | `:Process`, `:Organization`, `:SoftwareDefinedAsset` |

### Normative / standards

| Property | Domain | Range |
| --- | --- | --- |
| `:conforms_to` | `:Solution`, `:Process`, `:AICapability`, `:SoftwareDefinedAsset` | `:Standard` |
| `:governed_by` | `:Process`, `:Organization`, `:Solution` | `:Standard`, `:RegulatoryBody` |
| `:issued_by` | `:Standard` | `:StandardsBody`, `:ClassificationSociety`, `:RegulatoryBody` |

### Actors / stakeholders

| Property | Domain | Range |
| --- | --- | --- |
| `:collaborates_with` | `:Organization` | `:Organization` |
| `:competes_with` | `:Organization`, `:Solution` | `:Entity` |
| `:supplies` | `:Manufacturer` | `:Product`, `:SoftwareDefinedAsset`, `:Shipyard` |
| `:classifies` | `:ClassificationSociety` | `:Shipyard`, `:SoftwareDefinedAsset`, `:Process` |
| `:stakeholder_in` | `:Organization`, `:Person` | `:Process`, `:Solution`, `:Standard` |

> Note: `:supplies` references `:Product`. `:Product` is **not** a class in
> this schema; the range for supplied goods is `:SoftwareDefinedAsset` /
> `:Shipyard`. During implementation, drop the `:Product` term from
> `:supplies` (final range: `:SoftwareDefinedAsset`, `:Shipyard`) to avoid a
> dangling reference.

### Provenance / evidence

| Property | Domain | Range |
| --- | --- | --- |
| `:documented_in` | `:Entity` | `:Document` |
| `:mentions` | `:Document` | `:Entity` |
| `:authored_by` | `:Document`, `:AICapability` | `:Person`, `:Organization` |
| `:published_by` | `:Document` | `:Organization` |
| `:release_of` | `:Event` | `:AICapability`, `:Solution` |
| `:announced_at` | `:Event` | `:Place` |
| `:relates_to` | `:Entity` | `:Entity` |

## 5. Emergent attributes (induced, not in TBox)

These are captured by Pass-1 attribute induction on the relevant classes and
are **not** declared in the TTL:

- `:AICapability` / `:FoundationModel`: maturity/TRL, adoption level, momentum,
  openness (frontier vs open-weight), model scale, license, modality.
- `:Solution`: deployment maturity, target lifecycle stage.
- `:Process`: `software_defined` flag, automation level.
- `:Standard`: status (draft/published), version, jurisdiction.

## 6. Competency questions (what the graph should answer)

1. Which organizations develop foundation models applied in `:DesignProcess`,
   and how mature are they?
2. What is the lineage (`:builds_on`) chain behind a given capability?
3. Which digital twins / simulations span both design and manufacturing
   (`:applied_in` both `:DesignProcess` and `:ManufacturingProcess`)?
4. Which solutions `:conform_to` which class-society `:ClassRule`, and where are
   the gaps?
5. How does the `:DigitalThread` link a shipyard, an owner, a classification
   society, and manufacturers, and what data is `:data_exchanged_with` whom?
6. What is the direction of travel — recent `:Event` releases and
   `:supersedes` chains — for each capability area?

## 7. Validation / acceptance

- TTL parses with `rdflib` and loads via `parse_base_schema` without error;
  all classes reachable from `:Entity`; every `rdfs:domain`/`rdfs:range`
  references a declared class (no dangling terms — see `:Product` note).
- A smoke `mykg extract-graph` run on a small sample corpus with
  `--base-schema ontokg-shipai.ttl` completes and produces nodes typed to the
  new classes.

## 8. Out of scope / non-goals

- No merge with or modification to `ontokg-strategy.ttl`.
- No operations-phase entities (voyage, crewing, maintenance-in-service).
- No modeled `:Trend` class — trends are read out of aggregated attributes and
  `:Event`/`:supersedes` history.
