"""CLI wiring for build-wiki."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import cli


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return "## X\n\nBody."

    def endpoint_label(self):
        return "stub"


def _session(sessions_root: Path, name: str) -> None:
    out, inter = sessions_root / name / "output", sessions_root / name / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    (out / "nodes.jsonl").write_text(json.dumps(
        {"id": "person-x", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "X", "confidence": 0.9}},
         "source_files": ["d.md"]}))
    (out / "edges.jsonl").write_text("")
    (inter / "edge_metadata.json").write_text("{}")
    (inter / "chunk_node_index.json").write_text(json.dumps({"d.md": {"1": ["person-x"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"d.md": {"content": "X is a person. " * 40, "sha256": "s", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
         "properties": []}))


def test_build_wiki_missing_session_errors(tmp_path):
    with patch("mykg.cli._sessions_root", return_value=tmp_path):
        res = CliRunner().invoke(cli, ["build-wiki", "nope"])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()


def test_build_wiki_writes_vault(tmp_path):
    _session(tmp_path, "sess1")
    with patch("mykg.cli._sessions_root", return_value=tmp_path), \
         patch("mykg.config.WIKI_ROOT", str(tmp_path / "wiki")), \
         patch("mykg.llm.config.load_adapter", return_value=_StubAdapter()):
        res = CliRunner().invoke(cli, ["build-wiki", "sess1"])
    assert res.exit_code == 0, res.output
    vault = tmp_path / "wiki" / "sess1"
    assert (vault / "entities" / "person-x.md").exists()
    assert (vault / "Home.md").exists()
    # Extract session state must be untouched by the wiki run.
    assert not (tmp_path / "sess1" / "intermediate" / "pipeline_state.json").exists()
    assert (tmp_path / "sess1" / "wiki" / "pipeline_state.json").exists()
