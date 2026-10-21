"""Merge Spanish timing + Portuguese text -> SRT. Timing always comes from cues.es.json."""
import sys
from pathlib import Path

from common import job_dir, load, parse_translation, srt_time

LINE = 42


def wrap(text: str) -> str:
    if "\n" in text:
        return text
    if len(text) <= LINE:
        return text
    # balanced two-line split at the space closest to the middle
    mid = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    i = min(spaces, key=lambda k: abs(k - mid))
    return text[:i] + "\n" + text[i + 1:]


def build(video: Path) -> Path:
    d = job_dir(video)
    cues = load(d / "cues.es.json")
    tr = parse_translation(d / "translated.txt")
    blocks = []
    n = 0
    for c in cues:
        t = tr.get(c["id"], "").strip()
        if not t:
            continue
        n += 1
        blocks.append(f"{n}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{wrap(t)}\n")
    out = d / f"{video.stem}.pt.srt"
    out.write_text("\n".join(blocks), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
