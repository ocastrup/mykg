"""Tests for the topics config block, constants, and root/packaged parity."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
TOPICS_KEYS = {"resolution", "min_size", "members_max", "enabled"}


def _profiles(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())["profiles"]


def test_every_pipeline_profile_has_topics_block():
    for path in ("mykg_config.yaml", "src/mykg/data/mykg_config.yaml"):
        for name, prof in _profiles(path).items():
            pipe = prof.get("pipeline")
            if not pipe or "wiki" not in pipe:
                continue
            assert "topics" in pipe, f"{path}:{name} missing pipeline.topics"
            assert set(pipe["topics"].keys()) == TOPICS_KEYS, f"{path}:{name}"


def test_root_and_packaged_topics_blocks_match():
    root = _profiles("mykg_config.yaml")
    pkg = _profiles("src/mykg/data/mykg_config.yaml")
    for name in root:
        rp = root[name].get("pipeline", {})
        if "topics" in rp:
            assert rp["topics"] == pkg[name]["pipeline"]["topics"], name


def test_config_exposes_topics_constants():
    import mykg.config as c

    assert isinstance(c.TOPICS_RESOLUTION, float)
    assert isinstance(c.TOPICS_MIN_SIZE, int)
    assert isinstance(c.TOPICS_MEMBERS_MAX, int)
    assert isinstance(c.TOPICS_ENABLED, bool)
