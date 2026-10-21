/*
 * Caption file parsing: turns a raw caption file (json3, srv3/srv1 XML or
 * WebVTT) into the same cues the player shows, one per caption on screen.
 *
 * Kept free of DOM/Chrome APIs so it can be tested with plain Node.
 */
(() => {
  const STRONG = /[.!?…]["”')\]]*$/;
  // Drive puts the speaker on the first line: "(Amanda Kalil Souza)\nBuenas tardes…"
  const SPEAKER = /^\s*[([]([^)\]\n]{1,60})[)\]]\s*\n/;

  /** Raw caption file -> [{ t, end, speaker, text }] (ms), in time order. */
  function parseTrack(raw) {
    const s = String(raw || "")
      .replace(/^\)\]\}'\s*/, "")
      .trim();
    let out = [];
    if (s[0] === "{") out = parseJson3(s);
    else if (/^WEBVTT/.test(s)) out = parseVtt(s);
    else if (s[0] === "<") out = parseXml(s);
    out = out
      .map(withSpeaker)
      .filter((c) => c.text)
      .sort((a, b) => a.t - b.t);
    out.forEach((c, i) => {
      if (c.end <= c.t) c.end = out[i + 1] ? out[i + 1].t : c.t + 4000;
    });
    return out;
  }

  function withSpeaker(c) {
    const m = c.text.match(SPEAKER);
    return {
      t: c.t,
      end: c.end,
      speaker: m ? m[1].trim() : "",
      text: (m ? c.text.slice(m[0].length) : c.text).replace(/\s+/g, " ").trim(),
    };
  }

  function parseJson3(s) {
    let data;
    try {
      data = JSON.parse(s);
    } catch {
      return [];
    }
    const out = [];
    for (const ev of data.events || []) {
      if (!ev.segs) continue;
      const text = ev.segs.map((seg) => seg.utf8 || "").join("");
      if (!text.trim()) continue;
      const t = ev.tStartMs || 0;
      out.push({ t, end: t + (ev.dDurationMs || 0), text });
    }
    return out;
  }

  function parseXml(s) {
    const out = [];
    const re = /<(p|text)\b([^>]*)>([\s\S]*?)<\/\1>/g;
    let m;
    while ((m = re.exec(s))) {
      const a = attrs(m[2]);
      const ms = m[1] === "p"; // srv3 uses ms, srv1 uses seconds
      const t = ms ? +a.t || 0 : Math.round(parseFloat(a.start || 0) * 1000);
      const d = ms ? +a.d || 0 : Math.round(parseFloat(a.dur || 0) * 1000);
      const text = decode(m[3].replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, ""));
      out.push({ t, end: t + d, text });
    }
    return out;
  }

  function parseVtt(s) {
    const out = [];
    for (const block of s.replace(/\r/g, "").split(/\n\s*\n/)) {
      const lines = block.split("\n");
      const i = lines.findIndex((l) => l.includes("-->"));
      if (i < 0) continue;
      const [a, z] = lines[i].split("-->");
      const text = decode(
        lines
          .slice(i + 1)
          .join("\n")
          .replace(/<[^>]+>/g, "")
      );
      out.push({ t: vttTime(a), end: vttTime(z), text });
    }
    return out;
  }

  function vttTime(x) {
    const m = String(x).trim().match(/^(?:(\d+):)?(\d+):(\d+)[.,](\d+)/);
    if (!m) return 0;
    return ((+m[1] || 0) * 3600 + +m[2] * 60 + +m[3]) * 1000 + Math.round(+("0." + m[4]) * 1000);
  }

  function attrs(str) {
    const a = {};
    const re = /([\w:-]+)\s*=\s*"([^"]*)"/g;
    let m;
    while ((m = re.exec(str))) a[m[1]] = m[2];
    return a;
  }

  function decode(str) {
    const once = (x) =>
      x
        .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
        .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, "'")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&");
    let out = once(str);
    if (/&(#\d+|#x[0-9a-f]+|quot|apos|lt|gt|amp);/i.test(out)) out = once(out); // srv1 is often double-encoded
    return out;
  }

  const endsSentence = (s) => STRONG.test(String(s).trim());

  const api = { parseTrack, endsSentence };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.DVTR_CAPTIONS = api;
})();
