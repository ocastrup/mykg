#!/usr/bin/env python3
"""OntoKG reference schema — single source of truth, generator, and validator.

Generates docs/examples/ontokg/ontokg-base.ttl and ontokg-mapping.md from the
VOCAB below, and validates the committed .ttl by round-tripping it through
mykg's real parse_base_schema. Reconstructed from OntoKG (arXiv:2604.02618)
Appendix B; see the design spec at
docs/superpowers/specs/2026-07-11-ontokg-reference-schema-design.md.
"""

from __future__ import annotations

CATEGORIES = [
    "Person", "Organization", "Work", "Place",
    "Science", "Event", "Knowledge", "Product",
]

# Raw per-category tag lists, verbatim from spec §5 (Appendix B). Test-only.
APPENDIX_B = {
    "Person": ["entertainment", "creativity", "education", "politics", "sports",
               "religion", "finance", "military", "society", "crime", "family",
               "award", "healthcare", "legal", "culture", "government",
               "technology", "food"],
    "Organization": ["location", "affiliation", "education", "international",
                     "government", "corporation", "culture", "religion",
                     "politics", "sports", "broadcast", "finance", "society",
                     "healthcare", "military", "legal", "transportation",
                     "entertainment", "award", "food"],
    "Work": ["literature", "film", "television", "art", "comics", "periodical",
             "revenue", "museum", "music", "sports", "military", "religion",
             "character", "culture", "award", "authorship", "location"],
    "Place": ["dwelling", "commercial", "culture", "religion", "infrastructure",
              "transportation", "government", "administration", "sports",
              "heritage", "education", "nature", "finance", "military",
              "entertainment", "healthcare", "affiliation", "architecture",
              "food"],
    "Science": ["element", "compound", "mineral", "geology", "disease", "gene",
                "biofunction", "protein", "pharmaceutical", "anatomy",
                "organism", "botany", "astronomy", "clinical", "healthcare",
                "education", "biosystem", "clinical_trial", "cell_lineage",
                "genomics"],
    "Event": ["military", "conference", "exhibition", "disaster", "violence",
              "politics", "award", "sports", "society", "legal", "entertainment",
              "education", "religion", "transportation"],
    "Knowledge": ["language", "theorem", "algorithm", "specification", "abstract",
                  "position", "law", "unit", "field", "phenomenon", "publication",
                  "reference", "name", "religion", "jurisdiction"],
    "Product": ["cloud", "aircraft", "vehicle", "computer", "software", "game",
                "device", "military", "food", "tool", "currency", "fiction",
                "material", "artifact", "brand", "entertainment",
                "transportation", "technology", "award"],
}

# Intrinsic modules → (PascalCase subclass name, parent category).
# A tag is intrinsic when it names a *kind of* the parent entity (is-a noun).
INTRINSIC = {
    "corporation": ("Corporation", "Organization"),
    "literature": ("Literature", "Work"),
    "film": ("Film", "Work"),
    "television": ("Television", "Work"),
    "art": ("Art", "Work"),
    "comics": ("Comics", "Work"),
    "periodical": ("Periodical", "Work"),
    "music": ("Music", "Work"),
    "character": ("Character", "Work"),
    "dwelling": ("Dwelling", "Place"),
    "commercial": ("Commercial", "Place"),
    "infrastructure": ("Infrastructure", "Place"),
    "administration": ("Administration", "Place"),
    "heritage": ("Heritage", "Place"),
    "nature": ("Nature", "Place"),
    "architecture": ("Architecture", "Place"),
    "element": ("Element", "Science"),
    "compound": ("Compound", "Science"),
    "mineral": ("Mineral", "Science"),
    "geology": ("Geology", "Science"),
    "disease": ("Disease", "Science"),
    "gene": ("Gene", "Science"),
    "biofunction": ("Biofunction", "Science"),
    "protein": ("Protein", "Science"),
    "pharmaceutical": ("Pharmaceutical", "Science"),
    "anatomy": ("Anatomy", "Science"),
    "organism": ("Organism", "Science"),
    "botany": ("Botany", "Science"),
    "biosystem": ("Biosystem", "Science"),
    "clinical_trial": ("ClinicalTrial", "Science"),
    "cell_lineage": ("CellLineage", "Science"),
    "conference": ("Conference", "Event"),
    "exhibition": ("Exhibition", "Event"),
    "disaster": ("Disaster", "Event"),
    "language": ("Language", "Knowledge"),
    "theorem": ("Theorem", "Knowledge"),
    "algorithm": ("Algorithm", "Knowledge"),
    "specification": ("Specification", "Knowledge"),
    "abstract": ("Abstract", "Knowledge"),
    "law": ("Law", "Knowledge"),
    "unit": ("Unit", "Knowledge"),
    "phenomenon": ("Phenomenon", "Knowledge"),
    "publication": ("Publication", "Knowledge"),
    "reference": ("Reference", "Knowledge"),
    "name": ("Name", "Knowledge"),
    "cloud": ("Cloud", "Product"),
    "aircraft": ("Aircraft", "Product"),
    "vehicle": ("Vehicle", "Product"),
    "computer": ("Computer", "Product"),
    "software": ("Software", "Product"),
    "game": ("Game", "Product"),
    "device": ("Device", "Product"),
    "tool": ("Tool", "Product"),
    "currency": ("Currency", "Product"),
    "fiction": ("Fiction", "Product"),
    "material": ("Material", "Product"),
    "artifact": ("Artifact", "Product"),
    "brand": ("Brand", "Product"),
}

