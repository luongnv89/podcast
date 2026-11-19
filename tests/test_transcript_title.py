"""Tests for the Copy title button (podcast #50) and the full transcript on the episode pages
(podcast #51).

Standard library only, no network: ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

VTT = """WEBVTT

NOTE made by DropCast

1
00:00:00.000 --> 00:00:04.800
<v Bob>Welcome to the show.

2
00:00:05.100 --> 00:00:08.420
<v Bob>I'm Bob.

3
00:00:08.720 --> 00:00:15.320
<v Alice>And I'm Alice. Is 1 &lt; 2 &amp; does <b>bold</b>
work over two lines?

4
00:00:15.620 --> 00:00:19.220
<v Bob>Back to me: <script>alert(1)</script>
"""


def entry(ep_id: str, **extra) -> dict:
    ep = {
        "id": ep_id,
        "title": "A <Title> & more",
        "description": "Hook line.\n\nIn this episode:\n- one",
        "audio": f"episodes/{ep_id}/episode.mp3",
        "published": "2026-11-10T08:00:00+01:00",
        "duration_s": 300,
        "language": "en",
        "format": "podcast-2host",
        "show": "Build Wiz AI Show",
    }
    ep.update(extra)
    return ep


class Text(HTMLParser):
    """The text inside the page's transcript ``<details>``."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.summary = ""
        self.paras: list[str] = []
        self._where = ""

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.depth += 1
        elif self.depth and tag == "summary":
            self._where = "summary"
        elif self.depth and tag == "p":
            self._where = "p"
            self.paras.append("")

    def handle_endtag(self, tag):
        if tag == "details":
            self.depth -= 1
        if tag in ("summary", "p"):
            self._where = ""

    def handle_data(self, data):
        if self._where == "summary":
            self.summary += data
        elif self._where == "p":
            self.paras[-1] += data


