import subprocess
import sys
from pathlib import Path

import pytest

SKILL = (
    Path(__file__).resolve().parents[1]
    / "src" / "mykg" / "data" / "skills" / "mykg-synthesis-wiki"
)
FIXTURE = Path(r"C:\Users\oca\DNV\Yards - Documents\test-wiki")

pytestmark = pytest.mark.skipif(
    not (FIXTURE / "mykg_wiki").is_dir(),
    reason="test-wiki fixture vault not present on this machine",
)


def test_count_by_type_on_real_research_nodes(tmp_path):
    nodes = FIXTURE / "mykg_sessions" / "Research" / "output" / "nodes.jsonl"
    out = tmp_path / "research-types.png"
    r = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "chart.py"),
         "--from-jsonl", str(nodes), "--count-by", "type",
         "--out", str(out), "--title", "Research nodes by type"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_lint_runs_readonly_on_real_vault():
    # No Synthesis folder yet -> exit 2 with a clear message (read-only, no writes).
    r = subprocess.run(
        [sys.executable, str(SKILL / "scripts" / "lint_backlinks.py"),
         "--vault", str(FIXTURE / "mykg_wiki")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
    assert "synthesize first" in (r.stdout + r.stderr).lower()
