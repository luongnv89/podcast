"""Episode pages of French and Vietnamese stories in the story's language (podcast #38).

Standard library only, no network: ``python3 -m unittest discover -s tests``.

A story's episode page (``docs/episodes/<id>/index.html``, ``scripts/pages.py``) uses its
language for every UI word; English story pages and every Build Wiz AI Show page stay byte
for byte what they were. ``fixtures/episode_pages_38/expected/`` holds those pages as the
renderer before #38 wrote them, from ``fixtures/episode_pages_38/episodes.json``. The Share
button (podcast #43, with share.js for its drafts panel since #45) is the only later
addition: it is cut out (``without_share()``) before the comparison, and it must be there
exactly once.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FIXTURE = ROOT / "tests" / "fixtures" / "episode_pages_38"
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

# The English UI words of an episode page, as they appear in its HTML. None may be left on a
# French or Vietnamese story page once its content (title, description, source, alt) is cut.
ENGLISH_UI = (
    ">Listen on ", ">Download MP3<", ">Transcript<", ">Also in: ", ">Based on ", "</a> by ",
    "AI-voiced", "Voices are synthetic", "credits its source", '"Illustration: ',
    ">Share<", '"Share"', '"Link copied"', '"Copy failed"',
)
# The same English words in the page's text with every tag, script and style removed, so a
# label written with other markup is caught too ("Transcript" as a word: not "Transcription").
ENGLISH_WORDS = re.compile(r"Listen on|Download MP3|\bTranscript\b|Also in|Based on|AI-voiced|"
                           r"Voices are synthetic|credits its source|Illustration:")
# The English duration ("7 min", plain space). Vietnamese says "phút"; French writes "min"
# too, but with a no-break space, as site.js does ("7 min").
ENGLISH_MINUTES = re.compile(r'class="dur">\d+ min<')


def load_fixture() -> list[dict]:
    return json.loads((FIXTURE / "episodes.json").read_text(encoding="utf-8"))["episodes"]


def make_site(root: Path) -> Path:
    """The files the renderer looks for: the covers and the fixture story's art."""
    (root / "stories").mkdir()
    for lang in ("en", "fr", "vi"):
        (root / "stories" / f"cover-{lang}.jpg").write_bytes(b"jpg")
    (root / "cover.jpg").write_bytes(b"jpg")
    art = root / "art" / "2026-11-05_tale"
    art.mkdir(parents=True)
    for name in ("wide", "square", "thumb"):
        (art / f"{name}.jpg").write_bytes(b"jpg")
    return root


# What podcast #43 added to every episode page: three style rules, the button, the script
# (and #45 the share.js tag before it).
SHARE_CSS = (
    "  button.btn { background: transparent; color: #fff; font-family: inherit; line-height: inherit; cursor: pointer; }\n"
    "  .btn.is-done { border-color: var(--accent); color: var(--accent); }\n"
    "  .btn[hidden] { display: none; }\n"
)
# Podcast #45 loads share.js (the drafts panel) just before that script.
SHARE_SCRIPT = re.compile(r'<script src="\.\./\.\./share\.js\?v=\d+"></script>\n'
                          r"<script>\n\(\(\) => \{\n  const S = \{.*?\n\}\)\(\);\n</script>\n(?=</body>\n</html>\n$)", re.S)


def without_share(test: unittest.TestCase, html: str, label: str = "Share") -> str:
    """The page without the Share button's style, button and script, each there exactly once."""
    button = f'    <button class="btn" type="button" id="share" hidden><span aria-live="polite">{label}</span></button>\n'
    for part in (SHARE_CSS, button):
        test.assertEqual(html.count(part), 1)
        html = html.replace(part, "")
    html, n = SHARE_SCRIPT.subn("", html)
    test.assertEqual(n, 1)
    return html


def without_content(html: str, ep: dict) -> str:
    """The page with the episode's own text cut out, so only the UI words are left."""
    src = ep.get("source") if isinstance(ep.get("source"), dict) else {}
    image = ep.get("image") if isinstance(ep.get("image"), dict) else {}
    content = [ep.get("description"), ep.get("title"), src.get("title"), src.get("author"), image.get("alt"),
               ep.get("file_name")]
    for text in sorted((str(t) for t in content if t), key=len, reverse=True):
        html = html.replace(escape(text, quote=True), "")
    return html


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.site = make_site(Path(self._tmp.name))
        self.eps = load_fixture()
        self.by_id = {ep["id"]: ep for ep in self.eps}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def render(self, ep_id: str) -> str:
        return pages.render_page(self.by_id[ep_id], self.eps, self.site)


