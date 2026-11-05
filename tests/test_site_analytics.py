"""Static checks of the GA4 events in docs/site.js (DropCast #138).

Standard library only, no network: ``python3 -m unittest discover -s tests``.
The behaviour (each event once, a missing or throwing gtag) is checked in a browser;
these tests keep the guard and the README's event list from drifting.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ["episode_play", "episode_progress", "language_switch", "episode_download", "source_click"]
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


if __name__ == "__main__":
    unittest.main()
