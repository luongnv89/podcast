"""Once Upon a Time Show: one page per language, the chooser and the podcast switcher (podcast #35).

Standard library only, no network: ``python3 -m unittest discover -s tests``. The checks that
run site.js's own code need ``node`` and are skipped without it; the rest read the pages.
The behaviour in a browser (switcher usable at 1280 and 360 px, Play, no JS errors) is
checked with headless Chromium, see the PR.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BASE = "https://luongnv.com/podcast/"
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

LANGS = {"en": "English", "fr": "Français", "vi": "Tiếng Việt"}
# Every page and its URL; the current switcher item (None: the chooser is not one of them).
PAGES = {
    "build": (DOCS / "index.html", BASE, 0),
    "chooser": (DOCS / "stories" / "index.html", BASE + "stories/", None),
    "en": (DOCS / "stories" / "en" / "index.html", BASE + "stories/en/", 1),
    "fr": (DOCS / "stories" / "fr" / "index.html", BASE + "stories/fr/", 2),
    "vi": (DOCS / "stories" / "vi" / "index.html", BASE + "stories/vi/", 3),
}
SWITCHER = [BASE, BASE + "stories/en/", BASE + "stories/fr/", BASE + "stories/vi/"]
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
COVER = (ROOT / "assets" / "cover" / "stories-cover.html").read_text(encoding="utf-8")
STORY_MARK = re.search(r'<svg viewBox="0 0 64 64" aria-hidden="true">.*?</svg>', COVER).group(0)
BUILD_MARK = re.search(r'<a class="brand" href="\./">\s*(<svg.*?</svg>)', (DOCS / "index.html").read_text(encoding="utf-8"), re.S).group(1)


class Page(HTMLParser):
    """The switcher's links, every anchor, link and meta tag, the visible text and the text
    of the UI attributes (aria-label, placeholder, title) outside the switcher."""

    def __init__(self) -> None:
        super().__init__()
        self.html_lang = ""
        self.switch: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self.text: list[str] = []
        self.ld: list[str] = []
        self._depth = 0          # inside nav.shows
        self._skip = 0           # inside script/style
        self._ld = False

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang", "")
        if tag == "nav" and a.get("class") == "shows":
            self._depth = 1
        elif self._depth and tag == "nav":
            self._depth += 1
        if tag in ("script", "style"):
            self._skip += 1
            self._ld = a.get("type") == "application/ld+json"
            if self._ld:
                self.ld.append("")
        if tag == "a":
            (self.switch if self._depth and "show-item" in a.get("class", "") else self.anchors).append(a)
        if tag == "link":
            self.links.append(a)
        if tag == "meta" and (a.get("name") or a.get("property")):
            self.meta[a.get("name") or a.get("property")] = a.get("content", "")
        if not self._depth:
            self.text += [a[k] for k in ("aria-label", "placeholder", "title") if a.get(k)]

    def handle_endtag(self, tag):
        if tag == "nav" and self._depth:
            self._depth -= 1
        if tag in ("script", "style"):
            self._skip -= 1
            self._ld = False

    def handle_data(self, data):
        if self._ld:
            self.ld[-1] += data
        elif not self._skip and not self._depth and data.strip():
            self.text.append(data.strip())


def parse(path: Path) -> tuple[str, Page]:
    html = path.read_text(encoding="utf-8")
    page = Page()
    page.feed(html)
    return html, page


class SwitcherTest(unittest.TestCase):
    def test_every_page_has_the_four_shows_with_the_current_one_marked(self) -> None:
        for name, (path, url, current) in PAGES.items():
            with self.subTest(page=name):
                html, page = parse(path)
                self.assertEqual(html.count('<nav class="shows"'), 1)
                self.assertLess(html.index('<nav class="shows"'), html.index('<header class="mast">'))
                self.assertEqual([urljoin(url, a["href"]) for a in page.switch], SWITCHER)
                marked = [i for i, a in enumerate(page.switch) if a.get("aria-current") == "page"]
                self.assertEqual(marked, [] if current is None else [current])
                self.assertEqual([a.get("hreflang") for a in page.switch[1:]], list(LANGS))

    def test_one_icon_per_show_and_a_language_badge_on_the_story_icon(self) -> None:
        for name, (path, _, _) in PAGES.items():
            with self.subTest(page=name):
                html, _ = parse(path)
                nav = re.search(r'<nav class="shows".*?</nav>', html, re.S).group(0)
                items = re.findall(r'<a class="show-item[^"]*".*?</a>', nav, re.S)
                self.assertEqual(len(items), 4)
                self.assertIn(BUILD_MARK, items[0])
                self.assertNotIn("badge", items[0])
                for item, lang in zip(items[1:], LANGS):
                    self.assertIn(STORY_MARK, item)
                    self.assertIn(f'<span class="badge">{lang.upper()}</span>', item)
                    self.assertIn(f'<span lang="{lang}">{LANGS[lang]}</span>', item)
                    self.assertIn('<span class="sr-only">Once Upon a Time Show, </span>', item)
                self.assertNotRegex(nav, r"flag|🇬|🇫|🇻|\.png")

    def test_the_badge_is_legible(self) -> None:
        css = (DOCS / "site.css").read_text(encoding="utf-8")
        badge = re.search(r"\n\.badge \{(.*?)\}", css, re.S).group(1)
        self.assertIn("background: #F2C46D; color: var(--black)", badge)   # about 12:1
        self.assertIn("font: 800 9.5px/1 var(--display)", badge)
        # Four equal columns on a phone: the switcher fits 360 px without scrolling.
        self.assertIn(".shows-inner { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));", css)


class PagesTest(unittest.TestCase):
    def test_every_page_shares_the_versioned_script_and_stylesheet(self) -> None:
        versions = set()
        for name, (path, _, _) in PAGES.items():
            with self.subTest(page=name):
                html = path.read_text(encoding="utf-8")
                js = re.findall(r'<script src="((?:\.\./)*)site\.js\?v=(\w+)"></script>', html)
                css = re.findall(r'<link rel="stylesheet" href="((?:\.\./)*)site\.css\?v=(\w+)">', html)
                self.assertEqual(len(js), 1)
                self.assertEqual(js, css)
                depth = {"build": "", "chooser": "../"}.get(name, "../../")
                self.assertEqual(js[0][0], depth)
                versions.add(js[0][1])
                # Google Analytics once, as before (no new tracker).
                self.assertEqual(html.count("googletagmanager.com/gtag/js?id=G-FZV5YX8YPT"), 1)
        self.assertEqual(len(versions), 1)

    def test_language_pages(self) -> None:
        for lang in LANGS:
            with self.subTest(lang=lang):
                html, page = parse(PAGES[lang][0])
                url = PAGES[lang][1]
                self.assertEqual(page.html_lang, lang)
                self.assertIn(f'    lang: "{lang}",\n', html)
                self.assertIn('    show: "Once Upon a Time Show",\n', html)
                self.assertIn('    data: "../../episodes.json",\n', html)
                self.assertIn('pages: { "Build Wiz AI Show": "../../", "Once Upon a Time Show": "../{lang}/" }', html)
                self.assertIn({"rel": "canonical", "href": url}, page.links)
                for other in LANGS:
                    self.assertIn({"rel": "alternate", "hreflang": other, "href": BASE + f"stories/{other}/"}, page.links)
                self.assertIn({"rel": "alternate", "hreflang": "x-default", "href": BASE + "stories/"}, page.links)
                feeds = [link["href"] for link in page.links if link.get("type") == "application/rss+xml"]
                self.assertEqual(feeds, [f"../feed-{lang}.xml"])
                self.assertEqual(page.meta["og:url"], url)
                self.assertEqual(page.meta["og:image"], BASE + f"stories/cover-{lang}.jpg")
                self.assertTrue((DOCS / "stories" / f"cover-{lang}.jpg").is_file())
                self.assertEqual(page.meta["og:locale"], {"en": "en_US", "fr": "fr_FR", "vi": "vi_VN"}[lang])
                self.assertEqual(page.meta["og:description"], page.meta["description"])
                ld = json.loads(page.ld[0])
                self.assertEqual((ld["@type"], ld["inLanguage"], ld["url"]), ("PodcastSeries", lang, url))
                self.assertEqual(ld["webFeed"], BASE + f"stories/feed-{lang}.xml")
                self.assertIn(f'<span class="mark" aria-hidden="true">{STORY_MARK}<span class="badge">{lang.upper()}</span></span>', html)
                self.assertIn("<h1>Once Upon a <span", html)

    def test_listening_links_are_the_pages_language_only(self) -> None:
        # The three lines of the old stories page, split per language.
        chooser = parse(PAGES["chooser"][0])[1]
        by_lang: dict[str, set[str]] = {lang: set() for lang in LANGS}
        for a in chooser.anchors:
            if a.get("target") == "_blank" and a.get("hreflang") in by_lang:
                by_lang[a["hreflang"]].add(a["href"])
        self.assertEqual([len(v) for v in by_lang.values()], [3, 3, 3])
        for lang in LANGS:
            with self.subTest(lang=lang):
                page = parse(PAGES[lang][0])[1]
                out = {a["href"] for a in page.anchors if a.get("target") == "_blank"}
                self.assertEqual(out, by_lang[lang])

    def test_each_page_is_in_its_own_language(self) -> None:
        # The UI text English had on the stories page, and what French or Vietnamese uses
        # instead. Show names, platform names, the "/" key and "DropCast" stay as they are.
        english = re.compile(r"\b(Search|Sort|Newest|Oldest|Loading|Clear|Playback|Nothing playing|Back 15|Forward 30|"
                             r"Seek|stories|min of audio|Latest|Listen on|Watch on|Keyboard|Audio player|Categories|"
                             r"skip|play or pause|Press)\b", re.IGNORECASE)
        for lang in ("fr", "vi"):
            with self.subTest(lang=lang):
                html, page = parse(PAGES[lang][0])
                text = " | ".join(t for t in page.text if t not in ("Once Upon a", "Time", "Show"))
                self.assertNotRegex(text, english)
                tagline = json.loads((ROOT / "scripts" / "description_labels.json").read_text(encoding="utf-8"))
                expected = tagline["shows"]["Once Upon a Time Show"]["taglines"][lang].replace("'", "’")
                self.assertIn(f'<p class="tagline" id="tagline">{expected}</p>', html)
        self.assertIn("À écouter sur", PAGES["fr"][0].read_text(encoding="utf-8"))
        self.assertIn("Nghe trên", PAGES["vi"][0].read_text(encoding="utf-8"))

    def test_chooser(self) -> None:
        html, page = parse(PAGES["chooser"][0])
        choices = re.findall(r'<a class="choice" href="(\w+)/" hreflang="(\w+)" lang="(\w+)">(.*?)</a>', html, re.S)
        self.assertEqual([c[:3] for c in choices], [(lang, lang, lang) for lang in LANGS])
        for (lang, _, _, body), name in zip(choices, LANGS.values()):
            self.assertIn(STORY_MARK, body)
            self.assertIn(f'<span class="badge">{lang.upper()}</span>', body)
            self.assertIn(f"<h2>{name}</h2>", body)
        self.assertIn("    chooser: true,\n", html)
        self.assertIn('pages: { "Build Wiz AI Show": "../", "Once Upon a Time Show": "{lang}/" }', html)
        self.assertIn('    data: "../episodes.json",\n', html)
        self.assertIn({"rel": "canonical", "href": BASE + "stories/"}, page.links)
        # The feeds stay where they are (podcast apps know these URLs).
        feeds = [link["href"] for link in page.links if link.get("type") == "application/rss+xml"]
        self.assertEqual(feeds, [f"feed-{lang}.xml" for lang in LANGS])

    def test_build_wiz_page_only_gains_the_switcher(self) -> None:
        html = PAGES["build"][0].read_text(encoding="utf-8")
        self.assertIn('pages: { "Once Upon a Time Show": "stories/{lang}/" },', html)
        self.assertIn('legacyTabs: { bedtime: "stories/" },', html)
        # The switcher replaces the old "Our story show" line.
        self.assertNotIn("Our story show", html)
        self.assertNotIn('<a href="stories/">', html)
        for lang in LANGS:
            self.assertIn(f'<a class="show-item story" href="stories/{lang}/" hreflang="{lang}">', html)
        self.assertNotIn("lang:", re.search(r"window\.SHOW_PAGE = \{.*?\};", html, re.S).group(0))


class SiteJsStaticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (DOCS / "site.js").read_text(encoding="utf-8")

    def test_the_chooser_returns_before_the_list_and_player(self) -> None:
        chooser = self.js.index("if (PAGE.chooser) {")
        self.assertLess(chooser, self.js.index("addEventListener"))
        self.assertLess(chooser, self.js.index("function render()"))
        self.assertIn("location.replace(to);", self.js[chooser:chooser + 900])

    def test_episodes_are_filtered_by_page(self) -> None:
        self.assertIn("episodes = all.filter(onPage);", self.js)
        self.assertIn("others = all.filter((e) => !onPage(e));", self.js)
        self.assertIn("const page = away && pageFor(away);", self.js)

    def test_language_page_cards_have_no_language_links(self) -> None:
        # podcast #40: a card on a language page links no other language (the podcast
        # switcher moves between the pages); only an in-place switch of a story shown as one
        # row in several languages has buttons, and none of them is a link.
        css = (DOCS / "site.css").read_text(encoding="utf-8")
        self.assertNotIn("versionLinks", self.js)
        self.assertNotIn("hreflang", self.js)
        self.assertNotIn('"aria-current"', self.js)
        card = _block(self.js, "  function card(ep, i, u) {", "  // The story's square thumbnail")
        self.assertRegex(card, r"const langs = grouped\n\s*\? el\(\"div\", \{ class: \"langs\"")
        self.assertRegex(card, r"\}\)\)\n\s*: null;\n")
        self.assertNotIn("_alts", card)
        self.assertNotIn('el("a", { class: "lang"', self.js)
        self.assertNotRegex(css, r"a\.lang|span\.lang|\.lang\[aria-current")
        # language_switch is sent by the in-place switch only, never from a link.
        self.assertEqual(self.js.count('"language_switch"'), 1)
        self.assertIn('track("language_switch"', _block(self.js, "  function selectVersion(", "  // Puts a version on show."))
        # The other versions are still looked up on a language page, for the art only.
        self.assertIn("if (PAGE.lang) linkVersions(episodes, all);", self.js)
        rest = self.js.replace(_block(self.js, "  const artSource = ", "  const artOf = "), "")
        rest = rest.replace(_block(rest, "  // On a language page (podcast #35)", "  // The version shown first"), "")
        self.assertIn("_alts", self.js)
        self.assertNotIn("_alts", rest)   # read by artSource only, set by linkVersions only


def _block(js: str, start: str, end: str) -> str:
    return js[js.index(start):js.index(end)]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SiteJsInNode(unittest.TestCase):
    """Run site.js's routing, filtering and words in node, not just grep for them."""

    js = (DOCS / "site.js").read_text(encoding="utf-8")
    PRELUDE = """
const BUILD_SHOW = "Build Wiz AI Show";
const STORY_SHOW = "Once Upon a Time Show";
const STORY_FORMATS = ["bedtime-story", "storytelling"];
const showOf = (e) => (STORY_FORMATS.includes(e.format) || e.show === STORY_SHOW ? STORY_SHOW : BUILD_SHOW);
"""
    EPS = [
        {"id": "pod", "show": "Build Wiz AI Show", "format": "podcast-2host", "language": "en"},
        {"id": "pod-vi", "show": "Build Wiz AI Show", "format": "podcast-2host", "language": "vi"},
        {"id": "pigs", "show": "Once Upon a Time Show", "format": "bedtime-story", "language": "en",
         "story_group": "g", "published": "2026-11-10T01:00:00Z"},
        {"id": "pigs-fr", "show": "Once Upon a Time Show", "format": "bedtime-story", "language": "fr-FR",
         "story_group": "g", "published": "2026-11-10T02:00:00Z"},
        {"id": "pigs-vi", "show": "Build Wiz AI Show", "format": "bedtime-story", "language": "vi",
         "story_group": "g", "published": "2026-11-10T03:00:00Z"},
        {"id": "pigs-fr-old", "show": "Once Upon a Time Show", "format": "storytelling", "language": "fr",
         "story_group": "g", "published": "2026-11-01T00:00:00Z"},
        {"id": "maerchen", "show": "Once Upon a Time Show", "format": "bedtime-story", "language": "de"},
        {"id": "nolang", "show": "Once Upon a Time Show", "format": "bedtime-story"},
    ]

    ART = ('const DATA_URL = "https://luongnv.com/podcast/episodes.json";\n'
           'const T = { illustration: (t) => `Illustration: ${t}` };\n')

    def run_js(self, page: dict, body: str, routing_only: bool = True, art: bool = False):
        code = _block(self.js, "  // ---------- Which page lists an episode", "  // ---------- end of page routing")
        if not routing_only:
            code += _block(self.js, "  const LANGS = {", "  // The version shown first")
        if art:
            code += self.ART + _block(self.js, "  const ART_PATH", "  // The description's hook")
        script = (self.PRELUDE + f"const PAGE = {json.dumps(page)};\n" + code
                  + f"const EPS = {json.dumps(self.EPS)};\n" + "console.log(JSON.stringify((() => {" + body + "})()));")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_each_language_page_lists_only_its_language(self) -> None:
        listed = {}
        for lang in LANGS:
            page = {"show": "Once Upon a Time Show", "lang": lang, "pages": {}}
            listed[lang] = self.run_js(page, "return EPS.filter(onPage).map((e) => e.id);")
        # fr-FR is French; a story format is a story whatever its "show"; a language without
        # a page (de) and no language at all are on the English page; podcasts never are.
        self.assertEqual(listed, {"en": ["pigs", "maerchen", "nolang"], "fr": ["pigs-fr", "pigs-fr-old"], "vi": ["pigs-vi"]})
        main = self.run_js({"show": "Build Wiz AI Show", "pages": {}}, "return EPS.filter(onPage).map((e) => e.id);")
        self.assertEqual(main, ["pod", "pod-vi"])

    def test_every_episode_has_one_page_and_links_go_straight_there(self) -> None:
        main = {"show": "Build Wiz AI Show", "pages": {"Once Upon a Time Show": "stories/{lang}/"}}
        got = self.run_js(main, "return EPS.map((e) => pageFor(e));")
        self.assertEqual(got, [None, None, "stories/en/", "stories/fr/", "stories/vi/", "stories/fr/", "stories/en/", "stories/en/"])
        fr = {"show": "Once Upon a Time Show", "lang": "fr", "pages": {"Build Wiz AI Show": "../../", "Once Upon a Time Show": "../{lang}/"}}
        got = self.run_js(fr, "return EPS.map((e) => pageFor(e));")
        self.assertEqual(got, ["../../", "../../", "../en/", "../fr/", "../vi/", "../fr/", "../en/", "../en/"])
        # A page never maps its own key from the prototype (a hand-edited show name).
        self.assertIsNone(self.run_js(fr, 'return pageOfShow("constructor", "en");'))

    def test_old_links_on_the_chooser(self) -> None:
        chooser = {"chooser": True, "show": "Once Upon a Time Show",
                   "pages": {"Build Wiz AI Show": "../", "Once Upon a Time Show": "{lang}/"}}
        cases = {
            "fr story": ("#pigs-fr", "", [None, "en-US"], "fr/#pigs-fr"),
            "vi story": ("#pigs-vi", "", [], "vi/#pigs-vi"),
            "query and hash": ("#pigs", "?q=pig&sort=title", ["fr"], "en/?q=pig&sort=title#pigs"),
            "podcast": ("#pod", "", [], "../#pod"),
            "unknown language": ("#maerchen", "", [], "en/#maerchen"),
            "encoded id": ("#pigs%2Dfr", "", [], "fr/#pigs%2Dfr"),
            "search, French visitor": ("", "?q=pig", [None, "fr-CA", "en"], "fr/?q=pig"),
            "search, remembered choice": ("", "?q=pig", ["vi", "fr"], "vi/?q=pig"),
            "search, other browser": ("", "?q=pig", ["de-DE"], "en/?q=pig"),
            "old tab": ("", "?tab=all", [], "en/?tab=all"),
            "unknown id with a search": ("#nope", "?q=x", ["fr"], "fr/?q=x#nope"),
            "plain chooser": ("", "", ["fr"], None),
            "empty query": ("", "?", ["fr"], None),
            "unknown id": ("#nope", "", ["fr"], None),
            "malformed hash": ("#%E0%A4%A", "", ["fr"], None),
            # Tracking tags are not settings: such a link shows the chooser.
            "fbclid only": ("", "?fbclid=x", ["fr"], None),
            "utm only": ("", "?utm_source=n", ["fr"], None),
            "tracking tags only": ("", "?gclid=g&utm_medium=social&ref=x", ["fr"], None),
            "unknown id with tracking": ("#nope", "?utm_source=n", ["fr"], None),
            "search and tracking": ("", "?q=pigs&utm_source=n", ["fr"], "fr/?q=pigs"),
            "tracking around keys": ("", "?fbclid=x&sort=title&utm_source=n&order=asc", [], "en/?sort=title&order=asc"),
            "story with tracking": ("#pigs-fr", "?fbclid=x", [], "fr/#pigs-fr"),
            "encoded key and value": ("", "?%71=big%20pigs", ["vi"], "vi/?%71=big%20pigs"),
            "malformed tag dropped": ("", "?q=pig&%E0%A4%A=1", ["fr"], "fr/?q=pig"),
            "key without a value": ("", "?tab", ["fr"], "fr/?tab"),
        }
        for label, (hash_, search, prefer, want) in cases.items():
            with self.subTest(case=label):
                got = self.run_js(chooser, f"return chooserTarget(EPS, {json.dumps(hash_)}, {json.dumps(search)}, {json.dumps(prefer)});")
                self.assertEqual(got, want)
        # Without a story page to go to, a search stays put (never a redirect loop).
        bare = {"chooser": True, "show": "Once Upon a Time Show", "pages": {}}
        self.assertIsNone(self.run_js(bare, 'return chooserTarget(EPS, "", "?q=x", ["fr"]);'))

    def test_other_versions_are_known_on_a_language_page(self) -> None:
        fr = {"show": "Once Upon a Time Show", "lang": "fr", "pages": {"Build Wiz AI Show": "../../", "Once Upon a Time Show": "../{lang}/"}}
        got = self.run_js(fr, """
const eps = EPS.filter(onPage);
linkVersions(eps, EPS);
return Object.fromEntries(eps.map((e) => [e.id, (e._alts || []).map((o) => [o.id, pageFor(o)])]));
""", routing_only=False)
        # One per other language (the newest), in EN / FR / VI order; never the same language.
        self.assertEqual(got, {"pigs-fr": [["pigs", "../en/"], ["pigs-vi", "../vi/"]],
                               "pigs-fr-old": [["pigs", "../en/"], ["pigs-vi", "../vi/"]]})

    def test_a_version_without_art_shows_the_storys_art(self) -> None:
        # The language page's cards have no language links (#40), but a version without its
        # own illustration still borrows the story's from another language's version (_alts).
        body = """
const own = (k) => ({ wide: `art/${k}/wide.jpg`, square: `art/${k}/square.jpg`, thumb: `art/${k}/thumb.jpg`, alt: `Drawing ${k}` });
const byId = Object.fromEntries(EPS.map((e) => [e.id, e]));
byId["pigs"].image = own("pigs");
byId["pigs-fr-old"].image = own("old");
const eps = EPS.filter(onPage);
const before = eps.map((e) => artOf(e, "thumb"));
linkVersions(eps, EPS);
return { before, after: Object.fromEntries(eps.map((e) => [e.id, [artOf(e, "thumb"), artAlt(e)]])) };
"""
        base = "https://luongnv.com/podcast/art/"
        fr = {"show": "Once Upon a Time Show", "lang": "fr", "pages": {"Build Wiz AI Show": "../../", "Once Upon a Time Show": "../{lang}/"}}
        got = self.run_js(fr, body, routing_only=False, art=True)
        self.assertEqual(got["before"], [None, base + "old/thumb.jpg"])
        self.assertEqual(got["after"], {"pigs-fr": [base + "pigs/thumb.jpg", "Drawing pigs"],
                                        "pigs-fr-old": [base + "old/thumb.jpg", "Drawing old"]})
        vi = dict(fr, lang="vi")
        got = self.run_js(vi, body, routing_only=False, art=True)
        self.assertEqual(got["after"], {"pigs-vi": [base + "pigs/thumb.jpg", "Drawing pigs"]})

    def test_words_exist_in_every_language(self) -> None:
        code = _block(self.js, "  const TEXT = {", "  // ---------- end of words")
        script = ("const PAGE = {};\n" + code + """
const shape = (t) => Object.fromEntries(Object.entries(t).map(([k, v]) => [k, typeof v === "function" ? "fn" + v.length : typeof v]));
const call = (t) => ({ min: t.min(5), left: t.left(t.min(5)), of: t.of(9, "x"), noMatchText: t.noMatchText("q"), order: t.order("A", "b"),
  music: t.music("M"), playEp: t.playEp("T"), speed: t.speed(1.5), illustration: t.illustration("T"), presents: t.presents("S"),
  sorts: t.sorts, finished: t.finished, download: t.download, share: t.share, linkCopied: t.linkCopied });
console.log(JSON.stringify({ shapes: Object.fromEntries(Object.entries(TEXT).map(([k, t]) => [k, shape(t)])),
  calls: Object.fromEntries(Object.entries(TEXT).map(([k, t]) => [k, call(t)])), def: T === TEXT.en }));
""")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = json.loads(out.stdout)
        self.assertTrue(got["def"])   # a page without SHOW_PAGE.lang (Build Wiz AI Show) is in English
        self.assertEqual(got["shapes"]["fr"], got["shapes"]["en"])
        self.assertEqual(got["shapes"]["vi"], got["shapes"]["en"])
        en, fr, vi = (got["calls"][k] for k in ("en", "fr", "vi"))
        # English is word for word what the pages said before.
        self.assertEqual((en["min"], en["left"], en["of"], en["noMatchText"], en["order"], en["music"], en["playEp"], en["speed"]),
                         ("5 min", "5 min left", " of 9 x", "Nothing matches “q”. Try fewer or different words.",
                          "Order: A. Switch to b.", "Music: M", "Play T", "Playback speed 1.5×"))
        self.assertEqual(en["sorts"]["published"], ["Oldest first", "Newest first"])
        self.assertEqual((en["share"], en["linkCopied"]), ("Share", "Link copied"))
        # French: no-break space before the colon, « » quotes; Vietnamese minutes.
        self.assertEqual((fr["music"], fr["min"], fr["left"]), ("Musique : M", "5 min", "Il reste 5 min"))
        self.assertIn("« q »", fr["noMatchText"])
        self.assertEqual((vi["min"], vi["left"], vi["music"], vi["download"]), ("5 phút", "Còn 5 phút", "Nhạc: M", "Tải MP3"))
        for words in (fr, vi):
            self.assertNotEqual(words["sorts"], en["sorts"])
            self.assertNotEqual(words["finished"], en["finished"])


