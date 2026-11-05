"""Tests for scripts/publish.py: the sources and guests of an episode entry.

Standard library only, no network: ``python3 -m unittest discover -s tests``.
Each test builds a fake delivered DropCast job and a fake site in a temp folder.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("publish", ROOT / "scripts" / "publish.py")
assert _spec is not None and _spec.loader is not None
publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publish)

MAIN = {
    "title": "Why cities are bringing back quiet hours",
    "author": "Jane Example",
    "url": "https://example.com/articles/quiet-hours",
    "published": "2026-10-01",
    "kind": "article",
}
EXTRA = {
    "id": "rivers-study",
    "title": "A study of quiet",
    "url": "https://example.org/studies/quiet",
    "author": "Sam Rivers",
}
HOSTS = [
    {"id": "host_a", "name": "Bob", "role": "host-curious"},
    {"id": "host_b", "name": "Alice", "role": "host-expert"},
]
MAYA = {"id": "maya", "name": "Maya", "role": "guest-maya", "presents": ["rivers-study"]}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class EpisodeCreditsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.site = self.tmp / "docs"
        self.job = self.tmp / "2026-11-05_quiet-hours"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_job(self, sources, speakers, result=None, fact_check_pass=None, music=None) -> None:
        job = self.job
        script = {
            "title": "Quiet hours",
            "format": "podcast-2host",
            "language": "en",
            "show": {"hosts": {"host_a": "Bob", "host_b": "Alice"}},
            "sources": sources,
            "speakers": speakers,
        }
        if fact_check_pass is not None:
            script["fact_check_pass"] = fact_check_pass
        _write(job / "script.json", script)
        _write(job / "source.json", MAIN)
        _write(job / "job.json", {"steps": {"render": {"status": "done"}}})
        run = {"engine": "openrouter", "episode": "episode.mp3", "duration_s": 300,
               "finished": "2026-11-05T10:00:00Z"}
        if music is not None:
            run["music"] = music
        _write(job / "run.json", run)
        _write(job / "result.json", result if result is not None else {"status": "awaiting"})
        (job / "episode.mp3").write_bytes(b"ID3fake")

    def entry(self) -> dict:
        entry, _ = publish.episode_entry(self.job, self.site)
        return entry

    def test_single_source_entry_has_no_new_keys(self) -> None:
        self.make_job([MAIN["url"]], HOSTS)
        entry = self.entry()
        self.assertNotIn("sources", entry)
        self.assertNotIn("guests", entry)
        self.assertEqual(entry["source"]["url"], MAIN["url"])

    def test_extra_sources_from_script_and_fetched_page(self) -> None:
        listed = dict(EXTRA, author=None)  # a null listed author is read from the page
        self.make_job([MAIN["url"], listed], [*HOSTS, MAYA])
        _write(self.job / "sources" / "rivers-study" / "source.json",
               {"id": "rivers-study", "author": "Sam Rivers", "title": "A study of quiet"})
        entry = self.entry()
        self.assertEqual(
            entry["sources"],
            [
                {"title": MAIN["title"], "author": MAIN["author"], "url": MAIN["url"]},
                {"title": EXTRA["title"], "author": "Sam Rivers", "url": EXTRA["url"]},
            ],
        )
        self.assertEqual(entry["guests"], [{"name": "Maya", "presents": ["A study of quiet"]}])
        # The main source keeps its existing field.
        self.assertEqual(entry["source"]["title"], MAIN["title"])

    def test_result_delivery_sources_preferred(self) -> None:
        result = {
            "status": "delivered",
            "delivery": {
                "sources": [
                    {"id": "main", "title": "file notes.md", "author": None, "url": None,
                     "label": "file notes.md"},
                    {"id": "rivers-study", "title": "A Study of Quiet (delivered)",
                     "author": "Sam Rivers", "url": EXTRA["url"]},
                ]
            },
        }
        self.make_job([MAIN["url"], EXTRA], [*HOSTS, MAYA], result=result)
        entry = self.entry()
        # The main source still comes from source.json (no local file label).
        self.assertEqual(entry["sources"][0]["title"], MAIN["title"])
        self.assertEqual(entry["sources"][1]["title"], "A Study of Quiet (delivered)")
        self.assertEqual(entry["guests"][0]["presents"], ["A Study of Quiet (delivered)"])
        self.assertNotIn("label", json.dumps(entry["sources"]))

    def test_stale_result_sources_ignored(self) -> None:
        result = {"delivery": {"sources": [{"id": "main", "title": "x", "url": None}]}}
        self.make_job([MAIN["url"], EXTRA], [*HOSTS, MAYA], result=result)
        entry = self.entry()
        self.assertEqual([s["title"] for s in entry["sources"]], [MAIN["title"], EXTRA["title"]])

    def test_fact_check_report_fills_missing_fields(self) -> None:
        listed = {"id": "rivers-study", "title": None, "url": EXTRA["url"], "author": None}
        report = {"sources": [dict(EXTRA, claims=2, supported=2)]}
        self.make_job([MAIN["url"], listed], HOSTS, fact_check_pass=report)
        entry = self.entry()
        self.assertEqual(entry["sources"][1],
                         {"title": EXTRA["title"], "author": "Sam Rivers", "url": EXTRA["url"]})
        self.assertNotIn("guests", entry)

    def test_symlinked_fetched_source_not_read(self) -> None:
        outside = self.tmp / "elsewhere" / "source.json"
        _write(outside, {"author": "Someone Else", "title": "Not this"})
        listed = {"id": "rivers-study", "title": None, "url": EXTRA["url"], "author": None}
        self.make_job([MAIN["url"], listed], HOSTS)
        (self.job / "sources").mkdir()
        (self.job / "sources" / "rivers-study").symlink_to(outside.parent)
        entry = self.entry()
        self.assertEqual(entry["sources"][1],
                         {"title": "rivers-study", "author": None, "url": EXTRA["url"]})

    def test_index_round_trip_keeps_keys(self) -> None:
        self.make_job([MAIN["url"], EXTRA], [*HOSTS, MAYA])
        entry = self.entry()
        self.assertTrue(publish.update_index(self.site, [entry]))
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["episodes"][0]["sources"], entry["sources"])
        self.assertEqual(saved["episodes"][0]["guests"], entry["guests"])

class RobustCreditsTest(EpisodeCreditsTest):
    """Review of PR #8: bad fields never crash a publish run, links stay http(s)."""

    def test_badly_formed_fields_do_not_crash(self) -> None:
        maya = dict(MAYA, presents=[{"id": "rivers-study"}, "rivers-study"])
        result = {"delivery": "not a dict"}
        self.make_job([MAIN["url"], EXTRA], [*HOSTS, maya], result=result,
                      fact_check_pass="not a dict")
        entry = self.entry()
        self.assertEqual(entry["guests"], [{"name": "Maya", "presents": [EXTRA["title"]]}])

    def test_sources_value_that_is_not_a_list(self) -> None:
        self.make_job(5, HOSTS)
        self.assertNotIn("sources", self.entry())

    def test_symlinked_sources_folder_not_read(self) -> None:
        listed = dict(EXTRA, author=None)
        self.make_job([MAIN["url"], listed], HOSTS)
        outside = self.tmp / "elsewhere"
        _write(outside / "rivers-study" / "source.json", {"author": "Someone Else"})
        (self.job / "sources").symlink_to(outside, target_is_directory=True)
        self.assertIsNone(self.entry()["sources"][1]["author"])

    def test_delivered_null_title_is_filled_from_the_fetched_page(self) -> None:
        result = {"delivery": {"sources": [
            {"id": "main", "title": "x", "url": None},
            {"id": "rivers-study", "title": None, "author": None, "url": None},
        ]}}
        listed = {"id": "rivers-study", "title": None, "url": EXTRA["url"], "author": None}
        self.make_job([MAIN["url"], listed], [*HOSTS, MAYA], result=result)
        _write(self.job / "sources" / "rivers-study" / "source.json",
               {"id": "rivers-study", "author": "Sam Rivers", "title": "A study of quiet"})
        entry = self.entry()
        self.assertEqual(entry["sources"][1],
                         {"title": EXTRA["title"], "author": "Sam Rivers", "url": EXTRA["url"]})
        self.assertEqual(entry["guests"][0]["presents"], [EXTRA["title"]])

    def test_only_http_links_are_published(self) -> None:
        listed = dict(EXTRA, url="javascript:alert(1)")
        self.make_job([MAIN["url"], listed], HOSTS)
        self.assertIsNone(self.entry()["sources"][1]["url"])


