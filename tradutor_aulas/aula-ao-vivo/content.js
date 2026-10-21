/*
 * Meet ES → PT-BR captions  (v1.5 — append-only, fast)
 *
 * Reads Google Meet's own (Spanish) captions and shows a Brazilian Portuguese
 * translation in an overlay. Translation runs fully on-device through Chrome's
 * built-in Translator API: no servers, no keys.
 *
 * Pace over polish:
 *  - New words are translated in chunks and APPENDED. Printed text is never
 *    changed, even if Meet later corrects its own caption. A preset (Rápido /
 *    Equilibrado / Preciso) sets how much of the sentence is waited for.
 *  - The box has a fixed number of lines. When it is full the oldest line is
 *    dropped from the top and new text appears on the last line. No scrolling.
 */
(() => {
  if (window.__mptbrLoaded) return;
  window.__mptbrLoaded = true;

  const SRC = "es";
  const TGT = "pt"; // Chrome's "pt" model is Brazilian Portuguese
  const PIVOT = "en"; // used only if Chrome has no direct es->pt model
  const CAPTION_LABEL = /caption|legenda|subt[ií]tulo|sous-titre|untertitel/i;

  // How long to wait before printing a chunk. Quality needs context; context
  // needs waiting. strongMin/weakMin = min words before ending a chunk at a
  // sentence end (. ! ?) / at a comma (, ; :). cap = hard limit of words per
  // chunk. idle = speaker pause (ms) that flushes whatever is waiting.
  const PRESETS = {
    fast: { label: "Rápido", strongMin: 3, weakMin: 3, cap: 6, idle: 600 },
    balanced: { label: "Equilibrado", strongMin: 1, weakMin: 9, cap: 22, idle: 1000 },
    precise: { label: "Preciso", strongMin: 1, weakMin: Infinity, cap: 30, idle: 1400 },
  };
  const preset = () => PRESETS[settings.preset] || PRESETS.balanced;
  const MAX_LOG = 300; // chunks kept in memory
  const LOG = (...a) => console.log("[mptbr]", ...a);

  // ---------- settings (chrome.storage.local, best effort) ----------
  const settings = { x: null, y: null, size: 20, lines: 5, collapsed: false, preset: "balanced" };
  const store = {
    load() {
      return new Promise((res) => {
        try {
          chrome.storage.local.get("mptbr", (r) => {
            Object.assign(settings, (r && r.mptbr) || {});
            res();
          });
        } catch {
          res();
        }
      });
    },
    save() {
      try {
        chrome.storage.local.set({ mptbr: settings });
      } catch {}
    },
  };

  // ---------- translation engine ----------
  let translate = null; // async (text) => text
  let engineState = "idle"; // idle | loading | ready | error
  const cache = new Map();

  async function availability(source, target) {
    try {
      return await Translator.availability({ sourceLanguage: source, targetLanguage: target });
    } catch {
      return "unavailable";
    }
  }

  async function createTranslator(source, target) {
    return Translator.create({
      sourceLanguage: source,
      targetLanguage: target,
      monitor(m) {
        m.addEventListener("downloadprogress", (e) => {
          const pct = Math.round((e.loaded || 0) * 100);
          setStatus(`Baixando modelo de tradução ${source}→${target}: ${pct}%`);
        });
      },
    });
  }

  async function startEngine() {
    if (engineState === "loading" || engineState === "ready") return;
    if (typeof Translator === "undefined") {
      engineState = "error";
      setStatus("Este Chrome não tem a Translator API. Atualize o Chrome (versão 138 ou superior).");
      return;
    }
    engineState = "loading";
    setStatus("Preparando tradução…");
    try {
      let chain;
      if ((await availability(SRC, TGT)) !== "unavailable") {
        chain = [await createTranslator(SRC, TGT)];
      } else if (
        (await availability(SRC, PIVOT)) !== "unavailable" &&
        (await availability(PIVOT, TGT)) !== "unavailable"
      ) {
        LOG("direct es->pt unavailable, pivoting through", PIVOT);
        chain = [await createTranslator(SRC, PIVOT), await createTranslator(PIVOT, TGT)];
      } else {
        throw new Error("Par de idiomas espanhol→português indisponível neste Chrome.");
      }
      translate = async (text) => {
        let t = text;
        for (const tr of chain) t = await tr.translate(t);
        return t;
      };
      engineState = "ready";
      setStatus("");
      LOG("translator ready", chain.length === 1 ? "direct" : "pivot");
      for (const it of log) if (!it.pt) translateItem(it);
    } catch (err) {
      engineState = "error";
      LOG("engine error", err);
      setStatus(
        "Não foi possível iniciar a tradução: " +
          (err && err.message ? err.message : err) +
          " — clique em “Ativar” para tentar de novo."
      );
      showStartButton(true);
    }
  }

  async function xlate(text) {
    let out = cache.get(text);
    if (out === undefined) {
      out = await translate(text);
      cache.set(text, out);
      if (cache.size > 800) cache.delete(cache.keys().next().value);
    }
    return out;
  }

  // ---------- text helpers ----------
  function norm(str) {
    return str
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  const ENDS_SENTENCE = /[.!?…]["”')\]]*\s*$/;

  /** Make a chunk read naturally when glued after the previous one. */
  function tidy(src, out, prevEnded) {
    if (!ENDS_SENTENCE.test(src)) out = out.replace(/[.!?…]+\s*$/, "");
    if (!prevEnded && /^[a-záéíóúñü]/.test(src) && out) out = out.charAt(0).toLowerCase() + out.slice(1);
    return out.trim();
  }

  // ---------- caption model ----------
  /** Printed chunks, in order. Append-only: an item is never edited once shown. */
  const log = []; // { speaker, es, pt, prevEnded, ticket }
  /** One state per speaker block currently present in Meet's caption area. */
  const blocks = new Map(); // element -> { speaker, text, last: [normalized words], idleTimer }

  function findRegion() {
    for (const r of document.querySelectorAll('[role="region"][aria-label]')) {
      if (CAPTION_LABEL.test(r.getAttribute("aria-label") || "")) return r;
    }
    return null;
  }

  /** Pick the container whose children look most like per-speaker blocks. */
  function getBlocks(region) {
    let best = null;
    let bestScore = 0;
    for (const c of [region, ...region.querySelectorAll("div")]) {
      let score = 0;
      for (const ch of c.children) if (ch.querySelector("img")) score++;
      if (score > bestScore) {
        best = c;
        bestScore = score;
      }
    }
    const kids = best ? [...best.children] : [...region.children];
    return kids.filter((k) => !k.matches('button,[role="button"]') && (k.innerText || "").trim());
  }

  function parseBlock(el) {
    const lines = (el.innerText || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (el.querySelector("img") && lines.length > 1) {
      return { speaker: lines[0], text: lines.slice(1).join(" ") };
    }
    return { speaker: "", text: lines.join(" ") };
  }

  function translateItem(it) {
    if (!translate || it.pt) return;
    const ticket = ++it.ticket;
    xlate(it.es)
      .then((out) => {
        if (ticket === it.ticket && !it.pt) {
          it.pt = tidy(it.es, out, it.prevEnded) || it.es;
          render();
        }
      })
      .catch((err) => {
        LOG("translate error", err);
        if (!it.pt) {
          it.pt = it.es; // never block the flow: show the Spanish chunk instead
          render();
        }
      });
  }

  function printChunk(b, words, norms) {
    const es = words.join(" ");
    const prev = log.length ? log[log.length - 1] : null;
    const prevEnded = !prev || prev.speaker !== b.speaker || ENDS_SENTENCE.test(prev.es);
    const it = { speaker: b.speaker, es, pt: "", prevEnded, ticket: 0 };
    log.push(it);
    if (log.length > MAX_LOG) log.shift();
    b.last = b.last.concat(norms.filter(Boolean)).slice(-6);
    translateItem(it);
  }

  /** Index in `norms` right after the words we already printed, or -1 if lost. */
  function findStart(b, norms) {
    if (!b.last.length) return 0;
    for (const k of [3, 2, 1]) {
      if (b.last.length < k) continue;
      const seq = b.last.slice(-k);
      if (k === 1 && seq[0].length < 4) continue;
      for (let i = norms.length - k; i >= 0; i--) {
        let ok = true;
        for (let j = 0; j < k; j++) {
          if (norms[i + j] !== seq[j]) {
            ok = false;
            break;
          }
        }
        if (ok) return i + k;
      }
    }
    return -1;
  }

  /** Print any new words from this block. final=true: flush everything. */
  function processBlock(b, final) {
    const tokens = b.text.split(/\s+/).filter(Boolean);
    const norms = tokens.map(norm);
    let start = findStart(b, norms);
    if (start < 0) {
      // Lost track (Meet rewrote the block). Only restart after a pause,
      // so a quick correction doesn't print the same words twice.
      if (!final) return;
      b.last = [];
      start = 0;
    }
    // If Meet is trimming the start of a long caption and our unprinted words
    // are right there, print them now instead of losing them.
    const trimmed = b.first !== undefined && norms[0] !== b.first;
    b.first = norms[0];
    if (trimmed && start <= 6) final = true;
    let pend = tokens.slice(start);
    let pendNorms = norms.slice(start);
    const P = preset();
    const STRONG = /[.!?…]["”')\]]*$/;
    const WEAK = /[,;:]["”')\]]*$/;
    for (;;) {
      if (!pend.length) break;
      // The newest word is the one Meet most often rewrites, so hold it back,
      // unless it already closes a sentence.
      const hold = final || STRONG.test(pend[pend.length - 1]) ? 0 : 1;
      const avail = pend.length - hold;
      if (avail <= 0) break;
      const limit = Math.min(avail, P.cap);
      let n = 0;
      for (let j = limit - 1; j >= 0; j--) {
        if ((STRONG.test(pend[j]) && j + 1 >= P.strongMin) || (WEAK.test(pend[j]) && j + 1 >= P.weakMin)) {
          n = j + 1;
          break;
        }
      }
      if (!n && avail >= P.cap) n = P.cap; // too long without a boundary: cut here
      if (!n && final) n = limit;
      if (!n) break;
      printChunk(b, pend.slice(0, n), pendNorms.slice(0, n));
      pend = pend.slice(n);
      pendNorms = pendNorms.slice(n);
    }
    render();
  }

  function scan() {
    if (!region || !region.isConnected) return;
    const seen = new Set();
    for (const el of getBlocks(region)) {
      const { speaker, text } = parseBlock(el);
      if (!text) continue;
      let b = blocks.get(el);
      if (!b) {
        b = { speaker, text: "", last: [], idleTimer: 0, first: undefined };
        blocks.set(el, b);
      }
      seen.add(b);
      if (b.text !== text) {
        b.text = text;
        b.speaker = speaker;
        processBlock(b, false);
        clearTimeout(b.idleTimer);
        b.idleTimer = setTimeout(() => processBlock(b, true), preset().idle);
      }
    }
    for (const [el, b] of blocks) {
      if (!seen.has(b)) {
        clearTimeout(b.idleTimer);
        processBlock(b, true); // Meet removed the block: print what was left
        blocks.delete(el);
      }
    }
  }

  // ---------- overlay UI ----------
  // The box shows exactly N lines. No animation, no scrolling: when the text
  // needs more than N lines, the oldest line(s) are simply dropped from the top
  // and new words appear on the last line.
  let root, viewport, inner, statusEl, startBtn, presetBtn;
  let renderPending = false;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function lineHeight() {
    return Math.round(settings.size * 1.4);
  }

  function buildOverlay() {
    root = el("div");
    root.id = "mptbr-root";

    const head = el("div", "mptbr-head");
    head.appendChild(el("span", "mptbr-title", "Legendas ES → PT-BR"));

    startBtn = el("button", "mptbr-btn", "Ativar");
    startBtn.title = "Iniciar a tradução (baixa o modelo na primeira vez)";
    startBtn.addEventListener("click", () => {
      engineState = "idle"; // allow retry; click counts as user activation
      showStartButton(false);
      startEngine();
    });

    presetBtn = el("button", "mptbr-btn", preset().label);
    presetBtn.title = "Velocidade × qualidade: Rápido / Equilibrado / Preciso";
    presetBtn.addEventListener("click", () => {
      settings.preset = settings.preset === "fast" ? "balanced" : settings.preset === "balanced" ? "precise" : "fast";
      store.save();
      presetBtn.textContent = preset().label;
    });

    const smaller = el("button", "mptbr-btn", "A−");
    const bigger = el("button", "mptbr-btn", "A+");
    const taller = el("button", "mptbr-btn", "↕");
    taller.title = "Altura da caixa (3 / 5 / 8 linhas)";
    const fold = el("button", "mptbr-btn", "–");
    fold.title = "Recolher/expandir";

    smaller.addEventListener("click", () => setSize(settings.size - 2));
    bigger.addEventListener("click", () => setSize(settings.size + 2));
    taller.addEventListener("click", () => {
      settings.lines = settings.lines >= 8 ? 3 : settings.lines === 3 ? 5 : 8;
      store.save();
      applySettings();
    });
    fold.addEventListener("click", () => {
      settings.collapsed = !settings.collapsed;
      store.save();
      applySettings();
    });
    for (const b of [startBtn, presetBtn, smaller, bigger, taller, fold]) {
      b.addEventListener("pointerdown", (ev) => ev.stopPropagation());
      head.appendChild(b);
    }

    statusEl = el("div", "mptbr-status");
    const frame = el("div", "mptbr-frame");
    viewport = el("div", "mptbr-viewport");
    inner = el("div", "mptbr-inner");
    viewport.appendChild(inner);
    frame.appendChild(viewport);

    root.append(head, statusEl, frame);
    document.documentElement.appendChild(root);

    makeDraggable(head);
    applySettings();
  }

  function setSize(px) {
    settings.size = Math.max(12, Math.min(48, px));
    store.save();
    applySettings();
  }

  function applySettings() {
    const lh = lineHeight();
    root.style.setProperty("--mptbr-size", settings.size + "px");
    root.style.setProperty("--mptbr-lh", lh + "px");
    viewport.style.height = lh * settings.lines + "px";
    root.classList.toggle("mptbr-collapsed", !!settings.collapsed);
    if (settings.x !== null && settings.y !== null) {
      root.classList.add("mptbr-moved");
      root.style.left = settings.x + "px";
      root.style.top = settings.y + "px";
      root.style.bottom = "auto";
    }
    render();
  }

  function makeDraggable(handle) {
    handle.addEventListener("pointerdown", (ev) => {
      const r = root.getBoundingClientRect();
      const dx = ev.clientX - r.left;
      const dy = ev.clientY - r.top;
      handle.setPointerCapture(ev.pointerId);
      const move = (m) => {
        settings.x = Math.max(0, Math.min(window.innerWidth - 80, m.clientX - dx));
        settings.y = Math.max(0, Math.min(window.innerHeight - 40, m.clientY - dy));
        applySettings();
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        store.save();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  function showStartButton(show) {
    if (startBtn) startBtn.style.display = show ? "" : "none";
  }

  function render() {
    if (renderPending || !inner) return;
    renderPending = true;
    requestAnimationFrame(() => {
      renderPending = false;
      draw();
    });
  }

  function draw() {
    // One continuous paragraph (uniform line height => whole number of lines).
    const p = el("p", "mptbr-pt");
    let prev = null;
    const add = (speaker, text, live) => {
      if (!text) return;
      if (speaker && speaker !== prev) p.appendChild(el("span", "mptbr-speaker", speaker + ": "));
      prev = speaker;
      p.appendChild(el("span", live ? "mptbr-live" : "", text + " "));
    };
    // Print in order, stopping at the first chunk still being translated, so
    // text that is already on screen is never pushed around or changed.
    for (const it of log) {
      if (!it.pt) break;
      add(it.speaker, it.pt, false);
    }
    inner.replaceChildren(p);

    // Drop whole lines from the top once the box is full.
    const lh = lineHeight();
    const total = Math.round(inner.offsetHeight / lh);
    const hide = Math.max(0, total - settings.lines);
    inner.style.transform = hide ? `translateY(${-hide * lh}px)` : "";
  }

  // ---------- wiring ----------
  let region = null;
  let observer = null;
  let hintTimer = 0;
  let rafPending = false;

  function attach(r) {
    if (observer) observer.disconnect();
    region = r;
    observer = new MutationObserver(() => {
      if (rafPending) return;
      rafPending = true;
      requestAnimationFrame(() => {
        rafPending = false;
        scan();
      });
    });
    observer.observe(r, { childList: true, subtree: true, characterData: true });
    clearTimeout(hintTimer);
    hintTimer = 0;
    if (engineState === "ready") setStatus("");
    LOG("attached to captions region");
    scan();
  }

  function watchRegion() {
    const r = findRegion();
    if (r && r !== region) attach(r);
    if (!r && region && !region.isConnected) {
      region = null;
      if (observer) observer.disconnect();
      for (const b of blocks.values()) {
        clearTimeout(b.idleTimer);
        processBlock(b, true);
      }
      blocks.clear();
    }
    if (!r && engineState === "ready" && !statusEl.textContent && !hintTimer) {
      hintTimer = setTimeout(() => {
        hintTimer = 0;
        if (!region) setStatus("Ative as legendas do Meet (botão CC) e escolha “Espanhol” como idioma falado.");
      }, 6000);
    }
  }

  async function init() {
    await store.load();
    buildOverlay();
    showStartButton(false);
    setInterval(watchRegion, 1000);

    if (typeof Translator === "undefined") {
      startEngine(); // shows the "update Chrome" message
      return;
    }
    const a = await availability(SRC, TGT);
    const pivotOk =
      a === "unavailable" &&
      (await availability(SRC, PIVOT)) !== "unavailable" &&
      (await availability(PIVOT, TGT)) !== "unavailable";
    if (a === "available") {
      startEngine();
    } else if (a === "unavailable" && !pivotOk) {
      startEngine(); // reports the error
    } else {
      // Model must be downloaded: Chrome requires a user click for that.
      setStatus("Clique em “Ativar” para baixar o modelo de tradução (só na primeira vez).");
      showStartButton(true);
    }
  }

  init();
})();
