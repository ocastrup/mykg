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
