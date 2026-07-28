# OntoKG Industrial-AI-in-Shipbuilding Schema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone, validated mykg base-schema TTL that maps the research landscape of industrial AI in shipbuilding (design & manufacturing), plus a test suite that locks its classes, relations, and competency-question coverage.

**Architecture:** A single hand-written RDFS Turtle file `src/mykg/data/ontokg-shipai.ttl` (same style as the existing `ontokg-strategy.ttl`), using the default `:` = `<http://mykg.local/ontokg#>` namespace and `:Entity` root so it round-trips through mykg's namespace-agnostic `parse_base_schema`. A companion pytest module `tests/test_ontokg_shipai.py` asserts syntactic validity (via `mykg.schema_validator.validate_schema_ttl`), structural round-trip (via `mykg.base_schema.parse_base_schema`), the exact declared class/relation sets, a no-dangling-term guard, and a mapping proving all 15 competency questions are answerable.

**Tech Stack:** Python 3, `rdflib`, `pytest`, `uv` (package/test runner). Modules reused: `mykg.schema_validator`, `mykg.base_schema`.

**Spec:** `docs/superpowers/specs/2026-07-28-industrial-ai-shipbuilding-schema-design.md`

---

## File Structure

- **Create:** `src/mykg/data/ontokg-shipai.ttl` — the locked TBox (41 classes, 33 object properties). Sole responsibility: declare the domain schema. No attributes (induction adds them).
- **Create:** `tests/test_ontokg_shipai.py` — validation + coverage tests for the shipped TTL. Sole responsibility: guard the schema's shape and competency coverage.

Both files are self-contained. The TTL is the single source of truth; the test reads the committed file (no generator, matching `ontokg-strategy.ttl`'s hand-written pattern rather than `check_ontokg_base.py`'s generator pattern — the strategy schema is the closer precedent).

### Canonical class set (parent in parentheses)

```
Entity(-)
Organization(Entity)
  Shipyard(Organization) ShipOwner(Organization) ClassificationSociety(Organization)
  Manufacturer(Organization) ResearchOrg(Organization) TechVendor(Organization)
  RegulatoryBody(Organization) StandardsBody(Organization)
Person(Entity)
AICapability(Entity)
  FoundationModel(AICapability) SpatialAI(AICapability) RoboticSystem(AICapability)
  DigitalTwin(AICapability) Simulation(AICapability) GenerativeDesign(AICapability) AIMethod(AICapability)
Solution(Entity)
SoftwareDefinedAsset(Entity)
Process(Entity)
  DesignProcess(Process) ManufacturingProcess(Process) AssemblyProcess(Process)
DigitalThread(Entity)
Standard(Entity)
  ClassRule(Standard) Regulation(Standard) ReferenceArchitecture(Standard) TechnicalStandard(Standard)
Document(Entity)
  ResearchPaper(Document) Report(Document) Whitepaper(Document)
Benchmark(Entity) Dataset(Entity) Deliverable(Entity) Concept(Entity) Event(Entity) Place(Entity)
```
41 classes total.

### Canonical property set (domain → range)

