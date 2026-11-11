"""Static checks of the GA4 events in docs/site.js (DropCast #138).

Standard library only, no network: ``python3 -m unittest discover -s tests``.
The behaviour (each event once, a missing or throwing gtag) is checked in a browser;
these tests keep the guard and the README's event list from drifting.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ["episode_play", "episode_progress", "language_switch", "episode_download", "source_click",
          "description_copy"]
PARAMS = ["episode_id", "episode_title", "show", "episode_language", "story_group", "category",
          "percent", "from_language", "to_language"]


class SiteAnalyticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_gtag_is_called_only_through_the_guard(self) -> None:
        # One call site, behind a typeof check and inside a try.
        calls = re.findall(r"gtag\(", self.js)
        self.assertEqual(len(calls), 1)
        self.assertRegex(self.js, r'try \{ if \(typeof window\.gtag === "function"\) window\.gtag\("event", name, params\); \} catch')

    def test_every_event_is_sent_and_documented(self) -> None:
        for name in EVENTS:
            with self.subTest(event=name):
                self.assertRegex(self.js, rf'(track\("{name}"|"{name}", ep\))')
                self.assertIn(f"| `{name}` |", self.readme)

    def test_every_parameter_is_sent_and_documented(self) -> None:
        for name in PARAMS:
            with self.subTest(param=name):
                self.assertRegex(self.js, rf"([{{,]\s*{name}\s*:|\.{name}\s*=)")
                self.assertIn(f"`{name}`", self.readme)

    def test_reserved_language_parameter_is_not_sent(self) -> None:
        # GA4 fills `language` with the visitor's browser language; sending it would overwrite that.
        self.assertNotRegex(self.js, r"[{,]\s*language\s*:")

    def test_no_new_tracker(self) -> None:
        # The pages load GA4 once each; site.js loads no script and sets no cookie.
        self.assertNotIn("document.cookie", self.js)
        self.assertNotRegex(self.js, r"createElement\(\"script\"|googletagmanager|sendBeacon")
        for page in (ROOT / "docs" / "index.html", ROOT / "docs" / "stories" / "index.html"):
            html = page.read_text(encoding="utf-8")
            self.assertEqual(html.count("<script async src="), 1, page)
            self.assertEqual(html.count("googletagmanager.com/gtag/js?id=G-FZV5YX8YPT"), 1, page)


class SiteIllustrationTest(unittest.TestCase):
    """Static checks of the story illustration in docs/site.js and site.css (behaviour: browser)."""

    def setUp(self) -> None:
        self.js = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")
        self.css = (ROOT / "docs" / "site.css").read_text(encoding="utf-8")

    def test_only_safe_art_paths_are_used(self) -> None:
        m = re.search(r"const ART_PATH = /(.+)/;", self.js)
        self.assertTrue(m)
        pattern = re.compile(m.group(1).replace("\\/", "/"))
        self.assertTrue(pattern.fullmatch("art/2026-11-06_little-red-cap/thumb.jpg"))
        for bad in ("../art/x/thumb.jpg", "art/x/y/thumb.jpg", "https://evil.example/art/x/thumb.jpg",
                    "art/x/thumb.png", "javascript:alert(1)", "art//thumb.jpg"):
            self.assertIsNone(pattern.fullmatch(bad), bad)
        self.assertIn('!p.includes("..")', self.js)
        self.assertIn("new URL(p, DATA_URL).href", self.js)

    def test_thumbnail_in_the_card_row(self) -> None:
        self.assertIn('const thumbUrl = artOf(ep, "thumb");', self.js)
        self.assertIn('el("img", { class: "thumb", src: thumbUrl, alt: "", loading: "lazy", decoding: "async", width: 64, height: 64 })', self.js)
        self.assertIn('class: thumb ? "ep-row has-art" : "ep-row"', self.js)
        # Rows without art keep their three columns; the thumbnail is 64 px, 52 px on phones.
        self.assertIn(".ep-row { position: relative; display: grid; grid-template-columns: 44px minmax(0, 1fr) 20px;", self.css)
        self.assertIn(".ep-row.has-art { grid-template-columns: 44px 64px minmax(0, 1fr) 20px; }", self.css)
        self.assertIn(".ep-row.has-art { grid-template-columns: 44px 52px minmax(0, 1fr) 20px; }", self.css)

    def test_wide_image_in_the_details_and_media_session(self) -> None:
        self.assertIn('el("img", { class: "art", src: wideUrl, alt: artAlt(ep), loading: "lazy"', self.js)
        self.assertIn("return alt || T.illustration(ep.title);", self.js)
        self.assertIn("illustration: (t) => `Illustration: ${t}`,", self.js)
        self.assertRegex(self.js, r"\[\s*art, summaryItems\.length")
        # Every language version of a story shows the same art, also on a language page (#35).
        self.assertIn("[ep, ...((ep._unit && ep._unit.versions) || []), ...(ep._alts || [])]", self.js)
        # Lock screen: only the small thumbnail, never the 3000 px square (mobile data).
        self.assertIn('const artwork = [["thumb", "640x640"]]', self.js)
        self.assertNotIn('["square", "3000x3000"]', self.js)
        self.assertIn("...(artwork.length ? { artwork } : {})", self.js)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ArtHelpersRunInNode(unittest.TestCase):
    """Run site.js's art helpers (ART_PATH .. artAlt) in node, not just grep for them."""

    def test_art_paths_versions_and_alt(self):
        js = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")
        start = js.index("  const ART_PATH")
        end = js.index("  // The description's hook")
        script = (
            'const DATA_URL = "https://luongnv.com/podcast/episodes.json";\n'
            'const T = { illustration: (t) => `Illustration: ${t}` };\n'
            + js[start:end]
            + """
const ok = (p) => artPath({ square: p }, "square");
const en = { title: "Tale", image: { wide: "art/g1/wide.jpg", square: "art/g1/square.jpg", thumb: "art/g1/thumb.jpg", alt: " A drawing. " } };
const fr = { title: "Conte" };
const unit = { versions: [fr, en] }; en._unit = unit; fr._unit = unit;
console.log(JSON.stringify({
  good: ok("art/g1/square.jpg"),
  bad: ["../art/g1/square.jpg", "art/../x/square.jpg", "art/a..b/square.jpg", "//evil.com/art/g/square.jpg",
        "art/g/square.jpg?x", "art/g/square.jpg\\nx", "art/g/other.jpg", "https://evil.com/art/g/square.jpg"].map(ok),
  frThumb: artOf(fr, "thumb"), frAlt: artAlt(fr), noArt: artOf({ title: "x" }, "wide"), noAlt: artAlt({ title: "Pod" }),
}));
"""
        )
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
        got = json.loads(out.stdout)
        self.assertEqual(got["good"], "https://luongnv.com/podcast/art/g1/square.jpg")
        self.assertEqual(got["bad"], [None] * 8)
        self.assertEqual(got["frThumb"], "https://luongnv.com/podcast/art/g1/thumb.jpg")
        self.assertEqual(got["frAlt"], "A drawing.")
        self.assertIsNone(got["noArt"])
        self.assertEqual(got["noAlt"], "Illustration: Pod")
