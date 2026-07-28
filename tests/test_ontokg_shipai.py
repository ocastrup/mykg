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