CREDIT = (
    '"Music Box Theme" by Kevin MacLeod (incompetech.com), licensed under Creative '
    "Commons: By Attribution 4.0 License http://creativecommons.org/licenses/by/4.0/"
)


class MusicCreditTest(EpisodeCreditsTest):
    """Licensed music credited per episode, from run.json ``music.credit``."""

    def test_credit_is_published(self) -> None:
        music = {"title": "Music Box Theme", "author": "Kevin MacLeod",
                 "licence": "CC-BY-4.0", "source": "incompetech.com", "credit": f"  {CREDIT} "}
        self.make_job([MAIN["url"]], HOSTS, music=music)
        entry = self.entry()
        self.assertEqual(entry["music_credit"], CREDIT)
        self.assertTrue(publish.update_index(self.site, [entry]))
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["episodes"][0]["music_credit"], CREDIT)

    def test_republishing_the_same_credit_changes_nothing(self) -> None:
        music = {"title": "Music Box Theme", "author": "Kevin MacLeod",
                 "licence": "CC-BY-4.0", "source": "incompetech.com", "credit": CREDIT}
        self.make_job([MAIN["url"]], HOSTS, music=music)
        self.assertTrue(publish.update_index(self.site, [self.entry()]))
        before = (self.site / "episodes.json").read_text(encoding="utf-8")
        self.assertFalse(publish.update_index(self.site, [self.entry()]))
        self.assertEqual((self.site / "episodes.json").read_text(encoding="utf-8"), before)

    def test_run_json_wins_over_result_json(self) -> None:
        # result.json is not final when DropCast calls the publisher: never read from it.
        result = {"status": "awaiting", "music": {"credit": "stale"}}
        self.make_job([MAIN["url"]], HOSTS, result=result, music={"credit": CREDIT})
        self.assertEqual(self.entry()["music_credit"], CREDIT)

    def test_no_credit_no_key(self) -> None:
        for music in (None, {"credit": None}, {"credit": ""}, {"credit": "   "},
                      {"credit": 5}, {"title": "Theme"}, "not a dict", []):
            with self.subTest(music=music):
                self.make_job([MAIN["url"]], HOSTS, music=music)  # None: no music key
                self.assertNotIn("music_credit", self.entry())