```
develops            : Organization, Person                              -> AICapability, Solution
researches          : Organization, Person                              -> AICapability, Concept
builds_on           : AICapability                                      -> AICapability
supersedes          : AICapability, Solution, Standard                  -> Entity
trained_on          : FoundationModel                                   -> Dataset
benchmarked_on      : AICapability, Solution                            -> Benchmark
applies             : Solution                                          -> AICapability
applied_in          : Solution, AICapability                            -> Process
automates           : AICapability, Solution                            -> Process
simulates           : Simulation, DigitalTwin                           -> SoftwareDefinedAsset, Process
twin_of             : DigitalTwin                                       -> SoftwareDefinedAsset, Process
validates           : Simulation                                       -> DesignProcess, ManufacturingProcess, Deliverable
precedes            : Process                                           -> Process
produces            : Process                                           -> Deliverable, SoftwareDefinedAsset
integrates_with     : Solution, Process, DigitalThread                  -> Entity
data_exchanged_with : Process, Organization, DigitalThread              -> Entity
interoperates_with  : Organization                                      -> Organization
links               : DigitalThread                                    -> Process, Organization, SoftwareDefinedAsset
conforms_to         : Solution, Process, AICapability, SoftwareDefinedAsset -> Standard
governed_by         : Process, Organization, Solution                  -> Standard, RegulatoryBody
issued_by           : Standard                                          -> StandardsBody, ClassificationSociety, RegulatoryBody
collaborates_with   : Organization                                      -> Organization
competes_with       : Organization, Solution                           -> Entity
supplies            : Manufacturer                                      -> SoftwareDefinedAsset, Shipyard
classifies          : ClassificationSociety                             -> Shipyard, SoftwareDefinedAsset, Process
stakeholder_in      : Organization, Person                              -> Process, Solution, Standard
documented_in       : Entity                                            -> Document
mentions            : Document                                          -> Entity
authored_by         : Document, AICapability                            -> Person, Organization
published_by        : Document                                          -> Organization
release_of          : Event                                             -> AICapability, Solution
announced_at        : Event                                             -> Place
relates_to          : Entity                                            -> Entity
```
33 properties total. **Note:** `supplies` deliberately omits `:Product` (not a class in this schema) — resolving the dangling reference flagged in spec §4.

---

## Task 1: Failing validity + round-trip test

**Files:**
- Create: `tests/test_ontokg_shipai.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ontokg_shipai.py` with exactly this content:

```python
from pathlib import Path

import pytest
from rdflib import RDF, RDFS, Graph

from mykg.base_schema import parse_base_schema
from mykg.schema_validator import validate_schema_ttl

TTL_PATH = Path(__file__).parent.parent / "src" / "mykg" / "data" / "ontokg-shipai.ttl"

# --- Canonical schema definition (single source of truth for the tests) ------
# class -> parent (None for the root)
EXPECTED_CLASSES = {
    "Entity": None,
    "Organization": "Entity",
    "Shipyard": "Organization",
    "ShipOwner": "Organization",
    "ClassificationSociety": "Organization",
    "Manufacturer": "Organization",
    "ResearchOrg": "Organization",
    "TechVendor": "Organization",
    "RegulatoryBody": "Organization",
    "StandardsBody": "Organization",
    "Person": "Entity",
    "AICapability": "Entity",
    "FoundationModel": "AICapability",
    "SpatialAI": "AICapability",
    "RoboticSystem": "AICapability",
    "DigitalTwin": "AICapability",
    "Simulation": "AICapability",
    "GenerativeDesign": "AICapability",
    "AIMethod": "AICapability",
    "Solution": "Entity",
    "SoftwareDefinedAsset": "Entity",
    "Process": "Entity",
    "DesignProcess": "Process",
    "ManufacturingProcess": "Process",
    "AssemblyProcess": "Process",
    "DigitalThread": "Entity",
    "Standard": "Entity",
    "ClassRule": "Standard",
    "Regulation": "Standard",
    "ReferenceArchitecture": "Standard",
    "TechnicalStandard": "Standard",
    "Document": "Entity",
    "ResearchPaper": "Document",
    "Report": "Document",
    "Whitepaper": "Document",
    "Benchmark": "Entity",
    "Dataset": "Entity",
    "Deliverable": "Entity",
    "Concept": "Entity",
    "Event": "Entity",
    "Place": "Entity",
}

# property -> (set of domain classes, set of range classes)
EXPECTED_PROPERTIES = {
    "develops": ({"Organization", "Person"}, {"AICapability", "Solution"}),
    "researches": ({"Organization", "Person"}, {"AICapability", "Concept"}),
    "builds_on": ({"AICapability"}, {"AICapability"}),
    "supersedes": ({"AICapability", "Solution", "Standard"}, {"Entity"}),
    "trained_on": ({"FoundationModel"}, {"Dataset"}),
    "benchmarked_on": ({"AICapability", "Solution"}, {"Benchmark"}),
    "applies": ({"Solution"}, {"AICapability"}),
    "applied_in": ({"Solution", "AICapability"}, {"Process"}),
    "automates": ({"AICapability", "Solution"}, {"Process"}),
    "simulates": ({"Simulation", "DigitalTwin"}, {"SoftwareDefinedAsset", "Process"}),
    "twin_of": ({"DigitalTwin"}, {"SoftwareDefinedAsset", "Process"}),
    "validates": ({"Simulation"}, {"DesignProcess", "ManufacturingProcess", "Deliverable"}),
    "precedes": ({"Process"}, {"Process"}),
    "produces": ({"Process"}, {"Deliverable", "SoftwareDefinedAsset"}),
    "integrates_with": ({"Solution", "Process", "DigitalThread"}, {"Entity"}),
    "data_exchanged_with": ({"Process", "Organization", "DigitalThread"}, {"Entity"}),
    "interoperates_with": ({"Organization"}, {"Organization"}),
    "links": ({"DigitalThread"}, {"Process", "Organization", "SoftwareDefinedAsset"}),
    "conforms_to": (
        {"Solution", "Process", "AICapability", "SoftwareDefinedAsset"},
        {"Standard"},
    ),
    "governed_by": ({"Process", "Organization", "Solution"}, {"Standard", "RegulatoryBody"}),
    "issued_by": ({"Standard"}, {"StandardsBody", "ClassificationSociety", "RegulatoryBody"}),
    "collaborates_with": ({"Organization"}, {"Organization"}),
    "competes_with": ({"Organization", "Solution"}, {"Entity"}),
    "supplies": ({"Manufacturer"}, {"SoftwareDefinedAsset", "Shipyard"}),
    "classifies": ({"ClassificationSociety"}, {"Shipyard", "SoftwareDefinedAsset", "Process"}),
    "stakeholder_in": ({"Organization", "Person"}, {"Process", "Solution", "Standard"}),
    "documented_in": ({"Entity"}, {"Document"}),
    "mentions": ({"Document"}, {"Entity"}),
    "authored_by": ({"Document", "AICapability"}, {"Person", "Organization"}),
    "published_by": ({"Document"}, {"Organization"}),
    "release_of": ({"Event"}, {"AICapability", "Solution"}),
    "announced_at": ({"Event"}, {"Place"}),
    "relates_to": ({"Entity"}, {"Entity"}),
}


def _local(uri) -> str:
    return str(uri).split("/")[-1].split("#")[-1]


@pytest.fixture(scope="module")
def ttl_text() -> str:
    assert TTL_PATH.exists(), f"schema file missing: {TTL_PATH}"
    return TTL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def graph(ttl_text) -> Graph:
    g = Graph()
    g.parse(data=ttl_text, format="turtle")
    return g


def test_schema_is_valid(ttl_text):
    result = validate_schema_ttl(ttl_text)
    assert result.valid, result.errors


def test_parses_through_base_schema(ttl_text):
    parsed = parse_base_schema(ttl_text)
    assert "Entity" in parsed["locked_classes"]
    assert parsed["locked_properties"], "no object properties parsed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ontokg_shipai.py -v -p no:cov`
Expected: FAIL — `AssertionError: schema file missing: .../ontokg-shipai.ttl` (the TTL does not exist yet).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_ontokg_shipai.py
git commit -m "test: add failing validation test for ontokg-shipai schema"
```

---

## Task 2: Create the schema TTL

**Files:**
- Create: `src/mykg/data/ontokg-shipai.ttl`

- [ ] **Step 1: Create the TTL file**

Create `src/mykg/data/ontokg-shipai.ttl` with exactly this content:

```turtle
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix :     <http://mykg.local/ontokg#> .

