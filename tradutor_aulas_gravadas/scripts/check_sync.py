"""Audio-energy silence detection (no vision) used to (a) snap cue starts onto real speech onsets
and (b) report cues whose boundaries still fall inside silence.

The silence threshold adapts to each recording's noise floor, so it works for clean TTS
as well as noisy classroom audio.
"""
import sys
import wave
from pathlib import Path

import numpy as np

from common import job_dir, load

FRAME = 0.02        # 20 ms analysis frames
MIN_SIL = 0.30      # shortest pause treated as silence


def silences(wav: Path, min_d=MIN_SIL):
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * FRAME)
    frames = x[: len(x) // n * n].reshape(-1, n)
    db = 10 * np.log10((frames ** 2).mean(axis=1) + 1e-10)
    floor, loud = np.percentile(db, 5), np.percentile(db, 95)
    thr = floor + max(6.0, 0.3 * (loud - floor))
    quiet = db < thr
    out, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * FRAME >= min_d:
                out.append((start * FRAME, i * FRAME))
            start = None
    return out


def snap_starts(cues, sil, pre=0.05):
    """Whisper often places the first word after a pause too early. If a cue starts inside a
    detected silence that ends before the cue's speech ends, move the start to the speech onset."""
    j, moved = 0, 0
    for k, c in enumerate(cues):
        while j < len(sil) and sil[j][1] < c["start"]:
            j += 1
        if j < len(sil):
            s, e = sil[j]
            if s < c["start"] < e and e < c["end"] - 0.3:
                prev_end = cues[k - 1]["end"] if k else 0.0
                c["start"] = round(max(e - pre, prev_end + 0.02), 3)
                moved += 1
    return moved


def check(video: Path, margin=0.15):
    d = job_dir(video)
    sil = silences(d / "audio.wav")
    cues = load(d / "cues.es.json")
    bad = []
    for c in cues:
        for s, e in sil:
            if s + margin < c["start"] < e - margin:
                bad.append((c["id"], f"starts {c['start']:.2f}s inside silence {s:.2f}-{e:.2f}"))
    return bad, len(cues)


if __name__ == "__main__":
    bad, n = check(Path(sys.argv[1]).resolve())
    for i, why in bad:
        print(f"{i}: {why}")
    print(f"{n} cues, {len(bad)} suspicious")