class TranscriptParseTest(unittest.TestCase):
    def test_cues_group_by_speaker_without_timestamps(self) -> None:
        paras = pages.transcript_paragraphs(VTT)
        self.assertEqual(
            paras,
            [
                ("Bob", "Welcome to the show. I'm Bob."),
                ("Alice", "And I'm Alice. Is 1 < 2 & does bold work over two lines?"),
                ("Bob", "Back to me: alert(1)"),
            ],
        )

    def test_name_prefix_only_without_voice_tags(self) -> None:
        vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nAlice: Hi there.\n\n00:01.000 --> 00:02.000\nAlice: Again.\n\n" \
              "00:02.000 --> 00:03.000\nno speaker here\n"
        self.assertEqual(pages.transcript_paragraphs(vtt, ("Bob", "Alice")), [("Alice", "Hi there. Again."), ("", "no speaker here")])
        # With voice tags, a "Thesis: ..." line is text, not a speaker.
        tagged = VTT + "\n5\n00:00:20.000 --> 00:00:21.000\nThesis: loops matter.\n"
        self.assertEqual(pages.transcript_paragraphs(tagged)[-1], ("", "Thesis: loops matter."))

    def test_name_prefix_needs_a_known_speaker(self) -> None:
        def cue(text: str) -> str:
            return f"WEBVTT\n\n00:00.000 --> 00:01.000\n{text}\n"

        known = ("Bob", "Alice", "Le Roi")
        # Review nit 4: an ordinary label is not a speaker.
        self.assertEqual(pages.transcript_cues(cue("Note: this is not a speaker"), known), [("", "Note: this is not a speaker")])
        # Nor is a name the episode does not have, nor anything without the episode's speakers.
        self.assertEqual(pages.transcript_cues(cue("Carol: hello"), known), [("", "Carol: hello")])
        self.assertEqual(pages.transcript_cues(cue("Alice: hello")), [("", "Alice: hello")])
        # One or two capitalised words only (a lowercase accented first letter is not a name).
        self.assertEqual(pages.transcript_cues(cue("Le Roi: bonjour"), known), [("Le Roi", "bonjour")])
        self.assertEqual(pages.transcript_cues(cue("le roi: bonjour"), ("le roi",)), [("", "le roi: bonjour")])
        self.assertEqual(pages.transcript_cues(cue("élise: oui"), ("élise",)), [("", "élise: oui")])
        self.assertEqual(pages.transcript_cues(cue("Dear Old Bob: hi"), ("Dear Old Bob",)), [("", "Dear Old Bob: hi")])

    def test_every_voice_span_has_its_own_speaker(self) -> None:
        vtt = (
            "WEBVTT\n\n00:00.000 --> 00:02.000\n<v Bob>first</v>\n<v Alice>second</v>\n\n"
            "00:02.000 --> 00:03.000\n<i><v Carol>in italics</v></i>\n\n"
            "00:03.000 --> 00:04.000\n<v.loud Bob>tagged with a class <v Alice>and Alice\n"
        )
        self.assertEqual(
            pages.transcript_cues(vtt),
            [("Bob", "first"), ("Alice", "second"), ("Carol", "in italics"), ("Bob", "tagged with a class"), ("Alice", "and Alice")],
        )
        self.assertEqual(
            pages.transcript_paragraphs(vtt),
            [("Bob", "first"), ("Alice", "second"), ("Carol", "in italics"), ("Bob", "tagged with a class"), ("Alice", "and Alice")],
        )
        # Text before the first voice tag keeps no speaker.
        self.assertEqual(
            pages.transcript_cues("WEBVTT\n\n00:00.000 --> 00:01.000\nIntro <v Bob>hi\n"), [("", "Intro"), ("Bob", "hi")]
        )

    def test_long_run_is_cut_and_named_once(self) -> None:
        cues = "".join(f"\n{i}\n00:00:{i:02d}.000 --> 00:00:{i + 1:02d}.000\n<v Narrator>{'word ' * 40}{i}.\n" for i in range(10))
        paras = pages.transcript_paragraphs("WEBVTT\n" + cues)
        self.assertGreater(len(paras), 1)
        self.assertTrue(all(who == "Narrator" for who, _ in paras))
        self.assertTrue(all(len(text) < pages.PARAGRAPH_CHARS + 250 for _, text in paras))
        html = "\n".join(pages.transcript_html(paras, pages.UI["en"]))
        self.assertEqual(html.count("<strong>"), 1)
        self.assertEqual(html.count("<p>"), len(paras))

    def test_empty_or_broken_file(self) -> None:
        self.assertEqual(pages.transcript_paragraphs(""), [])
        self.assertEqual(pages.transcript_paragraphs("WEBVTT\n\nNOTE nothing\n"), [])
        self.assertEqual(pages.transcript_html([], pages.UI["en"]), [])

    def test_html_is_escaped(self) -> None:
        html = "\n".join(pages.transcript_html([("<b>Eve</b>", "x <script>alert(1)</script> & y")], pages.UI["en"]))
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>Eve", html)
        self.assertIn("<strong>&lt;b&gt;Eve&lt;/b&gt;:</strong> x &lt;script&gt;alert(1)&lt;/script&gt; &amp; y", html)

    def test_real_files_parse(self) -> None:
        for vtt in sorted((DOCS / "episodes").glob("*/transcript.vtt")):
            with self.subTest(vtt=vtt.parent.name):
                paras = pages.transcript_paragraphs(vtt.read_text(encoding="utf-8"))
                self.assertTrue(paras)
                self.assertTrue(all(who for who, _ in paras))
                for _, text in paras:
                    self.assertNotRegex(text, r"\d\d:\d\d[:.]\d\d|-->|<v ")