# OntoKG-ShipAI: a locked base schema (TBox) for a knowledge graph mapping the
# research landscape of INDUSTRIAL AI IN SHIPBUILDING — design & manufacturing
# stage only (operations are out of scope).
#
# Standalone schema (separate from ontokg-strategy.ttl). Same namespace and
# :Entity root as the other mykg schemas so it round-trips through
# parse_base_schema. Classes carry no attributes; Pass-1 induction adds them.
# Trends and maturity (momentum, TRL, adoption, openness) are induced
# attributes, not classes. Digital-thread / interoperability semantics are
# carried by relations.
#
# Usage:
#   mykg extract-graph <dir> --base-schema src/mykg/data/ontokg-shipai.ttl
#   mykg extract-graph <dir> --append --session <name> \
#       --base-schema src/mykg/data/ontokg-shipai.ttl --obsidian-vault
#
# Design spec: docs/superpowers/specs/2026-07-28-industrial-ai-shipbuilding-schema-design.md

# --- Root -------------------------------------------------------------------
:Entity a rdfs:Class .

# --- Actors -----------------------------------------------------------------
:Organization a rdfs:Class ; rdfs:subClassOf :Entity .
:Shipyard a rdfs:Class ; rdfs:subClassOf :Organization .
:ShipOwner a rdfs:Class ; rdfs:subClassOf :Organization .
:ClassificationSociety a rdfs:Class ; rdfs:subClassOf :Organization .
:Manufacturer a rdfs:Class ; rdfs:subClassOf :Organization .          # equipment / component supplier
:ResearchOrg a rdfs:Class ; rdfs:subClassOf :Organization .           # lab / academia / institute
:TechVendor a rdfs:Class ; rdfs:subClassOf :Organization .            # AI / software solution provider
:RegulatoryBody a rdfs:Class ; rdfs:subClassOf :Organization .
:StandardsBody a rdfs:Class ; rdfs:subClassOf :Organization .

:Person a rdfs:Class ; rdfs:subClassOf :Entity .                      # researcher / author / decision maker

# --- AI capabilities (what AI can do) ---------------------------------------
:AICapability a rdfs:Class ; rdfs:subClassOf :Entity .
:FoundationModel a rdfs:Class ; rdfs:subClassOf :AICapability .        # frontier vs open-weight = induced attrs
:SpatialAI a rdfs:Class ; rdfs:subClassOf :AICapability .             # 3D perception, SLAM, world models
:RoboticSystem a rdfs:Class ; rdfs:subClassOf :AICapability .         # autonomous mfg / assembly robotics
:DigitalTwin a rdfs:Class ; rdfs:subClassOf :AICapability .           # live, synced virtual replica
:Simulation a rdfs:Class ; rdfs:subClassOf :AICapability .            # predictive / offline virtual execution
:GenerativeDesign a rdfs:Class ; rdfs:subClassOf :AICapability .      # generative / optimization design AI
:AIMethod a rdfs:Class ; rdfs:subClassOf :AICapability .              # general fallback

# --- Applied solutions & software-defined assets ----------------------------
:Solution a rdfs:Class ; rdfs:subClassOf :Entity .                    # deployed system applying capabilities
:SoftwareDefinedAsset a rdfs:Class ; rdfs:subClassOf :Entity .        # asset/equipment/block/cell in software

# --- Shipbuilding processes & digital thread --------------------------------
:Process a rdfs:Class ; rdfs:subClassOf :Entity .
:DesignProcess a rdfs:Class ; rdfs:subClassOf :Process .
:ManufacturingProcess a rdfs:Class ; rdfs:subClassOf :Process .
:AssemblyProcess a rdfs:Class ; rdfs:subClassOf :Process .
:DigitalThread a rdfs:Class ; rdfs:subClassOf :Entity .               # integration backbone

# --- Normative (standards & rules) ------------------------------------------
:Standard a rdfs:Class ; rdfs:subClassOf :Entity .
:ClassRule a rdfs:Class ; rdfs:subClassOf :Standard .                 # classification-society rule
:Regulation a rdfs:Class ; rdfs:subClassOf :Standard .               # statutory / regulatory instrument
:ReferenceArchitecture a rdfs:Class ; rdfs:subClassOf :Standard .
:TechnicalStandard a rdfs:Class ; rdfs:subClassOf :Standard .         # ISO and other technical standards