# Relational modules → (authority, domain categories). "A" = paper-authoritative
# (spec §4); "I" = inferred. Domains = every category the tag appears under in
# Appendix B (hierarchy is the exception: spec §8.3, spans all 8).
RELATIONAL = {
    "entertainment": ("A", ["Person", "Organization", "Place", "Event", "Product"]),
    "creativity": ("I", ["Person"]),
    "education": ("A", ["Person", "Organization", "Place", "Science", "Event"]),
    "politics": ("A", ["Person", "Organization", "Event"]),
    "sports": ("A", ["Person", "Organization", "Work", "Place", "Event"]),
    "religion": ("A", ["Person", "Organization", "Work", "Place", "Event", "Knowledge"]),
    "finance": ("A", ["Person", "Organization", "Place"]),
    "military": ("A", ["Person", "Organization", "Work", "Place", "Event", "Product"]),
    "society": ("A", ["Person", "Organization", "Event"]),
    "crime": ("I", ["Person"]),
    "family": ("A", ["Person"]),
    "award": ("A", ["Person", "Organization", "Work", "Event", "Product"]),
    "healthcare": ("A", ["Person", "Organization", "Place", "Science"]),
    "legal": ("A", ["Person", "Organization", "Event"]),
    "culture": ("A", ["Person", "Organization", "Work", "Place"]),
    "government": ("A", ["Person", "Organization", "Place"]),
    "technology": ("A", ["Person", "Product"]),
    "food": ("A", ["Person", "Organization", "Place", "Product"]),
    "location": ("A", ["Organization", "Work"]),
    "affiliation": ("A", ["Organization", "Place"]),
    "international": ("I", ["Organization"]),
    "broadcast": ("I", ["Organization"]),
    "transportation": ("A", ["Organization", "Place", "Event", "Product"]),
    "revenue": ("I", ["Work"]),
    "museum": ("I", ["Work"]),
    "authorship": ("A", ["Work"]),
    "astronomy": ("I", ["Science"]),
    "clinical": ("I", ["Science"]),
    "genomics": ("A", ["Science"]),
    "violence": ("I", ["Event"]),
    "position": ("I", ["Knowledge"]),
    "field": ("I", ["Knowledge"]),
    "jurisdiction": ("I", ["Knowledge"]),
    "hierarchy": ("A", ["Person", "Organization", "Work", "Place",
                        "Science", "Event", "Knowledge", "Product"]),
}

NS = "http://mykg.local/ontokg#"

_PREAMBLE = (
    "@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    f"@prefix :     <{NS}> .\n"
)


def build_ttl() -> str:
    """Render VOCAB as an RDFS Turtle document parse_base_schema can load."""
    lines = [
        _PREAMBLE,
        "# OntoKG reference schema for mykg — reconstructed from arXiv:2604.02618",
        "# Appendix B. Generated by check_ontokg_base.py --generate; do not edit by hand.",
        "",
        ":Entity a rdfs:Class .",
    ]
    for cat in CATEGORIES:
        lines.append(f":{cat} a rdfs:Class ; rdfs:subClassOf :Entity .")

    lines += ["", "# Intrinsic modules → subclasses (no attributes; induction adds them)."]
    for tag, (cls, parent) in INTRINSIC.items():
        lines.append(f":{cls} a rdfs:Class ; rdfs:subClassOf :{parent} .  # {tag}")

    lines += ["", "# Relational modules → object properties (range :Entity)."]
    for tag, (auth, domains) in RELATIONAL.items():
        dom = ", ".join(f":{d}" for d in domains)
        lines.append(
            f":{tag} a rdf:Property ; rdfs:domain {dom} ; rdfs:range :Entity .  # {auth}"
        )

    return "\n".join(lines) + "\n"
