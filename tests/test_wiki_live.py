"""Live end-to-end build-wiki smoke test (real adapter)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.live
def test_build_wiki_on_latest_session():
    sessions = sorted(Path("kg_sessions").glob("*/output/nodes.jsonl"))
    if not sessions:
        pytest.skip("no completed session available")
    session = sessions[-1].parent.parent.name
    res = subprocess.run(["uv", "run", "mykg", "build-wiki", session],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    vault = Path("kg_sessions") / session / "wiki_vault"
    assert (vault / "Home.md").exists()
    assert any((vault / "entities").glob("*.md"))
    # Every wikilink target in every entity page must be a real file in the vault.
    import re
    ids = {p.stem for p in (vault / "entities").glob("*.md")}
    for page in (vault / "entities").glob("*.md"):
        for target in re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", page.read_text()):
            target = target.split("/")[-1]
            assert target in ids or target in {"Person", "Organization"} or \
                (vault / "hubs" / f"{target}.md").exists(), f"dangling link {target} in {page.name}"