class UnchangedPagesTest(Fixture):
    """English story pages and Build Wiz AI Show pages are byte-identical to before #38."""

    def test_english_and_build_wiz_pages_match_the_pages_before_38(self) -> None:
        expected = sorted((FIXTURE / "expected").glob("*.html"))
        # An English story with every part (art without alt, transcript, author, versions),
        # a plain one, a story in a language without a page, Build Wiz in English and in Vietnamese.
        self.assertEqual([p.stem for p in expected], ["2026-11-05_tale", "2026-11-06_plain", "2026-11-07_marchen",
                                                      "2026-11-08_pod", "2026-11-09_pod-vi"])
        for path in expected:
            with self.subTest(id=path.stem):
                self.assertEqual(without_share(self, self.render(path.stem)).encode("utf-8"), path.read_bytes())

    def test_build_wiz_page_in_another_language_keeps_english_ui(self) -> None:
        html = self.render("2026-11-09_pod-vi")
        self.assertIn('<html lang="vi">', html)  # the episode's language, as before
        self.assertIn(">Listen on Build Wiz AI Show</a>", html)
        self.assertIn(">Download MP3</a>", html)
        self.assertIn('class="dur">20 min<', html)
        self.assertIs(pages.ui_of(self.by_id["2026-11-09_pod-vi"]), pages.UI["en"])

    def test_live_english_story_and_build_wiz_pages_are_in_english(self) -> None:
        eps = pages.site_episodes(DOCS)
        checked = 0
        for ep in eps:
            # Chosen without ui_of(), so a Build Wiz page turned French would fail here.
            if pages.show_of(ep) == pages.STORY_SHOW and pages.story_lang(ep) != "en":
                continue
            with self.subTest(id=ep["id"]):
                html = (DOCS / "episodes" / ep["id"] / "index.html").read_text(encoding="utf-8")
                self.assertIn(f'>Listen on {pages.show_of(ep)}</a>', html)
                self.assertIn("<footer>AI-voiced episode made with DropCast. Voices are synthetic; "
                              "each episode credits its source.</footer>", html)
                checked += 1
        self.assertGreater(checked, 0)


