"""Spanish transcription with word-level timestamps (faster-whisper, CPU int8, offline after first model download).

Long audio is split into ~10 min chunks at the quietest point near each boundary (never mid-word).
Each finished chunk is saved to work/<name>/chunks/, so an interrupted run resumes where it stopped.
Progress (chunk, %, ETA) goes to stdout and work/<name>/progress.log.
"""
import argparse
import os
import shutil
import time
from pathlib import Path

import numpy as np

from common import ROOT, job_dir, load, save

SR = 16000
CHUNK_S = 600          # target chunk length
SEARCH_S = 30          # look +/- this far for a quiet cut point
GLOSSARY = ROOT / "glossario.txt"


def cut_points(audio: np.ndarray):
    """Chunk boundaries (samples) placed at the lowest-energy 100 ms frame near each target."""
    n, frame = len(audio), SR // 10
    cuts, t = [0], CHUNK_S * SR
    while t < n - SEARCH_S * SR:
        lo, hi = t - SEARCH_S * SR, t + SEARCH_S * SR
        win = audio[lo:hi][: (hi - lo) // frame * frame].reshape(-1, frame)
        best = lo + int(np.argmin((win ** 2).mean(axis=1))) * frame + frame // 2
        cuts.append(best)
        t = best + CHUNK_S * SR
    cuts.append(n)
    return list(zip(cuts[:-1], cuts[1:]))


def glossary_prompt() -> str | None:
    """Spanish terms from glossario.txt ('es = pt' lines) help Whisper spell technical words."""
    if not GLOSSARY.exists():
        return None
    terms = [ln.split("=")[0].strip() for ln in GLOSSARY.read_text(encoding="utf-8").splitlines()
             if "=" in ln and not ln.lstrip().startswith("#")]
    return ("Glosario: " + ", ".join(terms) + ".")[:600] if terms else None


class Progress:
    def __init__(self, path: Path, total_s: float):
        self.path, self.total, self.t0, self.done0 = path, total_s, time.time(), None

    def restart_clock(self, done_s: float):
        """Call after the model is loaded so download/load time doesn't distort the ETA."""
        self.t0, self.done0 = time.time(), done_s

    def __call__(self, done_s: float, msg: str):
        if self.done0 is None:
            self.done0 = done_s          # resumed chunks don't count for speed
        el = time.time() - self.t0
        rate = (done_s - self.done0) / el if el > 1 and done_s > self.done0 else 0
        eta = f"{(self.total - done_s) / rate / 60:.0f} min" if rate else "?"
        line = (f"{time.strftime('%H:%M:%S')} {done_s / self.total * 100:5.1f}% "
                f"({done_s / 60:.1f}/{self.total / 60:.1f} min audio) ETA {eta} | {msg}")
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def transcribe(video: Path, model_name="large-v3-turbo", device="auto", force=False,
               batch_size=1, threads=0) -> Path:
    from faster_whisper import BatchedInferencePipeline, WhisperModel, decode_audio
    from extract_audio import extract

    d = job_dir(video)
    out, cdir, meta_p = d / "words.json", d / "chunks", d / "chunks" / "meta.json"
    cfg = {"rev": 2, "model": model_name, "batch_size": batch_size, "chunk_s": CHUNK_S, "prompt": glossary_prompt()}
    same = meta_p.exists() and load(meta_p) == cfg
    if out.exists() and same and not force:
        return out
    if force or not same:
        shutil.rmtree(cdir, ignore_errors=True)          # settings changed: old chunks invalid
        out.unlink(missing_ok=True)
    cdir.mkdir(exist_ok=True)
    save(meta_p, cfg)

    audio = decode_audio(str(extract(video)), sampling_rate=SR)
    total = len(audio) / SR
    spans = cut_points(audio)
    prog = Progress(d / "progress.log", total)
    prog(0, f"start: {len(spans)} chunk(s), model {model_name}")

    model = None
    for i, (a, b) in enumerate(spans, 1):
        cp = cdir / f"{i:03d}.json"
        if cp.exists():
            prog(b / SR, f"chunk {i}/{len(spans)} cached")
            continue
        if model is None:
            compute = "int8" if device in ("auto", "cpu") else "float16"
            wm = WhisperModel(model_name, device=device, compute_type=compute,
                              cpu_threads=threads or max(1, (os.cpu_count() or 4) // 2))
            model = BatchedInferencePipeline(wm) if batch_size > 1 else wm
            prog.restart_clock(a / SR)
        kw = dict(language="es", beam_size=5, word_timestamps=True, vad_filter=True,
                  condition_on_previous_text=False, initial_prompt=cfg["prompt"],
                  hallucination_silence_threshold=2.0,
                  vad_parameters=dict(min_silence_duration_ms=300, speech_pad_ms=120))
        if batch_size > 1:
            kw["batch_size"] = batch_size
        segs, _ = model.transcribe(audio[a:b], **kw)
        off, res, last = a / SR, [], 0.0
        for s in segs:
            res.append({"start": s.start + off, "end": s.end + off, "text": s.text.strip(),
                        "conf": s.avg_logprob,
                        "words": [{"w": w.word, "s": w.start + off, "e": w.end + off, "p": w.probability}
                                  for w in (s.words or [])]})
            if s.end + off - last > 60:                  # heartbeat roughly every audio minute
                last = s.end + off
                prog(last, f"chunk {i}/{len(spans)}")
        save(cp, res)                                     # chunk done -> resumable
        prog(b / SR, f"chunk {i}/{len(spans)} done")

    segments = [s for i in range(1, len(spans) + 1) for s in load(cdir / f"{i:03d}.json")]
    segments.sort(key=lambda s: s["start"])
    save(out, {"duration": total, "model": model_name, "segments": segments})
    prog(total, "transcription finished")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--batch-size", type=int, default=1, help=">1 = batched decoding (faster but dropped speech in tests)")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(transcribe(Path(a.video), a.model, a.device, a.force, a.batch_size, a.threads))