class PageCase(unittest.TestCase):
    """Renders pages into a temporary site."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name) / "docs"
        self.site.mkdir()
        shutil.copy(DOCS / "cover.jpg", self.site / "cover.jpg")
        for lang in ("en", "fr", "vi"):
            (self.site / "stories").mkdir(exist_ok=True)
            shutil.copy(DOCS / "stories" / f"cover-{lang}.jpg", self.site / "stories" / f"cover-{lang}.jpg")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def render(self, ep: dict, vtt: str | None) -> str:
        folder = self.site / "episodes" / ep["id"]
        folder.mkdir(parents=True, exist_ok=True)
        if vtt is not None:
            (folder / "transcript.vtt").write_text(vtt, encoding="utf-8")
        elif (folder / "transcript.vtt").exists():
            (folder / "transcript.vtt").unlink()
        return pages.render_page(ep, [ep], self.site)


class TranscriptPageTest(PageCase):
    def test_page_without_transcript_is_unchanged(self) -> None:
        ep = entry("2026-11-10_no-vtt")
        before = self.render(ep, None)
        self.assertNotIn("<details", before)
        self.assertNotIn(".transcript", before)
        with_vtt = self.render(ep, VTT)
        # The transcript adds its styles and its block and nothing else.
        styles = [ln for ln in with_vtt.split("\n") if ln.startswith("  .transcript")]
        self.assertEqual(len(styles), 3)
        start = with_vtt.index('  <details class="transcript"')
        end = with_vtt.index("  </details>\n") + len("  </details>\n")
        stripped = with_vtt[:start] + with_vtt[end:]
        for ln in styles:
            stripped = stripped.replace(ln + "\n", "", 1)
        self.assertEqual(stripped, before)

    def test_live_pages_without_transcript_unchanged(self) -> None:
        # Every live page rendered as if it had no transcript.vtt has no transcript block.
        copy = Path(self.tmp.name) / "live"
        shutil.copytree(DOCS, copy, ignore=shutil.ignore_patterns("*.mp3", "*.vtt"))
        for ep in pages.site_episodes(copy):
            html = pages.render_page(ep, pages.site_episodes(copy), copy)
            self.assertNotIn("<details", html)
            self.assertNotIn("  .transcript", html)

    def test_block_is_in_the_html_and_the_language_of_the_page(self) -> None:
        cases = {
            "en": (entry("2026-11-10_build"), "Transcript", "Bob:"),
            "fr": (entry("2026-11-10_story-fr", language="fr", format="bedtime-story", show="Once Upon a Time Show"), "Transcription", "Bob\u00a0:"),
            "vi": (entry("2026-11-10_story-vi", language="vi", format="bedtime-story", show="Once Upon a Time Show"), "Lời kể", "Bob:"),
            # A Build Wiz AI Show page stays in English, whatever its language.
            "build-fr": (entry("2026-11-10_build-fr", language="fr"), "Transcript", "Bob:"),
        }
        for name, (ep, heading, speaker) in cases.items():
            with self.subTest(page=name):
                html = self.render(ep, VTT)
                parser = Text()
                parser.feed(html)
                self.assertEqual(parser.summary, heading)
                self.assertEqual(parser.paras[0], f"{speaker} Welcome to the show. I'm Bob.")
                self.assertEqual(len(parser.paras), 3)
                self.assertNotIn("00:00:", html.split("<details", 1)[1].split("</details>", 1)[0])
                self.assertLess(html.index("<details"), html.index("<footer>"))

    def test_json_ld_has_no_transcript(self) -> None:
        # schema.org puts `transcript` on AudioObject/VideoObject; the page's associatedMedia is
        # a MediaObject, so the JSON-LD is left as it was.
        html = self.render(entry("2026-11-10_ld"), VTT)
        ld = json.loads(re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', html, re.DOTALL).group(1))
        self.assertEqual(ld["associatedMedia"]["@type"], "MediaObject")
        self.assertNotIn("transcript", json.dumps(ld))

    def test_live_pages_carry_their_transcript(self) -> None:
        for ep in pages.site_episodes(DOCS):
            if not (DOCS / pages.page_path(ep["id"]) / "transcript.vtt").is_file():
                continue
            with self.subTest(ep=ep["id"]):
                html = (DOCS / pages.page_path(ep["id"]) / "index.html").read_text(encoding="utf-8")
                self.assertEqual(html, pages.render_page(ep, pages.site_episodes(DOCS), DOCS))
                self.assertEqual(html.count('<details class="transcript" id="transcript">'), 1)


class RoleNameTest(PageCase):
    NARRATED = "WEBVTT\n\n00:00.000 --> 00:01.000\n<v Narrator>Il était une fois.\n\n00:01.000 --> 00:02.000\n<v King Midas>Gold!\n"

    def test_generic_role_in_the_page_language(self) -> None:
        self.assertEqual(pages.role_name("Narrator", "fr"), "Narratrice")
        self.assertEqual(pages.role_name("narrator", "vi"), "Người kể chuyện")
        self.assertEqual(pages.role_name("Narrator", "en"), "Narrator")
        self.assertEqual(pages.role_name("King Midas", "fr"), "King Midas")
        self.assertEqual(pages.role_name("Narratrice", "fr"), "Narratrice")
        story = {"format": "bedtime-story", "show": "Once Upon a Time Show"}
        cases = {
            "fr": (entry("2026-11-10_role-fr", language="fr", **story), "Narratrice\u00a0:", "King Midas\u00a0:"),
            "vi": (entry("2026-11-10_role-vi", language="vi", **story), "Người kể chuyện:", "King Midas:"),
            "en": (entry("2026-11-10_role-en", **story), "Narrator:", "King Midas:"),
            # A Build Wiz AI Show page is in English whatever its language.
            "build-fr": (entry("2026-11-10_role-build-fr", language="fr"), "Narrator:", "King Midas:"),
        }
        for name, (ep, narrator, king) in cases.items():
            with self.subTest(page=name):
                parser = Text()
                parser.feed(self.render(ep, self.NARRATED))
                self.assertTrue(parser.paras[0].startswith(narrator + " Il était une fois."))
                self.assertTrue(parser.paras[1].startswith(king))


class Buttons(HTMLParser):
    """The page's copy buttons: ``data-copy`` -> attributes (unescaped) and label."""

    def __init__(self) -> None:
        super().__init__()
        self.buttons: dict[str, dict] = {}
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "button" and "data-copy" in a:
            self._in = a["data-copy"]
            self.buttons[self._in] = {**a, "label": ""}

    def handle_endtag(self, tag):
        if tag == "button":
            self._in = None

    def handle_data(self, data):
        if self._in:
            self.buttons[self._in]["label"] += data


