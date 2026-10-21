"""Validate translated.txt against cues.es.json. Prints ONLY problems (keeps token use tiny).

Exit code 0 = clean, 1 = problems (IDs listed so Claude re-translates just those).
"""
import argparse
import sys
from pathlib import Path

from common import job_dir, load, parse_translation

MAX_CHARS = 84     # 2 lines x 42
MAX_CPS = 20.0     # reading speed (chars / second)


def check(video: Path):
    d = job_dir(video)
    cues = load(d / "cues.es.json")
    tr = parse_translation(d / "translated.txt") if (d / "translated.txt").exists() else {}
    ids = {c["id"] for c in cues}
    problems = []
    for c in cues:
        t = tr.get(c["id"])
        if not t:
            problems.append((c["id"], "missing", c["es"]))
            continue
        flat = t.replace("\n", " ")
        dur = max(c["end"] - c["start"], 0.1)
        if len(flat) > MAX_CHARS:
            problems.append((c["id"], f"too long {len(flat)}>{MAX_CHARS} | pt: {flat}", c["es"]))
        elif len(flat) / dur > MAX_CPS:
            problems.append((c["id"], f"too fast {len(flat) / dur:.0f}cps in {dur:.1f}s, "
                                      f"max {int(MAX_CPS * dur)} chars | pt: {flat}", c["es"]))
    for extra in sorted(set(tr) - ids):
        problems.append((extra, "unknown id", ""))
    return problems


def report(probs, limit=40):
    for i, why, es in probs[:limit]:
        print(f"{i}: {why}" + (f" | es: {es}" if es and not why.startswith("missing") else ""))
    if len(probs) > limit:
        print(f"... +{len(probs) - limit} more")
    missing = [i for i, why, _ in probs if why == "missing"]
    if len(missing) > 5:
        print(f"missing ids: {missing[0]}..{missing[-1]} ({len(missing)}) -> re-run the batches that cover them")
    print("OK" if not probs else f"{len(probs)} problem(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    probs = check(Path(a.video).resolve())
    report(probs, a.limit)
    sys.exit(1 if probs else 0)
