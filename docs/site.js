// The episode list and player shared by the show pages. Each page sets window.SHOW_PAGE
// before loading this file: which show it lists, its tabs and where episodes.json is.
// Both shows share one episodes.json; an episode's show is its "show" field, and a story
// format always belongs to the story show (the same routing as scripts/publish.py).
(() => {
  "use strict";
  const BUILD_SHOW = "Build Wiz AI Show";
  const STORY_SHOW = "Once Upon a Time Show";
  const STORY_FORMATS = ["bedtime-story", "storytelling"];
  const showOf = (e) => (STORY_FORMATS.includes(e.format) || e.show === STORY_SHOW ? STORY_SHOW : BUILD_SHOW);
  const PAGE = Object.assign({ show: BUILD_SHOW, data: "episodes.json", tabs: [], pages: {}, legacyTabs: {} }, window.SHOW_PAGE || {});
  const DATA_URL = new URL(PAGE.data, location.href);

  // ---------- Words on the page (podcast #35) ----------
  // Each story page is written in its own language (SHOW_PAGE.lang: en, fr or vi); the main
  // page has no lang and is in English. The English is the text the pages always had. The
  // French and Vietnamese are only used on the story pages, so they speak of stories
  // ("histoires", "truyện"); they are written for their readers, not word for word, and
  // French puts a no-break space before ":" and inside « ».
  const TEXT = {
    en: {
      locale: "en",
      min: (n) => `${n} min`,
      left: (m) => `${m} left`,
      finished: "Finished",
      sorts: { published: ["Oldest first", "Newest first"], duration: ["Shortest first", "Longest first"], title: ["A to Z", "Z to A"], source: ["Oldest source first", "Newest source first"] },
      order: (cur, other) => `Order: ${cur}. Switch to ${other}.`,
      of: (total, n) => ` of ${total} ${n}`,
      noMatch: "No matching episodes",
      noMatchText: (q) => `Nothing matches “${q}”. Try fewer or different words.`,
      newSoon: "New episodes appear here as soon as they are published.",
      clearSearch: "Clear search",
      empty: "No episodes yet",
      emptyText: "The first one will appear here as soon as it is generated.",
      basedOn: "Based on ", by: " by ",
      sources: "Sources", untitled: "Untitled source",
      guests: "Guests: ", presents: (list) => ` (presents ${list})`,
      music: (c) => `Music: ${c}`,
      transcript: "Transcript", transcriptOf: (t) => `Transcript of ${t}`,
      loadingTranscript: "Loading transcript…", transcriptFailed: "The transcript could not be loaded. The audio still plays.",
      download: "Download MP3",
      copyDesc: "Copy description", copied: "Copied", copyFailed: "Copy failed",
      readSource: "Read the source",
      copyLink: "Copy link", linkCopied: "Link copied", linkInBar: "Link in address bar",
      langSwitch: "Language",
      play: "Play", pause: "Pause", playEp: (t) => `Play ${t}`, pauseEp: (t) => `Pause ${t}`,
      audioFailed: (t) => `Could not load audio: ${t}`,
      speed: (r) => `Playback speed ${r}×`,
      loadFailed: "Episodes could not be loaded.", loadFailedTitle: "Episodes could not be loaded", loadFailedText: "Check your connection and reload the page.",
      illustration: (t) => `Illustration: ${t}`,
    },
    fr: {
      locale: "fr",
      min: (n) => `${n} min`,
      left: (m) => `Il reste ${m}`,
      finished: "Écoutée",
      sorts: { published: ["Plus anciennes d’abord", "Plus récentes d’abord"], duration: ["Plus courtes d’abord", "Plus longues d’abord"], title: ["De A à Z", "De Z à A"], source: ["Source la plus ancienne d’abord", "Source la plus récente d’abord"] },
      order: (cur, other) => `Ordre : ${cur}. Passer à : ${other}.`,
      of: (total, n) => ` sur ${total} ${n}`,
      noMatch: "Aucune histoire ne correspond",
      noMatchText: (q) => `Rien ne correspond à « ${q} ». Essayez avec moins de mots, ou d’autres.`,
      newSoon: "Les nouvelles histoires arrivent ici dès leur publication.",
      clearSearch: "Effacer la recherche",
      empty: "Pas encore d’histoire",
      emptyText: "La première arrivera ici dès sa publication.",
      basedOn: "D’après ", by: ", de ",
      sources: "Sources", untitled: "Source sans titre",
      guests: "Invités : ", presents: (list) => ` (présente ${list})`,
      music: (c) => `Musique : ${c}`,
      transcript: "Transcription", transcriptOf: (t) => `Transcription de ${t}`,
      loadingTranscript: "Chargement de la transcription…", transcriptFailed: "Impossible de charger la transcription. Vous pouvez quand même écouter l’histoire.",
      download: "Télécharger le MP3",
      copyDesc: "Copier la description", copied: "Copiée", copyFailed: "Échec de la copie",
      readSource: "Lire le texte original",
      copyLink: "Copier le lien", linkCopied: "Lien copié", linkInBar: "Lien dans la barre d’adresse",
      langSwitch: "Langue",
      play: "Lecture", pause: "Pause", playEp: (t) => `Écouter ${t}`, pauseEp: (t) => `Mettre en pause ${t}`,
      audioFailed: (t) => `Impossible de charger l’audio : ${t}`,
      speed: (r) => `Vitesse de lecture ${r}×`,
      loadFailed: "Impossible de charger les histoires.", loadFailedTitle: "Impossible de charger les histoires", loadFailedText: "Vérifiez votre connexion, puis rechargez la page.",
      illustration: (t) => `Illustration : ${t}`,
    },
    vi: {
      locale: "vi",
      min: (n) => `${n} phút`,
      left: (m) => `Còn ${m}`,
      finished: "Đã nghe xong",
      sorts: { published: ["Cũ nhất trước", "Mới nhất trước"], duration: ["Ngắn nhất trước", "Dài nhất trước"], title: ["Từ A đến Z", "Từ Z đến A"], source: ["Bản gốc cũ nhất trước", "Bản gốc mới nhất trước"] },
      order: (cur, other) => `Thứ tự: ${cur}. Đổi sang: ${other}.`,
      of: (total, n) => ` trên ${total} ${n}`,
      noMatch: "Không tìm thấy truyện nào",
      noMatchText: (q) => `Không có truyện nào khớp với “${q}”. Hãy thử bớt từ hoặc dùng từ khác.`,
      newSoon: "Truyện mới sẽ xuất hiện ở đây ngay khi được đăng.",
      clearSearch: "Xóa tìm kiếm",
      empty: "Chưa có truyện nào",
      emptyText: "Truyện đầu tiên sẽ xuất hiện ở đây ngay khi được đăng.",
      basedOn: "Dựa theo ", by: " của ",
      sources: "Nguồn", untitled: "Nguồn không có tên",
      guests: "Khách mời: ", presents: (list) => ` (giới thiệu ${list})`,
      music: (c) => `Nhạc: ${c}`,
      transcript: "Lời kể", transcriptOf: (t) => `Lời kể của truyện ${t}`,
      loadingTranscript: "Đang tải lời kể…", transcriptFailed: "Không tải được lời kể. Bạn vẫn có thể nghe truyện bình thường.",
      download: "Tải MP3",
      copyDesc: "Sao chép mô tả", copied: "Đã sao chép", copyFailed: "Không sao chép được",
      readSource: "Đọc bản gốc",
      copyLink: "Sao chép liên kết", linkCopied: "Đã sao chép liên kết", linkInBar: "Liên kết ở thanh địa chỉ",
      langSwitch: "Ngôn ngữ",
      play: "Phát", pause: "Tạm dừng", playEp: (t) => `Phát truyện ${t}`, pauseEp: (t) => `Tạm dừng truyện ${t}`,
      audioFailed: (t) => `Không tải được âm thanh: ${t}`,
      speed: (r) => `Tốc độ phát ${r}×`,
      loadFailed: "Không tải được danh sách truyện.", loadFailedTitle: "Không tải được danh sách truyện", loadFailedText: "Hãy kiểm tra kết nối mạng rồi tải lại trang.",
      illustration: (t) => `Hình minh họa: ${t}`,
    },
  };
  const T = TEXT[Object.prototype.hasOwnProperty.call(TEXT, PAGE.lang) ? PAGE.lang : "en"];
  // ---------- end of words ----------

  const NOUN = PAGE.noun || ["episode", "episodes"];   // [one, many]: "story", "stories"
  const noun = (n) => NOUN[n === 1 ? 0 : 1];
  const PLAY = "M8 5v14l11-7z";
  const PAUSE = "M7 5h4v14H7zM13 5h4v14h-4z";
  const SPEEDS = [1, 1.25, 1.5, 2];
  const $ = (id) => document.getElementById(id);
  const audio = $("audio");
  const list = $("episodes");
  const player = $("player");
  const seek = $("p-seek");
  const qInput = $("q");
  let episodes = [];        // this show's episodes (every language version)
  let units = [];           // the list's rows: one episode, or one story in several languages
  let others = [];          // the other show's, only to forward their deep links
  let current = null;       // episode object playing
  let cues = new Map();     // id -> [{start, end, who, text, el}]
  let saveTimer = 0;
  let noMatch = null;       // the "no matches" row, built once

  const store = {           // per-viewer resume points; storage can be unavailable
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
  };

  // ---------- Which page lists an episode (podcast #35) ----------
  // Once Upon a Time Show has one page per language (stories/en/, fr/, vi/) and a chooser
  // (stories/). A page with SHOW_PAGE.lang lists only its show's episodes in that language; a
  // story in a language without a page is on the English one (its audio is in the English
  // stories repo too). SHOW_PAGE.pages maps a show to its page, "{lang}" standing for the
  // episode's language, so a deep link to an episode listed elsewhere goes straight there.
  const STORY_LANGS = ["en", "fr", "vi"];
  // Languages compare by their primary subtag ("en-US" is "en"), like the browser's.
  const primaryLang = (l) => (typeof l === "string" ? l.trim().toLowerCase().split(/[-_;]/)[0] : "");
  const langOf = (e) => primaryLang(e.language) || "en";
  const storyLang = (e) => (STORY_LANGS.includes(langOf(e)) ? langOf(e) : "en");
  const onPage = (e) => showOf(e) === PAGE.show && (!PAGE.lang || storyLang(e) === PAGE.lang);
  const pageOfShow = (show, lang) => {
    const p = Object.prototype.hasOwnProperty.call(PAGE.pages, show) ? PAGE.pages[show] : null;
    return typeof p === "string" && p ? p.replace("{lang}", lang) : null;
  };
  const pageFor = (e) => pageOfShow(showOf(e), storyLang(e));
  const hashId = (hash) => { try { return decodeURIComponent(String(hash || "").slice(1)); } catch { return ""; } };
  // The keys the old stories page read from its query. Anything else (fbclid, utm_*, gclid)
  // is a tracking tag a share or an ad added, not a setting.
  const OLD_QUERY = ["q", "sort", "order", "tab"];
  // The query with only those keys, as written (same encoding and order), or "".
  const keptQuery = (search) => {
    const kept = String(search || "").replace(/^\?/, "").split("&").filter((part) => {
      try { return OLD_QUERY.includes(decodeURIComponent(part.split("=")[0].replace(/\+/g, " "))); } catch { return false; }
    });
    return kept.length ? `?${kept.join("&")}` : "";
  };
  // The chooser (stories/) lists nothing: a link made before the language pages (#<id>, a
  // search) goes on to the page that lists that episode, keeping the hash and the old page's
  // keys. A search without a known episode goes to the visitor's language: the last one
  // picked on the site, else the browser's, else English. Anything else, a link with only
  // tracking tags included, stays on the chooser (null).
  function chooserTarget(all, hash, search, prefer) {
    const query = keptQuery(search);
    const id = hashId(hash);
    const ep = id ? all.find((e) => e && e.id === id) : null;
    const page = ep ? pageFor(ep) : null;
    if (page) return `${page}${query}${hash}`;
    if (!query) return null;
    const lang = prefer.map(primaryLang).find((l) => STORY_LANGS.includes(l)) || "en";
    const stories = pageOfShow(STORY_SHOW, lang);
    return stories ? `${stories}${query}${hash}` : null;
  }
  // ---------- end of page routing ----------

  if (PAGE.chooser) {
    if (location.hash.length > 1 || location.search.length > 1) {
      const prefer = [store.get("lang"), ...(navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language])];
      fetch(DATA_URL, { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : {}))
        .catch(() => ({}))
        .then((data) => {
          const all = data && Array.isArray(data.episodes) ? data.episodes : [];
          const to = chooserTarget(all, location.hash, location.search, prefer);
          if (to) location.replace(to);
        });
    }
    return;
  }
  const el = (tag, props = {}, kids = []) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("aria-") || k.startsWith("data-") || k === "role") n.setAttribute(k, v);
      else n[k] = v;
    }
    for (const kid of [].concat(kids)) if (kid) n.append(kid);
    return n;
  };
  const svg = (paths, cls) => {
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
    if (cls) s.setAttribute("class", cls);
    for (const d of paths) { const p = document.createElementNS(ns, "path"); p.setAttribute("d", d); s.append(p); }
    return s;
  };
  const clock = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
  };
  const minutes = (s) => T.min(Math.max(1, Math.round((s || 0) / 60)));
  const day = (iso, year = true) => {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(T.locale, year ? { year: "numeric", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
  };
  const host = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; } };
  const safeUrl = (url) => { try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? u.href : null; } catch { return null; } };
  const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The download name (DropCast #163): "<Show> - <Title> (<date>).mp3" from episodes.json,
  // else the episode id. Characters no file system accepts are dropped all the same.
  const fileName = (ep) => {
    const n = typeof ep.file_name === "string" ? ep.file_name.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, "").trim() : "";
    return n || `${ep.id}.mp3`;
  };
  // An episode's own page (docs/episodes/<id>/, written by scripts/pages.py), next to episodes.json.
  const pageOf = (ep) => new URL(`episodes/${encodeURIComponent(ep.id)}/`, DATA_URL).href;
  // A story's illustration (scripts/publish.py copies it to docs/art/<key>/): only a plain
  // "art/<key>/<wide|square|thumb>.jpg" path is used, resolved next to episodes.json.
  const ART_PATH = /^art\/[A-Za-z0-9][A-Za-z0-9._-]*\/(?:wide|square|thumb)\.jpg$/;
  const artPath = (img, kind) => {
    const p = img && typeof img === "object" ? img[kind] : null;
    return typeof p === "string" && ART_PATH.test(p) && !p.includes("..") ? new URL(p, DATA_URL).href : null;
  };
  // The episode's own art, else another language version's (on its page or another language's
  // page): every version of a story shows the same picture.
  const artSource = (ep, kind) => [ep, ...((ep._unit && ep._unit.versions) || []), ...(ep._alts || [])].find((v) => artPath(v.image, kind));
  const artOf = (ep, kind) => { const v = artSource(ep, kind); return v ? artPath(v.image, kind) : null; };
  const artAlt = (ep) => {
    const v = artSource(ep, "wide");
    const alt = v && typeof v.image.alt === "string" ? v.image.alt.trim() : "";
    return alt || T.illustration(ep.title);
  };
  // The description's hook (its first paragraph): the page's meta description while a deep link is open.
  const hookOf = (d) => String(d || "").trim().split(/\n\s*\n/)[0].replace(/\s+/g, " ").trim();
  const metaDesc = document.querySelector('meta[name="description"]');
  const baseDesc = metaDesc ? metaDesc.content : "";
  const setMetaDesc = (ep) => { if (metaDesc) metaDesc.content = (ep && hookOf(ep.description)) || baseDesc; };

  // ---------- Analytics (GA4 events, DropCast #138) ----------
  // The pages load GA4 (gtag) for page views; these events say what is listened to. No new
  // tracker or cookie: they go through the page's gtag, and every call is guarded, so a
  // blocked, missing or throwing gtag never breaks the page. Each counter is per page view.
  const MILESTONES = [25, 50, 75, 100];
  const played = new Set();   // episode ids whose episode_play was sent
  const reached = new Map();  // episode id -> progress milestones sent
  function track(name, params) {
    try { if (typeof window.gtag === "function") window.gtag("event", name, params); } catch { /* never breaks the page */ }
  }
  // The parameters every event carries (no personal data): the episode, its show, language,
  // story group (a story in several languages only) and category.
  function epParams(ep) {
    const p = { episode_id: String(ep.id), episode_title: String(ep.title || "").slice(0, 100), show: showOf(ep), episode_language: ep._lang || langOf(ep) };
    const g = typeof ep.story_group === "string" ? ep.story_group.trim() : "";
    if (g) p.story_group = g;
    if (typeof ep.category === "string" && ep.category) p.category = ep.category;
    return p;
  }
  // A link click (and a middle click, which opens a tab) sends one event.
  function trackLink(a, name, ep) {
    a.addEventListener("click", () => track(name, epParams(ep)));
    a.addEventListener("auxclick", (e) => { if (e.button === 1) track(name, epParams(ep)); });
    return a;
  }
  // 25 / 50 / 75 / 100 % of the episode reached in the player, each once, and only once
  // the episode has played in this page view (loading a resume point sends nothing).
  function trackProgress(ended) {
    if (!current || !played.has(current.id)) return;
    const d = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : current.duration_s || 0;
    const pct = ended ? 100 : d ? ((audio.currentTime || 0) / d) * 100 : 0;
    let sent = reached.get(current.id);
    if (!sent) reached.set(current.id, (sent = new Set()));
    for (const m of MILESTONES) {
      if (pct < m || sent.has(m)) continue;
      sent.add(m);
      track("episode_progress", { ...epParams(current), percent: m });
    }
  }

  // ---------- One story in several languages (DropCast #136) ----------
  // Entries sharing a "story_group" are one row with a language switch; each keeps its own
  // id (deep link), audio, transcript and resume point. Entries without one are unchanged.
  const LANGS = { en: ["EN", "English"], fr: ["FR", "Français"], vi: ["VI", "Tiếng Việt"] };
  const LANG_ORDER = Object.keys(LANGS);
  // An unknown language is labelled with its code, cut to 3 letters so the switch stays small.
  const langLabel = (l) => LANGS[l] || [l.slice(0, 3).toUpperCase(), l.slice(0, 3).toUpperCase()];
  const langRank = (l) => (LANG_ORDER.includes(l) ? LANG_ORDER.indexOf(l) : LANG_ORDER.length);
  function groupUnits(eps) {
    const out = [];
    const byGroup = new Map();
    // Newest first, so a second version in the same language stays its own row.
    const newest = eps.slice().sort((a, b) => (Date.parse(b.published) || 0) - (Date.parse(a.published) || 0));
    for (const e of newest) {
      e._lang = langOf(e);
      const g = typeof e.story_group === "string" ? e.story_group.trim() : "";
      let u = g && byGroup.get(g);
      if (u && !u.versions.some((v) => v._lang === e._lang)) { u.versions.push(e); e._unit = u; continue; }
      u = { versions: [e] };
      if (g && !byGroup.has(g)) byGroup.set(g, u);
      e._unit = u;
      out.push(u);
    }
    for (const u of out) {
      u.versions.sort((a, b) => langRank(a._lang) - langRank(b._lang) || a._lang.localeCompare(b._lang));
      u.grouped = u.versions.length > 1;
      u.sel = u.chosen = pickVersion(u);   // sel: the version on show; chosen: without a search
    }
    return out;
  }
  // On a language page (podcast #35) a story is listed in that language only, and its other
  // versions are on their own language's page: "_alts" holds one per other language, newest
  // first, each one listed on a page this one links to.
  function linkVersions(eps, all) {
    const newest = all.slice().sort((a, b) => (Date.parse(b.published) || 0) - (Date.parse(a.published) || 0));
    for (const e of eps) {
      const g = typeof e.story_group === "string" ? e.story_group.trim() : "";
      if (!g) continue;
      const seen = new Set([storyLang(e)]);
      e._alts = [];
      for (const o of newest) {
        if (o === e || !o || typeof o.story_group !== "string" || o.story_group.trim() !== g || showOf(o) !== showOf(e)) continue;
        if (seen.has(storyLang(o)) || !pageFor(o)) continue;
        seen.add(storyLang(o));
        e._alts.push(o);
      }
      e._alts.sort((a, b) => langRank(storyLang(a)) - langRank(storyLang(b)));
    }
  }
  // The language switch on a language page: this version, then links to the others on their
  // pages. Following one is a language switch (the same event as the in-place switch, with
  // the new version's parameters) and becomes the visitor's language choice.
  function versionLinks(ep) {
    const from = storyLang(ep);
    const items = [ep, ...ep._alts].sort((a, b) => langRank(storyLang(a)) - langRank(storyLang(b)));
    return el("div", { class: "langs", role: "group", "aria-label": T.langSwitch }, items.map((v) => {
      const lang = storyLang(v);
      const [short, name] = langLabel(lang);
      const kids = [el("span", { class: "sr-only", text: name }), el("span", { class: "l-long", text: name, "aria-hidden": "true" }), el("span", { class: "l-short", text: short, "aria-hidden": "true" })];
      if (v === ep) return el("span", { class: "lang", lang, title: name, "aria-current": "true" }, kids);
      const a = el("a", { class: "lang", href: `${pageFor(v)}#${encodeURIComponent(v.id)}`, lang, hreflang: lang, title: name }, kids);
      a.addEventListener("click", () => {
        store.set("lang", lang);
        track("language_switch", { ...epParams(v), from_language: from, to_language: lang });
      });
      return a;
    }));
  }
  // The version shown first: the visitor's last choice, else the browser's languages, else
  // English, else the first one.
  function pickVersion(u) {
    if (!u.grouped) return u.versions[0];
    const find = (l) => (typeof l === "string" && l ? u.versions.find((v) => v._lang === l) : null);
    const browser = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language])
      .map((l) => primaryLang(String(l || "")));
    for (const l of [primaryLang(store.get("lang")), ...browser, "en"]) { const v = find(l); if (v) return v; }
    return u.versions[0];
  }
  // A switch by the visitor (or a deep link) chooses the version; it stays on show for the
  // current search too, and comes back when the search is cleared.
  function selectVersion(u, v, byUser) {
    if (!u.versions.includes(v)) return;
    if (byUser) store.set("lang", v._lang);
    const hadFocus = u.sel._node.contains(document.activeElement);
    u.chosen = v;
    u.pin = terms().join(" ");
    if (v === u.sel) return;
    if (byUser) track("language_switch", { ...epParams(v), from_language: u.sel._lang, to_language: v._lang });
    showVersion(u, v, true);
    apply();
    if (hadFocus) v._langBtns.get(v._lang)?.focus();
  }
  // Puts a version on show. "follow": a real switch, so the transcript and the player follow
  // it; a search only swaps the card and leaves the player alone.
  function showVersion(u, v, follow) {
    const old = u.sel;
    if (v === old) return;
    const wasOpen = old._toggle.getAttribute("aria-expanded") === "true";
    const trOpen = !!old._tBtn && old._tBtn.getAttribute("aria-expanded") === "true";
    old._node.hidden = true;
    v._node.hidden = false;
    u.sel = v;
    expand(v, wasOpen);
    if (!follow) return;
    if (trOpen && v._tBtn && v._tBtn.getAttribute("aria-expanded") !== "true") openTranscript(v, v._panel, v._tBtn);
    // The player follows the switch: the story keeps playing (or stays paused) in the new language.
    if (current === old) {
      const playing = !audio.paused;
      savePos(audio.currentTime);
      if (playing) play(v); else { load(v); sync(); }
    }
  }
  // While a search is on, a story shows its chosen version if that one matches (or was
  // chosen during this search), else its first matching version. Nothing is stored.
  function versionFor(u, ts) {
    if (!ts.length || u.pin === ts.join(" ") || hits(u.chosen, ts)) return u.chosen;
    return u.versions.find((v) => hits(v, ts)) || u.chosen;
  }

  // ---------- Listening status (from the per-viewer resume points) ----------
  // "done:<id>" is set when an episode plays to the end; "pos:<id>" is the resume point.
  function statusOf(ep) {
    const pos = Number(store.get(`pos:${ep.id}`)) || 0;
    if (pos > 5 && (!ep.duration_s || pos < ep.duration_s - 5)) return "progress";
    return store.get(`done:${ep.id}`) ? "done" : "new";
  }
  function showStatus(ep) {
    if (!ep._status) return;
    const st = statusOf(ep);
    const pos = Number(store.get(`pos:${ep.id}`)) || 0;
    ep._status.hidden = st === "new";
    ep._status.textContent = st === "progress"
      ? T.left(minutes((ep.duration_s || 0) - pos))
      : st === "done" ? T.finished : "";
  }

  // ---------- Tab, search and sort state ----------
  const SORTS = {
    published: { def: "desc", key: (e) => Date.parse(e.published) || null },
    duration: { def: "desc", key: (e) => e.duration_s ?? null },
    title: { def: "asc", key: (e) => fold(e.title) || null },
    source: { def: "desc", key: (e) => Date.parse(e.source?.published) || null },
  };
  for (const [k, [asc, desc]] of Object.entries(T.sorts)) Object.assign(SORTS[k], { asc, desc });
  // Own keys only, so a hand-edited ?sort=constructor (or __proto__) falls back to the default.
  const isSort = (v) => Object.prototype.hasOwnProperty.call(SORTS, v);
  const KIND = { x: "X", article: "Article", paper: "Paper", thread: "Thread", blog: "Blog", web: "Web", pdf: "PDF", arxiv: "arXiv", youtube: "YouTube", reddit: "Reddit", hn: "Hacker News", github: "GitHub", substack: "Substack", medium: "Medium" };
  // Category tabs. Every episode sits in exactly one; "category" comes from
  // episodes.json, with a fallback for entries published before it existed.
  // The page's tabs (from SHOW_PAGE). A page with one tab hides the tab row and lists
  // every episode of its show; otherwise "category" picks the tab, unknown ones go last.
  const TABS = PAGE.tabs.length ? PAGE.tabs : [{ id: "all", label: "Episodes", empty: "No episodes yet.", tagline: [] }];
  const DEF_TAB = TABS[0].id;
  const isTab = (v) => TABS.some((t) => t.id === v);
  const catOf = (e) => (TABS.length === 1 ? DEF_TAB : isTab(e.category) ? e.category : TABS[TABS.length - 1].id);
  const state = { tab: DEF_TAB, q: "", sort: "published", dir: "desc" };
  const terms = () => fold(state.q).split(/\s+/).filter(Boolean);

  function readUrl() {
    const p = new URLSearchParams(location.search);
    // A tab that moved to another page (the old Bedtime tab): follow it there.
    const moved = Object.prototype.hasOwnProperty.call(PAGE.legacyTabs, p.get("tab")) && PAGE.legacyTabs[p.get("tab")];
    if (moved) { location.replace(`${moved}${location.hash}`); return false; }
    state.tab = isTab(p.get("tab")) ? p.get("tab") : DEF_TAB;
    state.q = p.get("q") || "";
    state.sort = isSort(p.get("sort")) ? p.get("sort") : "published";
    const dir = p.get("order");
    state.dir = dir === "asc" || dir === "desc" ? dir : SORTS[state.sort].def;
    return true;
  }
  function writeUrl() {
    // Only non-default settings go in the query, so a plain link stays clean. The hash
    // is the episode deep link and is kept as it is.
    const p = new URLSearchParams();
    if (state.tab !== DEF_TAB) p.set("tab", state.tab);
    if (state.q.trim()) p.set("q", state.q.trim());
    if (state.sort !== "published") p.set("sort", state.sort);
    if (state.dir !== SORTS[state.sort].def) p.set("order", state.dir);
    const qs = p.toString();
    try { history.replaceState(null, "", `${location.pathname}${qs ? `?${qs}` : ""}${location.hash}`); } catch { /* ignore */ }
  }

  // A story in several languages matches when any of its versions does.
  const hits = (ep, ts) => ts.every((t) => ep._hay.includes(t));
  function matches(u) {
    if (u._cat !== state.tab) return false;
    const ts = terms();
    return u.versions.some((ep) => hits(ep, ts));
  }

  function sorted() {
    const s = SORTS[state.sort];
    const mul = state.dir === "asc" ? 1 : -1;
    return units.slice().sort((ua, ub) => {
      const a = ua.sel, b = ub.sel;   // a story sorts by the version on show
      const ka = s.key(a), kb = s.key(b);
      // Missing values (an unknown source date, say) always sink to the end.
      if (ka == null && kb != null) return 1;
      if (kb == null && ka != null) return -1;
      if (ka != null && ka !== kb) return (ka < kb ? -1 : 1) * mul;
      return (Date.parse(b.published) || 0) - (Date.parse(a.published) || 0) || a.id.localeCompare(b.id);
    });
  }

  function mark(node, text, ts) {
    if (!ts.length) { node.textContent = text; return; }
    const re = new RegExp(`(${ts.map(escapeRe).join("|")})`, "gi");
    node.replaceChildren(...text.split(re).map((part, i) => (i % 2 ? el("mark", { text: part }) : part)));
  }

  function buildTabs() {
    const box = $("tabs");
    box.replaceChildren();
    box.hidden = TABS.length < 2;
    for (const t of TABS) {
      t.n = el("span", { class: "n" });
      t.btn = el("button", { class: "tab", type: "button", role: "tab", id: `tab-${t.id}`, "aria-controls": "episodes", "aria-selected": "false", tabIndex: -1 }, [el("span", { class: "l-long", text: t.label }), el("span", { class: "l-short", text: t.short || t.label, "aria-hidden": "true" }), t.n]);
      t.btn.addEventListener("click", () => selectTab(t.id));
      box.append(t.btn);
    }
    // Arrow keys move between tabs (the usual tablist pattern); Home and End jump.
    box.addEventListener("keydown", (e) => {
      const i = TABS.findIndex((t) => t.id === state.tab);
      const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
      if (to == null) return;
      e.preventDefault();
      const t = TABS[(to + TABS.length) % TABS.length];
      selectTab(t.id);
      t.btn.focus();
    });
  }

  function selectTab(id) {
    if (!isTab(id) || id === state.tab) return;
    state.tab = id;   // the search carries over
    apply();
  }

  function showTab() {
    const tab = TABS.find((t) => t.id === state.tab);
    for (const t of TABS) {
      const on = t === tab;
      const n = units.filter((u) => u._cat === t.id).length;
      t.btn.setAttribute("aria-selected", String(on));
      t.btn.tabIndex = on ? 0 : -1;
      t.btn.setAttribute("aria-label", `${t.label}, ${n} ${noun(n)}`);
      t.n.textContent = n;
    }
    list.setAttribute("aria-labelledby", `tab-${tab.id}`);
    if (tab.tagline.length) $("tagline").replaceChildren(...tab.tagline.map((part) => (Array.isArray(part) ? el("strong", { text: part[0] }) : part)));
    const sel = tab.btn;
    if (sel && sel.parentNode.scrollWidth > sel.parentNode.clientWidth) sel.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // Tabs, search and sorting move and hide the existing rows; they never rebuild them, so
  // the playing row, open transcripts and live cue highlights survive every change.
  function apply() {
    if (!isSort(state.sort)) { state.sort = "published"; state.dir = SORTS.published.def; }
    if (!isTab(state.tab)) state.tab = DEF_TAB;
    if (!noMatch) return;   // the toolbar is live before the episode list has loaded
    const ts = terms();
    for (const u of units) {
      u._cat = catOf(u.chosen);
      if (u.grouped) showVersion(u, versionFor(u, ts), false);
    }
    showTab();
    const order = sorted();
    const rows = [...list.children].filter((n) => n.classList.contains("ep") || n.classList.contains("ep-group"));
    if (order.some((u, i) => rows[i] !== u._node)) for (const u of order) list.insertBefore(u._node, noMatch);
    let shown = 0;
    for (const u of order) {
      const on = matches(u);
      u._node.hidden = !on;
      if (on) shown++;
      for (const e of u.versions) {
        mark(e._titleText, e.title, ts);
        e._summary.forEach((li, i) => mark(li, e.summary[i], ts));
      }
    }
    const total = units.filter((u) => u._cat === state.tab).length;
    const active = !!ts.length;
    const count = $("count");
    count.replaceChildren(...(active
      ? [el("b", { text: shown }), T.of(total, noun(total))]
      : [el("b", { text: total }), ` ${noun(total)} · ${SORTS[state.sort][state.dir].toLocaleLowerCase(T.locale)}`]));
    $("clear-all").hidden = !active;
    noMatch.hidden = shown > 0 || !units.length;
    noMatch.querySelector("div").hidden = !total;
    if (!total) {
      noMatch.querySelector("strong").textContent = TABS.find((t) => t.id === state.tab).empty;
      noMatch.querySelector("span").textContent = T.newSoon;
    } else if (!shown) {
      noMatch.querySelector("strong").textContent = T.noMatch;
      noMatch.querySelector("span").textContent = T.noMatchText(state.q.trim());
    }
    // Sort controls reflect the state (it may come from the URL).
    $("sort").value = state.sort;
    const ob = $("order");
    ob.dataset.dir = state.dir;
    $("order-label").textContent = SORTS[state.sort][state.dir];
    const other = SORTS[state.sort][state.dir === "asc" ? "desc" : "asc"];
    ob.setAttribute("aria-label", T.order(SORTS[state.sort][state.dir], other.toLocaleLowerCase(T.locale)));
    $("search").classList.toggle("has-q", !!state.q);
    writeUrl();
  }

  function clearAll(e) {
    const from = document.activeElement;
    state.q = ""; qInput.value = "";
    apply();
    // Both clear buttons hide themselves; on keyboard activation (click detail 0), keep focus on a stable control.
    if (e && e.detail === 0 && from && from !== document.body && from.closest("[hidden]")) qInput.focus();
  }

  // ---------- Render (once per load) ----------
  function render() {
    list.replaceChildren();
    list.removeAttribute("aria-busy");
    noMatch = el("li", { class: "state", hidden: true }, [
      el("strong", { text: T.noMatch }), el("span"),
      el("div", {}, el("button", { class: "btn", type: "button", text: T.clearSearch, onclick: clearAll })),
    ]);
    list.append(noMatch);
    if (!units.length) {
      list.prepend(el("li", { class: "state" }, [el("strong", { text: T.empty }), T.emptyText]));
    }
    units.forEach((u, i) => list.insertBefore(row(u, i), noMatch));
    // A story counts once, in its counts and in its minutes (the version shown first).
    const total = units.reduce((a, u) => a + (u.chosen.duration_s || 0), 0);
    const latest = episodes.map((e) => e.published).sort().pop();
    $("stat-count").textContent = units.length;
    $("stat-count-label").textContent = noun(units.length);
    $("stat-min").textContent = Math.round(total / 60);
    // Drop the year for this year's episodes: "Nov 3" says enough and keeps the strip on one line.
    const sameYear = latest && new Date(latest).getFullYear() === new Date().getFullYear();
    $("stat-latest").textContent = latest ? day(latest, !sameYear) : "–";
    buildTabs();
    apply();
    openTarget(false);
  }

  // One list row: an episode's card, or one card per language version of a story with
  // only the selected one shown.
  function row(u, i) {
    if (!u.grouped) return (u._node = card(u.sel, i, u));
    const li = el("li", { class: "ep-group enter" }, u.versions.map((v) => card(v, i, u)));
    li.style.animationDelay = `${Math.min(i, 10) * 40}ms`;
    li.addEventListener("animationend", (e) => { if (e.animationName === "rise") li.classList.remove("enter"); });
    return (u._node = li);
  }

  function card(ep, i, u) {
    const grouped = !!(u && u.grouped);
    const src = ep.source || {};
    const url = safeUrl(src.url);
    ep.summary = Array.isArray(ep.summary) ? ep.summary : [];
    // Every source used (main first) and the guests who presented the extra ones.
    const sources = (Array.isArray(ep.sources) ? ep.sources : []).filter((x) => x && typeof x === "object");
    const extras = sources.slice(1);
    const guests = (Array.isArray(ep.guests) ? ep.guests : []).filter((g) => g && typeof g.name === "string" && g.name);
    ep._hay = fold([ep.title, ...ep.summary, src.title, src.author, host(src.url), KIND[src.kind] || src.kind, (ep.hosts || []).join(" "), ep.voices,
      ...extras.flatMap((x) => [x.title, x.author, host(x.url)]), ...guests.map((g) => g.name)].join(" \n "));

    const playBtn = el("button", { class: "play", type: "button", "aria-label": T.playEp(ep.title) }, [
      svg([PLAY]), el("span", { class: "eq", "aria-hidden": "true" }, [el("b"), el("b"), el("b")]),
    ]);
    playBtn.addEventListener("click", () => toggle(ep));
    // No playable audio (resolveAudio() refused it): no Play button, as with Download.
    if (!ep.audio) playBtn.hidden = true;

    const detailId = `det-${ep.id}`;
    const titleText = el("span", grouped ? { text: ep.title, lang: ep._lang } : { text: ep.title });
    // The title links to the episode's own page (crawlers, a middle or modified click); a
    // plain click or Enter/Space expands the row as before.
    const toggleBtn = el("a", { class: "ep-toggle", href: pageOf(ep), "aria-expanded": "false", "aria-controls": detailId }, titleText);
    const status = el("span", { class: "st", hidden: true });
    const where = host(src.url);
    const meta = el("div", { class: "meta" }, [
      el("span", { class: "dur", text: minutes(ep.duration_s) }),
      el("span", { text: day(ep.published) }),
      where ? el("span", { text: where }) : null,
      status,
    ]);
    // The language switch of a story in several languages, labelled in each language.
    const langBtns = new Map();
    const langs = grouped
      ? el("div", { class: "langs", role: "group", "aria-label": T.langSwitch }, u.versions.map((v) => {
        const [short, name] = langLabel(v._lang);
        const b = el("button", { class: "lang", type: "button", lang: v._lang, title: name, "aria-label": name, "aria-pressed": String(v === ep) }, [
          el("span", { class: "l-long", text: name }), el("span", { class: "l-short", text: short, "aria-hidden": "true" }),
        ]);
        b.addEventListener("click", () => selectVersion(u, v, true));
        langBtns.set(v._lang, b);
        return b;
      }))
      : ep._alts && ep._alts.length ? versionLinks(ep) : null;
    // The story's square thumbnail next to the title (decorative there: the title names it).
    const thumbUrl = artOf(ep, "thumb");
    const thumb = thumbUrl ? el("img", { class: "thumb", src: thumbUrl, alt: "", loading: "lazy", decoding: "async", width: 64, height: 64 }) : null;
    const rowEl = el("div", { class: thumb ? "ep-row has-art" : "ep-row" }, [
      playBtn,
      thumb,
      el("div", { class: "ep-head" }, [el("h3", {}, toggleBtn), meta, langs]),
      svg(["M6 9l6 6 6-6"], "chev"),
    ]);

    const summaryItems = ep.summary.map((line) => el("li", grouped ? { text: line, lang: ep._lang } : { text: line }));
    const credit = el("p", { class: "credit" }, url
      ? [T.basedOn, trackLink(el("a", { href: url, target: "_blank", rel: "noopener", text: src.title || host(url) }), "source_click", ep), src.author ? `${T.by}${src.author}` : "", ` · ${host(url)}`]
      : [src.title ? `${T.basedOn}${src.title}` : ""]);
    let sourceList = null;
    if (sources.length > 1) {
      sourceList = el("div", { class: "sources" }, [
        el("h4", { text: T.sources }),
        el("ol", {}, sources.map((x) => {
          const u = safeUrl(x.url);
          const name = String(x.title || host(u) || T.untitled);
          return el("li", {}, [
            u ? trackLink(el("a", { href: u, target: "_blank", rel: "noopener", text: name }), "source_click", ep) : name,
            x.author ? `${T.by}${x.author}` : "",
            u ? ` · ${host(u)}` : "",
          ]);
        })),
      ]);
    }
    const guestLine = guests.length
      ? el("p", { class: "guests" }, [T.guests, ...guests.flatMap((g, i) => {
        const shows = (Array.isArray(g.presents) ? g.presents : []).filter((t) => typeof t === "string" && t);
        return [i ? ", " : "", el("strong", { text: g.name }), shows.length ? T.presents(shows.join(", ")) : ""];
      })])
      : null;
    // Licensed music that needs attribution (CC-BY): shown as plain text.
    const musicCredit = typeof ep.music_credit === "string" ? ep.music_credit.trim() : "";
    const musicLine = musicCredit ? el("p", { class: "music", text: T.music(musicCredit) }) : null;
    const actions = el("div", { class: "actions" });
    let panel = null;
    let tBtn = null;
    if (ep.transcript) {
      panel = el("div", { class: "transcript", hidden: true, id: `tr-${ep.id}` });
      tBtn = el("button", { class: "btn", type: "button", "aria-expanded": "false", "aria-controls": `tr-${ep.id}` }, [
        svg(["M4 6h16M4 12h16M4 18h10"]), T.transcript,
      ]);
      tBtn.addEventListener("click", () => openTranscript(ep, panel, tBtn));
      actions.append(tBtn);
    }
    if (ep.audio) actions.append(trackLink(el("a", { class: "btn", href: ep.audio, download: fileName(ep) }, [svg(["M12 4v12M6 10l6 6 6-6M5 20h14"]), T.download]), "episode_download", ep));
    // The copy-paste podcast description (DropCast #163), exactly as in episodes.json.
    if (typeof ep.description === "string" && ep.description.trim()) {
      const descLabel = el("span", { text: T.copyDesc, "aria-live": "polite" });
      const descBtn = el("button", { class: "btn", type: "button", "data-copy": "description" }, [svg(["M9 9h10v11H9zM5 15V4h10"]), descLabel]);
      descBtn.addEventListener("click", () => copyDescription(ep, descBtn, descLabel));
      actions.append(descBtn);
    }
    if (url) actions.append(trackLink(el("a", { class: "btn", href: url, target: "_blank", rel: "noopener" }, [svg(["M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"]), T.readSource]), "source_click", ep));
    const linkLabel = el("span", { text: T.copyLink });
    const linkBtn = el("button", { class: "btn", type: "button" }, [svg(["M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"]), linkLabel]);
    linkBtn.addEventListener("click", () => copyLink(ep, linkBtn, linkLabel));
    actions.append(linkBtn);
    // The wide illustration above the summary; lazy, so it loads when the details open.
    const wideUrl = artOf(ep, "wide");
    const art = wideUrl ? el("img", { class: "art", src: wideUrl, alt: artAlt(ep), loading: "lazy", decoding: "async", width: 1920, height: 1080 }) : null;
    const detail = el("div", { class: "ep-detail", id: detailId, hidden: true }, [
      art, summaryItems.length ? el("ul", { class: "summary" }, summaryItems) : null, credit, sourceList, guestLine, musicLine, actions, panel,
    ]);
    toggleBtn.addEventListener("click", (e) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // opens the page
      e.preventDefault();
      expand(ep, toggleBtn.getAttribute("aria-expanded") !== "true");
    });
    toggleBtn.addEventListener("keydown", (e) => { if (e.key === " ") { e.preventDefault(); toggleBtn.click(); } });

    const bar = el("div", { class: "progress", "aria-hidden": "true" }, el("i"));
    const pos = store.get(`pos:${ep.id}`);
    if (pos && ep.duration_s) bar.firstChild.style.width = `${Math.min(100, (pos / ep.duration_s) * 100)}%`;

    // A language version is a block inside its story's row; only the selected one shows.
    const li = grouped
      ? el("div", { class: "ep", id: `ep-${ep.id}`, lang: ep._lang, hidden: ep !== u.sel }, [rowEl, detail, bar])
      : el("li", { class: "ep enter", id: `ep-${ep.id}` }, [rowEl, detail, bar]);
    if (!grouped) {
      li.style.animationDelay = `${Math.min(i, 10) * 40}ms`;
      li.addEventListener("animationend", (e) => { if (e.animationName === "rise") li.classList.remove("enter"); });
    }
    Object.assign(ep, { _node: li, _bar: bar.firstChild, _btn: playBtn, _toggle: toggleBtn, _detail: detail, _titleText: titleText, _summary: summaryItems, _status: status, _tBtn: tBtn, _panel: panel, _langBtns: langBtns });
    showStatus(ep);
    return li;
  }

  function expand(ep, open) {
    ep._toggle.setAttribute("aria-expanded", String(open));
    ep._detail.hidden = !open;
    ep._node.classList.toggle("is-open", open);
  }

  async function copyLink(ep, btn, label) {
    const link = `${location.origin}${location.pathname}#${encodeURIComponent(ep.id)}`;
    try { await navigator.clipboard.writeText(link); label.textContent = T.linkCopied; }
    catch { history.replaceState(null, "", `${location.pathname}${location.search}#${encodeURIComponent(ep.id)}`); label.textContent = T.linkInBar; }
    btn.classList.add("is-done");
    setTimeout(() => { label.textContent = T.copyLink; btn.classList.remove("is-done"); }, 1800);
  }

  // Clipboard API, else a hidden textarea and execCommand (older browsers, http pages).
  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
    } catch { /* fall back */ }
    const focus = document.activeElement;
    const ta = el("textarea", { value: text, readOnly: true, "aria-hidden": "true", tabIndex: -1 });
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;";
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    if (focus && typeof focus.focus === "function") focus.focus({ preventScroll: true });
    return ok;
  }

  async function copyDescription(ep, btn, label) {
    const ok = await copyText(ep.description);
    label.textContent = ok ? T.copied : T.copyFailed;
    btn.classList.toggle("is-done", ok);
    if (ok) track("description_copy", epParams(ep));
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { label.textContent = T.copyDesc; btn.classList.remove("is-done"); }, 1800);
  }

  // A shared link (#<episode id>) opens that episode in its tab. If the search
  // hides it, the search is cleared so the link never lands on nothing.
  function openTarget(fromHashChange) {
    const id = hashId(location.hash);
    const ep = id && episodes.find((e) => e.id === id);
    setMetaDesc(ep || null);
    if (!ep) {
      // A link to an episode listed on another page (the other show's, shared before the
      // stories moved, or a story in another language): forward it.
      const away = id && others.find((e) => e.id === id);
      const page = away && pageFor(away);
      if (page) location.replace(`${page}${location.hash}`);
      return;
    }
    const u = ep._unit;
    selectVersion(u, ep, false);   // a version's link opens (and chooses) that version
    if (u._cat !== state.tab) { state.tab = u._cat; apply(); }
    if (u._node.hidden) clearAll();
    expand(ep, true);
    ep._node.classList.remove("is-target");
    void ep._node.offsetWidth;
    ep._node.classList.add("is-target");
    ep._node.scrollIntoView({ block: "start", behavior: fromHashChange && !reduced() ? "smooth" : "auto" });
  }

  // ---------- Transcript ----------
  function parseVtt(text) {
    const out = [];
    const toS = (t) => { const p = t.trim().split(":").map(Number); return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1]; };
    for (const block of text.replace(/\r/g, "").split(/\n\n+/)) {
      const lines = block.split("\n");
      const at = lines.findIndex((l) => l.includes("-->"));
      if (at < 0) continue;
      const [a, b] = lines[at].split("-->");
      let body = lines.slice(at + 1).join(" ").trim();
      let who = "";
      const m = body.match(/^<v\s+([^>]+)>/);
      if (m) { who = m[1].trim(); body = body.slice(m[0].length); }
      body = body.replace(/<[^>]+>/g, "").trim();
      // The end time may be followed by cue settings ("00:00:06.541 align:start").
      if (body) out.push({ start: toS(a), end: toS(b.trim().split(/\s+/)[0]), who, text: body });
    }
    return out;
  }

  async function openTranscript(ep, panel, btn) {
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    panel.hidden = open;
    if (open || cues.has(ep.id)) return;
    panel.replaceChildren(el("p", { class: "t-state", text: T.loadingTranscript }));
    try {
      const res = await fetch(ep.transcript);
      if (!res.ok) throw new Error(res.status);
      const items = parseVtt(await res.text());
      const ol = el("ol", { "aria-label": T.transcriptOf(ep.title) });
      for (const c of items) {
        const b = el("button", { class: "cue", type: "button" }, [
          el("time", { text: clock(c.start) }),
          el("span", {}, [c.who ? el("span", { class: "who", text: c.who }) : "", c.text]),
        ]);
        b.addEventListener("click", () => play(ep, c.start));
        c.el = b;
        ol.append(el("li", {}, b));
      }
      cues.set(ep.id, items);
      panel.replaceChildren(ol);
      if (current === ep) highlight();
    } catch {
      panel.replaceChildren(el("p", { class: "t-state", text: T.transcriptFailed }));
    }
  }

  function highlight() {
    const items = current && cues.get(current.id);
    if (!items) return;
    const t = audio.currentTime;
    for (const c of items) {
      const now = t >= c.start && t < c.end + 0.3;
      if (now && !c.el.classList.contains("is-now")) {
        c.el.classList.add("is-now");
        const box = c.el.closest("ol");
        if (box && !box.closest("[hidden]")) {
          const top = c.el.offsetTop - box.offsetTop - box.clientHeight / 3;
          box.scrollTo({ top, behavior: reduced() ? "auto" : "smooth" });
        }
      } else if (!now) c.el.classList.remove("is-now");
    }
  }

  // ---------- Playback ----------
  function toggle(ep) {
    if (current === ep && !audio.paused) audio.pause();
    else play(ep);
  }

  // Put an episode in the player (without starting it).
  function load(ep, at) {
    if (!ep || !ep.audio) return; // never audio.src = null (it would request "null")
    if (current) current._node.classList.remove("is-current", "is-playing");
    current = ep;
    audio.src = ep.audio;
    audio.playbackRate = Number(store.get("speed")) || 1;
    const resume = store.get(`pos:${ep.id}`);
    audio.currentTime = at ?? (resume && ep.duration_s && resume < ep.duration_s - 5 ? resume : 0);
    ep._node.classList.add("is-current");
    $("p-title").textContent = ep.title;
    player.classList.add("is-on");
    document.documentElement.style.setProperty("--player-h", `${player.offsetHeight}px`);
    if ("mediaSession" in navigator) {
      // The story's illustration as the lock-screen artwork: only the 640 px thumbnail, so a
      // play on a phone never downloads the 3000 px podcast-app artwork.
      const artwork = [["thumb", "640x640"]]
        .map(([kind, sizes]) => { const src = artOf(ep, kind); return src ? { src, sizes, type: "image/jpeg" } : null; })
        .filter(Boolean);
      navigator.mediaSession.metadata = new MediaMetadata({ title: ep.title, artist: PAGE.artist || (ep.hosts || []).join(" & "), album: PAGE.show, ...(artwork.length ? { artwork } : {}) });
    }
  }

  function play(ep, at) {
    if (!ep || !ep.audio) return;
    if (current !== ep) load(ep, at);
    else if (at != null) audio.currentTime = at;
    audio.play().catch(() => sync());
  }

  function sync() {
    const playing = current && !audio.paused;
    $("p-glyph").setAttribute("d", playing ? PAUSE : PLAY);
    $("p-toggle").setAttribute("aria-label", playing ? T.pause : T.play);
    for (const ep of episodes) {
      const on = ep === current && playing;
      ep._node.classList.toggle("is-playing", on);
      ep._btn.setAttribute("aria-label", on ? T.pauseEp(ep.title) : T.playEp(ep.title));
      ep._btn.querySelector("path").setAttribute("d", on ? PAUSE : PLAY);
    }
  }

  function savePos(t) {
    if (!current) return;
    store.set(`pos:${current.id}`, Math.floor(t));
    showStatus(current);
  }

  function tick() {
    const d = audio.duration || current?.duration_s || 0;
    const t = audio.currentTime || 0;
    const pct = d ? `${(t / d) * 100}%` : "0%";
    seek.max = Math.floor(d);
    if (!seek.matches(":active")) seek.value = Math.floor(t);
    seek.style.setProperty("--pct", pct);
    $("p-cur").textContent = clock(t);
    $("p-dur").textContent = clock(d);
    $("tb-progress").style.width = pct;
    if (current && d) current._bar.style.width = pct;
    highlight();
    trackProgress(false);
    if (current && Date.now() - saveTimer > 3000) { saveTimer = Date.now(); savePos(t); }
  }

  audio.addEventListener("play", sync);
  // The first time an episode really starts in this page view (not a resume after a pause).
  audio.addEventListener("playing", () => {
    if (!current || played.has(current.id)) return;
    played.add(current.id);
    track("episode_play", epParams(current));
  });
  audio.addEventListener("pause", () => { sync(); savePos(audio.currentTime); });
  audio.addEventListener("ended", () => { trackProgress(true); if (current) { store.set(`done:${current.id}`, true); savePos(0); } sync(); });
  audio.addEventListener("timeupdate", tick);
  audio.addEventListener("loadedmetadata", tick);
  audio.addEventListener("error", () => { if (current) $("p-title").textContent = T.audioFailed(current.title); sync(); });
  seek.addEventListener("input", () => { audio.currentTime = Number(seek.value); tick(); });
  $("p-toggle").addEventListener("click", () => current && toggle(current));
  $("p-back").addEventListener("click", () => { audio.currentTime = Math.max(0, audio.currentTime - 15); });
  $("p-fwd").addEventListener("click", () => { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 30); });
  const speedBtn = $("p-speed");
  const showSpeed = () => { speedBtn.textContent = `${audio.playbackRate}×`; speedBtn.setAttribute("aria-label", T.speed(audio.playbackRate)); };
  audio.playbackRate = Number(store.get("speed")) || 1; showSpeed();
  speedBtn.addEventListener("click", () => {
    const next = SPEEDS[(SPEEDS.indexOf(audio.playbackRate) + 1) % SPEEDS.length];
    audio.playbackRate = next; store.set("speed", next); showSpeed();
  });
  audio.addEventListener("ratechange", showSpeed);
  if ("mediaSession" in navigator) {
    navigator.mediaSession.setActionHandler("play", () => audio.play());
    navigator.mediaSession.setActionHandler("pause", () => audio.pause());
    navigator.mediaSession.setActionHandler("seekbackward", () => { audio.currentTime -= 15; });
    navigator.mediaSession.setActionHandler("seekforward", () => { audio.currentTime += 30; });
  }

  // ---------- Toolbar wiring ----------
  let qTimer = 0;
  qInput.addEventListener("input", () => {
    state.q = qInput.value;
    $("search").classList.toggle("has-q", !!state.q);
    clearTimeout(qTimer);
    qTimer = setTimeout(apply, 120);
  });
  qInput.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (qInput.value) { qInput.value = ""; state.q = ""; apply(); } else qInput.blur();
    e.stopPropagation();
  });
  $("search").addEventListener("click", (e) => { if (!e.target.closest("button")) qInput.focus(); });
  $("clear-q").addEventListener("click", () => { qInput.value = ""; state.q = ""; apply(); qInput.focus(); });
  $("sort").addEventListener("change", (e) => { state.sort = e.target.value; state.dir = SORTS[state.sort].def; apply(); });
  $("order").addEventListener("click", () => { state.dir = state.dir === "asc" ? "desc" : "asc"; apply(); });
  $("clear-all").addEventListener("click", clearAll);
  addEventListener("hashchange", () => openTarget(true));

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing) { e.preventDefault(); qInput.focus(); qInput.select(); return; }
    if (!current || typing || e.target.closest("button, a")) return;
    if (e.code === "Space") { e.preventDefault(); toggle(current); }
    else if (e.key === "ArrowLeft") audio.currentTime = Math.max(0, audio.currentTime - 5);
    else if (e.key === "ArrowRight") audio.currentTime += 5;
  });

  // Keep the sticky toolbar's height in a variable so deep-linked rows scroll clear of it.
  const toolbar = $("toolbar");
  const measure = () => {
    document.documentElement.style.setProperty("--toolbar-h", `${toolbar.offsetHeight}px`);
    if (player.classList.contains("is-on")) document.documentElement.style.setProperty("--player-h", `${player.offsetHeight}px`);
  };
  if ("ResizeObserver" in window) new ResizeObserver(measure).observe(toolbar);
  addEventListener("resize", measure);
  measure();

  // ---------- Load ----------
  // Media paths in episodes.json are relative to it, so a page in a subfolder resolves them.
  const resolve = (path) => (typeof path === "string" && path ? new URL(path, DATA_URL).href : path);
  // The episode audio is a file on the GitHub Pages site of its show/language media repo
  // (podcast #33; publish.py MEDIA_REPOS, pages_url()): an absolute URL is used only when,
  // after parsing, its origin is https://luongnv.com and its path is exactly
  // /<media repo>/<id>.mp3 (PAGES_PATH), or, until every entry is re-pointed, its origin is
  // https://github.com and its path is exactly
  // /luongnv89/<media repo>/releases/download/<tag>/<tag>.mp3 (MEDIA_PATH, podcast #30;
  // iPhone Safari does not play those). Never with credentials, "..", a backslash or a
  // percent-encoded dot, slash or backslash, which the parser would turn into a dot segment
  // or a slash; a relative path (before #30) resolves as above. Anything else (another
  // host, path or repo, a javascript: or data: URL) is dropped, and an episode without
  // audio gets no Play or Download button. Cross-origin `download` attributes are ignored,
  // so the download name is the file's.
  const MEDIA_REPO = "(?:buildwiz-ai-show|once-upon-a-time-(?:en|fr|vi))-media";
  const PAGES_PATH = new RegExp(`^\\/${MEDIA_REPO}\\/[A-Za-z0-9][A-Za-z0-9._-]*\\.mp3$`);
  const MEDIA_PATH = /^\/luongnv89\/(?:buildwiz-ai-show|once-upon-a-time-(?:en|fr|vi))-media\/releases\/download\/([A-Za-z0-9][A-Za-z0-9._-]*)\/([A-Za-z0-9][A-Za-z0-9._-]*)\.mp3$/;
  const mediaUrl = (path) => {
    if (/%2e|%2f|%5c|\.\.|\\/i.test(path)) return null;
    let url;
    try { url = new URL(path); } catch { return null; }
    if (url.username || url.password) return null;
    if (url.origin === "https://luongnv.com") return PAGES_PATH.test(url.pathname) ? url.origin + url.pathname : null;
    if (url.origin !== "https://github.com") return null;
    const m = MEDIA_PATH.exec(url.pathname);
    return m && m[1] === m[2] ? url.origin + url.pathname : null;
  };
  const resolveAudio = (path) => {
    if (typeof path !== "string" || !path) return null;
    if (/^[a-z][a-z0-9+.-]*:|^[\\/]{2}/i.test(path)) return mediaUrl(path);
    return resolve(path);
  };
  if (!readUrl()) return;
  qInput.value = state.q;
  fetch(DATA_URL, { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((data) => {
      const all = Array.isArray(data.episodes) ? data.episodes.filter((e) => e && e.id) : [];
      for (const e of all) { e.audio = resolveAudio(e.audio); e.transcript = resolve(e.transcript); }
      episodes = all.filter(onPage);
      others = all.filter((e) => !onPage(e));
      if (PAGE.lang) linkVersions(episodes, all);
      units = groupUnits(episodes);
      render();
    })
    .catch(() => {
      list.removeAttribute("aria-busy");
      $("count").textContent = T.loadFailed;
      for (const c of document.querySelectorAll("#toolbar input, #toolbar select, #toolbar button")) c.disabled = true;
      list.replaceChildren(el("li", { class: "state" }, [el("strong", { text: T.loadFailedTitle }), T.loadFailedText]));
    });
})();
