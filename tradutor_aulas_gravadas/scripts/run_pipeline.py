"""Orchestrator. Translation (between prepare and merge) is done by parallel `tradutor-legendas` subagents.

  prepare <video>  audio -> chunked/resumable transcription -> cues -> work/<name>/batches/in_NN.txt
  status  <video>  which batches still lack a complete out_NN.txt
  merge   <video>  out_NN.txt -> translated.txt, then validate (prints only problem cues)
  finish  <video>  validate -> .pt.srt -> video with Portuguese subtitles  [--burn]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import batches
import build_srt
import check_sync
import mux
import segment
import transcribe
import validate
from common import job_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "status", "merge", "finish"])
    ap.add_argument("video")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--batch-size", type=int, default=1, help="Whisper batched decoding (>1 faster but dropped speech in tests)")
    ap.add_argument("--cues-per-batch", type=int, default=batches.SIZE)
    ap.add_argument("--burn", action="store_true")
    ap.add_argument("--force", action="store_true", help="redo transcription from scratch")
    a = ap.parse_args()
    video = Path(a.video).resolve()
    if not video.exists():
        sys.exit(f"not found: {video}")

    if a.stage == "prepare":
        transcribe.transcribe(video, a.model, a.device, a.force, a.batch_size)
        _, n, low, odd = segment.prepare(video)
        nb = batches.split(video, a.cues_per_batch)
        bad, _ = check_sync.check(video)
        print(f"cues: {n}\nbatches: {nb} in {job_dir(video) / 'batches'}")
        print("low-confidence cues:", low or "none")
        print("timing-anomaly cues (listen to check):", odd or "none")
        print("sync-suspicious cues:", [i for i, _ in bad] or "none")
    elif a.stage == "status":
        p = batches.status(video)
        print("pending:", " ".join(f"{b}({k} missing)" for b, k in p) if p else "none")
    elif a.stage == "merge":
        p = batches.status(video)
        if p:
            print("incomplete batches:", " ".join(f"{b}({k} missing)" for b, k in p))
        print(batches.merge(video))
        probs = validate.check(video)
        validate.report(probs)
        sys.exit(1 if probs else 0)
    else:
        probs = validate.check(video)
        if probs:
            validate.report(probs)
            sys.exit("validation failed; fix those cues in translated.txt first")
        srt = build_srt.build(video)
        out = mux.mux(video, srt, a.burn)
        sidecar = video.parent / srt.name
        sidecar.write_bytes(srt.read_bytes())
        print(f"srt: {sidecar}\nvideo: {out}")


if __name__ == "__main__":
    main()
