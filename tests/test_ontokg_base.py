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
