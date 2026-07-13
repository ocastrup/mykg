"""Live end-to-end build-topics smoke test against the active LLM provider."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_build_topics_live(live_corpus, tmp_path):
    # 1. Extract a small graph.
    session = "topics-live"
    extract = subprocess.run(
        ["uv", "run", "mykg", "extract-graph", str(live_corpus),
         "--session", session, "--obsidian-vault"],
        capture_output=True, text=True)
    assert extract.returncode == 0, extract.stderr

    # 2. Build the entity wiki first so topic wikilinks resolve.
    subprocess.run(["uv", "run", "mykg", "build-wiki", session], check=True)

    # 3. Build topics.
    topics = subprocess.run(["uv", "run", "mykg", "build-topics", session],
                            capture_output=True, text=True)
    assert topics.returncode == 0, topics.stderr

    # 4. Assert outputs exist and never touched the extract session's intermediate state.
    import mykg.config as cfg
    vault = Path(cfg.WIKI_ROOT) / session
    assert (vault / "Topics.md").exists()
    assert (vault / "schema_proposals.md").exists()
    sess = Path(cfg.SESSIONS_DIR) / session
    assert not (sess / "intermediate" / "topics_pages.done").exists()
    assert (sess / "topics_state" / "topics_index.done").exists()