# --- Supporting -------------------------------------------------------------
:Document a rdfs:Class ; rdfs:subClassOf :Entity .
:ResearchPaper a rdfs:Class ; rdfs:subClassOf :Document .
:Report a rdfs:Class ; rdfs:subClassOf :Document .
:Whitepaper a rdfs:Class ; rdfs:subClassOf :Document .
:Benchmark a rdfs:Class ; rdfs:subClassOf :Entity .                   # evaluation benchmark (maturity evidence)
:Dataset a rdfs:Class ; rdfs:subClassOf :Entity .
:Deliverable a rdfs:Class ; rdfs:subClassOf :Entity .                 # process output / work product
:Concept a rdfs:Class ; rdfs:subClassOf :Entity .                     # theme / approach / strategy
:Event a rdfs:Class ; rdfs:subClassOf :Entity .                       # release, milestone, conference
:Place a rdfs:Class ; rdfs:subClassOf :Entity .

# --- Relations (object properties) ------------------------------------------
# Research landscape / development
:develops a rdf:Property ; rdfs:domain :Organization, :Person ; rdfs:range :AICapability, :Solution .
:researches a rdf:Property ; rdfs:domain :Organization, :Person ; rdfs:range :AICapability, :Concept .
:builds_on a rdf:Property ; rdfs:domain :AICapability ; rdfs:range :AICapability .
:supersedes a rdf:Property ; rdfs:domain :AICapability, :Solution, :Standard ; rdfs:range :Entity .
:trained_on a rdf:Property ; rdfs:domain :FoundationModel ; rdfs:range :Dataset .
:benchmarked_on a rdf:Property ; rdfs:domain :AICapability, :Solution ; rdfs:range :Benchmark .

# Applied solutions / usage
:applies a rdf:Property ; rdfs:domain :Solution ; rdfs:range :AICapability .
:applied_in a rdf:Property ; rdfs:domain :Solution, :AICapability ; rdfs:range :Process .
:automates a rdf:Property ; rdfs:domain :AICapability, :Solution ; rdfs:range :Process .
:simulates a rdf:Property ; rdfs:domain :Simulation, :DigitalTwin ; rdfs:range :SoftwareDefinedAsset, :Process .
:twin_of a rdf:Property ; rdfs:domain :DigitalTwin ; rdfs:range :SoftwareDefinedAsset, :Process .
:validates a rdf:Property ; rdfs:domain :Simulation ; rdfs:range :DesignProcess, :ManufacturingProcess, :Deliverable .

# Process / digital thread / interoperability
:precedes a rdf:Property ; rdfs:domain :Process ; rdfs:range :Process .
:produces a rdf:Property ; rdfs:domain :Process ; rdfs:range :Deliverable, :SoftwareDefinedAsset .
:integrates_with a rdf:Property ; rdfs:domain :Solution, :Process, :DigitalThread ; rdfs:range :Entity .
:data_exchanged_with a rdf:Property ; rdfs:domain :Process, :Organization, :DigitalThread ; rdfs:range :Entity .
:interoperates_with a rdf:Property ; rdfs:domain :Organization ; rdfs:range :Organization .
:links a rdf:Property ; rdfs:domain :DigitalThread ; rdfs:range :Process, :Organization, :SoftwareDefinedAsset .

# Normative / standards
:conforms_to a rdf:Property ; rdfs:domain :Solution, :Process, :AICapability, :SoftwareDefinedAsset ; rdfs:range :Standard .
:governed_by a rdf:Property ; rdfs:domain :Process, :Organization, :Solution ; rdfs:range :Standard, :RegulatoryBody .
:issued_by a rdf:Property ; rdfs:domain :Standard ; rdfs:range :StandardsBody, :ClassificationSociety, :RegulatoryBody .