def story(ep_id: str, lang: str | None, day: str) -> dict:
    ep = {"id": ep_id, "title": ep_id, "show": "Once Upon a Time Show", "format": "bedtime-story",
          "published": f"{day}T10:00:00Z", "audio": f"https://luongnv.com/once-upon-a-time-en-media/{ep_id}.mp3"}
    if lang:
        ep["language"] = lang
    return ep


class SitemapAndEpisodePagesTest(unittest.TestCase):
    EPS = [
        {"id": "pod", "title": "Pod", "show": "Build Wiz AI Show", "format": "podcast-2host", "published": "2026-11-09T10:00:00Z"},
        story("tale", "en", "2026-11-03"),
        story("tale-fr", "fr", "2026-11-07"),
        story("tale-de", "de", "2026-11-05"),
    ]

    def test_sitemap_lists_the_chooser_and_the_three_language_pages(self) -> None:
        root = ET.fromstring(pages.render_sitemap(self.EPS))
        rows = [(u.findtext(f"{SM}loc"), u.findtext(f"{SM}lastmod")) for u in root]
        self.assertEqual(rows[:5], [
            (BASE, "2026-11-09"),
            (BASE + "stories/", "2026-11-07"),           # the newest story of any language
            (BASE + "stories/en/", "2026-11-05"),        # the German story is on the English page
            (BASE + "stories/fr/", "2026-11-07"),
            (BASE + "stories/vi/", None),                # no Vietnamese story: no lastmod
        ])
        self.assertEqual(len(rows), 5 + len(self.EPS))

    def test_live_sitemap(self) -> None:
        locs = [u.findtext(f"{SM}loc") for u in ET.parse(DOCS / "sitemap.xml").getroot()]
        self.assertEqual(locs[:5], [BASE, BASE + "stories/", BASE + "stories/en/", BASE + "stories/fr/", BASE + "stories/vi/"])

    def test_episode_pages_link_back_to_their_language_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for ep, page in ((self.EPS[2], "stories/fr/"), (self.EPS[3], "stories/en/"), (self.EPS[0], "")):
                with self.subTest(id=ep["id"]):
                    html = pages.render_page(ep, self.EPS, Path(tmp))
                    self.assertIn(f'<a class="show" href="../../{page}">', html)
                    # The button is in the page's language (podcast #38): "Écouter sur" for French.
                    listen = "Écouter sur" if page == "stories/fr/" else "Listen on"
                    self.assertIn(f'href="../../{page}#{ep["id"]}">{listen} ', html)
                    self.assertIn(f'"url": "{BASE}{page}"', html)

    def test_live_story_pages_link_to_their_language(self) -> None:
        for ep in pages.site_episodes(DOCS):
            if pages.show_of(ep) != pages.STORY_SHOW:
                continue
            with self.subTest(id=ep["id"]):
                html = (DOCS / "episodes" / ep["id"] / "index.html").read_text(encoding="utf-8")
                lang = pages.story_lang(ep)
                self.assertIn(f'href="../../stories/{lang}/#{ep["id"]}"', html)
                self.assertNotIn('"../../stories/#', html)

    def test_the_feeds_still_link_the_chooser(self) -> None:
        # Feeds are untouched: their links land on the chooser, which forwards #<id>.
        for lang in LANGS:
            feed = (DOCS / "stories" / f"feed-{lang}.xml").read_text(encoding="utf-8")
            self.assertIn(f"<link>{BASE}stories/</link>", feed)


if __name__ == "__main__":
    unittest.main()
