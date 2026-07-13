from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import cli


class _StubAdapter:
    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        if context_label.startswith("topic-proposals:"):
            return "[]"
        return "# Theme\n\n[[person-x|X]] links [[org-y|Y]]."

    def endpoint_label(self):
        return "stub"


def _session(sessions_root: Path, name: str) -> None:
    out, inter = sessions_root / name / "output", sessions_root / name / "intermediate"
    out.mkdir(parents=True)
    inter.mkdir(parents=True)
    nodes = [
        {"id": "person-x", "type": "Person", "confidence": 0.9,
         "attributes": {"name": {"value": "X", "confidence": 0.9}}, "source_files": ["d.md"]},
        {"id": "org-y", "type": "Organization", "confidence": 0.9,
         "attributes": {"name": {"value": "Y", "confidence": 0.9}}, "source_files": ["d.md"]},
        {"id": "proj-z", "type": "Project", "confidence": 0.9,
         "attributes": {"name": {"value": "Z", "confidence": 0.9}}, "source_files": ["d.md"]},
    ]
    (out / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in nodes))
    edges = [
        {"id": "e1", "type": "at", "from": "person-x", "to": "org-y", "confidence": 0.9, "attributes": {}},
        {"id": "e2", "type": "runs", "from": "org-y", "to": "proj-z", "confidence": 0.9, "attributes": {}},
    ]
    (out / "edges.jsonl").write_text("\n".join(json.dumps(e) for e in edges))
    (inter / "edge_metadata.json").write_text(json.dumps({e["id"]: e for e in edges}))
    (inter / "chunk_node_index.json").write_text(json.dumps(
        {"d.md": {"1": ["person-x", "org-y", "proj-z"]}}))
    (inter / "file_manifest.json").write_text(json.dumps(
        {"d.md": {"content": "X at Y runs Z. " * 40, "sha256": "s", "token_count": 1}}))
    (inter / "schema.json").write_text(json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]},
                      {"type": "Organization", "parent": None, "attributes": ["name"]},
                      {"type": "Project", "parent": None, "attributes": ["name"]}],
         "properties": []}))


def test_build_topics_missing_session_errors(tmp_path):
    with patch("mykg.cli._sessions_root", return_value=tmp_path):
        res = CliRunner().invoke(cli, ["build-topics", "nope"])
    assert res.exit_code != 0
    assert "not found" in res.output.lower()


def test_build_topics_writes_topics(tmp_path):
    _session(tmp_path, "sess1")
    with patch("mykg.cli._sessions_root", return_value=tmp_path), \
         patch("mykg.config.WIKI_ROOT", str(tmp_path / "wiki")), \
         patch("mykg.config.TOPICS_MIN_SIZE", 3), \
         patch("mykg.llm.config.load_adapter", return_value=_StubAdapter()):
        res = CliRunner().invoke(cli, ["build-topics", "sess1"])
    assert res.exit_code == 0, res.output
    vault = tmp_path / "wiki" / "sess1"
    assert (vault / "Topics.md").exists()
    assert list((vault / "topics").glob("*.md"))
    assert (vault / "schema_proposals.md").exists()
    # Extract session state untouched by the topics run.
    assert not (tmp_path / "sess1" / "intermediate" / "pipeline_state.json").exists()
    assert (tmp_path / "sess1" / "topics_state" / "pipeline_state.json").exists()