# Actors / stakeholders
:collaborates_with a rdf:Property ; rdfs:domain :Organization ; rdfs:range :Organization .
:competes_with a rdf:Property ; rdfs:domain :Organization, :Solution ; rdfs:range :Entity .
:supplies a rdf:Property ; rdfs:domain :Manufacturer ; rdfs:range :SoftwareDefinedAsset, :Shipyard .
:classifies a rdf:Property ; rdfs:domain :ClassificationSociety ; rdfs:range :Shipyard, :SoftwareDefinedAsset, :Process .
:stakeholder_in a rdf:Property ; rdfs:domain :Organization, :Person ; rdfs:range :Process, :Solution, :Standard .

# Provenance / evidence
:documented_in a rdf:Property ; rdfs:domain :Entity ; rdfs:range :Document .
:mentions a rdf:Property ; rdfs:domain :Document ; rdfs:range :Entity .
:authored_by a rdf:Property ; rdfs:domain :Document, :AICapability ; rdfs:range :Person, :Organization .
:published_by a rdf:Property ; rdfs:domain :Document ; rdfs:range :Organization .
:release_of a rdf:Property ; rdfs:domain :Event ; rdfs:range :AICapability, :Solution .
:announced_at a rdf:Property ; rdfs:domain :Event ; rdfs:range :Place .
:relates_to a rdf:Property ; rdfs:domain :Entity ; rdfs:range :Entity .
```

- [ ] **Step 2: Run the Task 1 tests to verify they now pass**

Run: `uv run pytest tests/test_ontokg_shipai.py -v -p no:cov`
Expected: PASS — `test_schema_is_valid` and `test_parses_through_base_schema` both green.

- [ ] **Step 3: Commit**

```bash
git add src/mykg/data/ontokg-shipai.ttl
git commit -m "feat: add ontokg-shipai base schema (industrial AI in shipbuilding)"
```

---

## Task 3: Lock the class set

**Files:**
- Modify: `tests/test_ontokg_shipai.py` (append test functions)

- [ ] **Step 1: Write the failing test**

Append these functions to `tests/test_ontokg_shipai.py`:

```python
def test_class_set_is_exact(graph):
    declared = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDFS.Class))}
    assert declared == set(EXPECTED_CLASSES), {
        "missing": set(EXPECTED_CLASSES) - declared,
        "unexpected": declared - set(EXPECTED_CLASSES),
    }


def test_class_parents_match(graph):
    for cls, parent in EXPECTED_CLASSES.items():
        subj = next(
            s for s, _, _ in graph.triples((None, RDF.type, RDFS.Class)) if _local(s) == cls
        )
        parent_node = graph.value(subj, RDFS.subClassOf)
        got = _local(parent_node) if parent_node is not None else None
        assert got == parent, f"{cls}: expected parent {parent}, got {got}"
```

- [ ] **Step 2: Run to verify it passes (TTL already satisfies it)**

Run: `uv run pytest tests/test_ontokg_shipai.py::test_class_set_is_exact tests/test_ontokg_shipai.py::test_class_parents_match -v -p no:cov`
Expected: PASS. (If either FAILS, the TTL from Task 2 has a class-name or parent typo — fix the TTL to match `EXPECTED_CLASSES`, do not weaken the test.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_ontokg_shipai.py
git commit -m "test: lock ontokg-shipai class set and hierarchy"
```

---

## Task 4: Lock the relation set + no-dangling-term guard

**Files:**
- Modify: `tests/test_ontokg_shipai.py` (append test functions)

- [ ] **Step 1: Write the test**

Append these functions to `tests/test_ontokg_shipai.py`:

