"""Split cues into translation batches for parallel subagents, and merge their output.

  split  -> work/<name>/batches/in_NN.txt  (cues to translate + a few '#ctx' context lines)
  status -> lists batches whose out_NN.txt is missing or incomplete (what still needs an agent)
  merge  -> work/<name>/translated.txt from all out_NN.txt (then run validate.py)
"""
import argparse
import sys
from pathlib import Path

from common import ROOT, job_dir, load, parse_translation

GLOSSARY = ROOT / "glossario.txt"
SIZE = 300          # ~2-3 agents for a 1-hour class: per-agent overhead dominates cost, so fewer is cheaper
CONTEXT = 3


def split(video: Path, size=SIZE, context=CONTEXT):
    d = job_dir(video)
    cues = load(d / "cues.es.json")
    bdir = d / "batches"
    bdir.mkdir(exist_ok=True)
    for old in [*bdir.glob("in_*.txt"), *bdir.glob("out_*.txt")]:
        old.unlink()                       # new boundaries: old outputs no longer line up
    # glossary is embedded in every batch so each agent needs a single Read (fewer turns = fewer tokens)
    gloss = []
    if GLOSSARY.exists():
        entries = [ln.strip() for ln in GLOSSARY.read_text(encoding="utf-8").splitlines()
                   if "=" in ln and not ln.lstrip().startswith("#")]
        if entries:
            gloss = ["# GLOSSÁRIO (usar sempre estas traduções)"] + [f"#g {e}" for e in entries]
    n = 0
    for n, i in enumerate(range(0, len(cues), size), 1):
        before = cues[max(0, i - context):i]
        body = cues[i:i + size]
        after = cues[i + size:i + size + context]
        lines = list(gloss)
        if before:
            lines.append("# CONTEXTO ANTERIOR (não traduzir)")
            lines += [f"#ctx {c['id']}|{c['es']}" for c in before]
        lines.append("# TRADUZIR")
        lines += [f"{c['id']}|{c['es']}" for c in body]
        if after:
            lines.append("# CONTEXTO SEGUINTE (não traduzir)")
            lines += [f"#ctx {c['id']}|{c['es']}" for c in after]
        (bdir / f"in_{n:02d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def status(video: Path):
    """Batches whose output is missing or lacks some IDs."""
    bdir = job_dir(video) / "batches"
    pending = []
    for f in sorted(bdir.glob("in_*.txt")):
        want = set(parse_translation(f))
        out = bdir / f.name.replace("in_", "out_")
        have = set(parse_translation(out)) if out.exists() else set()
        if not want <= have:
            pending.append((f.stem[3:], len(want - have)))
    return pending


def merge(video: Path) -> Path:
    d = job_dir(video)
    tr = {}
    for f in sorted((d / "batches").glob("out_*.txt")):
        tr.update(parse_translation(f))
    out = d / "translated.txt"
    out.write_text("\n".join(f"{k}|{v.replace(chr(10), chr(92) + 'n')}" for k, v in sorted(tr.items())) + "\n",
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["split", "status", "merge"])
    ap.add_argument("video")
    ap.add_argument("--size", type=int, default=SIZE)
    a = ap.parse_args()
    v = Path(a.video).resolve()
    if a.action == "split":
        print(f"{split(v, a.size)} batch(es) in {job_dir(v) / 'batches'}")
    elif a.action == "status":
        p = status(v)
        print("pending:", " ".join(f"{b}({n} missing)" for b, n in p) if p else "none")
        sys.exit(1 if p else 0)
    else:
        print(merge(v))
