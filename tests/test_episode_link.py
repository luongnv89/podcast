"""The opened card's "Episode page" link (podcast #55).

Static checks of docs/site.js and the README, and a node run (skipped without node) of the
card's link code with a stubbed DOM and gtag: its href, label and GA4 event.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LABELS = {"en": "Episode page", "fr": "Page de l’épisode", "vi": "Trang tập"}
LIST_PAGES = {
    "build": (DOCS / "index.html", "https://example.test/podcast/"),
    "en": (DOCS / "stories" / "en" / "index.html", "https://example.test/podcast/stories/en/"),
    "fr": (DOCS / "stories" / "fr" / "index.html", "https://example.test/podcast/stories/fr/"),
    "vi": (DOCS / "stories" / "vi" / "index.html", "https://example.test/podcast/stories/vi/"),
}


def site_js() -> str:
    return (DOCS / "site.js").read_text(encoding="utf-8")


def between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i: text.index(end, i)]


def text_block(lang: str) -> str:
    js = site_js()
    nxt = {"en": "    fr: {", "fr": "    vi: {", "vi": "  };"}[lang]
    return between(js, f"    {lang}: {{", nxt)


def link_line() -> str:
    lines = [l for l in site_js().splitlines() if "T.episodePage" in l]
    assert len(lines) == 1, lines
    return lines[0].strip()


def page_data(html: str) -> str:
    m = re.search(r'data: "([^"]+)"', html)
    return m.group(1) if m else "episodes.json"


class WordsTest(unittest.TestCase):
    def test_label_in_each_language(self) -> None:
        for lang, label in LABELS.items():
            with self.subTest(lang=lang):
                self.assertIn(f'episodePage: "{label}",', text_block(lang))


class CardLinkTest(unittest.TestCase):
    def test_one_link_after_share_before_copy_buttons(self) -> None:
        js = site_js()
        actions = between(js, '    const actions = el("div", { class: "actions" });', "    const detail = el(")
        link = link_line()
        self.assertIn(link, actions)
        self.assertLess(actions.index("actions.append(shareBtn);"), actions.index(link))
        self.assertLess(actions.index(link), actions.index("actions.append(titleBtn);"))

    def test_plain_same_tab_link_with_button_look(self) -> None:
        link = link_line()
        self.assertIn('el("a", { class: "btn", href: pageOf(ep)', link)
        self.assertNotIn("target", link)
        self.assertNotIn("download", link)
        self.assertIn('"episode_page_open", ep)', link)

    def test_title_click_still_expands(self) -> None:
        js = site_js()
        self.assertIn('const toggleBtn = el("a", { class: "ep-toggle", href: pageOf(ep)', js)
        self.assertIn("expand(ep, toggleBtn.getAttribute(\"aria-expanded\") !== \"true\");", js)

    def test_readme_documents_event_and_link(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("| `episode_page_open` |", readme)
        self.assertIn("**Episode page** link (#55)", readme)

    def test_every_page_loads_the_bumped_assets(self) -> None:
        for page in ("index.html", "stories/index.html", "stories/en/index.html", "stories/fr/index.html", "stories/vi/index.html"):
            with self.subTest(page=page):
                html = (DOCS / page).read_text(encoding="utf-8")
                self.assertIn("site.js?v=202611191200", html)
                self.assertIn("site.css?v=202611191200", html)


RUN = r"""
const PAGE_URL = __PAGE_URL__, DATA = __DATA__, T = __T__;
const events = [];
const window = { gtag: (kind, name, params) => events.push([kind, name, params]) };
const document = { createElementNS: () => ({ setAttribute() {}, append() {} }) };
const el = (tag, props = {}, kids = []) => {
  const n = { tag, attrs: {}, kids: [], on: {}, addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); } };
  for (const [k, v] of Object.entries(props)) n.attrs[k] = v;
  for (const k of [].concat(kids)) if (k) n.kids.push(k);
  return n;
};
const showOf = (e) => e.show || "Build Wiz AI Show";
const langOf = (e) => String(e.language || "en").split("-")[0];
const DATA_URL = new URL(DATA, PAGE_URL);
const actions = { kids: [], append(n) { this.kids.push(n); } };
""" + "\n"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BehaviourTest(unittest.TestCase):
    """The real site.js code for the link, track() and epParams(), on each list page."""

    def run_link(self, page: str, ep: dict, label: str) -> dict:
        js = site_js()
        code = (between(js, "  const svg = (paths, cls) => {", "  const clock = ")
                + between(js, "  const pageOf = ", "  // A story's illustration")
                + between(js, "  function track(name, params) {", "  // 25 / 50 / 75 / 100 %")
                + link_line() + "\n")
        html, url = LIST_PAGES[page]
        script = (RUN.replace("__PAGE_URL__", json.dumps(url)).replace("__DATA__", json.dumps(page_data(html.read_text(encoding="utf-8"))))
                  .replace("__T__", json.dumps({"episodePage": label}))
                  + f"const ep = {json.dumps(ep)};\n" + code + r"""
const a = actions.kids[0];
a.on.click.forEach((f) => f({ button: 0 }));
a.on.auxclick.forEach((f) => f({ button: 2 }));   // a right click sends nothing
a.on.auxclick.forEach((f) => f({ button: 1 }));   // a middle click does
console.log(JSON.stringify({ n: actions.kids.length, tag: a.tag, attrs: a.attrs, text: a.kids.filter((k) => typeof k === "string"), events }));
""")
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)

    def test_href_label_and_event_on_each_list_page(self) -> None:
        cases = {
            "build": ({"id": "2026-11-03_the-road-to-self-improving-software", "title": "Road", "category": "ai"}, "en"),
            "en": ({"id": "2026-11-10_three-little-pigs", "title": "Pigs", "format": "bedtime-story", "show": "Once Upon a Time Show", "language": "en", "story_group": "pigs"}, "en"),
            "fr": ({"id": "2026-11-10_three-little-pigs-fr", "title": "Cochons", "show": "Once Upon a Time Show", "language": "fr-FR"}, "fr"),
            "vi": ({"id": "2026-11-10_three-little-pigs-vi", "title": "Heo", "show": "Once Upon a Time Show", "language": "vi"}, "vi"),
        }
        for page, (ep, lang) in cases.items():
            with self.subTest(page=page):
                got = self.run_link(page, ep, LABELS[lang])
                self.assertEqual((got["n"], got["tag"]), (1, "a"))
                self.assertEqual(got["attrs"]["href"], f"https://example.test/podcast/episodes/{ep['id']}/")
                self.assertEqual(got["attrs"]["class"], "btn")
                self.assertEqual(got["text"], [LABELS[lang]])
                self.assertEqual([(k, n) for k, n, _ in got["events"]], [("event", "episode_page_open")] * 2)
                params = got["events"][0][2]
                self.assertEqual(params["episode_id"], ep["id"])
                self.assertEqual(params["show"], ep.get("show", "Build Wiz AI Show"))
                self.assertEqual(params["episode_language"], lang)

    def test_id_is_encoded_in_href(self) -> None:
        got = self.run_link("build", {"id": "a b/c", "title": "x"}, "Episode page")
        self.assertEqual(got["attrs"]["href"], "https://example.test/podcast/episodes/a%20b%2Fc/")

    def test_throwing_gtag_does_not_break(self) -> None:
        js = site_js()
        code = between(js, "  function track(name, params) {", "  // 25 / 50 / 75 / 100 %")
        script = "const window = { gtag() { throw new Error('x'); } };\n" + code + "track('episode_page_open', {}); console.log('true');"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(out.stdout.strip(), "true")


if __name__ == "__main__":
    unittest.main()
