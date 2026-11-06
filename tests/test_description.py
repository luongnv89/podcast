"""Tests for the copy-paste description, the download name and the backfill (DropCast #163).

Standard library only, no network: ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
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

BUILD = "Build Wiz AI Show"
STORY = "Once Upon a Time Show"
CREDIT = (
    'Music by Kevin MacLeod (incompetech.com): "Music Box Theme". Licensed under Creative '
    "Commons: By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/"
)


def podcast(**extra) -> dict:
    entry = {
        "id": "2026-11-05_quiet-hours",
        "title": "Quiet hours: why cities want them back",
        "summary": [
            "Jane Example's article on why cities are bringing back quiet hours.",
            "Noise maps show the loudest streets and the hours that matter most.",
            "Why it matters: sleep, health and the cost of doing nothing.",
        ],
        "show": BUILD,
        "hosts": ["Bob", "Alice"],
        "language": "en",
        "format": "podcast-2host",
        "published": "2026-11-05T22:30:00Z",
        "duration_s": 610,
        "source": {"title": "WHY CITIES WANT QUIET.", "author": "JANE EXAMPLE (@janex)",
                   "url": "https://example.com/quiet"},
    }
    entry.update(extra)
    return entry


def story(**extra) -> dict:
    entry = podcast(
        id="2026-11-05_cinderella-fr", title="Cendrillon, une histoire du soir", show=STORY,
        format="bedtime-story", language="fr", hosts=[], duration_s=400, music_credit=CREDIT,
        summary=["Cendrillon, racontée tout en douceur, d'après Charles Perrault.",
                 "Une marraine fée, un carrosse-citrouille et une pantoufle de verre.",
                 "Une histoire qui finit par le pardon et un bonsoir tout calme."],
        source={"title": "Cinderella; or, The Little Glass Slipper", "author": None,
                "url": "https://example.org/cinderella"},
    )
    entry.update(extra)
    return entry


SHARED = json.loads((ROOT / "scripts" / "description_labels.json").read_text(encoding="utf-8"))


def check_layout(test: unittest.TestCase, text: str, show: str, music: bool, lang: str = "en") -> None:
    """The contract: hook / blank / In this episode + 2-4 bullets / blank / Sources,
    music (stories), last line = the show's last line (tagline + link) in ``lang``, all
    labels DropCast's in ``lang``; plain text, at most 600 characters."""
    names = SHARED["labels"][lang]
    test.assertLessEqual(len(text), 600)
    test.assertEqual(publish.description_problems(text), [])
    hook, middle, tail = text.split("\n\n")
    test.assertTrue(hook and "\n" not in hook)
    lines = middle.split("\n")
    test.assertEqual(lines[0], names["in_this_episode"])
    test.assertTrue(2 <= len(lines) - 1 <= 4)
    test.assertTrue(all(line.startswith("- ") for line in lines[1:]))
    tail_lines = tail.split("\n")
    test.assertTrue(tail_lines[0].startswith(names["sources"] + " "))
    test.assertEqual(any(line.startswith(names["music"] + " ") for line in tail_lines), music)
    test.assertEqual(tail_lines[-1], SHARED["shows"][show]["last_lines"][lang])


