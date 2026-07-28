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
    # Presence check only: asserts every class/property a CQ needs is declared.
    # The structural guarantee that those properties actually connect the right
    # classes (correct rdfs:domain/rdfs:range) is enforced by
    # test_property_domains_and_ranges_match.
    classes = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDFS.Class))}
    props = {_local(s) for s, _, _ in graph.triples((None, RDF.type, RDF.Property))}
    for cq, (need_classes, need_props) in COMPETENCY_REQUIREMENTS.items():
        missing_c = need_classes - classes
        missing_p = need_props - props
        assert not missing_c, f"{cq}: missing classes {missing_c}"
        assert not missing_p, f"{cq}: missing properties {missing_p}"


def test_all_fifteen_competency_questions_present():
    assert len(COMPETENCY_REQUIREMENTS) == 15
