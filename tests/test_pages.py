"""Tests for scripts/pages.py: one static page per episode and the sitemap (DropCast #163).

Standard library only, no network: ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class Head(HTMLParser):
    """Collects the page's title, meta tags, links, JSON-LD and download links."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.ld: list[str] = []
        self.desc = ""
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self._in = "title"
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            self.links.append(a)
        elif tag == "a":
            self.anchors.append(a)
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in = "ld"
            self.ld.append("")
        elif tag == "p" and a.get("id") == "description":
            self._in = "desc"

    def handle_endtag(self, tag):
        if tag in ("title", "script", "p"):
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "ld":
            self.ld[-1] += data
        elif self._in == "desc":
            self.desc += data


def parse(html: str) -> Head:
    head = Head()
    head.feed(html)
    return head


DESC = ("A story <b>for</b> bedtime & more. Second sentence.\n\nIn this episode:\n- One\n- Two\n\n"
        "Sources: Cinderella\nMusic: Kevin MacLeod (incompetech.com), CC BY 4.0\n"
        "Once Upon a Time Show: Gentle stories. luongnv.com/podcast/stories")


def episode(ep_id: str, lang: str, **extra) -> dict:
    entry = {
        "id": ep_id, "title": f"Cinderella </script> ({lang})", "show": "Once Upon a Time Show",
        "format": "bedtime-story", "language": lang, "published": "2026-11-05T14:59:09Z",
        "duration_s": 402.4, "audio": f"episodes/{ep_id}/episode.mp3",
        "transcript": f"episodes/{ep_id}/transcript.vtt", "description": DESC,
        "file_name": "Once Upon a Time Show - Cinderella (2026-11-05).mp3",
        "source": {"title": "Cinderella", "author": "Charles Perrault", "url": "https://example.org/c"},
        "story_group": "2026-11-05_cinderella",
    }
    entry.update(extra)
    return entry


class PageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.site = Path(self._tmp.name)
        (self.site / "stories").mkdir()
        (self.site / "stories" / "cover-en.jpg").write_bytes(b"jpg")
        self.eps = [
            episode("2026-11-05_cinderella", "en"),
            episode("2026-11-05_cinderella-fr", "fr"),
            {"id": "2026-11-06_pod", "title": "Roll-ups", "show": "Build Wiz AI Show",
             "format": "podcast-2host", "language": "en", "published": "2026-11-06T07:50:23Z",
             "duration_s": 770, "audio": "episodes/2026-11-06_pod/episode.mp3", "description": "Hook.\n\nRest.",
             "source": {"title": "X", "url": "javascript:alert(1)"}},
            {"id": "../evil", "title": "nope"},
        ]
        (self.site / "episodes.json").write_text(json.dumps({"episodes": self.eps}), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_story_page(self) -> None:
        html = pages.render_page(self.eps[0], self.eps, self.site)
        head = parse(html)
        url = "https://luongnv.com/podcast/episodes/2026-11-05_cinderella/"
        self.assertEqual(head.title, "Cinderella </script> (en) | Once Upon a Time Show")
        self.assertEqual(head.meta["description"], "A story <b>for</b> bedtime & more. Second sentence.")
        self.assertIn({"rel": "canonical", "href": url}, head.links)
        self.assertIn({"rel": "alternate", "hreflang": "fr",
                       "href": "https://luongnv.com/podcast/episodes/2026-11-05_cinderella-fr/"}, head.links)
        self.assertEqual(head.meta["og:url"], url)
        self.assertEqual(head.meta["og:image"], "https://luongnv.com/podcast/stories/cover-en.jpg")
        self.assertEqual(head.meta["og:description"], head.meta["description"])
        self.assertEqual(head.meta["twitter:card"], "summary")
        self.assertEqual(len(head.ld), 1)
        ld = json.loads(head.ld[0])
        self.assertEqual(ld["@type"], "PodcastEpisode")
        self.assertEqual(ld["description"], DESC)
        self.assertEqual(ld["timeRequired"], "PT6M42S")
        self.assertEqual(ld["partOfSeries"]["url"], "https://luongnv.com/podcast/stories/")
        self.assertNotIn("</script>", head.ld[0])  # the title cannot close the element
        self.assertEqual(head.desc, DESC)
        download = [a for a in head.anchors if "download" in a]
        self.assertEqual(download[0]["download"], "Once Upon a Time Show - Cinderella (2026-11-05).mp3")
        self.assertIn({"class": "btn", "href": "../../stories/#2026-11-05_cinderella"},
                      [{k: a[k] for k in ("class", "href") if k in a} for a in head.anchors])
        # The French cover is missing here, so the English one is used.
        fr = parse(pages.render_page(self.eps[1], self.eps, self.site))
        self.assertTrue(fr.meta["og:image"].endswith("stories/cover-en.jpg"))
        self.assertEqual(fr.meta["og:locale"], "fr_FR")

    def test_podcast_page(self) -> None:
        head = parse(pages.render_page(self.eps[2], self.eps, self.site))
        self.assertEqual(head.title, "Roll-ups | Build Wiz AI Show")
        self.assertEqual(head.meta["description"], "Hook.")
        self.assertEqual(head.meta["og:image"], "https://luongnv.com/podcast/cover.jpg")
        self.assertNotIn("javascript:", pages.render_page(self.eps[2], self.eps, self.site))
        download = [a for a in head.anchors if "download" in a]
        self.assertEqual(download[0]["download"], "2026-11-06_pod.mp3")  # no file_name: the id
        self.assertFalse([link for link in head.links if link.get("hreflang") == "fr"])

    def test_write_pages_and_sitemap(self) -> None:
        changed = pages.write_pages(self.site)
        self.assertEqual(len(changed), 4)  # 3 pages + sitemap; the unsafe id is skipped
        self.assertFalse((self.site / "evil").exists())
        self.assertEqual(pages.write_pages(self.site), [])  # nothing changes on a rebuild
        tree = ET.parse(self.site / "sitemap.xml")
        locs = [u.findtext(f"{SM}loc") for u in tree.getroot()]
        self.assertEqual(locs[:2], ["https://luongnv.com/podcast/", "https://luongnv.com/podcast/stories/"])
        self.assertIn("https://luongnv.com/podcast/episodes/2026-11-06_pod/", locs)
        self.assertEqual(len(locs), 5)


class LiveSiteTest(unittest.TestCase):
    """The committed pages and sitemap match episodes.json."""

    def test_every_episode_has_a_current_page(self) -> None:
        site = ROOT / "docs"
        eps = pages.site_episodes(site)
        self.assertGreaterEqual(len(eps), 18)
        for ep in eps:
            with self.subTest(id=ep["id"]):
                path = site / "episodes" / ep["id"] / "index.html"
                self.assertEqual(path.read_text(encoding="utf-8"), pages.render_page(ep, eps, site))
                ld = json.loads(parse(path.read_text(encoding="utf-8")).ld[0])
                self.assertEqual(ld["url"], pages.page_url(ep["id"]))
        self.assertEqual((site / "sitemap.xml").read_text(encoding="utf-8"), pages.render_sitemap(eps))
        self.assertTrue((site / "cover.jpg").is_file())
        self.assertIn("Sitemap: https://luongnv.com/podcast/sitemap.xml", (site / "robots.txt").read_text())


if __name__ == "__main__":
    unittest.main()