class FallbackDescriptionTest(unittest.TestCase):
    def test_podcast_layout(self) -> None:
        text = publish.fallback_description(podcast())
        check_layout(self, text, BUILD, music=False)
        self.assertIn("Bob and Alice unpack it in 10 minutes.", text)
        # An ALL-CAPS title and author are tidied; the trailing dot of the title goes.
        self.assertIn("Sources: Why Cities Want Quiet by Jane Example (@janex)", text)
        self.assertTrue(text.endswith("\nBig AI ideas, made clear for builders. luongnv.com/podcast"))

    def test_story_layout_and_music_credit(self) -> None:
        text = publish.fallback_description(story(language="en"))
        check_layout(self, text, STORY, music=True)
        self.assertIn("Music: Kevin MacLeod (incompetech.com), CC BY 4.0", text)
        self.assertIn("Sources: Cinderella; or, The Little Glass Slipper", text)

    def test_french_story_uses_dropcast_labels_and_last_line(self) -> None:
        text = publish.fallback_description(story())
        check_layout(self, text, STORY, music=True, lang="fr")
        self.assertIn("\n\nDans cet épisode :\n- ", text)
        self.assertIn("\n\nSources : Cinderella; or, The Little Glass Slipper\n", text)
        self.assertIn("\nMusique : Kevin MacLeod (incompetech.com), CC BY 4.0\n", text)
        self.assertTrue(text.endswith(
            "\nDe douces histoires pour le soir et l'heure du conte, racontées lentement par une "
            "voix chaleureuse. luongnv.com/podcast/stories"))
        for english in ("In this episode:", "Sources: ", "Music: ", "Once Upon a Time Show"):
            self.assertNotIn(english, text)

    def test_vietnamese_uses_dropcast_labels_and_last_line(self) -> None:
        text = publish.fallback_description(story(language="vi"))
        check_layout(self, text, STORY, music=True, lang="vi")
        self.assertIn("\n\nTrong tập này:\n- ", text)
        self.assertIn("\n\nNguồn: Cinderella", text)
        self.assertIn("\nNhạc: Kevin MacLeod", text)
        pod = publish.fallback_description(podcast(language="vi"))
        check_layout(self, pod, BUILD, music=False, lang="vi")
        self.assertIn("Nguồn: Why Cities Want Quiet của Jane Example (@janex)", pod)
        self.assertTrue(pod.endswith(
            "\nNhững ý tưởng lớn về AI, giải thích dễ hiểu cho người làm sản phẩm. luongnv.com/podcast"))

    def test_hook_keeps_two_sentences_by_dropping_bullets_first(self) -> None:
        # Four long points: dropping two of them is enough, so the hook keeps its
        # added sentence (two sentences) instead of falling back to one.
        point = "A point that takes quite a lot of words to say, " * 2 + "and ends here."
        entry = podcast(summary=["One hook sentence.", point, point, point, point])
        text = publish.fallback_description(entry)
        hook, middle, _ = text.split("\n\n")
        self.assertEqual(hook, "One hook sentence. Bob and Alice unpack it in 10 minutes.")
        self.assertLess(middle.count("\n- "), 4)
        self.assertGreaterEqual(middle.count("\n- "), 2)

    def test_solo_explainer_does_not_name_both_hosts(self) -> None:
        text = publish.fallback_description(podcast(format="solo-explainer"))
        self.assertNotIn("Bob and Alice", text)
        self.assertIn("Unpacked in 10 minutes.", text)

    def test_english_article(self) -> None:
        text = publish.fallback_description(story(language="en", duration_s=480))
        self.assertIn("An 8-minute listen", text)

    def test_long_entry_is_shortened_to_600(self) -> None:
        long = "word " * 60
        sources = [{"title": f"A long source title number {i} " * 3, "author": f"Author {i} (@a{i})",
                    "url": "https://example.com"} for i in range(8)]
        entry = podcast(summary=[long.strip() + ".", long.strip() + ".", long.strip() + ".",
                                 long.strip() + "."], sources=sources)
        text = publish.fallback_description(entry)
        self.assertLessEqual(len(text), 600)
        self.assertIn("In this episode:", text)
        self.assertTrue(text.endswith("luongnv.com/podcast"))

    def test_trims_sources_before_anything_else(self) -> None:
        sources = [{"title": "T" * 60, "author": f"Author {i} (@a{i})", "url": None} for i in range(4)]
        text = publish.fallback_description(podcast(sources=sources))
        self.assertIn("Sources: Author 0; Author 1; Author 2; Author 3", text)
        check_layout(self, text, BUILD, music=False)

    def test_no_summary(self) -> None:
        text = publish.fallback_description(podcast(summary=[]))
        self.assertTrue(text.startswith("Quiet hours: why cities want them back."))
        self.assertLessEqual(len(text), 600)

    def test_live_index_descriptions_follow_the_contract(self) -> None:
        data = json.loads((ROOT / "docs" / "episodes.json").read_text(encoding="utf-8"))
        for e in data["episodes"]:
            with self.subTest(id=e["id"]):
                show = STORY if e.get("format") in publish.STORY_FORMATS else BUILD
                check_layout(self, e["description"], show, music=bool(e.get("music_credit")),
                             lang=e.get("language") or "en")
                self.assertRegex(e["file_name"], r"^.+ - .+ \(\d{4}-\d{2}-\d{2}\)\.mp3$")
                self.assertTrue(e["file_name"].startswith(show + " - "))


