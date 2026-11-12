// Share drafts (podcast #45): clicking an episode's Share button opens a small panel with
// one X post and one short LinkedIn post, both editable, plus "More…" (the device's share
// sheet, else the link copied: podcast #43). Loaded by the list pages (before site.js) and
// by every episode page (scripts/pages.py), so the drafts and the panel exist once.
//
// The drafts are written only from the episode's own entry in episodes.json: its title,
// the description's hook and "In this episode" points, its summary and its source. Nothing
// is invented, so no number or claim appears that the entry does not hold. Each draft is in
// the episode's language (en, fr, vi; another language gets English); the panel's own words
// are in the page's language. Luong's rules (issue #45):
// - X: one post (not a thread), at most 280 characters as X counts them (a link is 23).
// - LinkedIn: one short post, readable without "see more": at most 400 characters besides
//   the link, at most two hashtags.
// - A Build Wiz AI Show post: a hook line, one or two key points, the link, the source credit.
//   On X it tags only a handle the data holds, an X source's author "Name (@handle)"; it
//   never guesses one from a name, and never says more than "based on a post by @handle".
//   LinkedIn names the author in words.
// - A story: a gentle bedtime (or story-time) framing, and no tags at all (no @, no #).
// Nothing here makes a request: the X and LinkedIn links open only when the visitor clicks.
(() => {
  "use strict";
  const BUILD_SHOW = "Build Wiz AI Show";
  const STORY_SHOW = "Once Upon a Time Show";
  const STORY_FORMATS = ["bedtime-story", "storytelling"];
  const X_MAX = 280;      // X's limit, in its weighted characters
  const X_URL = 23;       // every link counts as 23 on X (t.co)
  const LI_MAX = 400;     // LinkedIn: short enough to read without "see more" (link not counted)

  // ---------- Draft templates, one set per episode language ----------
  // Written for each language's readers, not word for word. French puts a no-break space
  // (\u00a0) before ":" and inside « », as the site does, and elides "de" before a vowel.
  const de = (name) => (/^[AEIOUYÀÂÄÉÈÊËÎÏÔÖÙÛÜaeiouyàâäéèêëîïôöùûüh]/.test(name) ? `d’${name}` : `de ${name}`);
  const DRAFT = {
    en: {
      listen: "🎧 Listen: ",
      colon: ":",
      byHandle: (h) => `Based on a post by @${h}`,
      post: (n) => `Based on a post by ${n}`,
      article: (n) => `Based on an article by ${n}`,
      source: (n) => `Source: ${n}`,
      titled: (t) => `Based on “${t}”`,
      frame: { "bedtime-story": "A gentle story to listen to at bedtime", storytelling: "A gentle story to listen to at story time" },
    },
    fr: {
      listen: "🎧 À écouter\u00a0: ",
      colon: "\u00a0:",
      byHandle: (h) => `D’après une publication de @${h}`,
      post: (n) => `D’après une publication ${de(n)}`,
      article: (n) => `D’après un article ${de(n)}`,
      source: (n) => `Source\u00a0: ${n}`,
      titled: (t) => `D’après «\u00a0${t}\u00a0»`,
      frame: { "bedtime-story": "Une histoire douce à écouter au moment du coucher", storytelling: "Une histoire douce à écouter à l’heure du conte" },
    },
    vi: {
      listen: "🎧 Nghe tại: ",
      colon: ":",
      byHandle: (h) => `Dựa trên bài đăng của @${h}`,
      post: (n) => `Dựa trên bài đăng của ${n}`,
      article: (n) => `Dựa trên bài viết của ${n}`,
      source: (n) => `Nguồn: ${n}`,
      titled: (t) => `Dựa trên “${t}”`,
      frame: { "bedtime-story": "Một câu chuyện nhẹ nhàng để nghe trước giờ đi ngủ", storytelling: "Một câu chuyện nhẹ nhàng cho giờ kể chuyện" },
    },
  };
  // LinkedIn topic hashtags (Build Wiz AI Show only, at most two), by the episode's category.
  const TAGS = { ai: ["#AI", "#Podcast"], daily: ["#AI", "#News"], marketing: ["#Marketing", "#AI"] };
  const DEFAULT_TAGS = ["#AI", "#Podcast"];
  // The description's own "Sources:" line (DropCast's labels, scripts/description_labels.json).
  const SOURCES_LINE = /^(?:Sources|Nguồn)\s*:\s*/;

  // ---------- The panel's words, in the page's language ----------
  const WORDS = {
    en: {
      title: { episode: "Share this episode", story: "Share this story" },
      note: { episode: "Drafts written from the episode’s own text. Edit them before you post.", story: "Drafts written from the story’s own text. Edit them before you post." },
      x: "Post for X", linkedin: "Post for LinkedIn",
      postX: "Post on X", postLinkedIn: "Post on LinkedIn",
      copy: "Copy", copied: "Copied", copyFailed: "Copy failed",
      count: (n, max) => `${n}/${max}`, over: (n, max) => `${n}/${max}, too long for X`,
      liHint: "If LinkedIn opens without the text, paste it: it is copied when you click.",
      more: "More…", close: "Close",
    },
    fr: {
      title: { episode: "Partager cet épisode", story: "Partager cette histoire" },
      note: { episode: "Des brouillons tirés du texte de l’épisode. Modifiez-les avant de publier.", story: "Des brouillons tirés du texte de l’histoire. Modifiez-les avant de publier." },
      x: "Publication pour X", linkedin: "Publication pour LinkedIn",
      postX: "Publier sur X", postLinkedIn: "Publier sur LinkedIn",
      copy: "Copier", copied: "Copié", copyFailed: "Échec de la copie",
      count: (n, max) => `${n}/${max}`, over: (n, max) => `${n}/${max}, trop long pour X`,
      liHint: "Si LinkedIn s’ouvre sans le texte, collez-le\u00a0: il est copié au moment du clic.",
      more: "Autres options…", close: "Fermer",
    },
    vi: {
      title: { episode: "Chia sẻ tập này", story: "Chia sẻ truyện này" },
      note: { episode: "Bản nháp viết từ chính nội dung của tập. Bạn có thể sửa trước khi đăng.", story: "Bản nháp viết từ chính nội dung của truyện. Bạn có thể sửa trước khi đăng." },
      x: "Bài đăng cho X", linkedin: "Bài đăng cho LinkedIn",
      postX: "Đăng lên X", postLinkedIn: "Đăng lên LinkedIn",
      copy: "Sao chép", copied: "Đã sao chép", copyFailed: "Không sao chép được",
      count: (n, max) => `${n}/${max}`, over: (n, max) => `${n}/${max}, quá dài cho X`,
      liHint: "Nếu LinkedIn mở ra mà chưa có nội dung, hãy dán vào: nội dung đã được sao chép khi bạn bấm.",
      more: "Cách khác…", close: "Đóng",
    },
  };

  // ---------- Reading the entry ----------
  const isStory = (ep) => STORY_FORMATS.includes(ep.format) || ep.show === STORY_SHOW;
  const langOf = (ep) => {
    const l = typeof ep.language === "string" ? ep.language.trim().toLowerCase().split(/[-_;]/)[0] : "";
    return Object.prototype.hasOwnProperty.call(DRAFT, l) ? l : "en";
  };
  const clean = (s) => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
  // Free text from the data never tags anyone: "@name" and "#word" lose their sign.
  const untag = (s) => clean(s).replace(/[@#](?=[\p{L}\p{N}_])/gu, "");
  const HANDLE = /\s*\(@([A-Za-z0-9_]{1,15})\)\s*$/;
  const X_HOSTS = /^(?:www\.|mobile\.)?(?:x|twitter)\.com$/i;
  const isXSource = (src) => {
    if (src.kind === "x") return true;
    try { return X_HOSTS.test(new URL(src.url).hostname); } catch { return false; }
  };
  // The handle to tag on X: only an X source's author written "Name (@handle)".
  function handleOf(src) {
    if (!src || typeof src !== "object" || typeof src.author !== "string" || !isXSource(src)) return null;
    const m = src.author.match(HANDLE);
    return m ? m[1] : null;
  }
  const nameOf = (author) => untag(typeof author === "string" ? author.replace(HANDLE, "") : "");
  // Sentences, without splitting initials ("D. L. Ashliman") or decimals ("1.4").
  const sentences = (s) => clean(s).split(/(?<=[^\s.]{2}[.?!…])\s+(?=[\p{Lu}\p{N}"“«‘'])/u).filter(Boolean);
  const paragraphs = (d) => (typeof d === "string" ? d.trim().split(/\n\s*\n/) : []);
  const summaryOf = (ep) => (Array.isArray(ep.summary) ? ep.summary.map(untag).filter(Boolean) : []);
  // The description's "In this episode" points ("- …" lines), else the summary after its first line.
  function pointsOf(ep) {
    const desc = typeof ep.description === "string" ? ep.description : "";
    const bullets = desc.split("\n").map((l) => l.match(/^\s*[-•]\s+(.+)$/)).filter(Boolean).map((m) => untag(m[1])).filter(Boolean);
    return bullets.length ? bullets : summaryOf(ep).slice(1);
  }
  const hookParagraph = (ep) => untag(paragraphs(ep.description)[0] || "") || summaryOf(ep)[0] || untag(ep.title);

  // The source credit of a Build Wiz AI Show post. tag: the X version (a handle may be tagged).
  function creditOf(ep, D, tag) {
    const src = ep.source && typeof ep.source === "object" ? ep.source : {};
    const name = nameOf(src.author);
    if (name && name.toLowerCase() === BUILD_SHOW.toLowerCase()) return "";   // the show's own text
    const handle = tag ? handleOf(src) : null;
    if (handle) return D.byHandle(handle);
    if (name) return isXSource(src) ? D.post(name) : src.kind === "article" ? D.article(name) : D.source(name);
    const title = untag(src.title);
    return title ? D.titled(title) : "";
  }
  // A story's credit: the description's own "Sources:" line, else the source's title.
  function storyCreditOf(ep, D) {
    const desc = typeof ep.description === "string" ? ep.description : "";
    const line = desc.split("\n").map((l) => l.trim()).find((l) => SOURCES_LINE.test(l));
    if (line) return untag(line.replace(HANDLE, ""));
    const title = untag(ep.source && ep.source.title);
    return title ? D.titled(title) : "";
  }

  // ---------- Lengths ----------
  // X's weighted length (twitter-text v3): a code point in X's light ranges counts 1, any
  // other 2 (Vietnamese letters with two marks, emoji, arrows); every http(s) link counts 23.
  // A bare domain ("a16z.news") may be linked by X too: it counts at least 23. So this never
  // counts less than X does.
  const LIGHT = [[0, 4351], [8192, 8205], [8208, 8223], [8242, 8247]];
  const weigh = (s) => {
    let n = 0;
    for (const ch of s) { const c = ch.codePointAt(0); n += LIGHT.some(([a, b]) => c >= a && c <= b) ? 1 : 2; }
    return n;
  };
  const LINKISH = /https?:\/\/\S+|(?:[\p{L}\p{N}-]+\.)+\p{L}{2,}(?:\/\S*)?/giu;
  function xLength(text) {
    const t = String(text || "").normalize("NFC");
    let n = 0, last = 0;
    for (const m of t.matchAll(LINKISH)) {
      n += weigh(t.slice(last, m.index)) + (/^https?:/i.test(m[0]) ? X_URL : Math.max(X_URL, weigh(m[0])));
      last = m.index + m[0].length;
    }
    return n + weigh(t.slice(last));
  }
  // LinkedIn: characters besides the episode's link.
  const linkedinLength = (text, url) => Array.from(String(text || "").split(url).join("")).length;

  // ---------- Building and fitting a draft ----------
  function compose(p) {
    const blocks = [p.hook];
    if (p.points.length) blocks.push(p.points.map((x) => `→ ${x}`).join("\n"));
    blocks.push([p.link, p.credit].filter(Boolean).join("\n"));
    return blocks.filter(Boolean).join("\n\n");
  }
  // The longest start of a text that still fits, cut at a word with "…" (at least 3 words).
  function cut(text, fits) {
    const words = text.split(" ");
    let lo = 3, hi = words.length - 1, best = "";
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const s = `${words.slice(0, mid).join(" ").replace(/[\s,;:–—-]+$/, "")}…`;
      if (fits(s)) { best = s; lo = mid + 1; } else hi = mid - 1;
    }
    return best;
  }
  // The richest version that fits: two points, then one; a story may then drop its points,
  // its credit, then its hook's later sentences. A Build Wiz AI Show post always keeps its
  // credit. Last resort: the point, then the hook, cut at a word.
  function fit(p, ok, story) {
    const tries = [];
    for (const n of [2, 1]) tries.push({ ...p, points: p.points.slice(0, n) });
    if (story) {
      tries.push({ ...p, points: [] }, { ...p, points: [], credit: "" });
      const ss = sentences(p.hook);
      for (let k = ss.length - 1; k >= 1; k--) tries.push({ ...p, hook: ss.slice(0, k).join(" "), points: [], credit: "" });
    }
    if (!p.points.length) tries.push({ ...p });
    for (const t of tries) { const s = compose(t); if (ok(s)) return s; }
    const last = story ? { ...p, hook: sentences(p.hook)[0] || p.hook, points: [], credit: "" } : { ...p, points: p.points.slice(0, 1) };
    if (last.points.length) {
      const point = cut(last.points[0], (s) => ok(compose({ ...last, points: [s] })));
      if (point) return compose({ ...last, points: [point] });
      last.points = [];
    }
    return compose({ ...last, hook: cut(last.hook, (s) => ok(compose({ ...last, hook: s }))) });
  }

  // The two drafts of an episode: { lang, x, linkedin }. url: the episode's own page.
  function drafts(ep, url) {
    const lang = langOf(ep);
    const D = DRAFT[lang];
    const xOk = (s) => xLength(s) <= X_MAX;
    const liOk = (s) => linkedinLength(s, url) <= LI_MAX;
    if (isStory(ep)) {
      const frame = D.frame[ep.format] || D.frame["bedtime-story"];
      const p = { hook: hookParagraph(ep), points: pointsOf(ep), link: `🌙 ${frame}${D.colon}\n${url}`, credit: storyCreditOf(ep, D) };
      return { lang, x: fit(p, xOk, true), linkedin: fit(p, liOk, true) };
    }
    const first = sentences(paragraphs(ep.description)[0] || "")[0] || "";
    const title = untag(ep.title);
    const hook = /\?[»"”’)]*$/.test(first) ? untag(first) : title || untag(first);
    const points = pointsOf(ep).filter((x) => x !== hook);
    const link = `${D.listen}${url}`;
    const tags = (TAGS[ep.category] || DEFAULT_TAGS).slice(0, 2).join(" ");
    const x = fit({ hook, points, link, credit: creditOf(ep, D, true) }, xOk, false);
    const credit = creditOf(ep, D, false);
    const linkedin = fit({ hook, points, link, credit: credit ? `${credit} ${tags}` : tags }, liOk, false);
    return { lang, x, linkedin };
  }

  // ---------- Intent links (opened only by the visitor's click) ----------
  const xIntent = (text) => `https://x.com/intent/post?text=${encodeURIComponent(text)}`;
  // LinkedIn's share box with the text filled in; its share-offsite page (the link only) when
  // there is no text or the address would be too long.
  function linkedinIntent(text, url) {
    const full = `https://www.linkedin.com/feed/?shareActive=true&text=${encodeURIComponent(text)}`;
    return String(text || "").trim() && full.length <= 8000
      ? full
      : `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`;
  }

  // ---------- The panel ----------
  // Inline under the episode's buttons (a card's details, or the episode page), not a modal:
  // the Share button says it is expanded and controls it; Esc, a click outside it or Close
  // closes it (Esc and Close give the focus back to Share). One panel is open at a time.
  const CSS = `
#share[aria-expanded="true"], .btn[data-share][aria-expanded="true"] { border-color: var(--accent, #22C55E); color: var(--accent, #22C55E); }
.sp, .sp * { box-sizing: border-box; }
.sp { margin-top: 14px; padding: 14px clamp(12px, 3vw, 18px) 16px; border: 1px solid var(--line-strong, rgba(255,255,255,.24)); border-top: 2px solid var(--accent, #22C55E); border-radius: var(--radius, 12px); background: rgba(255,255,255,.025); max-width: 860px; }
.sp-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sp-head h4 { margin: 0; font: 700 16px/1.25 var(--display, inherit); letter-spacing: -0.01em; }
.sp-head h4:focus { outline: none; }
.sp-x { flex: none; display: inline-grid; place-items: center; width: 36px; height: 36px; padding: 0; border: 1px solid transparent; border-radius: var(--r-ctl, 8px); background: transparent; color: inherit; font: 400 22px/1 inherit; cursor: pointer; }
.sp-x:hover { border-color: var(--line-strong, rgba(255,255,255,.24)); }
.sp-note { margin: 2px 0 0; font-size: 13px; color: var(--text-2, rgba(255,255,255,.72)); }
.sp-drafts { display: grid; gap: 14px; margin-top: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); }
.sp-draft { min-width: 0; display: flex; flex-direction: column; }
.sp-label { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 2px 8px; margin: 0 0 6px; font-size: 13px; font-weight: 600; }
.sp-count { font-weight: 500; font-variant-numeric: tabular-nums; color: var(--text-2, rgba(255,255,255,.72)); }
.sp-count.is-over { color: var(--white, #fff); font-weight: 700; text-decoration: underline; text-decoration-color: var(--accent, #22C55E); }
.sp textarea { display: block; width: 100%; min-height: 8em; flex: 1 0 auto; resize: vertical; margin: 0; padding: 10px 12px; border: 1px solid var(--line-strong, rgba(255,255,255,.24)); border-radius: var(--r-ctl, 8px); background: #000; color: #fff; font: 400 14px/1.5 var(--body, inherit); overflow-wrap: anywhere; }
.sp textarea:focus-visible { outline: 2px solid var(--accent, #22C55E); outline-offset: 1px; }
.sp-acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.sp .sp-post { border-color: var(--accent, #22C55E); }
.sp-hint { margin: 6px 0 0; font-size: 12px; line-height: 1.45; color: var(--text-3, rgba(255,255,255,.62)); }
.sp-more { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line, rgba(255,255,255,.12)); }
`;
  function ensureStyle() {
    if (document.getElementById("share-panel-style")) return;
    const s = document.createElement("style");
    s.id = "share-panel-style";
    s.textContent = CSS;
    document.head.append(s);
  }
  const h = (tag, props = {}, kids = []) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("aria-") || k.startsWith("data-") || k === "role" || k === "lang") n.setAttribute(k, v);
      else n[k] = v;
    }
    for (const kid of [].concat(kids)) if (kid) n.append(kid);
    return n;
  };
  // A draft's box grows to show the whole draft (up to 60% of the screen, then it scrolls).
  function grow(ta) {
    if (!ta.style || typeof ta.scrollHeight !== "number") return;
    ta.style.height = "auto";
    const max = Math.max(200, Math.round((window.innerHeight || 800) * 0.6));
    ta.style.height = `${Math.min(ta.scrollHeight + 2, max)}px`;
  }
  let open = null;   // the panel on show
  let uid = 0;
  let listening = false;

  function close(panel, focus) {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    panel._button.setAttribute("aria-expanded", "false");
    if (open === panel) open = null;
    if (focus) panel._button.focus();
  }
  function listen() {
    if (listening) return;
    listening = true;
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !open) return;
      // A panel inside details that were folded away is closed quietly (nothing to escape).
      const shown = typeof open.getClientRects !== "function" || open.getClientRects().length > 0;
      if (shown) e.preventDefault();
      close(open, shown);
    });
    document.addEventListener("pointerdown", (e) => {
      if (open && !open.contains(e.target) && !open._button.contains(e.target)) close(open, false);
    });
  }

  // o: { ep, url, lang (the page's), button, after (the element the panel follows),
  //      track(method), copy(text) -> Promise<boolean>, more(button, label, restingLabel) }
  function build(o) {
    const W = WORDS[o.lang] || WORDS.en;
    const kind = isStory(o.ep) ? "story" : "episode";
    const d = drafts(o.ep, o.url);
    const id = `share-panel-${++uid}`;
    const heading = h("h4", { id: `${id}-t`, tabIndex: -1, text: W.title[kind] });
    const closeBtn = h("button", { class: "sp-x", type: "button", "aria-label": W.close, "data-share-action": "close" }, "×");
    const draft = (which) => {
      const isX = which === "x";
      const ta = h("textarea", { id: `${id}-${which}`, rows: 8, spellcheck: true, lang: d.lang, value: d[which], "data-draft": which });
      const count = isX ? h("span", { class: "sp-count", id: `${id}-count` }) : null;
      if (isX) ta.setAttribute("aria-describedby", count.id);
      const post = h("a", { class: "btn sp-post", target: "_blank", rel: "noopener noreferrer", "data-share-action": which, text: isX ? W.postX : W.postLinkedIn });
      const update = () => {
        post.href = isX ? xIntent(ta.value) : linkedinIntent(ta.value, o.url);
        if (count) {
          const n = xLength(ta.value);
          count.textContent = n > X_MAX ? W.over(n, X_MAX) : W.count(n, X_MAX);
          count.classList.toggle("is-over", n > X_MAX);
        }
      };
      update();
      ta.addEventListener("input", () => { update(); grow(ta); });
      const sent = () => {
        o.track(which);
        if (!isX) o.copy(ta.value);   // so it can be pasted if LinkedIn opens empty
      };
      post.addEventListener("click", sent);
      post.addEventListener("auxclick", (e) => { if (e.button === 1) sent(); });
      const copyLabel = h("span", { text: W.copy, "aria-live": "polite" });
      const copyBtn = h("button", { class: "btn", type: "button", "data-share-action": `copy-${which}` }, copyLabel);
      copyBtn.addEventListener("click", async () => {
        const ok = await o.copy(ta.value);
        copyLabel.textContent = ok ? W.copied : W.copyFailed;
        copyBtn.classList.toggle("is-done", ok);
        if (ok) o.track("copy");
        clearTimeout(copyBtn._t);
        copyBtn._t = setTimeout(() => { copyLabel.textContent = W.copy; copyBtn.classList.remove("is-done"); }, 1800);
      });
      return h("div", { class: "sp-draft" }, [
        h("div", { class: "sp-label" }, [h("label", { htmlFor: ta.id, text: isX ? W.x : W.linkedin }), count]),
        ta,
        h("div", { class: "sp-acts" }, [post, copyBtn]),
        isX ? null : h("p", { class: "sp-hint", text: W.liHint }),
      ]);
    };
    const moreLabel = h("span", { text: W.more, "aria-live": "polite" });
    const moreBtn = h("button", { class: "btn", type: "button", "data-share-action": "more" }, moreLabel);
    moreBtn.addEventListener("click", () => o.more(moreBtn, moreLabel, W.more));
    const panel = h("section", { class: "sp", id, role: "region", "aria-labelledby": heading.id, hidden: true }, [
      h("div", { class: "sp-head" }, [heading, closeBtn]),
      h("p", { class: "sp-note", text: W.note[kind] }),
      h("div", { class: "sp-drafts" }, [draft("x"), draft("linkedin")]),
      h("div", { class: "sp-more" }, moreBtn),
    ]);
    closeBtn.addEventListener("click", () => close(panel, true));
    panel._button = o.button;
    panel._heading = heading;
    o.button.setAttribute("aria-controls", id);
    o.after.after(panel);
    return panel;
  }

  // The Share button's click: open its panel (built the first time), or close it.
  function toggle(o) {
    const b = o.button;
    const panel = b._sharePanel;
    if (panel && !panel.hidden) { close(panel, false); return panel; }
    ensureStyle();
    listen();
    if (open) close(open, false);
    const p = panel || (b._sharePanel = build(o));
    p.hidden = false;
    b.setAttribute("aria-expanded", "true");
    open = p;
    if (typeof p.querySelectorAll === "function") p.querySelectorAll("textarea").forEach(grow);
    p._heading.focus({ preventScroll: true });
    if (typeof p.scrollIntoView === "function") p.scrollIntoView({ block: "nearest" });
    return p;
  }

  window.PodcastShare = { drafts, xLength, linkedinLength, xIntent, linkedinIntent, handleOf, toggle, close, WORDS, DRAFT, X_MAX, LI_MAX };
})();