class EpisodePageCopyTest(PageCase):
    TITLE = 'A <Title> & "more" \'x\' </button><script>alert(1)</script>'
    DESC = 'Hook "line" & <b>bold</b>.\n\nIn this episode:\n- one\n- two </button><script>alert(2)</script>\n'

    def buttons(self, ep: dict) -> tuple[str, dict]:
        html = self.render(ep, None)
        parser = Buttons()
        parser.feed(html)
        return html, parser.buttons

    def test_buttons_copy_the_exact_text_escaped(self) -> None:
        html, found = self.buttons(entry("2026-11-10_copy", title=self.TITLE, description=self.DESC))
        self.assertEqual(list(found), ["title", "description"])
        self.assertEqual(found["title"]["data-text"], self.TITLE)
        self.assertEqual(found["description"]["data-text"], self.DESC)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("</button><script>", html)
        for b in found.values():
            self.assertIn("hidden", b)  # shown by the page's script, so no dead button without JS
        # Share, then Copy title, then Copy description, as on the list pages.
        self.assertLess(html.index('id="share"'), html.index('data-copy="title"'))
        self.assertLess(html.index('data-copy="title"'), html.index('data-copy="description"'))
        self.assertIn('document.querySelectorAll("button[data-copy]")', html)
        self.assertIn('copy(b.getAttribute("data-text")', html)

    def test_words_in_the_page_language(self) -> None:
        story = {"format": "bedtime-story", "show": "Once Upon a Time Show"}
        cases = {
            "en": (entry("2026-11-10_w-en"), ("Copy title", "Copied"), ("Copy description", "Copied")),
            "story-en": (entry("2026-11-10_w-sen", **story), ("Copy title", "Copied"), ("Copy description", "Copied")),
            "fr": (entry("2026-11-10_w-fr", language="fr", **story), ("Copier le titre", "Copié"), ("Copier la description", "Copiée")),
            "vi": (entry("2026-11-10_w-vi", language="vi", **story), ("Sao chép tiêu đề", "Đã sao chép"), ("Sao chép mô tả", "Đã sao chép")),
            "build-vi": (entry("2026-11-10_w-bvi", language="vi"), ("Copy title", "Copied"), ("Copy description", "Copied")),
        }
        for name, (ep, title, desc) in cases.items():
            with self.subTest(page=name):
                _, found = self.buttons(ep)
                self.assertEqual((found["title"]["label"], found["title"]["data-done"]), title)
                self.assertEqual((found["description"]["label"], found["description"]["data-done"]), desc)

    def test_no_description_no_description_button(self) -> None:
        for desc in (None, "", "   "):
            with self.subTest(desc=desc):
                _, found = self.buttons(entry("2026-11-10_nodesc", description=desc))
                self.assertEqual(list(found), ["title"])

    def test_live_pages_copy_their_entry(self) -> None:
        for ep in pages.site_episodes(DOCS):
            with self.subTest(ep=ep["id"]):
                parser = Buttons()
                parser.feed((DOCS / pages.page_path(ep["id"]) / "index.html").read_text(encoding="utf-8"))
                self.assertEqual(parser.buttons["title"]["data-text"], ep["title"])
                if (ep.get("description") or "").strip():
                    self.assertEqual(parser.buttons["description"]["data-text"], ep["description"])


class CopyTitleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (DOCS / "site.js").read_text(encoding="utf-8")

    def test_strings_in_every_language(self) -> None:
        want = {"en": "Copy title", "fr": "Copier le titre", "vi": "Sao chép tiêu đề"}
        done = {"en": "Copied", "fr": "Copié", "vi": "Đã sao chép"}
        text = self.js[self.js.index("const TEXT = {"): self.js.index("// ---------- end of words")]
        blocks = re.split(r"\n    (en|fr|vi): \{", text)[1:]
        langs = dict(zip(blocks[::2], blocks[1::2]))
        self.assertEqual(set(langs), set(want))
        for lang, label in want.items():
            with self.subTest(lang=lang):
                self.assertIn(f'copyTitle: "{label}"', langs[lang])
                self.assertIn(f'titleCopied: "{done[lang]}"', langs[lang])

    def test_button_copies_the_exact_title_next_to_description(self) -> None:
        self.assertIn('"data-copy": "title"', self.js)
        self.assertIn("copyTitle(ep, titleBtn, titleLabel)", self.js)
        body = self.js[self.js.index("async function copyTitle"):]
        body = body[: body.index("\n  }\n")]
        self.assertIn("await copyText(ep.title)", body)
        self.assertIn("T.titleCopied : T.copyFailed", body)
        self.assertIn('label.textContent = T.copyTitle', body)
        self.assertLess(self.js.index("actions.append(titleBtn);"), self.js.index("actions.append(descBtn);"))

    def test_every_page_loads_the_bumped_assets(self) -> None:
        for page in ("index.html", "stories/index.html", "stories/en/index.html", "stories/fr/index.html", "stories/vi/index.html"):
            with self.subTest(page=page):
                html = (DOCS / page).read_text(encoding="utf-8")
                self.assertIn("site.js?v=202611191200", html)
                self.assertIn("site.css?v=202611191200", html)


if __name__ == "__main__":
    unittest.main()