STORY = "Once Upon a Time Show"
BUILD = "Build Wiz AI Show"


class ShowRoutingTest(EpisodeCreditsTest):
    """Stories go to Once Upon a Time Show (DropCast #129); podcasts stay Build Wiz AI Show."""

    def make_show_job(self, fmt, script_show=None, brief_show=None, result=None) -> None:
        self.make_job([MAIN["url"]], HOSTS, result=result)
        script = json.loads((self.job / "script.json").read_text(encoding="utf-8"))
        script["format"] = fmt
        if script_show is not None:
            script["show"] = dict(script["show"], name=script_show)
        _write(self.job / "script.json", script)
        if brief_show is not None:
            _write(self.job / "brief.json", {"format": fmt, "show": brief_show})

    def test_podcast_unchanged(self) -> None:
        for fmt in ("podcast-2host", "solo-explainer"):
            with self.subTest(fmt=fmt):
                self.make_show_job(fmt, BUILD, {"name": BUILD, "register": "show"})
                self.assertEqual(self.entry()["show"], BUILD)

    def test_story_job_goes_to_the_story_show(self) -> None:
        for fmt in ("bedtime-story", "storytelling"):
            with self.subTest(fmt=fmt):
                register = "bedtime" if fmt == "bedtime-story" else "story"
                self.make_show_job(fmt, STORY, {"name": STORY, "register": register})
                self.assertEqual(self.entry()["show"], STORY)

    def test_legacy_story_with_the_build_wiz_name_is_routed_by_format(self) -> None:
        # A story briefed before #126: script.json and brief.json both say Build Wiz AI Show.
        self.make_show_job("bedtime-story", BUILD, {"name": BUILD, "register": "bedtime"})
        entry = self.entry()
        self.assertEqual(entry["show"], STORY)
        self.assertEqual(entry["category"], "bedtime")
        self.make_show_job("storytelling", BUILD)  # no brief.json at all
        self.assertEqual(self.entry()["show"], STORY)

    def test_story_named_by_the_brief_or_script_only(self) -> None:
        # A story format this site does not know yet, named by its brief or script.
        self.make_show_job("fable", None, {"name": STORY, "register": "story"})
        self.assertEqual(self.entry()["show"], STORY)
        self.make_show_job("fable", STORY)
        self.assertEqual(self.entry()["show"], STORY)

    def test_old_or_unknown_show_names_publish_as_build_wiz(self) -> None:
        self.make_show_job("podcast-2host", "The AI Show", {"name": "The AI Show"})
        self.assertEqual(self.entry()["show"], BUILD)
        (self.job / "brief.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.entry()["show"], BUILD)

    def test_result_json_is_not_read_for_the_show(self) -> None:
        # result.json is not final when DropCast calls the publisher.
        result = {"status": "awaiting", "delivery": {"show": STORY}}
        self.make_show_job("podcast-2host", BUILD, result=result)
        self.assertEqual(self.entry()["show"], BUILD)

    def test_index_lists_both_shows(self) -> None:
        self.make_show_job("bedtime-story", STORY)
        self.assertTrue(publish.update_index(self.site, [self.entry()]))
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["show"]["name"], BUILD)
        self.assertEqual([s["name"] for s in saved["shows"]], [BUILD, STORY])
        self.assertEqual(saved["shows"][1]["page"], "stories/")
        self.assertEqual(saved["episodes"][0]["show"], STORY)


