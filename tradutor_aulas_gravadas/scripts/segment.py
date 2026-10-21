"""words.json -> readable subtitle cues (cues.es.json) + compact to_translate.txt for Claude."""
import re
import sys
from pathlib import Path

from common import job_dir, load, save

MAX_CUE_CHARS = 84       # 2 lines x 42
MAX_DUR = 6.0
MIN_DUR = 1.0
GAP_SPLIT = 0.6          # pause that forces a cue break
PRE, POST = 0.05, 0.15   # lead-in / tail around speech
STRONG = re.compile(r"[.!?…]$")
WEAK = re.compile(r"[,;:]$")


def max_word_dur(word: str) -> float:
    return 0.8 + 0.12 * len(word.strip())


def words_of(data):
    """Yield (word, confidence). Words with implausible durations (Whisper stretching a word over
    unrecognised audio) are trimmed toward their closer neighbour and get confidence -9 (flagged)."""
    ws = [(w, seg["conf"]) for seg in data["segments"] for w in seg["words"] if w["w"].strip()]
    for k, (w, conf) in enumerate(ws):
        lim = max_word_dur(w["w"])
        if w["e"] - w["s"] > lim:
            w = dict(w)
            gap_prev = w["s"] - ws[k - 1][0]["e"] if k else 99
            gap_next = ws[k + 1][0]["s"] - w["e"] if k + 1 < len(ws) else 99
            if gap_next <= gap_prev:
                w["s"] = w["e"] - lim
            else:
                w["e"] = w["s"] + lim
            conf = -9.0
        yield w, conf


def build(data):
    cues, cur, confs = [], [], []

    def flush(upto=None):
        """Emit cur[:upto] as a cue and keep the rest as the start of the next one."""
        if not cur:
            return
        upto = len(cur) if upto is None else upto
        part, pconf = cur[:upto], confs[:upto]
        text = "".join(w["w"] for w in part).strip()
        cues.append({"start": part[0]["s"], "end": part[-1]["e"], "es": re.sub(r"\s+", " ", text),
                     "conf": round(min(pconf), 2)})
        del cur[:upto], confs[:upto]

    def best_split():
        """For a forced break (too long): prefer punctuation, else the widest pause, in the back 2/3."""
        lo = max(1, len(cur) // 3)
        cands = range(lo, len(cur))
        punct = [i for i in cands if STRONG.search(cur[i - 1]["w"].strip()) or WEAK.search(cur[i - 1]["w"].strip())]
        if punct:
            return punct[-1]
        return max(cands, key=lambda i: cur[i]["s"] - cur[i - 1]["e"], default=len(cur))

    for w, conf in words_of(data):
        if cur:
            gap = w["s"] - cur[-1]["e"]
            text = "".join(x["w"] for x in cur).strip()
            last = cur[-1]["w"].strip()
            if (gap >= GAP_SPLIT or (STRONG.search(last) and len(text) >= 25)
                    or (WEAK.search(last) and len(text) >= 45)):
                flush()
            elif len(text) + len(w["w"]) > MAX_CUE_CHARS or w["e"] - cur[0]["s"] > MAX_DUR:
                flush(best_split())
        cur.append(w)
        confs.append(conf)
    flush()

    # merge tiny cues into the previous one when the pause is short
    merged = []
    for c in cues:
        if merged and (c["end"] - c["start"] < MIN_DUR or len(c["es"]) < 12):
            p = merged[-1]
            if (c["start"] - p["end"] < 0.4 and len(p["es"]) + len(c["es"]) + 1 <= MAX_CUE_CHARS
                    and c["end"] - p["start"] <= MAX_DUR):
                p["end"], p["es"] = c["end"], p["es"] + " " + c["es"]
                p["conf"] = min(p["conf"], c["conf"])
                continue
        merged.append(c)

    # final timing: pad, clamp to neighbours, enforce min duration when room allows
    for i, c in enumerate(merged):
        nxt = merged[i + 1]["start"] if i + 1 < len(merged) else data["duration"]
        prv = merged[i - 1]["end"] if i else 0.0
        c["start"] = max(prv + 0.02, c["start"] - PRE) if i else max(0.0, c["start"] - PRE)
        c["end"] = min(c["end"] + POST, nxt - 0.04)
        if c["end"] - c["start"] < MIN_DUR:
            c["end"] = min(c["start"] + MIN_DUR, nxt - 0.04)
        c["start"], c["end"] = round(c["start"], 3), round(max(c["end"], c["start"] + 0.2), 3)
        c["id"] = i + 1
    return merged


def prepare(video: Path):
    d = job_dir(video)
    cues = build(load(d / "words.json"))
    from check_sync import silences, snap_starts
    snap_starts(cues, silences(d / "audio.wav"))
    save(d / "cues.es.json", cues)
    (d / "to_translate.txt").write_text(
        "\n".join(f"{c['id']}|{c['es']}" for c in cues), encoding="utf-8")
    low = [c["id"] for c in cues if -9 < c["conf"] < -0.8]
    odd = [c["id"] for c in cues if c["conf"] <= -9]
    return d / "to_translate.txt", len(cues), low, odd


if __name__ == "__main__":
    p, n, low, odd = prepare(Path(sys.argv[1]).resolve())
    print(p, n, "cues; low-confidence:", low, "; timing anomalies:", odd)
