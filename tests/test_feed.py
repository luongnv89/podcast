"""Tests for scripts/feed.py: the Once Upon a Time Show feeds (one per language) and the
Build Wiz AI Show feed.

Standard library only, no network: ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("feed", ROOT / "scripts" / "feed.py")
assert _spec is not None and _spec.loader is not None
feed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feed)

IT = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
NOW = datetime(2026, 11, 5, 22, 0, tzinfo=timezone.utc)


def story(ep_id: str, lang: str, published: str, **extra) -> dict:
    entry = {
        "id": ep_id,
        "title": f"Story {ep_id}",
        "summary": ["Line one.", "Line two.", "Line three."],
        "show": "Once Upon a Time Show",
        "language": lang,
        "format": "bedtime-story",
        "published": published,
        "duration_s": 403.6,
        "size_bytes": 1234,
        "audio": f"episodes/{ep_id}/episode.mp3",
        "transcript": f"episodes/{ep_id}/transcript.vtt",
        "voices": "OpenRouter · heygen/heygen-voice-1-turbo:free",
        "source": {"title": "Hansel and Gretel", "author": None,
                   "url": "https://sites.pitt.edu/~dash/grimm015.html"},
        "music_credit": "Music by Kevin MacLeod (incompetech.com). CC BY 4.0",
    }
    entry.update(extra)
    return entry


class FeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        self.index = {
            "episodes": [
                story("a", "en", "2026-11-05T21:28:03Z"),
                story("a-fr", "fr", "2026-11-05T22:10:03Z"),
                story("a-vi", "vi", "2026-11-05T21:34:30Z"),
                story("b", "en", "2026-11-04T10:00:00Z"),
                story("hidden", "en", "2026-11-06T10:00:00Z", feed=False),
                {"id": "pod", "title": "A podcast", "show": "Build Wiz AI Show", "language": "en",
                 "format": "podcast-2host", "published": "2026-11-07T00:00:00Z",
                 "audio": "episodes/pod/episode.mp3"},
            ]
        }
        (self.site / "episodes.json").write_text(json.dumps(self.index), encoding="utf-8")
        mp3 = self.site / "episodes" / "a" / "episode.mp3"
        mp3.parent.mkdir(parents=True)
        mp3.write_bytes(b"ID3 fake audio")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def channel(self, lang: str) -> ET.Element:
        xml = feed.render_feed(self.index, lang, self.site, NOW)
        root = ET.fromstring(xml.encode("utf-8"))
        channel = root.find("channel")
        assert channel is not None
        return channel

    def test_each_language_gets_only_its_stories_newest_first(self) -> None:
        en = [i.findtext("guid") for i in self.channel("en").findall("item")]
        self.assertEqual(en, ["a", "b"])  # no podcast, no fr/vi, not the opted-out one
        self.assertEqual([i.findtext("guid") for i in self.channel("fr").findall("item")], ["a-fr"])
        self.assertEqual([i.findtext("guid") for i in self.channel("vi").findall("item")], ["a-vi"])

    def test_channel_has_the_tags_spotify_requires(self) -> None:
        for lang in ("en", "fr", "vi"):
            ch = self.channel(lang)
            self.assertEqual(ch.findtext("language"), lang)
            self.assertTrue(ch.findtext("title", "").startswith("Once Upon a Time Show"))
            self.assertEqual(ch.find(f"{IT}owner/{IT}email").text, "buildwizai@gmail.com")
            self.assertTrue(ch.find(f"{IT}image").get("href").endswith(f"stories/cover-{lang}.jpg"))
            cat = ch.find(f"{IT}category")
            self.assertEqual(cat.get("text"), "Kids & Family")
            self.assertEqual(cat[0].get("text"), "Stories for Kids")
            self.assertEqual(ch.findtext(f"{IT}explicit"), "false")

    def test_descriptions_fit_spotify_limit(self) -> None:
        for lang, meta in feed.FEEDS.items():
            self.assertLessEqual(len(meta["description"]), 600, lang)

    def test_item_audio_url_is_versioned_and_notes_credit_source_and_music(self) -> None:
        item = self.channel("en").find("item")
        url = item.find("enclosure").get("url")
        self.assertRegex(url, r"episodes/a/episode\.mp3\?v=[0-9a-f]{8}$")
        self.assertEqual(item.find("enclosure").get("type"), "audio/mpeg")
        self.assertEqual(item.findtext(f"{IT}duration"), "404")
        notes = item.findtext("description")
        self.assertIn("Source: Hansel and Gretel (https://sites.pitt.edu/~dash/grimm015.html)", notes)
        self.assertIn("Kevin MacLeod", notes)
        self.assertIn("Written and voiced with AI", notes)

    def test_write_feeds_ignores_build_date_only_changes(self) -> None:
        first = feed.write_feeds(self.site, NOW)
        self.assertEqual(len(first), 4)  # en, fr, vi stories + Build Wiz AI Show
        later = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(feed.write_feeds(self.site, later), [])
        self.index["episodes"].append(story("c", "en", "2026-11-07T00:00:00Z"))
        (self.site / "episodes.json").write_text(json.dumps(self.index), encoding="utf-8")
        changed = feed.write_feeds(self.site, later)
        self.assertEqual([p.name for p in changed], ["feed-en.xml"])

    def test_item_image_from_the_story_illustration(self) -> None:
        square = self.site / "art" / "g" / "square.jpg"
        square.parent.mkdir(parents=True)
        square.write_bytes(b"jpg")
        image = {"square": "art/g/square.jpg", "wide": "art/g/wide.jpg", "thumb": "art/g/thumb.jpg", "alt": None}
        self.index["episodes"][0]["image"] = image
        self.index["episodes"][3]["image"] = dict(image, square="art/missing/square.jpg")
        items = {i.findtext("guid"): i for i in self.channel("en").findall("item")}
        self.assertEqual(items["a"].find(f"{IT}image").get("href"), "https://luongnv.com/podcast/art/g/square.jpg")
        self.assertIsNone(items["b"].find(f"{IT}image"))  # the file is not on the site
        # The channel keeps the show's cover.
        self.assertTrue(self.channel("en").find(f"{IT}image").get("href").endswith("stories/cover-en.jpg"))

    def test_no_item_image_without_a_safe_existing_file(self) -> None:
        for image in (None, {}, {"square": "../../etc/passwd"}, {"square": "art/../x/square.jpg"},
                      {"square": "https://evil.example/x.jpg"}, "art/g/square.jpg"):
            with self.subTest(image=image):
                ep = story("z", "en", "2026-11-05T00:00:00Z", image=image)
                self.assertIsNone(feed.item_image(ep, self.site))
        xml = feed.render_feed(self.index, "en", self.site, NOW)
        self.assertEqual(xml.count("<itunes:image"), 1)  # the channel's only


    def test_build_wiz_feed_holds_only_english_podcasts(self) -> None:
        self.index["episodes"] += [
            {"id": "pod-vi", "title": "Tập", "show": "Build Wiz AI Show", "language": "vi",
             "format": "podcast-2host", "published": "2026-11-08T00:00:00Z",
             "audio": "episodes/pod-vi/episode.mp3"},
            {"id": "pod-old", "title": "Older", "language": "en", "format": "solo-explainer",
             "published": "2026-11-01T00:00:00Z", "audio": "episodes/pod-old/episode.mp3"},
            {"id": "pod-off", "title": "Off", "show": "Build Wiz AI Show", "language": "en",
             "format": "podcast-2host", "published": "2026-11-09T00:00:00Z",
             "audio": "episodes/pod-off/episode.mp3", "feed": False},
        ]
        guids = [i.findtext("guid") for i in self.channel("buildwiz").findall("item")]
        self.assertEqual(guids, ["pod", "pod-old"])  # no story, no Vietnamese, not opted out
        self.assertNotIn("pod", [i.findtext("guid") for i in self.channel("en").findall("item")])

    def test_daily_episode_is_in_the_build_wiz_feed_only(self) -> None:
        self.index["episodes"].append(
            {"id": "daily-1", "title": "AI news, Nov 12", "show": "Build Wiz AI Show",
             "language": "en", "format": "podcast-2host", "category": "daily",
             "published": "2026-11-12T07:50:00Z", "audio": "episodes/daily-1/episode.mp3"})
        guids = [i.findtext("guid") for i in self.channel("buildwiz").findall("item")]
        self.assertEqual(guids, ["daily-1", "pod"])
        for lang in ("en", "fr", "vi"):
            with self.subTest(lang=lang):
                self.assertNotIn("daily-1", [i.findtext("guid") for i in self.channel(lang).findall("item")])

    def test_build_wiz_channel_tags(self) -> None:
        ch = self.channel("buildwiz")
        self.assertEqual(ch.findtext("title"), "Build Wiz AI Show")
        self.assertEqual(ch.findtext("language"), "en")
        self.assertEqual(ch.findtext("link"), "https://luongnv.com/podcast/")
        self.assertEqual(ch.findtext(f"{IT}author"), "Build Wiz AI Show")
        self.assertEqual(ch.find(f"{IT}owner/{IT}email").text, "buildwizai@gmail.com")
        self.assertEqual(ch.find(f"{IT}image").get("href"), "https://luongnv.com/podcast/cover-3000.jpg")
        cat = ch.find(f"{IT}category")
        self.assertEqual(cat.get("text"), "Technology")
        self.assertEqual(len(cat), 0)
        self.assertEqual(ch.findtext(f"{IT}explicit"), "false")
        self.assertEqual(feed.FEEDS["buildwiz"]["file"], "feed.xml")

    def test_build_wiz_notes_credit_every_source(self) -> None:
        self.index["episodes"][5].update(
            summary=["One.", "Two.", "Three."],
            voices="OpenRouter · heygen/heygen-voice-1-turbo:free",
            sources=[
                {"title": "Main post", "author": "Ann Author", "url": "https://x.com/a/status/1"},
                {"title": "Guest study", "author": None, "url": "https://example.org/study"},
                {"title": "No link", "author": "Bo", "url": "javascript:alert(1)"},
            ],
        )
        item = self.channel("buildwiz").find("item")
        notes = item.findtext("description")
        self.assertIn("Sources:\n- Main post, Ann Author (https://x.com/a/status/1)", notes)
        self.assertIn("- Guest study (https://example.org/study)", notes)
        self.assertIn("- No link, Bo", notes)
        self.assertNotIn("javascript", notes)
        self.assertIn("Written and voiced with AI", notes)


if __name__ == "__main__":
    unittest.main()