class SharedLabelsTest(unittest.TestCase):
    def test_labels_file_is_loaded(self) -> None:
        self.assertEqual(publish.LABELS_FILE, ROOT / "scripts" / "description_labels.json")
        self.assertEqual(publish.LABELS, SHARED["labels"])
        self.assertEqual(publish.labels("fr"), {"in_this_episode": "Dans cet épisode :",
                                                "sources": "Sources :", "music": "Musique :"})
        self.assertEqual(publish.labels("vi"), {"in_this_episode": "Trong tập này:",
                                                "sources": "Nguồn:", "music": "Nhạc:"})
        self.assertEqual(publish.labels("de"), SHARED["labels"]["en"])
        for show, texts in SHARED["shows"].items():
            self.assertEqual(publish.SHOW_LINKS[show], texts["link"])
            for lang, line in texts["last_lines"].items():
                self.assertEqual(publish.last_line(show, lang), line)
                self.assertFalse(line.startswith(show))

    def test_bad_labels_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "description_labels.json"
            bad.write_text(json.dumps({"labels": {"fr": {}}, "shows": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                publish._load_labels(bad)


class DescriptionCheckTest(unittest.TestCase):
    def test_problems(self) -> None:
        self.assertEqual(publish.description_problems("Fine.\n\n- a point"), [])
        self.assertTrue(publish.description_problems("x" * 601))
        self.assertTrue(publish.description_problems(""))
        for bad in ("A <b>bold</b> move", "**bold**", "[link](https://x.y)", "# Title\nText"):
            with self.subTest(bad=bad):
                self.assertIn("contains Markdown or HTML", publish.description_problems(bad))

    def test_hook(self) -> None:
        self.assertEqual(publish.description_hook("One.\nTwo.\n\nIn this episode:\n- a"), "One. Two.")


class FileNameTest(unittest.TestCase):
    def test_issue_example(self) -> None:
        self.assertEqual(
            publish.episode_file_name(BUILD, "AI Roll-Ups: Buy a Boring Business, Run It with Agents", "2026-11-06"),
            "Build Wiz AI Show - AI Roll-Ups Buy a Boring Business, Run It with Agents (2026-11-06).mp3",
        )

    def test_unsafe_and_control_characters_dropped(self) -> None:
        name = publish.episode_file_name(BUILD, 'a/b\\c:d*e?f"g<h>i|j\tk\x00l  m', "2026-11-06")
        # as DropCast: control characters become spaces
        self.assertEqual(name, "Build Wiz AI Show - abcdefghij k l m (2026-11-06).mp3")

    def test_format_characters_dropped(self) -> None:
        # bidi overrides and zero-width characters cannot disguise the name
        name = publish.episode_file_name(BUILD, "a\u202egnp.exe\u200b now", "2026-11-06")
        self.assertEqual(name, "Build Wiz AI Show - agnp.exe now (2026-11-06).mp3")

    def test_byte_cap_keeps_the_title(self) -> None:
        # Same results as DropCast's delivery.episode_file_name (checked against it).
        for title in ("\u1edd" * 200, "\u6df1" * 120):
            name = publish.episode_file_name(BUILD, title, "2026-11-06")
            self.assertLessEqual(len(name.encode()), 250)
            self.assertRegex(name, r"^Build Wiz AI Show - .+ \(2026-11-06\)\.mp3$")
        self.assertEqual(
            len(publish.episode_file_name(BUILD, "\u1edd" * 200, "2026-11-06")),
            len("Build Wiz AI Show -  (2026-11-06).mp3") + 71,
        )

    def test_delivered_name_over_the_byte_cap_is_rebuilt(self) -> None:
        entry = {"show": BUILD, "title": "T", "published": "2026-11-06T08:00:00Z"}
        too_long = "Build Wiz AI Show - " + "\u6df1" * 120 + " (2026-11-06).mp3"
        self.assertEqual(publish.entry_file_name(entry, too_long), "Build Wiz AI Show - T (2026-11-06).mp3")

    def test_long_title_cut_at_a_word(self) -> None:
        name = publish.episode_file_name(BUILD, "word " * 60, "2026-11-06")
        stem = name[: -len(".mp3")]
        self.assertLessEqual(len(stem), 150)
        self.assertTrue(stem.endswith("word (2026-11-06)"))

    def test_paris_date(self) -> None:
        # 23:30 UTC on Nov 5 is already Nov 6 in Paris (UTC+1).
        self.assertEqual(publish.paris_date("2026-11-05T23:30:00Z"), "2026-11-06")
        self.assertEqual(publish.paris_date("2026-11-05T22:30:00Z"), "2026-11-05")
        self.assertIsNone(publish.paris_date(None))

    def test_delivered_name_wins_when_clean(self) -> None:
        entry = podcast()
        given = "Build Wiz AI Show - Quiet (2026-11-05).mp3"
        self.assertEqual(publish.entry_file_name(entry, given), given)
        rebuilt = "Build Wiz AI Show - Quiet hours why cities want them back (2026-11-05).mp3"
        for bad in ("../x.mp3", "x.wav", "", None, 5, "a" * 200 + ".mp3"):
            with self.subTest(bad=bad):
                self.assertEqual(publish.entry_file_name(entry, bad), rebuilt)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


class PublishDescriptionTest(unittest.TestCase):
    """publish.py copies ``description`` and ``file_name`` into each entry."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.site = self.tmp / "docs"
        self.job = self.tmp / "2026-11-05_quiet-hours"
        _write(self.job / "script.json", {"title": "Quiet hours", "format": "podcast-2host", "language": "en",
                                          "show": {"hosts": {"host_a": "Bob", "host_b": "Alice"}}})
        _write(self.job / "source.json", {"title": "Why cities want quiet", "author": "Jane Example",
                                          "url": "https://example.com/quiet"})
        _write(self.job / "job.json", {"steps": {"render": {"status": "done"}}})
        _write(self.job / "run.json", {"engine": "openrouter", "episode": "episode.mp3", "duration_s": 300,
                                       "finished": "2026-11-05T10:00:00Z"})
        (self.job / "summary.txt").write_text("Line one.\nLine two.\nLine three.\n", encoding="utf-8")
        (self.job / "episode.mp3").write_bytes(b"ID3fake")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def entry(self) -> dict:
        entry, _ = publish.episode_entry(self.job, self.site)
        return entry

    def test_fallback_and_rebuilt_name(self) -> None:
        entry = self.entry()
        check_layout(self, entry["description"], BUILD, music=False)
        self.assertTrue(entry["description"].startswith("Line one. Bob and Alice unpack it in 5 minutes."))
        self.assertEqual(entry["file_name"], "Build Wiz AI Show - Quiet hours (2026-11-05).mp3")
        self.assertNotIn("_description_problems", entry)

    def test_description_txt_wins(self) -> None:
        text = "Hook one. Hook two.\n\nIn this episode:\n- a\n- b\n\nSources: Jane Example\nBuild Wiz AI Show: x luongnv.com/podcast"
        (self.job / "description.txt").write_text(text + "\n\n", encoding="utf-8")
        self.assertEqual(self.entry()["description"], text)

    def test_bad_description_txt_falls_back_with_a_note(self) -> None:
        (self.job / "description.txt").write_text("x" * 700, encoding="utf-8")
        entry = self.entry()
        self.assertLessEqual(len(entry["description"]), 600)
        self.assertTrue(entry["_description_problems"])

    def test_hand_fixed_description_survives_a_republish(self) -> None:
        _write(self.site / "episodes.json", {"episodes": [{"id": self.job.name, "description": "Hand fixed."}]})
        self.assertEqual(self.entry()["description"], "Hand fixed.")

    def test_delivered_file_name(self) -> None:
        run = json.loads((self.job / "run.json").read_text(encoding="utf-8"))
        run["delivery"] = {"file_name": "Build Wiz AI Show - Quiet hours (2026-11-06).mp3"}
        _write(self.job / "run.json", run)
        self.assertEqual(self.entry()["file_name"], "Build Wiz AI Show - Quiet hours (2026-11-06).mp3")

    def test_backfill_fills_only_missing(self) -> None:
        old = podcast(id="old-episode")
        done = podcast(id="done", description="Kept.", file_name="Kept.mp3")
        _write(self.site / "episodes.json", {"version": 1, "episodes": [old, done]})
        changed, filled = publish.backfill(self.site, self.tmp / "no-jobs")
        self.assertTrue(changed)
        self.assertEqual([f["id"] for f in filled], ["old-episode"])
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))["episodes"]
        check_layout(self, saved[0]["description"], BUILD, music=False)
        self.assertEqual(saved[0]["file_name"], "Build Wiz AI Show - Quiet hours why cities want them back (2026-11-05).mp3")
        self.assertEqual((saved[1]["description"], saved[1]["file_name"]), ("Kept.", "Kept.mp3"))
        self.assertEqual(publish.backfill(self.site, self.tmp / "no-jobs"), (False, []))

    def test_backfill_reads_a_job_description(self) -> None:
        _write(self.site / "episodes.json", {"version": 1, "episodes": [podcast(id=self.job.name)]})
        (self.job / "description.txt").write_text("Written by Echo.", encoding="utf-8")
        _, filled = publish.backfill(self.site, self.tmp)
        self.assertEqual(filled[0]["description"], "description.txt")
        saved = json.loads((self.site / "episodes.json").read_text(encoding="utf-8"))["episodes"]
        self.assertEqual(saved[0]["description"], "Written by Echo.")

    def test_backfill_usage_errors(self) -> None:
        for argv in (["--backfill", "--all"], ["--backfill", str(self.job)],
                     ["--backfill", "--category", "ai"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(publish.main(argv), 2)


class SiteScriptTest(unittest.TestCase):
    """Static checks of the site's copy button and download name (behaviour: browser)."""

    def setUp(self) -> None:
        self.js = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")

    def test_copy_button_and_download_name(self) -> None:
        self.assertIn("Copy description", self.js)
        self.assertIn('track("description_copy", epParams(ep))', self.js)
        self.assertIn("navigator.clipboard.writeText(text)", self.js)
        self.assertIn('document.execCommand("copy")', self.js)
        self.assertIn("download: fileName(ep)", self.js)
        self.assertNotIn("download: `${ep.id}.mp3`", self.js)
        self.assertRegex(self.js, r"return n \|\| `\$\{ep\.id\}\.mp3`")

    def test_titles_link_to_the_episode_pages(self) -> None:
        self.assertIn('el("a", { class: "ep-toggle", href: pageOf(ep)', self.js)
        self.assertTrue(re.search(r"new URL\(`episodes/\$\{encodeURIComponent\(ep\.id\)\}/`, DATA_URL\)", self.js))


if __name__ == "__main__":
    unittest.main()
