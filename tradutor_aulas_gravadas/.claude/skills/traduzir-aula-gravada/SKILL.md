---
name: traduzir-aula-gravada
description: Add Portuguese (pt-BR) subtitles to a recorded class video whose audio is in Spanish. Fully local transcription and timing (no upload, no vision on the video); only the Spanish text is translated, by parallel subagents. Use when the user gives a video file (mp4/mkv/mov/...) and wants it subtitled/translated from Spanish to Portuguese. Handles long (1h+) videos.
---

# Traduzir aula gravada (ES → PT-BR subtitles)

Run every command from the project root `tradutor_aulas_gravadas/`. `PY` = `.venv\Scripts\python.exe`. `<video>` = absolute path, quoted.

## Hard rules (privacy + tokens)
- NEVER upload the video, extract frames, or look at the video. Timing comes only from local audio analysis.
- The main session NEVER reads the Spanish or Portuguese text in bulk. Translation is done by `tradutor-legendas` subagents that read and write files themselves. The main session reads only short script output.
- Don't read `words.json`, `cues.es.json`, `chunks/`, batch files or the `.srt`.

## Workflow
1. **Setup (first time only).** Run `python scripts/setup.py --check`. If it prints MISSING, run `python scripts/setup.py`.
2. **Glossary (optional).** If the user gives technical terms, add `espanhol = português` lines to `glossario.txt`. They're used to steer Whisper's spelling and to keep the translation consistent across batches.
3. **Prepare (local, 0 tokens). Run it in the background:**
   `PY scripts\run_pipeline.py prepare "<video>"`
   - Use Bash `run_in_background: true` and wait for the completion notification. Don't poll in a loop. If the user asks for progress, read only the last 3 lines of `work/<name>/progress.log`.
   - A 1-hour video takes about 35–40 min on this CPU (measured ≈0.6× real time). Tell the user the ETA the log shows after the first few minutes.
   - Don't pass `--batch-size` above 1: batched decoding dropped speech in tests.
   - It's resumable: if it's interrupted, run the same command again and finished 10-minute chunks are skipped.
   - Model: default `large-v3-turbo`. Use `--model medium` or `small` for speed; `--model large-v3` for maximum accuracy (≈2–3× slower).
   - Output (short): cue count, number of batches, low-confidence cue IDs, timing-anomaly cue IDs and sync-suspicious cue IDs. Pass the anomaly and sync IDs on to the user in the final report as spots worth a listen.
4. **Translate: launch subagents in parallel.** In a single message, make one `Agent` call per batch (`subagent_type: "tradutor-legendas"`), all with `run_in_background: false`. If there are more than 8 batches, send waves of 8. Prompt for each, and nothing more:
   `Entrada: <abs>\work\<name>\batches\in_NN.txt  Saída: <abs>\work\<name>\batches\out_NN.txt`
   (The glossary is already embedded in each batch file. If you edit `glossario.txt` after `prepare`, re-split with `PY scripts\batches.py split "<video>"`.)
   Each agent replies with one line. If agents report `incerto:` terms, choose one rendering. If the batches disagree, add it to `glossario.txt` and re-run only the affected batches.
5. **Merge + validate:** `PY scripts\run_pipeline.py merge "<video>"`
   - If batches are incomplete, re-run the agent for those batch numbers only, then merge again.
   - If a few cues are flagged (too long or too fast), fix them yourself: edit those lines in `work/<name>/translated.txt`, shortening to the char limit shown. Then run `PY scripts\validate.py "<video>"` until it prints `OK`. Don't re-run `merge` after manual edits, because it would overwrite them.
6. **Finish:** `PY scripts\run_pipeline.py finish "<video>" [--burn]`
   - Default: a soft Portuguese subtitle track, with video and audio stream-copied (takes seconds). This gives `<video>.pt.mp4` (or `.pt.mkv`) plus a sidecar `<video>.pt.srt` next to the original.
   - `--burn`: subtitles hard-coded into the picture, which needs a full re-encode (about as long as the video on CPU; run it in the background). This gives `<video>.pt.burned.mp4`.
7. **Report briefly:** output paths, cue count, and any low-confidence or sync-suspicious IDs worth a listen.

## Timing guarantees
Cue times come only from faster-whisper word timestamps with VAD. Translation never touches times, because the scripts re-attach the text by cue ID. Chunks are cut at the quietest point near each 10-minute mark, so no word is split. Cues break at pauses and punctuation, are padded 50 ms before and 150 ms after speech, and are clamped to their neighbours. `scripts\check_sync.py` cross-checks cue boundaries against ffmpeg silence detection. If the user reports drift, run `prepare ... --model large-v3 --force` and redo steps 4–6.