class StoryLanguageTest(Fixture):
    """French and Vietnamese story pages speak their language."""

    def assert_no_english_ui(self, html: str, ep: dict) -> None:
        ui = without_content(html, ep)
        for word in ENGLISH_UI:
            self.assertNotIn(word, ui)
        self.assertIsNone(ENGLISH_MINUTES.search(ui))
        text = re.sub(r"<(script|style)\b.*?</\1>|<[^>]*>", " ", ui, flags=re.S)
        self.assertIsNone(ENGLISH_WORDS.search(text))

    def test_french_story_page(self) -> None:
        html = self.render("2026-11-05_tale-fr")
        self.assertIn('<html lang="fr">', html)
        self.assertIn('<meta property="og:locale" content="fr_FR">', html)
        self.assertIn('#2026-11-05_tale-fr">Écouter sur Once Upon a Time Show</a>', html)
        self.assertIn('download="Once Upon a Time Show - La pantoufle de verre (2026-11-05).mp3">Télécharger le MP3</a>', html)
        self.assertIn('<a class="btn" href="transcript.vtt">Transcription</a>', html)
        self.assertIn('<p class="langs">Également disponible en\u00a0: <a href="../2026-11-05_tale/"', html)
        self.assertIn('<p class="credit">D’après <a href="https://example.org/cendrillon" rel="noopener">Cendrillon</a>'
                      ", de Charles Perrault</p>", html)
        self.assertIn('class="dur">7\u00a0min<', html)
        self.assertIn("<footer>Histoire réalisée avec DropCast", html)
        # The picture has no alt text: the fallback names it in French, in the page and the share tags.
        self.assertIn('alt="Illustration\u00a0: La pantoufle de verre"', html)
        self.assertIn('<meta property="og:image:alt" content="Illustration\u00a0: La pantoufle de verre">', html)
        self.assert_no_english_ui(html, self.by_id["2026-11-05_tale-fr"])

    def test_vietnamese_story_page(self) -> None:
        html = self.render("2026-11-05_tale-vi")
        self.assertIn('<html lang="vi">', html)
        self.assertIn('<meta property="og:locale" content="vi_VN">', html)
        self.assertIn('#2026-11-05_tale-vi">Nghe trên Once Upon a Time Show</a>', html)
        self.assertIn(">Tải MP3</a>", html)
        self.assertIn('<a class="btn" href="transcript.vtt">Lời kể</a>', html)
        self.assertIn('<p class="langs">Truyện này còn có bản: <a href="../2026-11-05_tale/"', html)
        self.assertIn('<p class="credit">Dựa theo <a href="https://example.org/lo-lem" rel="noopener">Cô bé Lọ Lem</a>'
                      " của Charles Perrault</p>", html)
        self.assertIn('class="dur">8 phút<', html)
        self.assertIn("<footer>Truyện này được làm bằng DropCast", html)
        self.assertIn('alt="Hình minh họa: Chiếc giày thủy tinh"', html)
        self.assert_no_english_ui(html, self.by_id["2026-11-05_tale-vi"])

    def test_versions_keep_their_own_language_names(self) -> None:
        # The links to the other versions name each language in itself, on every page.
        html = self.render("2026-11-05_tale-vi")
        self.assertIn('hreflang="en" lang="en">English</a>, <a href="../2026-11-05_tale-fr/" hreflang="fr" lang="fr">Français</a>',
                      html)

    def test_every_language_has_every_word(self) -> None:
        self.assertEqual(set(pages.UI), set(pages.STORY_LANGS))
        for lang, words in pages.UI.items():
            with self.subTest(lang=lang):
                self.assertEqual(set(words), set(pages.UI["en"]))
                self.assertTrue(all(isinstance(w, str) and w.strip() for w in words.values()))

    def test_live_french_and_vietnamese_story_pages_have_no_english_ui(self) -> None:
        eps = pages.site_episodes(DOCS)
        seen = set()
        for ep in eps:
            lang = pages.story_lang(ep)
            if pages.show_of(ep) != pages.STORY_SHOW or lang == "en":
                continue
            with self.subTest(id=ep["id"]):
                html = (DOCS / "episodes" / ep["id"] / "index.html").read_text(encoding="utf-8")
                self.assertIn(f'<html lang="{lang}">', html)
                self.assertIn(pages.UI[lang]["footer"], html)
                self.assert_no_english_ui(html, ep)
                seen.add(lang)
        self.assertEqual(seen, {"fr", "vi"})


class SameWordsAsSiteJsTest(unittest.TestCase):
    """The words the episode pages share with the story pages are site.js's own (#37)."""

    def text_block(self, lang: str) -> str:
        js = (DOCS / "site.js").read_text(encoding="utf-8")
        match = re.search(rf"\n    {lang}: \{{\n(.*?)\n    \}},", js, re.S)
        assert match, f"no {lang} block in site.js TEXT"
        return match.group(1)

    def js_string(self, block: str, key: str) -> str:
        match = re.search(rf'\b{key}: "([^"]*)"', block)
        assert match, f"no {key} in site.js"
        return match.group(1)

    def js_template(self, block: str, key: str, arg: str, name: str) -> str:
        match = re.search(rf"\b{key}: \({arg}\) => `([^`]*)`", block)
        assert match, f"no {key} in site.js"
        return match.group(1).replace(f"${{{arg}}}", f"{{{name}}}")

    def test_shared_words_match_site_js(self) -> None:
        for lang, ui in pages.UI.items():
            block = self.text_block(lang)
            with self.subTest(lang=lang):
                self.assertEqual(ui["download"], self.js_string(block, "download"))
                self.assertEqual(ui["transcript"], self.js_string(block, "transcript"))
                self.assertEqual(ui["based_on"], self.js_string(block, "basedOn"))
                self.assertEqual(ui["by"], self.js_string(block, "by"))
                self.assertEqual(ui["min"], self.js_template(block, "min", "n", "n"))
                self.assertEqual(ui["illustration"], self.js_template(block, "illustration", "t", "title"))
                self.assertEqual(ui["share"], self.js_string(block, "share"))
                self.assertEqual(ui["link_copied"], self.js_string(block, "linkCopied"))
                self.assertEqual(ui["copy_failed"], self.js_string(block, "copyFailed"))


if __name__ == "__main__":
    unittest.main()
