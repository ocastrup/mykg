"""Tests for the wiki config block, constants, and root/packaged parity."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
WIKI_KEYS = {
    "max_workers",
    "min_attr_confidence",
    "min_edge_confidence",
    "max_grounding_tokens",
    "neighbors_max",
}


def _profiles(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())["profiles"]


def test_every_pipeline_profile_has_wiki_block():
    for path in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        for name, prof in _profiles(path).items():
            if "pipeline" not in prof:
                continue
            assert "wiki" in prof["pipeline"], f"{path}:{name} missing pipeline.wiki"
            assert set(prof["pipeline"]["wiki"].keys()) == WIKI_KEYS, f"{path}:{name}"


def test_root_and_packaged_wiki_blocks_match():
    root = _profiles("mykg_config.yaml")
    pkg = _profiles("src/mykg/data/mykg_config.yaml")
    for name in root:
        if "pipeline" in root[name] and "wiki" in root[name]["pipeline"]:
            assert root[name]["pipeline"]["wiki"] == pkg[name]["pipeline"]["wiki"], name


def test_config_exposes_wiki_constants():
    import mykg.config as c

    assert isinstance(c.WIKI_MAX_WORKERS, int)
    assert isinstance(c.WIKI_MIN_ATTR_CONFIDENCE, float)
    assert isinstance(c.WIKI_MIN_EDGE_CONFIDENCE, float)
    assert isinstance(c.WIKI_MAX_GROUNDING_TOKENS, int)
    assert isinstance(c.WIKI_NEIGHBORS_MAX, int)


def test_top_level_paths_block_is_profile_independent():
    """sessions_root / wiki_root live in a top-level `paths:` block (not inside
    any profile), so switching `profile:` never changes where data lives."""
    for rel in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        raw = yaml.safe_load((ROOT / rel).read_text())
        assert "paths" in raw, f"{rel}: missing top-level paths block"
        assert set(raw["paths"]) == {"sessions_root", "wiki_root"}, rel
        # And no profile should reintroduce the old per-profile keys.
        for name, prof in raw.get("profiles", {}).items():
            paths = prof.get("pipeline", {}).get("paths", {})
            assert "sessions_dir" not in paths, f"{rel}:{name} still has sessions_dir"
            wiki = prof.get("pipeline", {}).get("wiki", {})
            assert "vault_dir" not in wiki, f"{rel}:{name} still has wiki.vault_dir"


def test_config_exposes_top_level_path_constants():
    import mykg.config as c

    assert isinstance(c.SESSIONS_DIR, str) and c.SESSIONS_DIR
    assert isinstance(c.WIKI_ROOT, str) and c.WIKI_ROOT
