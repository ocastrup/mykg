# KG Synthesis Wiki Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `mykg-synthesis-wiki` agent skill that answers competence questions grounded only in the mykg knowledge graphs (all domains) and maintains an LLM-authored synthesis wiki with backlinks and charts under `mykg_wiki/Synthesis/`.

**Architecture:** A description-triggered agent skill (`SKILL.md` + `references/` templates) plus two deterministic Python helper scripts: `chart.py` (matplotlib PNG renderer) and `lint_backlinks.py` (validates/fixes wikilinks in the synthesis folder against the KG-generated domain wikis). The skill reads `mykg_sessions/<Domain>/output/{nodes,edges}.jsonl`, never source docs, never modifies domain wikis, and writes only to `mykg_wiki/Synthesis/`.

**Tech Stack:** Python 3.11+, matplotlib (new optional/dev dep), pyyaml (existing), pytest (existing), uv for running. Skill authored as markdown for the Copilot CLI / Claude Code skill loader.

**Reference spec:** `docs/superpowers/specs/2026-07-28-kg-synthesis-wiki-skill-design.md`
**Fixture vault:** `C:\Users\oca\DNV\Yards - Documents\test-wiki` (domains: `Research`, `Yard`).

---

## File Structure

Created under the package so the skill ships with mykg (matches the existing `mykg` skill at `src/mykg/data/skills/mykg/`):

```
src/mykg/data/skills/mykg-synthesis-wiki/
├── SKILL.md                     workflow + boundaries (agent-facing)
├── references/
│   ├── report-template.md       synthesis report skeleton
│   ├── index-template.md        Synthesis/index.md row format
│   └── log-format.md            Synthesis/log.md line formats
└── scripts/
    ├── chart.py                 PNG chart renderer (matplotlib)
    └── lint_backlinks.py        backlink validator/fixer over Synthesis/

tests/
├── test_synthesis_chart.py       subprocess tests for chart.py
└── test_synthesis_lint.py        subprocess tests for lint_backlinks.py
```

Responsibilities:
- **SKILL.md** — the only agent-facing logic; encodes boundaries, discovery, verbs, wikilink rules.
- **chart.py** — pure renderer: JSON/JSONL in → PNG out. No KG interpretation.
- **lint_backlinks.py** — pure validator: given the vault, check/fix `[[...]]` targets in `Synthesis/` only.
- **references/** — exact output formats so the agent is deterministic.

---

## Task 1: Scaffold skill directory and add matplotlib dependency

**Files:**
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/SKILL.md` (placeholder frontmatter only for now)
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/scripts/` (dir)
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/references/` (dir)
- Modify: `pyproject.toml` (add matplotlib to dev group + a `wiki` optional extra)

- [ ] **Step 1: Create the skill directory tree with a minimal SKILL.md**

Create `src/mykg/data/skills/mykg-synthesis-wiki/SKILL.md` with just the frontmatter (full body added in Task 5):

```markdown
---
name: mykg-synthesis-wiki
description: "Use to answer competence questions from the mykg knowledge graphs and maintain an LLM-authored synthesis wiki. Triggers: 'synthesize ...', 'what does the KG/graph say about X', 'add to the synthesis wiki', 'write a synthesis report on ...', 'compare A and B across domains', 'lint the synthesis wiki', 'check synthesis backlinks'. Reads ONLY the knowledge graphs (mykg_sessions/*/output/nodes.jsonl + edges.jsonl, all domains); never reads source documents; never modifies the KG-generated domain wikis. Writes only to mykg_wiki/Synthesis/."
---

# mykg Synthesis Wiki

(body added in Task 5)
```

Create the two empty subdirectories (add a temporary `.gitkeep` in each so git tracks them; delete once real files land):

```bash
mkdir -p "src/mykg/data/skills/mykg-synthesis-wiki/scripts"
mkdir -p "src/mykg/data/skills/mykg-synthesis-wiki/references"
```

- [ ] **Step 2: Add matplotlib to pyproject (dev group for tests + optional `wiki` extra for users)**

In `pyproject.toml`, add an optional-dependencies table after the `[project.scripts]` block:

```toml
[project.optional-dependencies]
wiki = [
    "matplotlib>=3.8",
]
```

And add matplotlib to the existing `[dependency-groups] dev` list so tests can run:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=7.1.0",
    "ruff>=0.4",
    "snakeviz>=2.2.2",
    "matplotlib>=3.8",
]
```

