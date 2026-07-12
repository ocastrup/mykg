# OntoKG Reference Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reusable OntoKG-derived reference schema (`ontokg-base.ttl`) plus a companion mapping doc and a validation script, so `mykg extract-graph --base-schema` can seed its Pass-1 induction from a principled published ontology — with **zero pipeline code changes**.

**Architecture:** All three deliverables derive from **one Python source-of-truth** (`VOCAB` = `CATEGORIES` + `INTRINSIC` + `RELATIONAL` dicts) living inside the single deliverable script `check_ontokg_base.py`. The script both **generates** the `.ttl` and `.md` artifacts (`--generate`) and **validates** the committed `.ttl` by round-tripping it through mykg's real `parse_base_schema` (default mode). This eliminates three-way drift between the TTL, the mapping table, and the validator — the tedious, error-prone part (unioning multi-category domains for ~34 relational properties) is done by code, not by hand.

**Tech Stack:** Python 3, `rdflib` (already a dependency, via `mykg.base_schema`), `pytest`, `uv`. No new dependencies.

## Global Constraints

- **No pipeline code changes.** Do not touch `parse_base_schema`, Pass 1, Pass 2, or the CLI. All work is confined to three new files under `docs/examples/ontokg/`. (Spec §1, §9)
- **Deliverable locations (exact):**
  - `docs/examples/ontokg/ontokg-base.ttl`
  - `docs/examples/ontokg/ontokg-mapping.md`
  - `docs/examples/ontokg/check_ontokg_base.py`
  - Test: `tests/test_ontokg_base.py`
- **RDF namespace:** `http://mykg.local/ontokg#` (default `:` prefix). (Spec §4 worked fragment)
- **Naming:** categories & intrinsic modules → **PascalCase** classes; relational modules → **snake_case** properties (keep the tag verbatim). Compound tags map `clinical_trial → ClinicalTrial`, `cell_lineage → CellLineage`. (Spec §4)
- **Relational-edge range is always `:Entity`.** (Spec §3, decision locked)
- **Every mapping-doc row is marked `A` (authoritative) or `I` (inferred).** Only the 22 relational modules enumerated in §4 of the spec are `A`; everything else is `I`. (Spec §4)
- **This is a reconstruction from the paper's Appendix B**, not the (inaccessible) OntoKG repo. Counts differ from the Wikidata instantiation's 94/56/38 and that is expected. (Spec §2.3, §8.5)

---

## File Structure

