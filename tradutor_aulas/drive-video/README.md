# Drive Vídeo ES → PT-BR Captions

Chrome extension that translates the Spanish captions of a video played in
Google Drive's own player into Brazilian Portuguese, synced with the video,
entirely on-device (Chrome's built-in Translator API). No servers, no API keys,
no data leaves the browser.

It works on files whose owner turned off downloads: it never downloads the
video, it only reads the caption file the player already loads to show captions.

## Install
1. Chrome 138+ → open `chrome://extensions`
2. Turn on **Developer mode**
3. **Load unpacked** → select this `drive-video` folder (separate from the Meet
   extension in the parent folder; both can be installed at the same time)

## Use
1. Open the video in Google Drive and turn on captions (**CC**), choosing
   **Spanish** if the player offers several languages.
   If CC was already on before the extension was installed, turn it off and on
   again (or reload the page) so the player fetches the captions again.
2. An overlay "Legendas → PT-BR" appears over the player. First time only:
   click **Ativar** to download the translation model (Chrome requires a click).
3. Play the video. The box shows the translation of exactly the caption the
   player is showing, speaker name on top, and changes when the CC changes.
   Seeking, pausing and playback speed changes follow automatically.
4. Drag the header to move the box anywhere on the Drive page (it is not tied
   to the player area). `A−` / `A+` change font size, `–` collapses it.
   The position is remembered. Fullscreen is supported.
5. A caption not translated yet shows briefly in Spanish, dimmed and in italics.

## How it works
- `hook.js` (page world, runs first) watches the player's network requests and
  passes any caption file it receives (json3, srv3/srv1 XML or WebVTT) to the
  extension. The response the player gets is unchanged.
- `captions.js` parses the file into the same cues the player shows, and
  splits off the speaker line Drive adds, e.g. `(Amanda Kalil Souza)`.
- `content.js` translates every cue ahead of playback, starting from the
  current position, and shows the active one in sync with `video.currentTime`.
- The player sits in an iframe where Chrome does not allow the Translator API
  and a box could not leave the player's area. So the player frame decides
  what to show, and the top Drive page translates and draws the box; they talk
  with `postMessage`. If the player frame itself goes fullscreen, it draws its
  own box.

Each cue is translated on its own (Drive cuts sentences into 4-second pieces),
so the text matches the CC exactly; the price is that a cue cut mid-sentence
is translated without the rest of its sentence.

## Notes
- Source language is read from the caption request (`lang=`), Spanish if absent.
  Portuguese captions are shown as they are.
- Debug logs are prefixed `[dvtr]` in the DevTools console (choose the player's
  iframe in the console's context menu to see the player side). A
  `caption file captured` line confirms the captions were picked up.