- [ ] **Step 3: Sync the environment and verify matplotlib imports**

Run: `uv sync --group dev`
Then run: `uv run python -c "import matplotlib; print(matplotlib.__version__)"`
Expected: prints a version string (e.g. `3.9.x`), exit 0.

- [ ] **Step 4: Commit**

```bash
git add src/mykg/data/skills/mykg-synthesis-wiki pyproject.toml uv.lock
git commit -m "chore: scaffold mykg-synthesis-wiki skill and add matplotlib dep"
```

---

## Task 2: chart.py — PNG chart renderer (TDD)

**Files:**
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/scripts/chart.py`
- Test: `tests/test_synthesis_chart.py`

`chart.py` is a CLI renderer with two input modes:
- `--data <json>` + `--kind {bar,line,hist}` — generic data → chart.
- `--from-jsonl <file> --count-by <field>` — count a top-level field across JSONL lines → bar chart.

Data JSON schemas:
- bar: `{"labels": [str,...], "values": [number,...]}`
- line: `{"x": [number|str,...], "y": [number,...]}`
- hist: `{"values": [number,...], "bins": int}`  (`bins` optional, default 10)

CLI flags: `--out <path>` (required), `--title`, `--xlabel`, `--ylabel`. Missing matplotlib → stderr hint, exit 2. Success → exit 0.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_synthesis_chart.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src" / "mykg" / "data" / "skills" / "mykg-synthesis-wiki"
    / "scripts" / "chart.py"
)


def _run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


def _is_png(path: Path) -> bool:
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_bar_chart_from_data(tmp_path):
    data = tmp_path / "d.json"
    data.write_text(json.dumps({"labels": ["A", "B", "C"], "values": [3, 1, 2]}))
    out = tmp_path / "bar.png"
    r = _run(["--kind", "bar", "--data", str(data), "--out", str(out),
              "--title", "T", "--xlabel", "x", "--ylabel", "y"])
    assert r.returncode == 0, r.stderr
    assert out.exists() and _is_png(out)


def test_hist_chart_from_data(tmp_path):
    data = tmp_path / "h.json"
    data.write_text(json.dumps({"values": [0.1, 0.2, 0.2, 0.9, 0.95], "bins": 5}))
    out = tmp_path / "hist.png"
    r = _run(["--kind", "hist", "--data", str(data), "--out", str(out)])
    assert r.returncode == 0, r.stderr
    assert out.exists() and _is_png(out)


def test_count_by_from_jsonl(tmp_path):
    jl = tmp_path / "nodes.jsonl"
    jl.write_text(
        '{"id": "a", "type": "Person"}\n'
        '{"id": "b", "type": "Person"}\n'
        '{"id": "c", "type": "Org"}\n'
    )
    out = tmp_path / "counts.png"
    r = _run(["--from-jsonl", str(jl), "--count-by", "type",
              "--out", str(out), "--title", "Nodes by type"])
    assert r.returncode == 0, r.stderr
    assert out.exists() and _is_png(out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synthesis_chart.py -v -p no:cacheprovider`
Expected: FAIL (script file does not exist → non-zero returncode, assertions fail).

- [ ] **Step 3: Implement chart.py**

Create `src/mykg/data/skills/mykg-synthesis-wiki/scripts/chart.py`:

```python
#!/usr/bin/env python3
"""Render a PNG chart for the mykg synthesis wiki.

Pure renderer: the agent computes the data from the KG and passes it in.
Two input modes:
  --data <json>  --kind {bar,line,hist}
  --from-jsonl <file>  --count-by <field>   (bar chart of value counts)
Writes a single PNG to --out. Exits 2 if matplotlib is unavailable.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _load_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ModuleNotFoundError:
        sys.stderr.write(
            "matplotlib is required for chart generation. "
            "Install it with:  pip install 'mykg[wiki]'  (or  pip install matplotlib)\n"
        )
        raise SystemExit(2)


def _counts_from_jsonl(path: Path, field: str) -> dict:
    counter: Counter = Counter()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            counter[str(obj.get(field, "(missing)"))] += 1
    ordered = counter.most_common()
    return {"labels": [k for k, _ in ordered], "values": [v for _, v in ordered]}


def _render(plt, kind: str, data: dict, args) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    if kind == "bar":
        ax.bar(data["labels"], data["values"])
        ax.tick_params(axis="x", rotation=45)
    elif kind == "line":
        ax.plot(data["x"], data["y"], marker="o")
    elif kind == "hist":
        ax.hist(data["values"], bins=int(data.get("bins", 10)))
    else:  # pragma: no cover - argparse restricts choices
        raise SystemExit(f"unknown kind: {kind}")
    if args.title:
        ax.set_title(args.title)
    if args.xlabel:
        ax.set_xlabel(args.xlabel)
    if args.ylabel:
        ax.set_ylabel(args.ylabel)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render a PNG chart for the synthesis wiki.")
    p.add_argument("--out", required=True)
    p.add_argument("--kind", choices=["bar", "line", "hist"], default="bar")
    p.add_argument("--data")
    p.add_argument("--from-jsonl", dest="from_jsonl")
    p.add_argument("--count-by", dest="count_by")
    p.add_argument("--title")
    p.add_argument("--xlabel")
    p.add_argument("--ylabel")
    args = p.parse_args(argv)

    if args.from_jsonl:
        if not args.count_by:
            p.error("--from-jsonl requires --count-by")
        data = _counts_from_jsonl(Path(args.from_jsonl), args.count_by)
        kind = "bar"
    elif args.data:
        data = json.loads(Path(args.data).read_text(encoding="utf-8"))
        kind = args.kind
    else:
        p.error("provide either --data or --from-jsonl")

    plt = _load_matplotlib()
    _render(plt, kind, data, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synthesis_chart.py -v -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/data/skills/mykg-synthesis-wiki/scripts/chart.py tests/test_synthesis_chart.py
git commit -m "feat: add synthesis-wiki chart.py PNG renderer"
```

---

## Task 3: lint_backlinks.py — backlink validator/fixer (TDD)

**Files:**
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/scripts/lint_backlinks.py`
- Test: `tests/test_synthesis_lint.py`

Behavior (operates over the vault; only reads/writes files under the synthesis subdir):
- Discover **domains** = immediate subdirs of the vault, excluding `.obsidian`, hidden dirs, and the synthesis subdir.
- Build a target index by walking each domain for `*.md`: map bare stem → set of domains, and record each note's domain-relative path (e.g. `entities/x`, `hubs/Y`) and vault-relative path (e.g. `Research/entities/x`).
- Walk the synthesis subdir for `*.md`, extract every `[[target|alias]]` / `![[target]]`. For each target (strip alias after `|`, strip `#`/`^` anchors):
  - Skip targets that resolve to a file inside the synthesis subdir (internal, e.g. `assets/...`).
  - Path target (contains `/`): OK if it matches a vault-relative or a single domain-relative path; collision if a domain-relative path matches in >1 domain; else dangling.
  - Bare stem: 1 domain → OK; >1 → collision; 0 → dangling.
