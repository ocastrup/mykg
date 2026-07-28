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