- **`docs/examples/ontokg/check_ontokg_base.py`** (deliverable #3, and the single source of truth)
  - `CATEGORIES: list[str]` — the 8 top categories.
  - `INTRINSIC: dict[str, tuple[str, str]]` — `module → (PascalCaseClassName, parent_category)`.
  - `RELATIONAL: dict[str, tuple[str, list[str]]]` — `module → (authority, [domain categories])`.
  - `APPENDIX_B: dict[str, list[str]]` — the raw per-category tag lists transcribed verbatim from spec §5, used **only** by the completeness test.
  - `build_ttl() -> str`, `build_mapping_md() -> str` — generators.
  - `validate(ttl_path) -> dict` — round-trips the committed TTL through `mykg.base_schema.parse_base_schema` and asserts structure.
  - `main()` — `--generate` writes both artifacts; default validates the committed `.ttl`.
- **`docs/examples/ontokg/ontokg-base.ttl`** (deliverable #1) — generated, committed.
- **`docs/examples/ontokg/ontokg-mapping.md`** (deliverable #2) — generated, committed.
- **`tests/test_ontokg_base.py`** — unit tests for completeness, TTL round-trip, and mapping-doc shape.

`docs/examples/ontokg/` is a data/example directory, **not** a Python package. The test loads the script by file path via `importlib.util`.

---

## Task 1: Source-of-truth vocabulary (`VOCAB`) + completeness test

Encode the classified OntoKG vocabulary as three dicts and prove the encoding covers spec §5 exactly, with no transcription errors.

**Files:**
- Create: `docs/examples/ontokg/check_ontokg_base.py`
- Test: `tests/test_ontokg_base.py`

**Interfaces:**
- Produces:
  - `CATEGORIES: list[str]` (8 items)
  - `INTRINSIC: dict[str, tuple[str, str]]` (58 items) — key = original tag, value = `(ClassName, parent)`
  - `RELATIONAL: dict[str, tuple[str, list[str]]]` (34 items) — key = tag, value = `(authority, domains)`; `authority ∈ {"A","I"}`
  - `APPENDIX_B: dict[str, list[str]]` (8 keys) — raw §5 lists
- Consumes: nothing (first task).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ontokg_base.py`:

```python
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "docs/examples/ontokg/check_ontokg_base.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_ontokg_base", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _load()


def test_counts(m):
    assert len(m.CATEGORIES) == 8
    assert len(m.INTRINSIC) == 58
    assert len(m.RELATIONAL) == 34


def test_every_appendix_b_tag_classified_exactly_once(m):
    classified = set(m.INTRINSIC) | set(m.RELATIONAL)
    for cat, tags in m.APPENDIX_B.items():
        for tag in tags:
            assert tag in classified, f"{tag} (under {cat}) is unclassified"
    # No tag is both intrinsic and relational.
    assert not (set(m.INTRINSIC) & set(m.RELATIONAL))


def test_no_stray_classified_tags(m):
    # Every classified tag comes from Appendix B, except `hierarchy`
    # (spec §8.3: authoritative relational module not present as a §5 tag).
    all_tags = {t for tags in m.APPENDIX_B.values() for t in tags}
    extra = (set(m.INTRINSIC) | set(m.RELATIONAL)) - all_tags
    assert extra == {"hierarchy"}, extra


def test_relational_domains_are_categories(m):
    cats = set(m.CATEGORIES)
    for tag, (auth, domains) in m.RELATIONAL.items():
        assert auth in {"A", "I"}, tag
        assert domains, f"{tag} has no domains"
        assert set(domains) <= cats, f"{tag} domains {domains} not all categories"


def test_relational_domains_match_appendix_b(m):
    # A relational tag's domains are exactly the categories it appears under
    # in Appendix B (hierarchy is the documented exception: spans all 8).
    for tag, (auth, domains) in m.RELATIONAL.items():
        if tag == "hierarchy":
            assert set(domains) == set(m.CATEGORIES)
            continue
        appears_in = {c for c, tags in m.APPENDIX_B.items() if tag in tags}
        assert set(domains) == appears_in, f"{tag}: {set(domains)} != {appears_in}"


def test_authoritative_relational_set(m):
    authoritative = {
        "affiliation", "authorship", "award", "culture", "education",
        "entertainment", "finance", "food", "government", "healthcare",
        "hierarchy", "legal", "location", "military", "politics", "religion",
        "society", "sports", "technology", "transportation", "family", "genomics",
    }
    marked_a = {t for t, (auth, _) in m.RELATIONAL.items() if auth == "A"}
    assert marked_a == authoritative


def test_intrinsic_class_names_pascalcase_and_unique(m):
    names = [cls for cls, _ in m.INTRINSIC.values()]
    assert len(names) == len(set(names)), "duplicate intrinsic class names"
    for cls, parent in m.INTRINSIC.values():
        assert cls[0].isupper() and "_" not in cls, cls
        assert parent in m.CATEGORIES, parent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ontokg_base.py -q`
Expected: FAIL — `ModuleNotFoundError` / `FileNotFoundError` because `docs/examples/ontokg/check_ontokg_base.py` does not exist yet.

- [ ] **Step 3: Write the vocabulary**

Create `docs/examples/ontokg/check_ontokg_base.py` with the data only (generators/validator come in later tasks):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ontokg_base.py -q`
Expected: PASS (7 tests). If `test_relational_domains_match_appendix_b` fails, a domain list in `RELATIONAL` disagrees with §5 — fix the domain list, not the test.

- [ ] **Step 5: Commit**

```bash
git add docs/examples/ontokg/check_ontokg_base.py tests/test_ontokg_base.py
git commit -m "feat(ontokg): add classified OntoKG reference vocabulary with completeness tests"
```

---

## Task 2: TTL generator + `parse_base_schema` round-trip

Turn `VOCAB` into RDFS Turtle, and prove the generated TTL survives mykg's **real** `parse_base_schema` (the whole point — validates compatibility with the parser's quirks: object-property class-range detection and first-domain truncation).

**Files:**
- Modify: `docs/examples/ontokg/check_ontokg_base.py`
- Test: `tests/test_ontokg_base.py`

**Interfaces:**
- Consumes: `CATEGORIES`, `INTRINSIC`, `RELATIONAL` (Task 1).
- Produces:
  - `NS: str = "http://mykg.local/ontokg#"`
  - `build_ttl() -> str` — full Turtle document.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ontokg_base.py`:

```python
def test_build_ttl_roundtrips_through_parse_base_schema(m):
    from mykg.base_schema import parse_base_schema

    parsed = parse_base_schema(m.build_ttl())
    lc = parsed["locked_classes"]
    lp = parsed["locked_properties"]

    # Synthetic root + 8 categories under it.
    assert "Entity" in lc
    for cat in m.CATEGORIES:
        assert cat in lc, cat
        assert lc[cat]["parent"] == "Entity", cat

    # Every intrinsic module → locked subclass of its category.
    for tag, (cls, parent) in m.INTRINSIC.items():
        assert cls in lc, cls
        assert lc[cls]["parent"] == parent, cls

    # Every relational module → locked object property with range :Entity.
    # parse_base_schema records only the FIRST domain (spec §8.4) — assert that.
    for tag, (auth, domains) in m.RELATIONAL.items():
        assert tag in lp, tag
        assert lp[tag]["range"] == "Entity", tag
        assert lp[tag]["domain"] == domains[0], tag

    # No name is both a class and a property.
    assert not (set(lc) & set(lp))
    # Nothing became a datatype attribute (no rdfs:Literal ranges used).
    assert all(c["attributes"] == [] for c in lc.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ontokg_base.py::test_build_ttl_roundtrips_through_parse_base_schema -q`
Expected: FAIL with `AttributeError: module 'check_ontokg_base' has no attribute 'build_ttl'`.

- [ ] **Step 3: Write the generator**

Append to `docs/examples/ontokg/check_ontokg_base.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ontokg_base.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Generate and commit the TTL artifact**

Generation is added in Task 4's `main()`, but the artifact can be produced now with a one-liner so the committed file exists:

```bash
cd /Users/oca/PythonProjects/mykg
uv run python -c "import importlib.util,pathlib; \
p=pathlib.Path('docs/examples/ontokg/check_ontokg_base.py'); \
s=importlib.util.spec_from_file_location('c',p); m=importlib.util.module_from_spec(s); \
s.loader.exec_module(m); \
pathlib.Path('docs/examples/ontokg/ontokg-base.ttl').write_text(m.build_ttl())"
```

Sanity-check it renders as expected:

Run: `head -20 docs/examples/ontokg/ontokg-base.ttl`
Expected: prefixes, `:Entity a rdfs:Class .`, then the 8 category lines.

```bash
git add docs/examples/ontokg/check_ontokg_base.py docs/examples/ontokg/ontokg-base.ttl tests/test_ontokg_base.py
git commit -m "feat(ontokg): generate ontokg-base.ttl and verify parse_base_schema round-trip"
```

---

## Task 3: Mapping doc generator + committed `ontokg-mapping.md`

Produce the human-auditable table (spec §6 deliverable 2): one row per distinct module, marked intrinsic/relational and `A`/`I`.

**Files:**
- Modify: `docs/examples/ontokg/check_ontokg_base.py`
- Create: `docs/examples/ontokg/ontokg-mapping.md`
- Test: `tests/test_ontokg_base.py`

**Interfaces:**
- Consumes: `INTRINSIC`, `RELATIONAL` (Task 1).
- Produces: `build_mapping_md() -> str` — a Markdown document with a table.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ontokg_base.py`:

```python
def test_build_mapping_md_has_a_row_per_module(m):
    md = m.build_mapping_md()
    # Header columns (spec §6): module | category(ies) | type | A|I | representation
    assert "| module |" in md
    assert "intrinsic" in md and "relational" in md
    # One table row per distinct module.
    for tag in list(m.INTRINSIC) + list(m.RELATIONAL):
        assert f"| `{tag}` |" in md, f"missing row for {tag}"
    # Authority markers only ever A or I.
    for tag, (auth, _) in m.RELATIONAL.items():
        assert f"| {auth} |" in md
    # Total data rows == distinct module count.
    data_rows = [ln for ln in md.splitlines() if ln.startswith("| `")]
    assert len(data_rows) == len(m.INTRINSIC) + len(m.RELATIONAL)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ontokg_base.py::test_build_mapping_md_has_a_row_per_module -q`
Expected: FAIL with `AttributeError: ... has no attribute 'build_mapping_md'`.

- [ ] **Step 3: Write the generator**

Append to `docs/examples/ontokg/check_ontokg_base.py`:

```python
def build_mapping_md() -> str:
    """Render the module → typing decision table (spec §6 deliverable 2)."""
    rows = []
    for tag, (cls, parent) in INTRINSIC.items():
        rows.append((tag, parent, "intrinsic", "I", f":{cls} ⊑ :{parent}"))
    for tag, (auth, domains) in RELATIONAL.items():
        cats = ", ".join(domains)
        rows.append((tag, cats, "relational", auth,
                     f":{tag} (domain: {cats}; range :Entity)"))
    rows.sort(key=lambda r: r[0])

    header = (
        "# OntoKG → mykg module mapping\n\n"
        "Reconstructed from OntoKG (arXiv:2604.02618) Appendix B. `A` = the "
        "intrinsic/relational typing is authoritative (named in the paper, "
        "spec §4); `I` = inferred by the §4 heuristic. Because mykg seeds and "
        "then extends, every `I` call is a starting point Pass-1 induction may "
        "revise. Generated by check_ontokg_base.py --generate; do not edit by hand.\n\n"
        "| module | category(ies) | type | A/I | mykg representation |\n"
        "|---|---|---|---|---|\n"
    )
    body = "\n".join(
        f"| `{tag}` | {cats} | {typ} | {auth} | {rep} |"
        for tag, cats, typ, auth, rep in rows
    )
    return header + body + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ontokg_base.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Generate and commit the mapping doc**

```bash
cd /Users/oca/PythonProjects/mykg
uv run python -c "import importlib.util,pathlib; \
p=pathlib.Path('docs/examples/ontokg/check_ontokg_base.py'); \
s=importlib.util.spec_from_file_location('c',p); m=importlib.util.module_from_spec(s); \
s.loader.exec_module(m); \
pathlib.Path('docs/examples/ontokg/ontokg-mapping.md').write_text(m.build_mapping_md())"
```

Run: `head -8 docs/examples/ontokg/ontokg-mapping.md`
Expected: title, the authority-legend paragraph, and the table header row.

```bash
git add docs/examples/ontokg/check_ontokg_base.py docs/examples/ontokg/ontokg-mapping.md tests/test_ontokg_base.py
git commit -m "feat(ontokg): generate ontokg-mapping.md typing-decision table"
```

---

## Task 4: `validate()` + `main()` CLI (the deliverable-3 entrypoint)

Give `check_ontokg_base.py` its documented behavior: run as a script to **validate the committed TTL** (spec §6.3, §7.1), or `--generate` to rewrite both artifacts. Guarantees the committed `.ttl` and the generator can't silently drift.

**Files:**
- Modify: `docs/examples/ontokg/check_ontokg_base.py`
- Test: `tests/test_ontokg_base.py`

**Interfaces:**
- Consumes: `build_ttl`, `build_mapping_md`, and `mykg.base_schema.parse_base_schema`.
- Produces:
  - `validate(ttl_path: str | Path) -> dict` — asserts structure, prints counts, returns the parsed dict.
  - `main(argv=None) -> int` — `--generate` writes files; default validates the committed `.ttl`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ontokg_base.py`:

```python
def test_validate_accepts_committed_ttl(m):
    ttl_path = SCRIPT.parent / "ontokg-base.ttl"
    parsed = m.validate(ttl_path)  # asserts internally; returns parsed dict
    assert "Entity" in parsed["locked_classes"]


def test_committed_ttl_matches_generator(m):
    # The committed artifact must be exactly what build_ttl() produces —
    # catches a stale checked-in file.
    ttl_path = SCRIPT.parent / "ontokg-base.ttl"
    assert ttl_path.read_text() == m.build_ttl()


def test_committed_mapping_matches_generator(m):
    md_path = SCRIPT.parent / "ontokg-mapping.md"
    assert md_path.read_text() == m.build_mapping_md()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ontokg_base.py::test_validate_accepts_committed_ttl -q`
Expected: FAIL with `AttributeError: ... has no attribute 'validate'`.

- [ ] **Step 3: Write `validate()` and `main()`**

Append to `docs/examples/ontokg/check_ontokg_base.py`:

```python
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TTL_PATH = _HERE / "ontokg-base.ttl"
_MD_PATH = _HERE / "ontokg-mapping.md"


def validate(ttl_path: str | Path = _TTL_PATH) -> dict:
    """Round-trip the TTL through mykg's parse_base_schema and assert structure."""
    from mykg.base_schema import parse_base_schema

    parsed = parse_base_schema(Path(ttl_path).read_text())
    lc, lp = parsed["locked_classes"], parsed["locked_properties"]

    assert "Entity" in lc, "missing synthetic root :Entity"
    for cat in CATEGORIES:
        assert lc.get(cat, {}).get("parent") == "Entity", f"category {cat} not under :Entity"
    for tag, (cls, parent) in INTRINSIC.items():
        assert lc.get(cls, {}).get("parent") == parent, f"intrinsic {cls} not ⊑ {parent}"
    for tag, (auth, domains) in RELATIONAL.items():
        assert lp.get(tag, {}).get("range") == "Entity", f"relational {tag} range != :Entity"
    assert not (set(lc) & set(lp)), "a name is both a class and a property"

    print(
        f"OK — {len(CATEGORIES)} categories, {len(INTRINSIC)} intrinsic subclasses, "
        f"{len(RELATIONAL)} relational properties "
        f"({len(lc)} locked classes incl. :Entity, {len(lp)} locked properties)."
    )
    return parsed


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Generate or validate the OntoKG reference schema.")
    ap.add_argument("--generate", action="store_true",
                    help="rewrite ontokg-base.ttl and ontokg-mapping.md from VOCAB")
    args = ap.parse_args(argv)

    if args.generate:
        _TTL_PATH.write_text(build_ttl())
        _MD_PATH.write_text(build_mapping_md())
        print(f"Wrote {_TTL_PATH.name} and {_MD_PATH.name}.")
    validate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the script**

Run: `uv run pytest tests/test_ontokg_base.py -q`
Expected: PASS (12 tests).

Run: `uv run python docs/examples/ontokg/check_ontokg_base.py`
Expected: one line `OK — 8 categories, 58 intrinsic subclasses, 34 relational properties (67 locked classes incl. :Entity, 34 locked properties).`

Run (idempotence — regenerate must not change the committed files):
```bash
uv run python docs/examples/ontokg/check_ontokg_base.py --generate
git diff --stat docs/examples/ontokg/
```
Expected: no diff (regeneration is byte-identical to the committed artifacts).

- [ ] **Step 5: Commit**

```bash
git add docs/examples/ontokg/check_ontokg_base.py tests/test_ontokg_base.py
git commit -m "feat(ontokg): add validate()/main entrypoint round-tripping the committed TTL"
```

---

## Task 5: Live smoke run (spec §7.2) — manual verification

Confirm the reference schema actually seeds Pass 1 end-to-end. This is a **live LLM run**, so it is a documented manual procedure, not an automated pytest. Record the real result — do not fabricate output.

**Files:**
- None created. May append a short "Verified" note to `docs/examples/ontokg/ontokg-mapping.md`'s header only if the user wants it recorded (optional; skip by default).

**Interfaces:**
- Consumes: the committed `ontokg-base.ttl`; the `mykg extract-graph --base-schema` hook (`cli.py:567`); a small corpus (`docs/examples/blog_demo_run/.../input/` — 4 `.md` files).

- [ ] **Step 1: Run a small live extraction against the reference schema**

```bash
cd /Users/oca/PythonProjects/mykg
uv run mykg extract-graph \
  docs/examples/blog_demo_run/2026-06-07T21-24-38/input \
  --base-schema docs/examples/ontokg/ontokg-base.ttl
```
Note: `--session <name>` only *resumes/appends* an existing session (`omit to auto-create`), so a fresh smoke run must omit it — mykg auto-creates a timestamped session under `mykg_sessions/`. Expected: the run completes through Pass 1 (schema induction). Capture the session dir it prints for the checks below.

- [ ] **Step 2: Confirm (a) — the Pass-1 locked block listed the OntoKG vocabulary**

Run:
```bash
S="$(ls -td mykg_sessions/*/ 2>/dev/null | head -1)"   # latest (the smoke run)
grep -RIn "base_schema_parsed.json written\|locked class" "$S/run.log" | head
```
Expected: the induction prompt / log shows the `EXISTING SCHEMA (DO NOT RENAME…)` block naming OntoKG classes (`Person`, `Organization`, …, intrinsic subclasses) and properties (`affiliation`, `military`, …). If the log doesn't capture the prompt, confirm instead by inspecting `intermediate/` schema history for the locked names.

- [ ] **Step 3: Confirm (b) — schema.json contains OntoKG concepts plus induced ones, no renaming/duplication of locked names**

Run:
```bash
S="$(ls -td mykg_sessions/*/ 2>/dev/null | head -1)"   # latest (the smoke run)
uv run python -c "import json,sys; \
d=json.load(open(sys.argv[1])); \
names={c.get('type') for c in (d if isinstance(d,list) else d.get('concepts',d.get('types',[])))}; \
locked={'Person','Organization','Work','Place','Science','Event','Knowledge','Product','Entity'}; \
print('locked present:', sorted(locked & names)); \
print('total concepts:', len(names))" "$S/intermediate/schema.json" 2>/dev/null \
 || uv run python -c "print('inspect schema.json manually at:', '$S/intermediate/schema.json')"
```
Expected: the OntoKG category names appear verbatim in `schema.json` (no `Organisation`/`Org` variants — that would be a rename), and total concept count ≥ 8 (induced additions are fine). Manually eyeball `schema.json` if the one-liner's shape assumptions don't fit the actual file.

- [ ] **Step 4: Report the result**

Report to the user, in prose: whether Pass 1 completed, whether the locked block listed the OntoKG vocabulary (2a), and whether `schema.json` preserved the locked names while allowing extensions (2b). If any locked name was renamed or duplicated, that is a **finding** — surface it; do not paper over it. The smoke session is disposable (the auto-created `mykg_sessions/<timestamp>/`, i.e. the latest); mention it can be deleted.

- [ ] **Step 5: Final full-suite check + optional cleanup**

Run: `uv run pytest -m "not live" -q`
Expected: full suite passes (the new `tests/test_ontokg_base.py` included).

Run: `uv run ruff check docs/examples/ontokg/check_ontokg_base.py tests/test_ontokg_base.py`
Expected: no lint errors.

No commit unless Step 1 surfaced a schema fix. The disposable smoke session is not committed.

---

## Self-Review

**Spec coverage:**

- §3 decisions (Hybrid mapping / Seed+extend / range `:Entity`) → encoded in `INTRINSIC`/`RELATIONAL` structure + Task 2 generator + Task 2 test asserting range `Entity`. ✓
- §4 mapping rules (categories→classes, intrinsic→subclasses, relational→properties with unioned domains) → Task 2 `build_ttl`. ✓
- §4 authority (A/I marking; 22 authoritative names) → `RELATIONAL` authority field + `test_authoritative_relational_set` (Task 1) + mapping doc column (Task 3). ✓
- §5 vocabulary (verbatim) → `APPENDIX_B` + `test_every_appendix_b_tag_classified_exactly_once` / `test_no_stray_classified_tags` (Task 1). ✓
- §6 deliverable 1 (`ontokg-base.ttl`) → Task 2 Step 5. ✓
- §6 deliverable 2 (`ontokg-mapping.md`, module|category|type|A/I|representation) → Task 3. ✓
- §6 deliverable 3 (`check_ontokg_base.py` asserting 8 categories/intrinsic subclasses/relational props + counts) → Task 4 `validate()`. ✓
- §7.1 round-trip → Task 2 test + Task 4 Step 4 script run. ✓
- §7.2 smoke run (a + b) → Task 5. ✓
- §8.3 `hierarchy` (authoritative relational, not a §5 tag) → in `RELATIONAL` with all-8 domain; `test_no_stray_classified_tags` allows it as the sole exception. ✓
- §8.4 first-domain truncation is cosmetic → `test_build_ttl_roundtrips_through_parse_base_schema` asserts `lp[tag]["domain"] == domains[0]`, documenting the behavior rather than fighting it. ✓
- Global "no pipeline code" → all files under `docs/examples/ontokg/` + one test file; nothing under `src/mykg/` touched. ✓

**Placeholder scan:** No TBD / "add error handling" / "write tests for the above" / "similar to Task N". Full `VOCAB`, generators, validator, and every test are spelled out. ✓

**Type consistency:** `CATEGORIES`/`INTRINSIC`/`RELATIONAL`/`APPENDIX_B`/`build_ttl`/`build_mapping_md`/`validate`/`main`/`NS` are named identically across Tasks 1-4 and their tests. `INTRINSIC` values are `(ClassName, parent)` everywhere; `RELATIONAL` values are `(authority, domains)` everywhere. `parse_base_schema` return shape (`locked_classes`/`locked_properties`, each entry with `parent`/`range`/`domain`/`attributes`) matches `src/mykg/base_schema.py`. ✓

**Counts:** 8 categories, 58 intrinsic, 34 relational (92 distinct modules + `hierarchy` already counted in the 34). `parse_base_schema` yields 67 locked classes (`:Entity` + 8 + 58) and 34 locked properties. Reconstruction differs from the Wikidata 94/56/38 by design (spec §2.3, §8.5). ✓