- `--fix`: for a collision, read the report's YAML frontmatter `domains:` list; if exactly one colliding domain is listed, rewrite the target to that domain's vault-relative path (`<Domain>/entities/<stem>` or the note's actual relpath), preserving the alias. Otherwise leave and mark ambiguous.
- Output human summary, or JSON with `--json`. Exit 0 only if no dangling and no unresolved collisions/ambiguous remain.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_synthesis_lint.py`:

```python
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
    vault = tmp_path / "mykg_wiki"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synthesis_lint.py -v -p no:cacheprovider`
Expected: FAIL (script missing).

- [ ] **Step 3: Implement lint_backlinks.py**

Create `src/mykg/data/skills/mykg-synthesis-wiki/scripts/lint_backlinks.py`:

```python
#!/usr/bin/env python3
"""Validate (and optionally fix) wikilinks in the mykg synthesis folder.

Only files under <vault>/<synthesis> are read for links and are the only files
ever written. Domain wikis (all other top-level folders in the vault) are read
read-only to build the set of valid link targets.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

LINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")


def _iter_md(root: Path):
    for p in root.rglob("*.md"):
        if any(part == ".obsidian" for part in p.parts):
            continue
        yield p


def _domains(vault: Path, synthesis: str) -> list[Path]:
    out = []
    for child in sorted(vault.iterdir()):
        if not child.is_dir():
            continue
        if child.name == synthesis or child.name.startswith("."):
            continue
        out.append(child)
    return out


def _build_index(domains: list[Path], vault: Path):
    stem_to_domains: dict[str, set[str]] = {}
    domain_rel: dict[str, set[str]] = {}   # domain name -> set of "entities/x" style
    vault_rel: set[str] = set()
    for d in domains:
        rels = set()
        for md in _iter_md(d):
            stem = md.stem
            stem_to_domains.setdefault(stem, set()).add(d.name)
            rel = md.relative_to(d).with_suffix("").as_posix()
            rels.add(rel)
            vault_rel.add(md.relative_to(vault).with_suffix("").as_posix())
        domain_rel[d.name] = rels
    return stem_to_domains, domain_rel, vault_rel


def _clean_target(raw: str) -> str:
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0].split("^", 1)[0]
    return target.strip()


def _load_frontmatter_domains(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    block = text[3:end]
    try:
        meta = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return []
    doms = meta.get("domains", [])
    if isinstance(doms, str):
        return [doms]
    return [str(x) for x in doms] if isinstance(doms, list) else []


def _classify(target: str, stem_to_domains, domain_rel, vault_rel, synth_rel):
    if target in synth_rel:
        return "internal", []
    if "/" in target:
        if target in vault_rel:
            return "ok", []
        hits = [dname for dname, rels in domain_rel.items() if target in rels]
        if len(hits) == 1:
            return "ok", hits
        if len(hits) > 1:
            return "collision", hits
        return "dangling", []
    doms = sorted(stem_to_domains.get(target, set()))
    if len(doms) == 1:
        return "ok", doms
    if len(doms) > 1:
        return "collision", doms
    return "dangling", []


def _qualify_path(domain: str, stem: str, domain_rel) -> str:
    for rel in domain_rel.get(domain, set()):
        if rel.rsplit("/", 1)[-1] == stem:
            return f"{domain}/{rel}"
    return f"{domain}/entities/{stem}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Lint synthesis-wiki backlinks.")
    p.add_argument("--vault", required=True)
    p.add_argument("--synthesis", default="Synthesis")
    p.add_argument("--fix", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    vault = Path(args.vault)
    synth = vault / args.synthesis
    if not synth.is_dir():
        sys.stderr.write(f"no synthesis folder at {synth}; synthesize first.\n")
        return 2

    domains = _domains(vault, args.synthesis)
    stem_to_domains, domain_rel, vault_rel = _build_index(domains, vault)
    synth_rel = {
        md.relative_to(synth).with_suffix("").as_posix() for md in _iter_md(synth)
    }

    report = {"reports_checked": 0, "links_checked": 0, "ok": 0,
              "dangling": [], "collisions": [], "fixed": [], "ambiguous": []}

    for md in _iter_md(synth):
        report["reports_checked"] += 1
        text = md.read_text(encoding="utf-8")
        fm_domains = _load_frontmatter_domains(text)
        changed = False
        for m in list(LINK_RE.finditer(text)):
            if m.group(0).startswith("!"):
                continue  # embeds (images/transclusions) are not backlinks
            raw = m.group(1)
            target = _clean_target(raw)
            if not target:
                continue
            report["links_checked"] += 1
            kind, doms = _classify(
                target, stem_to_domains, domain_rel, vault_rel, synth_rel
            )
            rel_name = md.relative_to(vault).as_posix()
            if kind == "internal" or kind == "ok":
                if kind == "ok":
                    report["ok"] += 1
                continue
            if kind == "dangling":
                report["dangling"].append({"file": rel_name, "target": target})
                continue
            # collision
            pick = [d for d in doms if d in fm_domains]
            if args.fix and len(pick) == 1:
                new_target = _qualify_path(pick[0], target, domain_rel)
                new_raw = raw.replace(target, new_target, 1)
                text = text.replace(f"[[{raw}]]", f"[[{new_raw}]]", 1)
                changed = True
                report["fixed"].append(
                    {"file": rel_name, "target": target, "new": new_target}
                )
            else:
                report["collisions"].append(
                    {"file": rel_name, "target": target, "domains": doms}
                )
        if changed:
            md.write_text(text, encoding="utf-8")

    unresolved = report["dangling"] or report["collisions"] or report["ambiguous"]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"reports={report['reports_checked']} links={report['links_checked']} "
            f"ok={report['ok']} dangling={len(report['dangling'])} "
            f"collisions={len(report['collisions'])} fixed={len(report['fixed'])}"
        )
        for d in report["dangling"]:
            print(f"  DANGLING {d['file']}: [[{d['target']}]]")
        for c in report["collisions"]:
            print(f"  COLLISION {c['file']}: [[{c['target']}]] in {c['domains']}")
        for f in report["fixed"]:
            print(f"  FIXED {f['file']}: [[{f['target']}]] -> [[{f['new']}]]")
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synthesis_lint.py -v -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/data/skills/mykg-synthesis-wiki/scripts/lint_backlinks.py tests/test_synthesis_lint.py
git commit -m "feat: add synthesis-wiki lint_backlinks.py validator/fixer"
```

---

## Task 4: references/ templates

**Files:**
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/references/report-template.md`
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/references/index-template.md`
- Create: `src/mykg/data/skills/mykg-synthesis-wiki/references/log-format.md`

- [ ] **Step 1: Create report-template.md**

```markdown
---
title: <Human-readable report title>
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
theme: <one theme label, e.g. "AI capabilities">
domains:
- <Domain the cited entities come from, one per line, e.g. Research>
entities:
- <mykg_id of each cited entity, one per line>
---

# <Report title>

## Answer

<Synthesized prose grounded strictly in the KG. Reference entities inline as
`[[<mykg_id>|<display name>]]`. When a fact spans domains, name the domain.>

## Diagram

<Optional. Mermaid block for relationships/flow, e.g.:

```mermaid
graph LR
  A["Alice Chen"] -->|works_at| B["Acme Corp"]
```

or an embedded PNG chart:

![[assets/<slug>-01.png]]
>

## Key entities

- [[<mykg_id>|<display name>]] — <one-line role in this answer>

## Domains & grounding

- Domains read: <Research, Yard, ...>
- All statements above are grounded in nodes.jsonl / edges.jsonl for those domains.
```

- [ ] **Step 2: Create index-template.md**

```markdown
# Synthesis Index

<One `##` section per theme. One row per report under its theme.>

## <Theme>

| Report | Summary | Updated |
| --- | --- | --- |
| [[reports/<slug>\|<Report title>]] | <one-line summary> | <YYYY-MM-DD> |
```

- [ ] **Step 3: Create log-format.md**

```markdown
# Synthesis Log

<Append-only. One block per operation. Formats:>

## [YYYY-MM-DD] synthesize | <report title>
- Report: reports/<slug>.md
- Domains: <Research, Yard>
- Charts: <assets/<slug>-01.png, ...>   (omit line if none)

## [YYYY-MM-DD] lint | <N> links checked, <D> dangling, <C> collisions, <F> fixed

## [YYYY-MM-DD] query | in-conversation only (no files written)
```

- [ ] **Step 4: Commit**

```bash
git add src/mykg/data/skills/mykg-synthesis-wiki/references
git commit -m "docs: add synthesis-wiki reference templates"
```

---

## Task 5: Write the full SKILL.md body

**Files:**
- Modify: `src/mykg/data/skills/mykg-synthesis-wiki/SKILL.md`

- [ ] **Step 1: Replace the placeholder body with the full workflow**

Overwrite `SKILL.md` keeping the Task 1 frontmatter, with this body after the frontmatter:

```markdown
# mykg Synthesis Wiki

Answer the user's competence questions **grounded only in the mykg knowledge
graphs**, and persist the answers as an LLM-authored synthesis wiki. This is the
synthesis layer beside the KG-generated per-domain wikis — it reads the graphs,
never the sources, and writes only to its own folder.

## Boundaries (hard rules)

- **Read only the KGs.** Load `mykg_sessions/<Domain>/output/nodes.jsonl` and
  `edges.jsonl` for every domain. Never read `raw/` or any source document.
- **Never modify the domain wikis.** `mykg_wiki/<Domain>/` (e.g. `Research/`,
  `Yard/`) is read-only. You may read a domain's `.wiki_manifest.json` for link
  validation, nothing else there.
- **Write only to `mykg_wiki/Synthesis/`.** All reports, charts, index, and log
  live there.
- **Never fabricate.** If the graphs do not contain the answer, say so. Never
  invent a backlink to an entity that is not in the KG.

## Locate the vault root

The vault root is the folder that contains both `mykg_sessions/` and
`mykg_wiki/`. Resolve in this order and confirm with the user if unsure:
1. A path the user gave in the request.
2. The `MYKG_WIKI_ROOT` environment variable, if set.
3. The current directory, if it contains both `mykg_sessions/` and `mykg_wiki/`.
4. Otherwise, ask the user for the path.

Reference/fixture root for testing:
`C:\Users\oca\DNV\Yards - Documents\test-wiki`.

## Discover domains and load the KGs

1. List subfolders of `<root>/mykg_sessions/` → domain names (e.g. `Research`,
   `Yard`).
2. For each, read `output/nodes.jsonl` and `output/edges.jsonl`.
3. Build an in-context entity table: `id -> {display, type, domain}` where
   `display = attributes.name.value` if present, else the id humanized
   (split on `-`, drop the leading type token when it duplicates `type`,
   title-case). Note any id that appears in more than one domain (collision set).

## Verbs

### Synthesize / answer a competence question
Triggers: "synthesize …", "what does the KG say about X", "write a synthesis
report on …", "compare A and B across domains", "add to the synthesis wiki".

1. Select the relevant nodes/edges across **all** domains.
2. Write the answer grounded strictly in them. Prefer KG content over training
   knowledge; attribute the domain when a fact spans domains.
3. Initialize `Synthesis/` if missing: create `Synthesis/`, `reports/`,
   `assets/`, `index.md` (heading `# Synthesis Index`, empty body), `log.md`
   (heading `# Synthesis Log`, empty body). Never overwrite existing files.
4. Write `reports/<slug>.md` following `references/report-template.md`. Slug =
   kebab-case of the topic, max 60 chars, numeric suffix on collision.
5. Reference entities as `[[<mykg_id>|<display>]]`. If the id is in the collision
   set, write it path-qualified: `[[<Domain>/entities/<id>|<display>]]`.
6. Update `index.md` (add/update the report's row under its theme; see
   `references/index-template.md`) and append a `synthesize` block to `log.md`
   (see `references/log-format.md`).

A plain conversational answer the user does **not** ask to persist writes no
files — answer in the conversation and, if the discipline block applies, log a
`query | in-conversation only` line only when they asked to record it.

### Chart
Charts are required. Choose the mechanism:
- **Mermaid inline** for relationships/flow/hierarchy or trivial counts. Embed a
  fenced ```mermaid block in the report. Use entity display names as labels.
- **PNG via scripts/chart.py** for quantitative charts (bar/line/hist:
  confidence distributions, node-degree rankings, per-type counts). Compute the
  data yourself from the loaded jsonl, then render:

  ```bash
  uv run python "<skill_dir>/scripts/chart.py" --kind bar --data data.json \
    --out "<root>/mykg_wiki/Synthesis/assets/<slug>-01.png" --title "…"
  ```

  Or count a field directly from a domain's nodes:

  ```bash
  uv run python "<skill_dir>/scripts/chart.py" \
    --from-jsonl "<root>/mykg_sessions/<Domain>/output/nodes.jsonl" \
    --count-by type --out "<root>/mykg_wiki/Synthesis/assets/<slug>-01.png" \
    --title "<Domain> nodes by type"
  ```

  Embed in the report with `![[assets/<slug>-01.png]]`. If chart.py exits 2,
  matplotlib is missing — tell the user to run `pip install 'mykg[wiki]'`.

### Lint
Triggers: "lint the synthesis wiki", "check synthesis backlinks". Two parts:

1. **Backlinks (script).** Run over the synthesis folder only:

   ```bash
   uv run python "<skill_dir>/scripts/lint_backlinks.py" \
     --vault "<root>/mykg_wiki" --fix
   ```

   It validates every `[[…]]` target against the domain wikis, auto-qualifies
   collisions using each report's `domains:` frontmatter, and reports dangling
   links (it never deletes them and never writes outside `Synthesis/`). Add
   `--json` for machine-readable output. Report the dangling/ambiguous items to
   the user for a decision.

2. **Index consistency (you).** Compare `index.md` rows against `reports/*.md`:
   a report with no row → add a row with `(no summary)`; a row pointing at a
   missing report → mark it `[MISSING]` (do not delete). Append a `lint` block to
   `log.md`.

## Wikilink rules

- Entity backlink: `[[<mykg_id>|<display>]]` (matches the KG wiki's own style).
- Collision id (present in >1 domain): `[[<Domain>/entities/<id>|<display>]]`.
- Never link an id that is absent from every KG — render it as plain text and
  note that it is not in the graph.

## Error handling

- No `mykg_sessions/` or an empty `output/` for a domain → tell the user to run
  extraction first; do not fabricate.
- KG regenerated and an id disappeared → lint flags the backlink as dangling;
  never silently delete.
- Write `index.md`/`log.md` only after the report file is written, so a crash
  leaves a detectable missing report (lint `[MISSING]`), not a corrupt half-state.
```

- [ ] **Step 2: Verify frontmatter parses and required anchors exist**

Run:
```bash
uv run python -c "import pathlib,sys; t=pathlib.Path('src/mykg/data/skills/mykg-synthesis-wiki/SKILL.md').read_text(encoding='utf-8'); assert t.startswith('---'); [sys.exit('missing: '+s) for s in ['Boundaries (hard rules)','Discover domains','### Synthesize','### Chart','### Lint','Wikilink rules'] if s not in t]; print('SKILL.md ok')"
```
Expected: prints `SKILL.md ok`, exit 0.

- [ ] **Step 3: Remove the temporary .gitkeep files (scripts/ and references/ now have real files)**

```bash
rm -f "src/mykg/data/skills/mykg-synthesis-wiki/scripts/.gitkeep" "src/mykg/data/skills/mykg-synthesis-wiki/references/.gitkeep"
```

- [ ] **Step 4: Commit**

```bash
git add src/mykg/data/skills/mykg-synthesis-wiki/SKILL.md
git rm --cached --ignore-unmatch "src/mykg/data/skills/mykg-synthesis-wiki/scripts/.gitkeep" "src/mykg/data/skills/mykg-synthesis-wiki/references/.gitkeep"
git commit -m "docs: write mykg-synthesis-wiki SKILL.md workflow"
```

---

## Task 6: Integration smoke test against the real fixture vault

**Files:**
- Test: `tests/test_synthesis_integration.py`

This test exercises the scripts against the real `test-wiki` vault when it is
present, and is skipped otherwise (so CI on other machines stays green).

- [ ] **Step 1: Write the integration test**

Create `tests/test_synthesis_integration.py`:

```python
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
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_synthesis_integration.py -v -p no:cacheprovider`
Expected on this machine: 2 passed (fixture present). On machines without the
fixture: 2 skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/test_synthesis_integration.py
git commit -m "test: add synthesis-wiki integration smoke test against fixture vault"
```

---

## Task 7: Full suite + install the skill for live use

**Files:**
- None (verification + install action)

- [ ] **Step 1: Run the whole new test set together**

Run: `uv run pytest tests/test_synthesis_chart.py tests/test_synthesis_lint.py tests/test_synthesis_integration.py -v -p no:cacheprovider`
Expected: all pass (integration may skip if fixture absent).

- [ ] **Step 2: Run the full suite to confirm no regressions**

Run: `uv run pytest -q -p no:cacheprovider -m "not live"`
Expected: existing tests still pass; new tests included.

- [ ] **Step 3: Install the skill into the Copilot CLI skills folder (this machine)**

Copy the bundled skill so the loader picks it up (mirrors how `mykg init`
installs the `mykg` skill). PowerShell:

```powershell
$src = "src/mykg/data/skills/mykg-synthesis-wiki"
$dst = Join-Path $env:USERPROFILE ".copilot/skills/mykg-synthesis-wiki"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Copy-Item -Recurse -Force $src $dst
Get-ChildItem -Recurse $dst | Select-Object FullName
```

Expected: `SKILL.md`, `references/*`, and `scripts/*` appear under
`~/.copilot/skills/mykg-synthesis-wiki`. Restart Copilot CLI so the skill loads.

- [ ] **Step 4: Final commit (if any tracked changes remain)**

```bash
git add -A
git commit -m "chore: finalize mykg-synthesis-wiki skill" --allow-empty
```

---

## Notes for the implementer

- `<skill_dir>` in SKILL.md means the skill's base directory (the folder holding
  `SKILL.md`); Copilot/Claude surface it as the skill base path.
- The scripts are deliberately dependency-light: `chart.py` needs matplotlib
  (optional `wiki` extra), `lint_backlinks.py` needs only pyyaml (already a core
  dependency).
- Do not wire this skill into `mykg init` — that installer is scoped to the
  `mykg` skill and changing it is out of scope for this plan.
