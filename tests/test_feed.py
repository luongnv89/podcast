"""Tests for scripts/feed.py (stdlib unittest: python3 -m unittest discover tests)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import feed  # noqa: E402

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def _episode(episode_id: str, language: str = "en", **extra) -> dict:
    return {
        "id": episode_id,
        "title": f"Title & {episode_id}",
        "summary": ["Line one.", "Line <two>.", "Line three."],
        "language": language,
        "published": "2026-11-03T07:01:29Z",
        "duration_s": 702.4,
        "size_bytes": 1234,
        "audio": f"episodes/{episode_id}/episode.mp3",
        "transcript": f"episodes/{episode_id}/transcript.vtt",
        "source": {"title": "A post", "author": "Someone", "url": "https://example.com/p?a=1&b=2"},
        **extra,
    }


class FeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name)
        self.index = {
            "version": 1,
            "episodes": [
                _episode("en-in", feed=True),
                _episode("en-out"),
                _episode("vi-flagged", language="vi", feed=True),
            ],
        }
        (self.site / feed.INDEX).write_text(json.dumps(self.index), encoding="utf-8")
        audio = self.site / "episodes" / "en-in" / "episode.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"ID3 fake mp3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_only_opted_in_english_episodes(self) -> None:
        ids = [e["id"] for e in feed.feed_episodes(self.index)]
        self.assertEqual(ids, ["en-in"])

    def test_feed_is_valid_rss_with_required_tags(self) -> None:
        root = ET.fromstring(feed.render_feed(self.index, self.site))
        channel = root.find("channel")
        assert channel is not None
        for tag in ("title", "link", "description", "language", ITUNES + "author",
                    ITUNES + "image", ITUNES + "category", ITUNES + "owner"):
            self.assertIsNotNone(channel.find(tag), tag)
        self.assertEqual(channel.findtext(f"{ITUNES}owner/{ITUNES}email"), "buildwizai@gmail.com")
        items = channel.findall("item")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.findtext("guid"), "en-in")
        self.assertEqual(item.findtext("title"), "Title & en-in")
        self.assertEqual(item.findtext("pubDate"), "Tue, 03 Nov 2026 07:01:29 +0000")
        self.assertEqual(item.findtext(ITUNES + "duration"), "702")
        enclosure = item.find("enclosure")
        assert enclosure is not None
        self.assertEqual(enclosure.get("length"), "1234")
        self.assertEqual(enclosure.get("type"), "audio/mpeg")
        # A new audio file gets a new URL, so Spotify downloads it again.
        self.assertRegex(enclosure.get("url") or "", r"/en-in/episode\.mp3\?v=[0-9a-f]{8}$")
        self.assertIn("Source: A post by Someone", item.findtext("description") or "")

    def test_write_feed_ignores_build_date_only_changes(self) -> None:
        self.assertTrue(feed.write_feed(self.site))
        self.assertFalse(feed.write_feed(self.site))

    def test_add_refuses_other_languages_and_unknown_ids(self) -> None:
        changed, errors = feed.set_flag(self.site, ["en-out", "vi-flagged", "nope"], True)
        self.assertEqual(changed, ["en-out"])
        self.assertEqual([e["id"] for e in errors], ["vi-flagged", "nope"])
        saved = json.loads((self.site / feed.INDEX).read_text(encoding="utf-8"))
        flags = {e["id"]: e.get("feed") for e in saved["episodes"]}
        self.assertTrue(flags["en-out"])

    def test_remove_clears_the_flag(self) -> None:
        changed, errors = feed.set_flag(self.site, ["en-in"], False)
        self.assertEqual((changed, errors), (["en-in"], []))
        saved = json.loads((self.site / feed.INDEX).read_text(encoding="utf-8"))
        self.assertNotIn("feed", saved["episodes"][0])


if __name__ == "__main__":
    unittest.main()
