"""Tests for the mlx-local profile and its OpenAI-compatible adapter construction."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml

from mykg.llm.config import load_adapter
from mykg.llm.openai_adapter import OpenAIAdapter


def _load_mlx_profile() -> dict:
    repo_root = Path(__file__).parent.parent
    raw = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())
    profile = raw["profiles"]["mlx-local"]
    cfg = deepcopy(raw)
    for key in ("provider", "llm", "llm_retry", "pipeline"):
        if key in profile:
            cfg[key] = profile[key]
    return cfg


def test_mlx_profile_present_in_root_yaml():
    repo_root = Path(__file__).parent.parent
    raw = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())
    assert "mlx-local" in raw["profiles"]
    profile = raw["profiles"]["mlx-local"]
    assert profile["provider"] == "openai"
    assert profile["llm"]["base_url"] == "http://localhost:8000"
    assert profile["llm"]["api_key"] == "PostFuru"
    assert "model" in profile["llm"]


def test_mlx_profile_present_in_packaged_template():
    repo_root = Path(__file__).parent.parent
    packaged = yaml.safe_load(
        (repo_root / "src" / "mykg" / "data" / "mykg_config.yaml").read_text()
    )
    assert "mlx-local" in packaged["profiles"]
    profile = packaged["profiles"]["mlx-local"]
    assert profile["provider"] == "openai"
    assert profile["llm"]["base_url"] == "http://localhost:8000"
    assert "api_key" in profile["llm"]


def test_mlx_profile_structural_parity():
    """Root and packaged template must have identical key sets under mlx-local."""
    repo_root = Path(__file__).parent.parent
    root = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())["profiles"]["mlx-local"]
    packaged = yaml.safe_load(
        (repo_root / "src" / "mykg" / "data" / "mykg_config.yaml").read_text()
    )["profiles"]["mlx-local"]
    assert set(root.keys()) == set(packaged.keys())
    assert set(root["llm"].keys()) == set(packaged["llm"].keys())
    assert set(root["pipeline"].keys()) == set(packaged["pipeline"].keys())


def test_load_adapter_constructs_openai_adapter_from_mlx_profile():
    cfg = _load_mlx_profile()
    with patch("openai.OpenAI"):
        adapter = load_adapter(_raw=cfg)
    assert isinstance(adapter, OpenAIAdapter)


def test_mlx_profile_endpoint_label():
    cfg = _load_mlx_profile()
    with patch("openai.OpenAI"):
        adapter = load_adapter(_raw=cfg)
    label = adapter.endpoint_label()
    assert "localhost:8000" in label
    assert cfg["llm"]["model"] in label
