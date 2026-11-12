#!/usr/bin/env python3
"""Write one static page per episode and the sitemap (DropCast #163), for search engines.

Usage:
    python3 scripts/pages.py build            # rewrite every page and docs/sitemap.xml

The show pages are single pages with ``#<id>`` links, which give crawlers no episode of
their own. So each episode in ``docs/episodes.json`` also gets
``docs/episodes/<id>/index.html``: title ``<Title> | <Show>``, ``<meta name="description">``
= the description's hook (its first paragraph), a canonical URL, Open Graph and Twitter
tags with the show's cover, ``PodcastEpisode`` JSON-LD, the audio player (the entry's
``audio``: its media site URL or release asset URL, or the page's own ``episode.mp3`` for a relative path), the full
description, the download link, a Share button (podcast #43: the share sheet, else the
page's URL copied) and a link back to ``#<id>`` on the page that lists it (a story's
language page, ``stories/<lang>/``, podcast #35). A story in several languages links
its other versions (``hreflang``). ``docs/sitemap.xml`` lists Build Wiz AI Show's page, the
stories' language chooser (``stories/``), the three story language pages and every episode
page.

A story with an illustration (``image`` in ``episodes.json``, its files under ``docs/art/``)
shows the wide picture at the top of its page, uses it for ``og:image``/``twitter:image``
(``summary_large_image``) and the square one for the JSON-LD ``image``. Without one the page
is exactly as before.

A story's page is in the story's language (podcast #38): every word around the episode's
own text comes from ``UI``, French or Vietnamese for a story listed on those pages. Every
Build Wiz AI Show page, and every English story page, is in English, word for word as
before. ``<html lang>`` is the episode's own language, as before (so a Vietnamese Build Wiz
AI Show episode keeps ``lang="vi"`` around the English words).

``publish.py`` rebuilds them after every publish (and with ``--backfill``), so they always
follow ``episodes.json``. A file is rewritten only when its bytes change, and nothing
depends on the clock, so a rebuild with no new episode changes nothing.

Standard library only. Prints one JSON object. Exit 0 ok, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs"
INDEX = "episodes.json"
BASE_URL = "https://luongnv.com/podcast/"
BUILD_SHOW = "Build Wiz AI Show"
STORY_SHOW = "Once Upon a Time Show"
STORY_FORMATS = ("bedtime-story", "storytelling")
GA_ID = "G-FZV5YX8YPT"
# A show's page lists its episodes; the stories have one page per language (podcast #35),
# under the chooser ``stories/`` (``STORY_CHOOSER``).
SHOWS = {
    BUILD_SHOW: {"page": "", "cover": "cover.jpg", "accent": "#22C55E"},
    STORY_SHOW: {"page": "stories/{lang}/", "cover": "stories/cover-{lang}.jpg", "accent": "#F2C46D"},
}
STORY_CHOOSER = "stories/"
LANG_NAMES = {"en": "English", "fr": "Français", "vi": "Tiếng Việt"}
# The story languages with a page of their own; a story in any other language is listed on
# the English page (as its audio goes to the English stories repo). site.js: STORY_LANGS.
STORY_LANGS = tuple(LANG_NAMES)
LOCALES = {"en": "en_US", "fr": "fr_FR", "vi": "vi_VN"}
# The words of an episode page (podcast #38). A story's page is in its language (the one of
# the page that lists it, ``story_lang()``); every Build Wiz AI Show page is in English,
# whatever its language, word for word as before. The English is the text the pages always
# had. The French and Vietnamese speak of stories ("histoire", "truyện") like the story
# pages; "download", "transcript", "based on ... by", "min", "illustration" and the Share
# button's words (podcast #43) are the words of site.js's TEXT (docs/site.js:20), and the
# footer follows the story pages' own footer. French puts a no-break space (\u00a0) before
# ":" and in "7 min", as in site.js. The show's name is a name and stays as it is, as on
# the story pages.
UI = {
    "en": {
        "listen": "Listen on {show}",
        "download": "Download MP3",
        "transcript": "Transcript",
        "also_in": "Also in: ",
        "based_on": "Based on ",
        "by": " by ",
        "min": "{n} min",
        "illustration": "Illustration: {title}",
        "share": "Share",
        "link_copied": "Link copied",
        "copy_failed": "Copy failed",
        "footer": "AI-voiced episode made with DropCast. Voices are synthetic; each episode credits its source.",
    },
    "fr": {
        "listen": "Écouter sur {show}",
        "download": "Télécharger le MP3",
        "transcript": "Transcription",
        "also_in": "Également disponible en\u00a0: ",
        "based_on": "D’après ",
        "by": ", de ",
        "min": "{n}\u00a0min",
        "illustration": "Illustration\u00a0: {title}",
        "share": "Partager",
        "link_copied": "Lien copié",
        "copy_failed": "Échec de la copie",
        "footer": "Histoire réalisée avec DropCast et lue par une voix de synthèse. "
        "Chaque histoire cite le texte dont elle s’inspire.",
    },
    "vi": {
        "listen": "Nghe trên {show}",
        "download": "Tải MP3",
        "transcript": "Lời kể",
        "also_in": "Truyện này còn có bản: ",
        "based_on": "Dựa theo ",
        "by": " của ",
        "min": "{n} phút",
        "illustration": "Hình minh họa: {title}",
        "share": "Chia sẻ",
        "link_copied": "Đã sao chép liên kết",
        "copy_failed": "Không sao chép được",
        "footer": "Truyện này được làm bằng DropCast và kể bằng giọng đọc nhân tạo. Mỗi truyện đều ghi nguồn văn bản gốc.",
    },
}
# The Share button (podcast #43, #45). A click opens the panel of X and LinkedIn drafts that
# docs/share.js builds from the episode's own entry (``window.PodcastShare``, the same file
# the list pages load), under the page's buttons. Its "More…" button does what Share did in
# #43, the same as site.js's shareEpisode(): the device's share sheet where navigator.share
# exists (title and the page's URL, nothing else; a cancelled sheet does nothing), else the URL
# copied (Clipboard API, else a hidden text area and execCommand) with a short confirmation.
# Without share.js the button does that itself. GA4's episode_share goes through the page's
# own gtag, guarded, only on an action, with its method (x, linkedin, copy, share_sheet). The
# button stays hidden until this script runs, so a page without JavaScript shows no dead
# button. ``SHARE`` is the JSON from ``share_data()``.
SHARE_SCRIPT = """\
(() => {
  const S = SHARE;
  const btn = document.getElementById("share");
  const label = btn.querySelector("span");
  const track = (method) => {
    try { if (typeof window.gtag === "function") window.gtag("event", "episode_share", Object.assign({}, S.params, { method })); } catch (e) { /* never breaks the page */ }
  };
  const copy = async (text) => {
    try {
      if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
    } catch (e) { /* fall back */ }
    const back = document.activeElement || btn;
    const ta = document.createElement("textarea");
    ta.value = text; ta.readOnly = true; ta.tabIndex = -1; ta.setAttribute("aria-hidden", "true");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;";
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    if (back && typeof back.focus === "function") back.focus({ preventScroll: true });
    return ok;
  };
  const more = async (b, l, rest) => {
    if (b._busy) return;
    b._busy = true;
    try {
      const data = { title: S.title, url: S.url };
      if (typeof navigator.share === "function" && (typeof navigator.canShare !== "function" || navigator.canShare(data))) {
        try { await navigator.share(data); track("share_sheet"); return; }
        catch (err) { if (err && err.name === "AbortError") return; }
      }
      const ok = await copy(S.url);
      l.textContent = ok ? S.copied : S.failed;
      b.classList.toggle("is-done", ok);
      if (ok) track("copy");
      clearTimeout(b._t);
      b._t = setTimeout(() => { l.textContent = rest; b.classList.remove("is-done"); }, 1800);
    } finally {
      b._busy = false;
    }
  };
  btn.addEventListener("click", () => {
    const P = window.PodcastShare;
    if (P && typeof P.toggle === "function") P.toggle({ ep: S.ep, url: S.url, lang: S.lang, button: btn, after: btn.parentNode, track, copy, more });
    else return more(btn, label, S.label);
  });
  btn.hidden = false;
})();"""
# The version of docs/share.js the episode pages load (``share.js?v=``): the list pages'
# site.js/site.css/share.js version, bumped with them (a test keeps them in step).
ASSET_VERSION = "202611130200"
# The entry's fields the drafts are written from (docs/share.js drafts()).
DRAFT_FIELDS = ("id", "title", "summary", "description", "format", "show", "language", "category")
DRAFT_SOURCE_FIELDS = ("title", "author", "url", "kind")
SITEMAP = "sitemap.xml"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def show_of(ep: dict[str, Any]) -> str:
    """The same routing as publish.py and site.js: a story format is always a story."""
    if ep.get("format") in STORY_FORMATS or ep.get("show") == STORY_SHOW:
        return STORY_SHOW
    return BUILD_SHOW


def _lang(ep: dict[str, Any]) -> str:
    lang = str(ep.get("language") or "en").strip().lower().split("-")[0].split("_")[0]
    return lang if re.fullmatch(r"[a-z]{2,3}", lang) else "en"


def story_lang(ep: dict[str, Any]) -> str:
    """The language page that lists a story: its own language when it has one, else English."""
    lang = _lang(ep)
    return lang if lang in STORY_LANGS else "en"


def show_page(ep: dict[str, Any]) -> str:
    """The page (relative to the site root) that lists the episode: ``""`` for Build Wiz AI
    Show, ``stories/<lang>/`` for a story."""
    return SHOWS[show_of(ep)]["page"].format(lang=story_lang(ep))


def ui_of(ep: dict[str, Any]) -> dict[str, str]:
    """The words of the episode's page (``UI``): its story language's for a story, English
    for Build Wiz AI Show."""
    return UI[story_lang(ep) if show_of(ep) == STORY_SHOW else "en"]


def _hook(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().split("\n\n", 1)[0]).strip()


def _web_url(value: Any) -> str | None:
    url = value.strip() if isinstance(value, str) else ""
    return url if re.match(r"https?://[^/\s]", url, re.IGNORECASE) else None


def page_path(ep_id: str) -> str:
    return f"episodes/{ep_id}/"


def page_url(ep_id: str) -> str:
    return BASE_URL + page_path(ep_id)


def cover_url(ep: dict[str, Any], site: Path = SITE) -> str:
    show = show_of(ep)
    cover = SHOWS[show]["cover"].format(lang=_lang(ep))
    if not (site / cover).is_file():
        cover = SHOWS[show]["cover"].format(lang="en")
    return BASE_URL + cover


_ART_PATH = re.compile(r"art/[A-Za-z0-9][A-Za-z0-9._-]*/(?:wide|square|thumb)\.jpg")


def art_of(ep: dict[str, Any], site: Path = SITE) -> dict[str, str] | None:
    """The story illustration of an episode (``image`` in episodes.json) when its wide and
    square files are on the site: ``wide``/``square`` absolute URLs, ``wide_rel`` (from the
    episode page) and ``alt``; else None."""
    image = ep.get("image")
    if not isinstance(image, dict):
        return None
    paths = {k: image.get(k) for k in ("wide", "square")}
    for path in paths.values():
        if not isinstance(path, str) or not _ART_PATH.fullmatch(path) or ".." in path:
            return None
        if not (site / path).is_file():
            return None
    alt = image.get("alt") if isinstance(image.get("alt"), str) and image["alt"].strip() else None
    title = str(ep.get("title") or ep.get("id") or "")
    return {
        "wide": BASE_URL + str(paths["wide"]),
        "square": BASE_URL + str(paths["square"]),
        "wide_rel": "../../" + str(paths["wide"]),
        "alt": re.sub(r"\s+", " ", alt).strip() if alt else ui_of(ep)["illustration"].format(title=title),
    }


def _iso_duration(seconds: Any) -> str | None:
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    h, rest = divmod(max(0, s), 3600)
    m, s = divmod(rest, 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m or h else "") + f"{s}S"


def _minutes(seconds: Any, unit: str = UI["en"]["min"]) -> str:
    try:
        return unit.format(n=max(1, round(float(seconds) / 60)))
    except (TypeError, ValueError):
        return ""


def _json_ld(data: dict[str, Any], indent: int | None = 1) -> str:
    # "<" escaped so a title can never close the script element.
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def share_data(ep: dict[str, Any]) -> dict[str, Any]:
    """What the episode page's Share button needs (podcast #43, #45): the page's own URL, the
    title, the button's words and the page's language (the panel's words), the GA4 parameters
    every site.js event carries (``epParams()``) and the entry's fields the drafts are written
    from (``ep``)."""
    ui = ui_of(ep)
    title = str(ep.get("title") or ep.get("id"))
    params: dict[str, Any] = {
        "episode_id": str(ep["id"]),
        "episode_title": title[:100],
        "show": show_of(ep),
        "episode_language": _lang(ep),
    }
    group = ep.get("story_group").strip() if isinstance(ep.get("story_group"), str) else ""
    if group:
        params["story_group"] = group
    if isinstance(ep.get("category"), str) and ep["category"]:
        params["category"] = ep["category"]
    draft: dict[str, Any] = {k: ep[k] for k in DRAFT_FIELDS if ep.get(k) is not None}
    if isinstance(ep.get("source"), dict):
        src = {k: ep["source"][k] for k in DRAFT_SOURCE_FIELDS if ep["source"].get(k) is not None}
        if "url" in src and not _web_url(src["url"]):
            del src["url"]  # only a web address (it tells an X post apart)
        draft["source"] = src
    return {
        "url": page_url(str(ep["id"])),
        "title": title,
        "label": ui["share"],
        "copied": ui["link_copied"],
        "failed": ui["copy_failed"],
        "lang": story_lang(ep) if show_of(ep) == STORY_SHOW else "en",
        "params": params,
        "ep": draft,
    }


def versions_of(ep: dict[str, Any], episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The other language versions of a story (same ``story_group``), one per language."""
    group = ep.get("story_group")
    if not isinstance(group, str) or not group.strip():
        return []
    seen = {_lang(ep)}
    out = []
    for other in episodes:
        if other is ep or other.get("story_group") != group or _lang(other) in seen:
            continue
        if not _SAFE_ID.fullmatch(str(other.get("id") or "")):
            continue
        seen.add(_lang(other))
        out.append(other)
    return sorted(out, key=lambda o: list(LANG_NAMES).index(_lang(o)) if _lang(o) in LANG_NAMES else 9)


def render_page(ep: dict[str, Any], episodes: list[dict[str, Any]], site: Path = SITE) -> str:
    """The static page of one episode (``docs/episodes/<id>/index.html``)."""
    ep_id = str(ep["id"])
    show = show_of(ep)
    lang = _lang(ep)
    ui = ui_of(ep)
    title = str(ep.get("title") or ep_id)
    description = str(ep.get("description") or "").strip()
    hook = _hook(description) or " ".join(s for s in ep.get("summary") or [] if isinstance(s, str))
    url = page_url(ep_id)
    show_url = BASE_URL + show_page(ep)
    back = f"../../{show_page(ep)}#{ep_id}"
    # The audio is an absolute https URL (the media repo's Pages site, podcast #33, or a
    # release asset, #30) or, before #30, the episode.mp3 next to this page; the relative
    # case renders as before.
    given = str(ep.get("audio") or f"episodes/{ep_id}/episode.mp3")
    remote = given.startswith("https://")
    audio = given if remote else BASE_URL + given
    player_src = audio if remote else "episode.mp3"
    cover = cover_url(ep, site)
    art = art_of(ep, site)
    share = art["wide"] if art else cover  # og:image / twitter:image
    file_name = str(ep.get("file_name") or f"{ep_id}.mp3")
    published = str(ep.get("published") or "")
    day = published[:10]
    src: dict[str, Any] = ep["source"] if isinstance(ep.get("source"), dict) else {}
    src_url = _web_url(src.get("url"))
    others = versions_of(ep, episodes)
    duration = _iso_duration(ep.get("duration_s"))
    minutes = _minutes(ep.get("duration_s"), ui["min"])

    ld: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": title,
        "description": description or hook,
        "url": url,
        "inLanguage": lang,
        "image": art["square"] if art else cover,
        "associatedMedia": {"@type": "MediaObject", "contentUrl": audio, "encodingFormat": "audio/mpeg"},
        "partOfSeries": {"@type": "PodcastSeries", "name": show, "url": show_url},
    }
    if published:
        ld["datePublished"] = published
    if duration:
        ld["timeRequired"] = duration
        ld["associatedMedia"]["duration"] = duration
    if src_url:
        ld["isBasedOn"] = src_url

    e = lambda v: escape(str(v), quote=True)  # noqa: E731
    head = [
        "<!doctype html>",
        f'<html lang="{e(lang)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(title)} | {e(show)}</title>",
        f'<meta name="description" content="{e(hook)}">',
        f'<link rel="canonical" href="{e(url)}">',
        f'<link rel="alternate" hreflang="{e(lang)}" href="{e(url)}">',
        *(f'<link rel="alternate" hreflang="{e(_lang(o))}" href="{e(page_url(str(o["id"])))}">' for o in others),
        '<meta name="theme-color" content="#000000">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{e(show)}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(hook)}">',
        f'<meta property="og:url" content="{e(url)}">',
        f'<meta property="og:image" content="{e(share)}">',
        *(
            [
                '<meta property="og:image:width" content="1920">',
                '<meta property="og:image:height" content="1080">',
                f'<meta property="og:image:alt" content="{e(art["alt"])}">',
            ]
            if art
            else []
        ),
        f'<meta property="og:locale" content="{e(LOCALES.get(lang, lang))}">',
        f'<meta property="og:audio" content="{e(audio)}">',
        '<meta property="og:audio:type" content="audio/mpeg">',
        f'<meta name="twitter:card" content="{"summary_large_image" if art else "summary"}">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(hook)}">',
        f'<meta name="twitter:image" content="{e(share)}">',
        *([f'<meta name="twitter:image:alt" content="{e(art["alt"])}">'] if art else []),
        f'<script type="application/ld+json">\n{_json_ld(ld)}\n</script>',
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>',
        "<script>",
        "  window.dataLayer = window.dataLayer || [];",
        "  function gtag(){dataLayer.push(arguments);}",
        "  gtag('js', new Date());",
        f"  gtag('config', '{GA_ID}');",
        "</script>",
        "<style>",
        f"  :root {{ --accent: {SHOWS[show]['accent']}; color-scheme: dark; }}",
        "  body { margin: 0; background: #000; color: #fff; font: 400 16px/1.6 \"Helvetica Neue\", Arial, sans-serif; }",
        "  main { max-width: 760px; margin: 0 auto; padding: 24px clamp(16px, 4vw, 40px) 48px; }",
        "  a { color: #fff; text-decoration-color: var(--accent); text-underline-offset: 3px; }",
        "  a:hover { color: var(--accent); }",
        "  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }",
        "  .show { font-weight: 700; text-decoration: none; }",
        "  h1 { font-size: clamp(26px, 5vw, 36px); line-height: 1.15; letter-spacing: -0.02em; margin: 18px 0 6px; overflow-wrap: anywhere; }",
        "  .meta { color: rgba(255,255,255,.72); font-size: 14px; margin: 0 0 16px; }",
        "  .meta .dur { color: var(--accent); font-weight: 600; }",
        "  audio { width: 100%; margin: 4px 0 16px; }",
        "  .desc { white-space: pre-line; color: rgba(255,255,255,.86); margin: 0 0 18px; overflow-wrap: anywhere; }",
        "  .actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; }",
        "  .btn { display: inline-flex; align-items: center; min-height: 36px; padding: 6px 12px; border: 1px solid rgba(255,255,255,.24); border-radius: 8px; font-size: 14px; font-weight: 600; text-decoration: none; }",
        "  .btn:hover { border-color: #fff; color: #fff; }",
        "  button.btn { background: transparent; color: #fff; font-family: inherit; line-height: inherit; cursor: pointer; }",
        "  .btn.is-done { border-color: var(--accent); color: var(--accent); }",
        "  .btn[hidden] { display: none; }",
        "  .langs, .credit { font-size: 14px; color: rgba(255,255,255,.72); margin: 0 0 8px; overflow-wrap: anywhere; }",
        "  footer { font-size: 13px; color: rgba(255,255,255,.62); border-top: 1px solid rgba(255,255,255,.12); margin-top: 28px; padding-top: 14px; }",
        *(
            ["  .hero { display: block; width: 100%; max-width: 100%; height: auto; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 12px; margin: 16px 0 0; background: #111; }"]
            if art
            else []
        ),
        "</style>",
        "</head>",
    ]
    body = [
        "<body>",
        "<main>",
        f'  <a class="show" href="../../{show_page(ep)}">{e(show)}</a>',
        *(
            [f'  <img class="hero" src="{e(art["wide_rel"])}" alt="{e(art["alt"])}" width="1920" height="1080" decoding="async" fetchpriority="high">']
            if art
            else []
        ),
        f'  <h1 id="title">{e(title)}</h1>',
        '  <p class="meta">'
        + " · ".join(
            x
            for x in (
                f'<span class="dur">{e(minutes)}</span>' if minutes else "",
                f'<time datetime="{e(published)}">{e(day)}</time>' if day else "",
                e(LANG_NAMES.get(lang, lang.upper())),
            )
            if x
        )
        + "</p>",
        f'  <audio controls preload="none" src="{e(player_src)}" aria-labelledby="title"></audio>',
        f'  <p class="desc" id="description">{e(description or hook)}</p>',
        '  <p class="actions">',
        f'    <a class="btn" href="{e(back)}">{e(ui["listen"].format(show=show))}</a>',
        f'    <a class="btn" href="{e(player_src)}" download="{e(file_name)}">{e(ui["download"])}</a>',
    ]
    if ep.get("transcript"):
        body.append(f'    <a class="btn" href="transcript.vtt">{e(ui["transcript"])}</a>')
    body.append(f'    <button class="btn" type="button" id="share" hidden><span aria-live="polite">{e(ui["share"])}</span></button>')
    body.append("  </p>")
    if others:
        links = ", ".join(
            f'<a href="../{e(o["id"])}/" hreflang="{e(_lang(o))}" lang="{e(_lang(o))}">{e(LANG_NAMES.get(_lang(o), _lang(o).upper()))}</a>'
            for o in others
        )
        body.append(f'  <p class="langs">{e(ui["also_in"])}{links}</p>')
    if src_url:
        author = f"{e(ui['by'])}{e(src.get('author'))}" if src.get("author") else ""
        body.append(
            f'  <p class="credit">{e(ui["based_on"])}<a href="{e(src_url)}" rel="noopener">{e(src.get("title") or src_url)}</a>{author}</p>'
        )
    body += [
        f"  <footer>{e(ui['footer'])}</footer>",
        "</main>",
        f'<script src="../../share.js?v={ASSET_VERSION}"></script>',
        "<script>",
        SHARE_SCRIPT.replace("SHARE;", _json_ld(share_data(ep), indent=None) + ";", 1),
        "</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(head + body)


def render_sitemap(episodes: list[dict[str, Any]]) -> str:
    """Build Wiz AI Show's page, the stories' chooser, the three story language pages, then
    every episode page. A list page's ``lastmod`` is its newest episode's day (the chooser's:
    the newest story's); a page with no episode has none."""
    latest: dict[str, str] = {}
    rows = []
    for ep in episodes:
        day = str(ep.get("published") or "")[:10]
        for page in {show_page(ep), STORY_CHOOSER if show_of(ep) == STORY_SHOW else show_page(ep)}:
            if day > latest.get(page, ""):
                latest[page] = day
        rows.append((page_url(str(ep["id"])), day))
    lists = [SHOWS[BUILD_SHOW]["page"], STORY_CHOOSER] + [SHOWS[STORY_SHOW]["page"].format(lang=lang) for lang in STORY_LANGS]
    urls = [(BASE_URL + page, latest.get(page, "")) for page in lists] + rows
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, day in urls:
        lastmod = f"<lastmod>{escape(day)}</lastmod>" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else ""
        lines.append(f"  <url><loc>{escape(loc)}</loc>{lastmod}</url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)
    return True


def site_episodes(site: Path = SITE) -> list[dict[str, Any]]:
    try:
        data = json.loads((site / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    eps = data.get("episodes") if isinstance(data, dict) else None
    return [e for e in eps or [] if isinstance(e, dict) and _SAFE_ID.fullmatch(str(e.get("id") or ""))]


def write_pages(site: Path = SITE) -> list[Path]:
    """Every episode page and the sitemap; returns the files that changed."""
    episodes = site_episodes(site)
    changed = []
    for ep in episodes:
        path = site / page_path(str(ep["id"])) / "index.html"
        if _write(path, render_page(ep, episodes, site)):
            changed.append(path)
    if _write(site / SITEMAP, render_sitemap(episodes)):
        changed.append(site / SITEMAP)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=["build"])
    parser.parse_args(argv)
    changed = write_pages(SITE)
    print(json.dumps({"changed": [str(p.relative_to(REPO)) for p in changed]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
