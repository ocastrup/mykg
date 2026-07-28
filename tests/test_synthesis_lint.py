import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src" / "mykg" / "data" / "skills" / "mykg-synthesis-wiki"
    / "scripts" / "lint_backlinks.py"
)


def _run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "kg_wiki"
    for rel in [
        "Research/entities/benchmark-mmlu.md",
        "Research/entities/shared-node.md",
        "Yard/entities/shared-node.md",
        "Yard/entities/yard-only.md",
    ]:
        f = vault / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# note\n")
    report = vault / "Synthesis" / "reports" / "r1.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "---\n"
        "title: R1\n"
        "domains:\n"
        "- Research\n"
        "---\n\n"
        "See [[benchmark-mmlu|MMLU]] and [[shared-node|Shared]] "
        "and [[does-not-exist|X]].\n\n"
        "![[assets/r1-01.png]]\n"
    )
    return vault


def test_reports_dangling_and_collision(tmp_path):
    vault = _make_vault(tmp_path)
    r = _run(["--vault", str(vault), "--json"])
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    dangling = {d["target"] for d in data["dangling"]}
    collisions = {c["target"] for c in data["collisions"]}
    assert "does-not-exist" in dangling
    assert "shared-node" in collisions
    assert "benchmark-mmlu" not in dangling
    assert "benchmark-mmlu" not in collisions
    # PNG embeds are not backlinks and must not be flagged
    assert not any("assets/" in t for t in dangling)


def test_fix_qualifies_collision_using_frontmatter(tmp_path):
    vault = _make_vault(tmp_path)
    r = _run(["--vault", str(vault), "--fix", "--json"])
    data = json.loads(r.stdout)
    fixed_targets = {f["target"] for f in data["fixed"]}
    assert "shared-node" in fixed_targets
    body = (vault / "Synthesis" / "reports" / "r1.md").read_text()
    assert "[[Research/entities/shared-node|Shared]]" in body
    # dangling remains, so exit code stays 1
    assert r.returncode == 1


def test_no_write_outside_synthesis(tmp_path):
    vault = _make_vault(tmp_path)
    before = (vault / "Yard" / "entities" / "shared-node.md").read_text()
    _run(["--vault", str(vault), "--fix"])
    after = (vault / "Yard" / "entities" / "shared-node.md").read_text()
    assert before == after


def test_fix_does_not_corrupt_same_named_embed(tmp_path):
    # An embed sharing the collision target's name appears BEFORE the backlink.
    # The fix must rewrite only the backlink, never the embed.
    vault = tmp_path / "kg_wiki"
    for rel in ["Research/entities/shared-node.md", "Yard/entities/shared-node.md"]:
        f = vault / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# note\n")
    report = vault / "Synthesis" / "reports" / "r.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "---\ntitle: R\ndomains:\n- Research\n---\n\n"
        "![[shared-node]]\n\n"
        "See [[shared-node|Shared]].\n"
    )
    r = _run(["--vault", str(vault), "--fix", "--json"])
    body = report.read_text()
    # Embed left untouched:
    assert "![[shared-node]]" in body
    # Backlink qualified:
    assert "[[Research/entities/shared-node|Shared]]" in body
    # Only one collision remained to fix, now resolved -> exit 0.
    assert r.returncode == 0, r.stdout


def test_fix_qualifies_slash_qualified_collision_target(tmp_path):
    # Target already contains a path segment; qualification must not duplicate
    # "entities/" (no "entities/entities/...").
    vault = tmp_path / "kg_wiki"
    for rel in ["Research/entities/shared.md", "Yard/entities/shared.md"]:
        f = vault / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# note\n")
    report = vault / "Synthesis" / "reports" / "r.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "---\ntitle: R\ndomains:\n- Research\n---\n\n"
        "See [[entities/shared|S]].\n"
    )
    r = _run(["--vault", str(vault), "--fix", "--json"])
    body = report.read_text()
    assert "[[Research/entities/shared|S]]" in body
    assert "entities/entities" not in body
    assert r.returncode == 0, r.stdout
