"""Tests for the wiki config block, constants, and root/packaged parity."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
WIKI_KEYS = {
    "vault_dir",
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

    assert isinstance(c.WIKI_VAULT_DIR, str)
    assert isinstance(c.WIKI_MAX_WORKERS, int)
    assert isinstance(c.WIKI_MIN_ATTR_CONFIDENCE, float)
    assert isinstance(c.WIKI_MIN_EDGE_CONFIDENCE, float)
    assert isinstance(c.WIKI_MAX_GROUNDING_TOKENS, int)
    assert isinstance(c.WIKI_NEIGHBORS_MAX, int)
