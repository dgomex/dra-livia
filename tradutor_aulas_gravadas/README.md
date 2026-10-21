# tradutor_aulas_gravadas

Spanish-audio class video in → same video out with synchronized Portuguese (pt-BR) subtitles.

- **Local & private:** audio extraction, transcription and muxing run on this machine. The video is never uploaded and never given to a vision model.
- **Cheap:** only plain `id|texto` lines are translated, by parallel `tradutor-legendas` subagents that each see just their batch. The main session never loads the transcript.
- **Accurate timing:** faster-whisper word timestamps + VAD → readable cues. The translation keeps the original cue timing by ID.
- **Long videos:** transcription runs in ~10-minute chunks cut at silences. It's resumable and writes a progress/ETA log.

## Use
In Claude Code, opened in this folder: *"traduz a aula `C:\...\aula1.mp4`"*. This runs the skill `traduzir-aula-gravada`.

Pipeline (what the skill runs):
```
python scripts/setup.py                                         # once: venv + faster-whisper + bundled ffmpeg
.venv\Scripts\python.exe scripts\run_pipeline.py prepare aula.mp4   # transcribe + cues + batches (background)
#   -> Claude launches one tradutor-legendas subagent per work\aula\batches\in_NN.txt
.venv\Scripts\python.exe scripts\run_pipeline.py merge aula.mp4     # merge + validate
.venv\Scripts\python.exe scripts\run_pipeline.py finish aula.mp4 [--burn]
```

| Path | Purpose |
|---|---|
| `.claude/skills/traduzir-aula-gravada/SKILL.md` | the workflow Claude follows |
| `.claude/agents/tradutor-legendas.md` | translator subagent (Sonnet, Read/Write only) |
| `glossario.txt` | optional `espanhol = português` terms (ASR hint + translation consistency) |
| `scripts/transcribe.py` | chunked, resumable, batched faster-whisper; `work/<name>/progress.log` |
| `scripts/segment.py` | words → subtitle cues (≤84 chars, ≤6 s, split at pauses/punctuation) |
| `scripts/batches.py` | split cues into batches with context / status / merge |
| `scripts/validate.py` | lists only problem cues (missing, too long, too fast) |
| `scripts/check_sync.py` | audio-only sync check vs ffmpeg silence detection |
| `scripts/build_srt.py`, `scripts/mux.py` | SRT + soft track (stream copy) or `--burn` |

Intermediate files live in `work/<video name>/` (git-ignored). Delete that folder to start over.

## Whisper models (CPU int8)
`large-v3-turbo` is the default: near large-v3 accuracy at a fraction of the cost. On this machine (12 logical CPUs, no GPU) it measured ≈0.6× real time, so a 1-hour class takes about 35–40 min. Alternatives: `small`/`medium` (faster), `large-v3` (best, ≈2–3× slower). Changing the model or the glossary invalidates the cached chunks automatically.

The first run downloads the model once. After that, set `HF_HUB_OFFLINE=1` to guarantee zero network use.

## Token cost (1-hour class, ~700–800 cues)
- The translated text itself is only ~35–45k tokens. Each subagent also has a fixed overhead: its system prompt is re-sent on every tool turn, and most of it is cached input.
- In tests with general-purpose agents (heavier than `tradutor-legendas`), one agent used ~72–74k tokens whether it translated 57 or 150 cues.
- That is why batches are 300 cues: about 3 agents per hour of class, so roughly ≤ 225k subagent tokens, mostly cache reads.
- The main session itself uses only a few thousand tokens.

## Troubleshooting
- Drift/odd timing: `prepare --model large-v3 --force`, then inspect with `scripts/check_sync.py`.
- Subtitle track not shown: use `finish --burn`, or load the sidecar `.pt.srt`.
- `--batch-size 8` (batched decoding) is faster but **dropped whole sentences and produced stretched timestamps in tests**. It's kept only as an opt-in. The default is sequential decoding.
- "timing-anomaly cues" in the prepare output: Whisper stretched a word over audio it couldn't recognise (cough, music, crosstalk). The word is trimmed automatically. Give those moments a quick listen.