```python
def test_property_set_is_exact(graph):
    declared = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDF.Property))}
    assert declared == set(EXPECTED_PROPERTIES), {
        "missing": set(EXPECTED_PROPERTIES) - declared,
        "unexpected": declared - set(EXPECTED_PROPERTIES),
    }


def test_property_domains_and_ranges_match(graph):
    for prop, (exp_domains, exp_ranges) in EXPECTED_PROPERTIES.items():
        subj = next(
            s for s, _, _ in graph.triples((None, RDF.type, RDF.Property)) if _local(s) == prop
        )
        domains = {_local(o) for o in graph.objects(subj, RDFS.domain)}
        ranges = {_local(o) for o in graph.objects(subj, RDFS.range)}
        assert domains == exp_domains, f"{prop} domains: {domains} != {exp_domains}"
        assert ranges == exp_ranges, f"{prop} ranges: {ranges} != {exp_ranges}"


def test_no_dangling_terms(graph):
    # Every class referenced by subClassOf / domain / range must be declared.
    declared = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDFS.Class))}
    referenced = set()
    for _, _, o in graph.triples((None, RDFS.subClassOf, None)):
        referenced.add(_local(o))
    for _, _, o in graph.triples((None, RDFS.domain, None)):
        referenced.add(_local(o))
    for _, _, o in graph.triples((None, RDFS.range, None)):
        referenced.add(_local(o))
    referenced.discard("Literal")  # rdfs:Literal is a datatype, not a class
    undeclared = referenced - declared
    assert not undeclared, f"undeclared terms referenced: {undeclared}"
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/test_ontokg_shipai.py::test_property_set_is_exact tests/test_ontokg_shipai.py::test_property_domains_and_ranges_match tests/test_ontokg_shipai.py::test_no_dangling_terms -v -p no:cov`
Expected: PASS. `test_no_dangling_terms` specifically proves `:Product` was NOT left in `:supplies`. (If a relation test FAILS, fix the TTL's `rdfs:domain`/`rdfs:range` for that property to match `EXPECTED_PROPERTIES` — do not weaken the test.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_ontokg_shipai.py
git commit -m "test: lock ontokg-shipai relations and add no-dangling-term guard"
```

---

## Task 5: Competency-question coverage test

**Files:**
- Modify: `tests/test_ontokg_shipai.py` (append test function)

This test ties the schema back to the 15 competency questions in spec §6: each CQ is answerable only if its required classes and relations exist. It fails loudly if a future edit removes a term a CQ depends on.

- [ ] **Step 1: Write the test**

Append this to `tests/test_ontokg_shipai.py`:

```python
# Each competency question (spec section 6) -> (required classes, required properties)
COMPETENCY_REQUIREMENTS = {
    "CQ01_who_develops_capabilities": (
        {"ResearchOrg", "TechVendor", "AICapability"}, {"develops"},
    ),
    "CQ02_capability_lineage": ({"AICapability"}, {"builds_on"}),
    "CQ03_open_vs_frontier_models": ({"FoundationModel"}, {"develops"}),
    "CQ04_direction_of_travel": ({"AICapability", "Event"}, {"release_of", "supersedes"}),
    "CQ05_maturity_of_applied_capabilities": ({"AICapability", "Process"}, {"applied_in"}),
    "CQ06_benchmarks_and_datasets": (
        {"AICapability", "Solution", "Benchmark", "Dataset", "FoundationModel"},
        {"benchmarked_on", "trained_on"},
    ),
    "CQ07_solutions_into_processes": (
        {"Solution", "AICapability", "Process"}, {"applies", "applied_in"},
    ),
    "CQ08_automation_coverage": ({"AICapability", "Solution", "Process"}, {"automates"}),
    "CQ09_twins_sims_span_design_and_mfg": (
        {"DigitalTwin", "Simulation", "DesignProcess", "ManufacturingProcess", "SoftwareDefinedAsset"},
        {"applied_in", "simulates"},
    ),
    "CQ10_live_twin_vs_predictive_sim": (
        {"SoftwareDefinedAsset", "DigitalTwin", "Simulation", "Deliverable"},
        {"twin_of", "simulates", "validates"},
    ),
    "CQ11_digital_thread_links_stakeholders": (
        {"DigitalThread", "Shipyard", "ShipOwner", "ClassificationSociety", "Manufacturer"},
        {"links", "data_exchanged_with"},
    ),
    "CQ12_interoperability_gaps": (
        {"Process", "Organization"}, {"integrates_with", "data_exchanged_with"},
    ),
    "CQ13_conformance_and_gaps": (
        {"Solution", "Process", "SoftwareDefinedAsset", "Standard", "ClassRule",
         "Regulation", "TechnicalStandard"},
        {"conforms_to"},
    ),
    "CQ14_who_issues_standards": (
        {"Standard", "ClassificationSociety", "StandardsBody"}, {"issued_by"},
    ),
    "CQ15_full_capability_profile": (
        {"AICapability", "SpatialAI", "RoboticSystem", "Process", "Standard", "Organization"},
        {"develops", "applied_in", "governed_by"},
    ),
}


def test_competency_questions_are_answerable(graph):
    classes = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDFS.Class))}
    props = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDF.Property))}
    for cq, (need_classes, need_props) in COMPETENCY_REQUIREMENTS.items():
        missing_c = need_classes - classes
        missing_p = need_props - props
        assert not missing_c, f"{cq}: missing classes {missing_c}"
        assert not missing_p, f"{cq}: missing properties {missing_p}"


