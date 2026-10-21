/*
 * Runs in the page's own JS world (MAIN), before the player loads.
 *
 * Drive's player downloads the caption file when CC is turned on. We watch the
 * player's fetch/XHR traffic and hand any caption file it receives to
 * content.js (isolated world) as a DOM event. Nothing is changed or blocked:
 * the player gets exactly the same response.
 */
(() => {
  if (window.__dvtrHook) return;
  window.__dvtrHook = true;

  const WANT = /timedtext|caption|subtitle|\.vtt\b/i;

  function send(url, text) {
    if (typeof text !== "string" || text.length < 20) return;
    const head = text.slice(0, 200).trim();
    const looksLikeCaptions =
      /^WEBVTT/.test(head) || /<timedtext|<transcript/.test(head) || (head[0] === "{" && text.includes('"events"'));
    if (!looksLikeCaptions) return;
    document.dispatchEvent(new CustomEvent("dvtr-track", { detail: JSON.stringify({ url: String(url), text }) }));
  }

  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input) {
      const p = origFetch.apply(this, arguments);
      try {
        const url = typeof input === "string" ? input : input && input.url;
        if (url && WANT.test(url)) {
          p.then((r) => r.clone().text())
            .then((t) => send(url, t))
            .catch(() => {});
        }
      } catch {}
      return p;
    };
  }

  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    try {
      this.__dvtrUrl = String(url);
    } catch {}
    return open.apply(this, arguments);
  };
  const xsend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    if (this.__dvtrUrl && WANT.test(this.__dvtrUrl)) {
      this.addEventListener("load", () => {
        try {
          if (this.responseType === "" || this.responseType === "text") send(this.__dvtrUrl, this.responseText);
          else if (this.responseType === "json") send(this.__dvtrUrl, JSON.stringify(this.response));
        } catch {}
      });
    }
    return xsend.apply(this, arguments);
  };
})();
