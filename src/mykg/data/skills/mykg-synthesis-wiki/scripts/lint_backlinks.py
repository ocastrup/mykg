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


def _qualify_path(domain: str, target: str, domain_rel) -> str:
    rels = domain_rel.get(domain, set())
    if target in rels:  # target is already a domain-relative path (e.g. "entities/x")
        return f"{domain}/{target}"
    for rel in rels:  # target is a bare stem
        if rel.rsplit("/", 1)[-1] == target:
            return f"{domain}/{rel}"
    return f"{domain}/entities/{target}"


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
        pending_fixes = []  # (start, end, replacement) against original text
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
                # Anchor the rewrite to this exact match span so an identically
                # named embed elsewhere in the file is never touched.
                pending_fixes.append((m.start(), m.end(), f"[[{new_raw}]]"))
                report["fixed"].append(
                    {"file": rel_name, "target": target, "new": new_target}
                )
            else:
                report["collisions"].append(
                    {"file": rel_name, "target": target, "domains": doms}
                )
        if pending_fixes:
            for start, end, replacement in sorted(pending_fixes, reverse=True):
                text = text[:start] + replacement + text[end:]
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