def test_all_fifteen_competency_questions_present():
    assert len(COMPETENCY_REQUIREMENTS) == 15
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/test_ontokg_shipai.py::test_competency_questions_are_answerable tests/test_ontokg_shipai.py::test_all_fifteen_competency_questions_present -v -p no:cov`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ontokg_shipai.py
git commit -m "test: prove ontokg-shipai answers all 15 competency questions"
```

---

## Task 6: Full-suite green + smoke run

**Files:** none (verification only)

- [ ] **Step 1: Run the whole new test module**

Run: `uv run pytest tests/test_ontokg_shipai.py -v -p no:cov`
Expected: PASS — all tests (validity, round-trip, class set, hierarchy, property set, domains/ranges, no-dangling, competency coverage, count).

- [ ] **Step 2: Confirm nothing else broke**

Run: `uv run pytest tests/test_base_schema.py tests/test_schema_validator.py tests/test_ontokg_base.py -q -p no:cov`
Expected: PASS — the shared schema utilities are unaffected (this schema adds a file and a test module only).

- [ ] **Step 3: Smoke-validate the shipped file directly**

Run:
```bash
uv run python -c "from pathlib import Path; from mykg.schema_validator import validate_schema_ttl; r = validate_schema_ttl(Path('src/mykg/data/ontokg-shipai.ttl').read_text(encoding='utf-8')); print('valid:', r.valid, 'errors:', r.errors)"
```
Expected: `valid: True errors: []`

- [ ] **Step 4: Final commit (if any lint fixups were needed)**

```bash
git add -A
git commit -m "chore: finalize ontokg-shipai schema and tests" --allow-empty
```

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- Spec §3 (class hierarchy) → Task 2 TTL + Task 3 class-lock tests. All 41 classes present.
- Spec §4 (relations) → Task 2 TTL + Task 4 relation-lock tests. All 33 properties present; `:Product` dropped from `:supplies` and guarded by `test_no_dangling_terms`.
- Spec §2 (conventions/compatibility) → Task 1 `test_parses_through_base_schema`, Task 6 smoke run.
- Spec §5 (emergent attributes) → honored by declaring no attributes in the TTL; nothing to test beyond absence (class-lock test would flag stray attribute classes).
- Spec §6 (15 competency questions) → Task 5 coverage test.
- Spec §7 (validation/acceptance) → Task 1 validity, Task 4 no-dangling, Task 6 smoke + suite.
- Spec §8 (non-goals) → no `:Trend` class and no operations entities appear in `EXPECTED_CLASSES`; the exact-set test enforces their absence.

**2. Placeholder scan** — no TBD/TODO/"add error handling"/"similar to Task N". Every code and TTL block is complete and literal.

**3. Type consistency** — class and property names are identical across the TTL (Task 2), `EXPECTED_CLASSES`/`EXPECTED_PROPERTIES` (Task 1), and `COMPETENCY_REQUIREMENTS` (Task 5): e.g. `SoftwareDefinedAsset`, `data_exchanged_with`, `twin_of`, `applied_in` are spelled the same everywhere. `_local()` in the test mirrors `_local()` in `base_schema.py`. Test commands consistently use `uv run pytest ... -p no:cov` to bypass the repo's default `--cov` addopts for fast targeted runs.