class StoryGroupTest(EpisodeCreditsTest):
    """One story in several languages (DropCast #136): ``story_group`` and ``language``."""

    def make_story(self, **fields) -> None:
        self.make_job([MAIN["url"]], HOSTS)
        script = json.loads((self.job / "script.json").read_text(encoding="utf-8"))
        script.update(format="bedtime-story", **fields)
        for key in [k for k, v in script.items() if v is None]:
            del script[key]
        _write(self.job / "script.json", script)

    def test_group_and_language_are_copied(self) -> None:
        for lang in ("en", "fr", "vi"):
            with self.subTest(lang=lang):
                self.make_story(story_group="2026-11-05_cinderella", language=lang)
                entry = self.entry()
                self.assertEqual(entry["story_group"], "2026-11-05_cinderella")
                self.assertEqual(entry["language"], lang)

    def test_group_is_trimmed(self) -> None:
        self.make_story(story_group="  2026-11-05_cinderella \n", language="fr")
        self.assertEqual(self.entry()["story_group"], "2026-11-05_cinderella")

    def test_old_job_has_no_group_key(self) -> None:
        self.make_story(language="vi")
        entry = self.entry()
        self.assertNotIn("story_group", entry)
        self.assertEqual(entry["language"], "vi")
        self.make_story(language=None)  # no language at all: English, as before
        self.assertEqual(self.entry()["language"], "en")

    def test_bad_group_values_are_left_out(self) -> None:
        for bad in ("", "   ", 5, ["a"], {"id": "a"}, True):
            with self.subTest(bad=bad):
                self.make_story(story_group=bad, language="en")
                self.assertNotIn("story_group", self.entry())

    def test_result_json_is_not_read_for_the_group(self) -> None:
        self.make_story(language="fr")
        _write(self.job / "result.json", {"status": "delivered", "story_group": "x",
                                          "delivery": {"story_group": "x", "language": "en"}})
        entry = self.entry()
        self.assertNotIn("story_group", entry)
        self.assertEqual(entry["language"], "fr")

    def test_index_round_trip_keeps_the_group(self) -> None:
        self.make_story(story_group="2026-11-05_cinderella", language="vi")
        self.assertTrue(publish.update_index(self.site, [self.entry()]))
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["episodes"][0]["story_group"], "2026-11-05_cinderella")
        self.assertEqual(saved["episodes"][0]["language"], "vi")
        self.assertFalse(publish.update_index(self.site, [self.entry()]))


class SiteMigrationTest(unittest.TestCase):
    """The live index after #129: stories moved to their own page, nothing removed."""

    def setUp(self) -> None:
        self.data = json.loads((ROOT / "docs" / "episodes.json").read_text(encoding="utf-8"))
        self.episodes = self.data["episodes"]

    def test_stories_are_on_the_story_show(self) -> None:
        stories = {e["id"] for e in self.episodes if e["show"] == STORY}
        self.assertTrue({"2026-11-04_the-golden-touch",
                         "2026-11-05_cinderella-or-the-little-glass-slipper"} <= stories)
        for e in self.episodes:
            with self.subTest(id=e["id"]):
                story = e.get("format") in publish.STORY_FORMATS
                self.assertEqual(e["show"], STORY if story else BUILD)
                if story:
                    self.assertTrue((ROOT / "docs" / e["audio"]).is_file())

    def test_no_episode_removed(self) -> None:
        self.assertGreaterEqual(len(self.episodes), 10)
        self.assertEqual(len({e["id"] for e in self.episodes}), len(self.episodes))
        for e in self.episodes:
            self.assertTrue((ROOT / "docs" / e["audio"]).is_file(), e["id"])

    def test_both_pages_share_the_index_and_script(self) -> None:
        main = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        stories = (ROOT / "docs" / "stories" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="stories/"', main)
        self.assertNotIn('id: "bedtime"', main)
        # Both pages load the same shared script and stylesheet, with the same cache-busting version.
        main_v = re.search(r'<script src="site\.js\?v=(\w+)"></script>', main)
        story_v = re.search(r'<script src="\.\./site\.js\?v=(\w+)"></script>', stories)
        self.assertTrue(main_v and story_v)
        self.assertEqual(main_v.group(1), story_v.group(1))
        self.assertIn(f'href="site.css?v={main_v.group(1)}"', main)
        self.assertIn(f'href="../site.css?v={main_v.group(1)}"', stories)
        self.assertIn('data: "../episodes.json"', stories)
        self.assertIn("<h1>Once Upon a <span", stories)
        self.assertEqual([s["name"] for s in self.data["shows"]], [BUILD, STORY])


if __name__ == "__main__":
    unittest.main()
