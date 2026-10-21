# Meet ES → PT-BR Captions

Chrome extension that translates Google Meet's Spanish captions into Brazilian
Portuguese, in near real time, entirely on-device (Chrome's built-in Translator
API). No servers, no API keys, no data leaves the browser.

## Install
1. Chrome 138+ → open `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select this folder

## Use
1. Join a Meet call, click **CC** and set the spoken language to **Spanish**.
2. An overlay "Legendas ES → PT-BR" appears. First time only: click **Ativar**
   to download the translation model (Chrome requires a click for this).
3. Drag the header to move it. `A−` / `A+` change font size, `↕` cycles the
   box height (3 / 5 / 8 lines), `–` collapses it.
4. The box shows a fixed number of lines and never scrolls. When it is full,
   the oldest line disappears from the top and new text appears on the last
   line.
5. Append-only: translated text already on screen is never changed, even if
   Meet later corrects its own caption.
6. The preset button (in the header) trades speed for quality:
   - **Rápido**: ~6-word chunks, ~1-2 s behind. Roughest translation.
   - **Equilibrado** (default): prints at the end of a sentence, or at a comma
     after 9+ words, or after a 1 s pause, never more than 22 words. ~2-5 s behind.
   - **Preciso**: full sentences only (pause of 1.4 s or 30 words as fallback).
     Best translation, longest lag.

## Notes
- Meet's own captions are left untouched; the overlay only reads them and shows Portuguese.
- Uses the direct es→pt model; if Chrome lacks it, pivots es→en→pt (still local).
- If Meet changes its caption markup, the selectors in `findRegion()` /
  `getBlocks()` in `content.js` are the only place to adjust.
- Debug logs are prefixed `[mptbr]` in the DevTools console.

## See also
- `drive-video/`: separate extension for recorded videos played in Google Drive.
