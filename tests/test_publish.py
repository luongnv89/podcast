"""Tests for scripts/publish.py: the sources and guests of an episode entry.

Standard library only, no network: ``python3 -m unittest discover -s tests``.
Each test builds a fake delivered DropCast job and a fake site in a temp folder.
"""

from __future__ import annotations

import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
