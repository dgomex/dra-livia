/*
 * Drive video ES → PT-BR captions  (v1.1)
 *
 * For recorded classes played in Google Drive's own video player, including
 * files whose owner turned off downloads: we only read the captions the
 * player already loads to show on screen.
 *
 * A recording's caption file is complete before playback starts, so:
 *  - hook.js captures the caption file when the player fetches it,
 *  - every caption is translated ahead of playback,
 *  - the box shows the translation of exactly the caption the player is
 *    showing (same text, same moment, speaker on top), following the video's
 *    current time. Seeking, pausing and speed changes just work.
 *
 * Frames: Drive's player lives in an iframe, where Chrome's Translator API is
 * not allowed and a box could not leave the player's area. So the top Drive
 * page ("hub") translates and draws the box anywhere on screen, while the
 * frame with the <video> ("player") decides what to show. In fullscreen only
 * the player frame is visible, so the player draws its own box there. They
 * talk via postMessage. If no hub answers (player embedded in some other
 * site), the player frame does everything itself.
 */
(() => {
  if (window.__dvtrLoaded) return;
  window.__dvtrLoaded = true;

  const { parseTrack, endsSentence } = window.DVTR_CAPTIONS;
  const DEFAULT_SRC = "es"; // used when the caption URL doesn't name its language
  const TGT = "pt"; // Chrome's "pt" model is Brazilian Portuguese
  const PIVOT = "en"; // used only if Chrome has no direct src->pt model
  const IS_TOP = window === window.top;
  const LOG = (...a) => console.log("[dvtr]", ...a);

  // ---------- messaging ----------
  const PFX = Math.random().toString(36).slice(2) + ":";
  let seq = 0;
  const pending = new Map();
  let hubWin = window.top;

  function call(op, data, timeout) {
    return new Promise((res, rej) => {
      const id = PFX + ++seq;
      pending.set(id, { res, rej });
      hubWin.postMessage({ dvtr: "req", id, op, ...data }, "*");
      if (timeout) setTimeout(() => pending.delete(id) && rej(new Error("timeout")), timeout);
    });
  }

  window.addEventListener("message", (ev) => {
    const m = ev.data;
    if (!m || typeof m !== "object" || typeof m.dvtr !== "string") return;
    if (m.dvtr === "req" && hub.serving && ev.source) {
      const from = ev.source;
      hubHandle(m, from).then(
        (value) => from.postMessage({ dvtr: "res", id: m.id, ok: true, value }, "*"),
        (err) => from.postMessage({ dvtr: "res", id: m.id, ok: false, error: String((err && err.message) || err) }, "*")
      );
    } else if (m.dvtr === "res") {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.ok) p.res(m.value);
      else p.rej(new Error(m.error));
    } else if (m.dvtr === "push" && ev.source === hubWin) {
      onPush(m);
    }
  });

  // ---------- hub: translation and on-screen box (top frame) ----------
  const hub = {
    serving: IS_TOP,
    players: new Set(), // windows that receive status/track pushes
    track: null, // { url, text }: last caption file seen in this tab
    engines: new Map(), // src -> Promise<(text) => Promise<text>>
    cache: new Map(),
    view: null, // Promise<overlay> drawn here for a player in a child frame
    viewOwner: null,
  };

  async function availability(source, target) {
    try {
      return await Translator.availability({ sourceLanguage: source, targetLanguage: target });
    } catch {
      return "unavailable";
    }
  }

  /** "available" | "downloadable" | "unavailable" | "noapi" for src -> pt (direct or via English). */
  async function pairState(src) {
    if (typeof Translator === "undefined") return "noapi";
    const direct = await availability(src, TGT);
    if (direct !== "unavailable") return direct === "available" ? "available" : "downloadable";
    if (src === PIVOT) return "unavailable";
    const a = await availability(src, PIVOT);
    const b = await availability(PIVOT, TGT);
    if (a === "unavailable" || b === "unavailable") return "unavailable";
    return a === "available" && b === "available" ? "available" : "downloadable";
  }

  function push(msg) {
    for (const w of hub.players) {
      try {
        w.postMessage({ dvtr: "push", ...msg }, "*");
      } catch {
        hub.players.delete(w);
      }
    }
  }

  function createTranslator(source, target) {
    return Translator.create({
      sourceLanguage: source,
      targetLanguage: target,
      monitor(m) {
        m.addEventListener("downloadprogress", (e) => {
          const pct = Math.round((e.loaded || 0) * 100);
          push({ kind: "status", msg: `Baixando modelo de tradução ${source}→${target}: ${pct}%` });
        });
      },
    });
  }

  function engine(src) {
    let p = hub.engines.get(src);
    if (p) return p;
    p = (async () => {
      if (typeof Translator === "undefined") {
        throw new Error("Este Chrome não tem a Translator API. Atualize o Chrome (versão 138 ou superior).");
      }
      let chain;
      if ((await availability(src, TGT)) !== "unavailable") {
        chain = [await createTranslator(src, TGT)];
      } else if (
        src !== PIVOT &&
        (await availability(src, PIVOT)) !== "unavailable" &&
        (await availability(PIVOT, TGT)) !== "unavailable"
      ) {
        LOG(`direct ${src}->pt unavailable, pivoting through`, PIVOT);
        chain = [await createTranslator(src, PIVOT), await createTranslator(PIVOT, TGT)];
      } else {
        throw new Error(`Par de idiomas ${src}→português indisponível neste Chrome.`);
      }
      LOG("translator ready", src, chain.length === 1 ? "direct" : "pivot");
      return async (text) => {
        let t = text;
        for (const tr of chain) t = await tr.translate(t);
        return t;
      };
    })();
    hub.engines.set(src, p);
    p.catch(() => hub.engines.delete(src)); // allow a retry
    return p;
  }

  async function hubHandle(m, from) {
    switch (m.op) {
      case "hello":
        hub.players.add(from);
        return hub.track;
      case "state":
        return pairState(m.src);
      case "start":
        await engine(m.src);
        return true;
      case "translate": {
        const key = m.src + "|" + m.text;
        let out = hub.cache.get(key);
        if (out === undefined) {
          out = await (await engine(m.src))(m.text);
          hub.cache.set(key, out);
          if (hub.cache.size > 3000) hub.cache.delete(hub.cache.keys().next().value);
        }
        return out;
      }
      case "track":
        if (!hub.track || hub.track.text !== m.text) {
          hub.track = { url: m.url, text: m.text };
          push({ kind: "track", ...hub.track });
        }
        return true;
      case "view":
        if (m.state) hub.viewOwner = from;
        if (!hub.view && !m.state) return true;
        if (!hub.view) {
          hub.view = createOverlay("dvtr", () => {
            if (hub.viewOwner) hub.viewOwner.postMessage({ dvtr: "push", kind: "activate" }, "*");
          });
        }
        (await hub.view).update(m.state);
        return true;
    }
    throw new Error("unknown op " + m.op);
  }

  // ---------- capture: caption files seen by hook.js in this frame ----------
  document.addEventListener("dvtr-track", (e) => {
    let d;
    try {
      d = JSON.parse(e.detail);
      d.url = new URL(d.url, location.href).href;
    } catch {
      return;
    }
    LOG("caption file captured", d.url.slice(0, 160), d.text.length, "chars");
    call("track", { url: d.url, text: d.text }).catch(() => {});
  });

  // ---------- overlay box (built in whichever frame draws it) ----------
  // `key` names its saved size/position, so the box on the Drive page and the
  // one in fullscreen each remember their own place.
  async function createOverlay(key, onStart) {
    const settings = { x: null, y: null, size: 22, collapsed: false };
    await new Promise((res) => {
      try {
        chrome.storage.local.get(key, (r) => {
          Object.assign(settings, (r && r[key]) || {});
          res();
        });
      } catch {
        res();
      }
    });
    const save = () => {
      try {
        chrome.storage.local.set({ [key]: settings });
      } catch {}
    };

    const el = (tag, cls, text) => {
      const n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text) n.textContent = text;
      return n;
    };

    const root = el("div");
    root.id = "dvtr-root";
    const head = el("div", "dvtr-head");
    head.appendChild(el("span", "dvtr-title", "Legendas → PT-BR"));

    const startBtn = el("button", "dvtr-btn", "Ativar");
    startBtn.title = "Iniciar a tradução (baixa o modelo na primeira vez)";
    startBtn.addEventListener("click", () => {
      startBtn.style.display = "none";
      onStart();
    });
    const smaller = el("button", "dvtr-btn", "A−");
    const bigger = el("button", "dvtr-btn", "A+");
    const fold = el("button", "dvtr-btn", "–");
    fold.title = "Recolher/expandir";
    smaller.addEventListener("click", () => setSize(settings.size - 2));
    bigger.addEventListener("click", () => setSize(settings.size + 2));
    fold.addEventListener("click", () => {
      settings.collapsed = !settings.collapsed;
      save();
      apply();
    });
    for (const b of [startBtn, smaller, bigger, fold]) {
      b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
      head.appendChild(b);
    }

    const statusEl = el("div", "dvtr-status");
    const frame = el("div", "dvtr-frame");
    const speakerEl = el("div", "dvtr-speaker");
    const textEl = el("div", "dvtr-text");
    frame.append(speakerEl, textEl);
    root.append(head, statusEl, frame);

    function setSize(px) {
      settings.size = Math.max(12, Math.min(48, px));
      save();
      apply();
    }

    function apply() {
      root.style.setProperty("--dvtr-size", settings.size + "px");
      root.classList.toggle("dvtr-collapsed", !!settings.collapsed);
      if (settings.x !== null && settings.y !== null) {
        root.classList.add("dvtr-moved");
        root.style.left = clamp(settings.x, window.innerWidth - root.offsetWidth) + "px";
        root.style.top = clamp(settings.y, window.innerHeight - root.offsetHeight) + "px";
      }
    }

    // Keep the whole box on screen.
    const clamp = (v, max) => Math.max(0, Math.min(Math.max(0, max), v));

    // Keep the box inside the fullscreen element, or it would be hidden. When
    // the fullscreen element is a frame, the box drawn inside that frame shows.
    function mount() {
      const fs = document.fullscreenElement;
      const host = fs && !/^(VIDEO|IFRAME)$/.test(fs.tagName) ? fs : document.documentElement;
      if (root.parentNode !== host) host.appendChild(root);
      apply();
    }
    document.addEventListener("fullscreenchange", mount);

    head.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      const r = root.getBoundingClientRect();
      const dx = ev.clientX - r.left;
      const dy = ev.clientY - r.top;
      head.setPointerCapture(ev.pointerId);
      const move = (mv) => {
        settings.x = clamp(mv.clientX - dx, window.innerWidth - root.offsetWidth);
        settings.y = clamp(mv.clientY - dy, window.innerHeight - root.offsetHeight);
        apply();
      };
      const up = () => {
        head.removeEventListener("pointermove", move);
        head.removeEventListener("pointerup", up);
        head.removeEventListener("pointercancel", up);
        save();
      };
      head.addEventListener("pointermove", move);
      head.addEventListener("pointerup", up);
      head.addEventListener("pointercancel", up);
    });

    mount();
    return {
      /** state: { status, showStart, speaker, text, pending } or null to hide */
      update(s) {
        root.style.display = s ? "" : "none";
        if (!s) return;
        statusEl.textContent = s.status || "";
        startBtn.style.display = s.showStart ? "" : "none";
        speakerEl.textContent = s.speaker ? s.speaker + ":" : "";
        textEl.textContent = s.text || "";
        textEl.classList.toggle("dvtr-pending", !!s.pending);
        mount();
      },
    };
  }

  // ---------- player: the caption on screen, translated ----------
  let video = null;
  let cues = []; // { t, end, speaker, es, pt, prevEnded }
  let src = DEFAULT_SRC;
  let trackText = "";
  let trackGen = 0;
  let engineState = "idle"; // idle | loading | ready | error
  let pumping = false;
  let shownIdx = -2;
  let statusMsg = "";
  let hint = "";
  let showStart = false;

  function langOf(url) {
    try {
      const q = new URL(url, location.href).searchParams;
      const l = q.get("tlang") || q.get("lang");
      if (l) return l.toLowerCase().split(/[-_]/)[0];
    } catch {}
    return DEFAULT_SRC;
  }

  /** Make a caption that continues the previous one read as a continuation. */
  function tidy(es, out, prevEnded) {
    if (!endsSentence(es)) out = out.replace(/[.!?…]+\s*$/, "");
    if (!prevEnded && /^[a-záéíóúñü]/.test(es) && out) out = out.charAt(0).toLowerCase() + out.slice(1);
    return out.trim();
  }

  function setTrack(url, text) {
    if (!text || text === trackText) return;
    const parsed = parseTrack(text);
    if (!parsed.length) return;
    trackText = text;
    trackGen++;
    cues = parsed.map((c, i) => ({
      t: c.t,
      end: c.end,
      speaker: c.speaker,
      es: c.text,
      pt: "",
      prevEnded: i === 0 || parsed[i - 1].speaker !== c.speaker || endsSentence(parsed[i - 1].text),
    }));
    const lang = langOf(url);
    LOG("track loaded:", cues.length, "captions, language", lang);
    hint = "";
    shownIdx = -2;
    if (lang !== src) {
      src = lang;
      engineState = "idle";
      showStart = false;
      checkEngine();
    }
    pump();
    present();
  }

  function onPush(m) {
    if (m.kind === "status") {
      statusMsg = m.msg;
      present();
    } else if (m.kind === "track") {
      setTrack(m.url, m.text);
    } else if (m.kind === "activate") {
      activate();
    }
  }

  /** Index of the last caption started by now, or -1 before the first one. */
  function curIndex() {
    if (!video || !cues.length) return -1;
    const now = video.currentTime * 1000;
    let lo = 0;
    let hi = cues.length - 1;
    let ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (cues[mid].t <= now) {
        ans = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return ans;
  }

  /** The caption the player is showing right now, if any. */
  function activeCue() {
    const i = curIndex();
    const c = cues[i];
    return c && video.currentTime * 1000 < c.end ? c : null;
  }

  /** Untranslated caption to do next: the current one, then ahead, then behind. */
  function nextToTranslate() {
    const from = Math.max(0, curIndex());
    for (let k = from; k < cues.length; k++) if (!cues[k].pt) return cues[k];
    for (let k = from - 1; k >= 0; k--) if (!cues[k].pt) return cues[k];
    return null;
  }

  async function pump() {
    if (pumping || engineState !== "ready") return;
    pumping = true;
    try {
      for (;;) {
        const c = nextToTranslate();
        if (!c) break;
        const gen = trackGen;
        let out;
        if (src === TGT) out = c.es;
        else {
          try {
            out = await call("translate", { src, text: c.es });
          } catch (err) {
            LOG("translate error", err);
            out = c.es; // never block the flow: show the original caption instead
          }
        }
        if (gen !== trackGen) continue;
        c.pt = tidy(c.es, out, c.prevEnded) || c.es;
        if (c === activeCue()) present();
      }
    } finally {
      pumping = false;
    }
  }

  async function checkEngine() {
    if (src === TGT) {
      engineState = "ready";
      pump();
      return;
    }
    let st;
    try {
      st = await call("state", { src });
    } catch {
      st = "unavailable";
    }
    if (st === "available") startEngine();
    else if (st === "downloadable") {
      statusMsg = "Clique em “Ativar” para baixar o modelo de tradução (só na primeira vez).";
      showStart = true;
    } else if (st === "noapi") {
      statusMsg = "Este Chrome não tem a Translator API. Atualize o Chrome (versão 138 ou superior).";
    } else {
      statusMsg = `Par de idiomas ${src}→português indisponível neste Chrome.`;
    }
    present();
  }

  function activate() {
    engineState = "idle"; // allow retry; the click counts as user activation
    showStart = false;
    startEngine();
  }

  async function startEngine() {
    if (engineState === "loading" || engineState === "ready") return;
    engineState = "loading";
    statusMsg = "Preparando tradução…";
    present();
    const forSrc = src;
    try {
      await call("start", { src: forSrc });
      if (forSrc !== src) return;
      engineState = "ready";
      statusMsg = "";
      present();
      pump();
    } catch (err) {
      if (forSrc !== src) return;
      engineState = "error";
      LOG("engine error", err);
      statusMsg =
        "Não foi possível iniciar a tradução: " +
        (err && err.message ? err.message : err) +
        " — clique em “Ativar” para tentar de novo.";
      showStart = true;
      present();
    }
  }

  // ---------- presenting: box on the Drive page, or in this frame in fullscreen ----------
  let localView = null; // Promise<overlay> drawn in this frame
  let lastKey = "";
  let sentToHub = false;

  async function present() {
    const c = activeCue();
    const s = {
      status: statusMsg || hint,
      showStart,
      speaker: c ? c.speaker : "",
      text: c ? c.pt || c.es : "",
      pending: !!c && !c.pt,
    };
    const local = hubWin === window || !!document.fullscreenElement;
    const key = local + JSON.stringify(s);
    if (key === lastKey) return;
    lastKey = key;
    if (local) {
      if (sentToHub) {
        sentToHub = false;
        call("view", { state: null }).catch(() => {});
      }
      if (!localView) localView = createOverlay("dvtrFrame", activate);
      (await localView).update(s);
    } else {
      if (localView) (await localView).update(null);
      sentToHub = true;
      call("view", { state: s }).catch(() => {});
    }
  }

  function tick() {
    if (!video) return;
    const i = curIndex();
    if (i !== shownIdx) {
      shownIdx = i;
      pump();
    }
    present();
  }

  // ---------- wiring ----------
  function findVideo() {
    let best = null;
    let area = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      if (r.width * r.height > area) {
        best = v;
        area = r.width * r.height;
      }
    }
    return area > 20000 ? best : null;
  }

  async function startPlayer() {
    let track;
    try {
      track = await call("hello", {}, 2500);
    } catch {
      // No Drive page above us: translate and draw in this frame.
      LOG("no hub answered, translating in this frame");
      hubWin = window;
      hub.serving = true;
      track = await call("hello", {});
    }
    document.addEventListener("fullscreenchange", present);
    setInterval(tick, 100);
    if (track) setTrack(track.url, track.text);
    checkEngine();
    setTimeout(() => {
      if (!cues.length) {
        hint = "Ative as legendas (CC) do vídeo e escolha Espanhol. Se já estavam ativas, desative e ative de novo.";
        present();
      }
    }, 5000);
  }

  let started = false;
  setInterval(() => {
    if (video && video.isConnected) return;
    const v = findVideo();
    if (!v) return;
    video = v;
    shownIdx = -2;
    if (!started) {
      started = true;
      startPlayer();
    }
  }, 1000);
})();
