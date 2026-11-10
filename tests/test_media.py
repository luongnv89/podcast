"""Tests for the episode audio on GitHub Releases (podcast #30).

publish.py uploads each MP3 as a release asset of its show/language media repo (through a
fake here: no gh, no network), feed.py and pages.py link the absolute URL, and ``--migrate-audio`` moves
the MP3s still in docs/. Standard library only (plus the fake in media_fake.py).
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from unittest import mock

from media_fake import FakeMedia

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publish = _load("publish")
feed = _load("feed")
pages = _load("pages")

EP = "2026-11-05_quiet-hours"
BUILDWIZ = "luongnv89/buildwiz-ai-show-media"
URL = f"https://github.com/{BUILDWIZ}/releases/download/{EP}/{EP}.mp3"
MP3 = b"ID3\x04fake audio bytes" * 10
SHA = hashlib.sha256(MP3).hexdigest()
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def make_job(job: Path, mp3: bytes = MP3, **run_extra) -> None:
    _write(job / "script.json", {"title": "Quiet hours", "format": "podcast-2host", "language": "en",
                                 "show": {"hosts": {"host_a": "Bob", "host_b": "Alice"}}})
    _write(job / "source.json", {"title": "Why cities want quiet", "author": "Jane Example",
                                 "url": "https://example.com/quiet"})
    _write(job / "job.json", {"steps": {"render": {"status": "done"}}})
    run = {"engine": "openrouter", "episode": "episode.mp3", "transcript": "transcript.vtt",
           "duration_s": 300, "finished": "2026-11-05T10:00:00Z", **run_extra}
    _write(job / "run.json", run)
    (job / "summary.txt").write_text("Line one.\nLine two.\nLine three.\n", encoding="utf-8")
    (job / "transcript.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (job / "episode.mp3").write_bytes(mp3)


class Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.site = self.tmp / "docs"
        self.site.mkdir()
        self.job = self.tmp / "jobs" / EP

    def tearDown(self) -> None:
        self._tmp.cleanup()


class MediaRepoTest(unittest.TestCase):
    STORY = "Once Upon a Time Show"

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("PODCAST_MEDIA_REPO_OVERRIDE", None)

    def test_one_repo_per_show_and_language(self) -> None:
        cases = {
            ("Build Wiz AI Show", "en"): BUILDWIZ,
            ("Build Wiz AI Show", "fr"): BUILDWIZ,
            ("Build Wiz AI Show", "vi"): BUILDWIZ,
            (self.STORY, "en"): "luongnv89/once-upon-a-time-en-media",
            (self.STORY, "fr"): "luongnv89/once-upon-a-time-fr-media",
            (self.STORY, "vi"): "luongnv89/once-upon-a-time-vi-media",
            (self.STORY, "FR-fr"): "luongnv89/once-upon-a-time-fr-media",
            (self.STORY, None): "luongnv89/once-upon-a-time-en-media",
            ("An unknown show", "de"): BUILDWIZ,  # anything else is Build Wiz AI Show
        }
        for (show, lang), repo in cases.items():
            with self.subTest(show=show, lang=lang):
                self.assertEqual(publish.media_repo(show, lang), (repo, None))
        self.assertEqual(len(set(publish.MEDIA_REPOS.values())), 4)

    def test_other_story_language_falls_back_with_a_note(self) -> None:
        repo, note = publish.media_repo(self.STORY, "de")
        self.assertEqual(repo, "luongnv89/once-upon-a-time-en-media")
        self.assertIn("'de'", note)

    def test_entry_routing_follows_the_format(self) -> None:
        self.assertEqual(publish.entry_media_repo({"format": "bedtime-story", "show": "Build Wiz AI Show",
                                                   "language": "vi"})[0], "luongnv89/once-upon-a-time-vi-media")
        self.assertEqual(publish.entry_media_repo({"show": "Build Wiz AI Show", "language": "fr"})[0], BUILDWIZ)

    def test_override_sends_everything_to_one_repo(self) -> None:
        os.environ["PODCAST_MEDIA_REPO_OVERRIDE"] = "someone/test-media"
        for show, lang in (("Build Wiz AI Show", "en"), (self.STORY, "fr"), (self.STORY, "de")):
            self.assertEqual(publish.media_repo(show, lang), ("someone/test-media", None))
        for bad in ("nope", "a/b/c", "../x", "a/b c"):
            with self.subTest(bad=bad):
                os.environ["PODCAST_MEDIA_REPO_OVERRIDE"] = bad
                with self.assertRaises(ValueError):
                    publish.media_repo("Build Wiz AI Show", "en")
        # The old variable name does nothing.
        os.environ.pop("PODCAST_MEDIA_REPO_OVERRIDE")
        os.environ["PODCAST_MEDIA_REPO"] = "someone/old"
        self.assertEqual(publish.media_repo("Build Wiz AI Show", "en")[0], BUILDWIZ)

    def test_asset_url_and_local_paths(self) -> None:
        self.assertEqual(publish.audio_url(BUILDWIZ, EP), URL)
        self.assertEqual(publish.local_audio_id(f"episodes/{EP}/episode.mp3"), EP)
        for other in (URL, "episodes/../x/episode.mp3", "episodes/a/other.mp3", None, 3):
            self.assertIsNone(publish.local_audio_id(other), other)
        with self.assertRaises(ValueError):
            publish.asset_name("../evil")


class GhCommandTest(Tmp):
    """GhMedia builds argument lists for gh (never a shell string)."""

    def test_commands(self) -> None:
        calls = []

        def fake_gh(*args, timeout=900):
            calls.append(list(args))
            if args[0] == "api":
                return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
            return subprocess.CompletedProcess(args, 0, "", "")

        mp3 = self.tmp / "x.mp3"
        mp3.write_bytes(MP3)
        with mock.patch.object(publish, "_gh", fake_gh):
            media = publish.GhMedia("luongnv89/buildwiz-ai-show-media")
            result = publish.upload_audio(media, EP, "Quiet hours", mp3, SHA)
        self.assertEqual(result, {"url": URL, "asset": f"{EP}.mp3", "uploaded": True})
        self.assertEqual(calls[0], ["api", f"repos/luongnv89/buildwiz-ai-show-media/releases/tags/{EP}"])
        self.assertEqual(calls[1], ["release", "create", EP, "-R", "luongnv89/buildwiz-ai-show-media", "--title", "Quiet hours",
                                    "--notes", f"Audio for https://luongnv.com/podcast/episodes/{EP}/"])
        self.assertEqual(calls[2][:2], ["release", "upload"])
        self.assertEqual(calls[2][2], EP)
        self.assertTrue(calls[2][3].endswith(f"/{EP}.mp3"))
        self.assertEqual(calls[2][4:], ["-R", "luongnv89/buildwiz-ai-show-media"])  # a new asset: no --clobber

    def test_gh_errors_are_upload_errors(self) -> None:
        def broken(*args, timeout=900):
            return subprocess.CompletedProcess(args, 1, "", "HTTP 502: Bad Gateway")

        with mock.patch.object(publish, "_gh", broken):
            with self.assertRaisesRegex(publish.UploadError, "could not read release"):
                publish.GhMedia("o/r").assets(EP)
            with self.assertRaisesRegex(publish.UploadError, "could not upload"):
                publish.GhMedia("o/r").upload(EP, self.tmp / "x.mp3")


class PublishUploadTest(Tmp):
    def test_upload_called_with_the_right_args(self) -> None:
        make_job(self.job)
        media = FakeMedia()
        entry, changed = publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.calls, [
            ("assets", EP),
            ("create_release", EP, "Quiet hours", f"Audio for https://luongnv.com/podcast/episodes/{EP}/"),
            ("upload", EP, f"{EP}.mp3", len(MP3), SHA),
        ])
        self.assertEqual(media.uploaded[f"{EP}/{EP}.mp3"], MP3)
        self.assertEqual(media.repos, [BUILDWIZ])
        # The entry: absolute release URL, the job file's size and SHA-256.
        self.assertEqual(entry["audio"], URL)
        self.assertEqual(entry["size_bytes"], len(MP3))
        self.assertEqual(entry["audio_sha256"], SHA)
        self.assertEqual(entry["transcript"], f"episodes/{EP}/transcript.vtt")
        # No MP3 in docs/; the transcript is copied as before.
        self.assertFalse(list(self.site.rglob("*.mp3")))
        self.assertTrue((self.site / "episodes" / EP / "transcript.vtt").is_file())
        self.assertIn(self.site / "episodes" / EP / "transcript.vtt", changed)

    def test_story_goes_to_its_language_repo(self) -> None:
        for lang, repo, noted in (("fr", "luongnv89/once-upon-a-time-fr-media", False),
                                  ("vi", "luongnv89/once-upon-a-time-vi-media", False),
                                  ("de", "luongnv89/once-upon-a-time-en-media", True)):
            with self.subTest(lang=lang):
                make_job(self.job)
                _write(self.job / "script.json", {"title": "Hansel", "format": "bedtime-story", "language": lang})
                media = FakeMedia()
                entry, _ = publish.episode_entry(self.job, self.site, media=media)
                self.assertEqual(media.repos, [repo])
                self.assertEqual(entry["audio"], f"https://github.com/{repo}/releases/download/{EP}/{EP}.mp3")
                self.assertEqual("_media_note" in entry, noted)

    def test_override_env_var(self) -> None:
        make_job(self.job)
        media = FakeMedia()
        with mock.patch.dict(os.environ, {"PODCAST_MEDIA_REPO_OVERRIDE": "someone/test-media"}):
            entry, _ = publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.repos, ["someone/test-media"])
        self.assertTrue(entry["audio"].startswith("https://github.com/someone/test-media/releases/download/"))

    def test_existing_release_is_not_created_again(self) -> None:
        make_job(self.job)
        media = FakeMedia(releases={EP: {f"{EP}.mp3": 1}})
        publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.names(), ["assets", "replace"])

    def test_skipped_when_the_recorded_sha_and_size_match(self) -> None:
        make_job(self.job)
        _write(self.site / "episodes.json", {"episodes": [{"id": EP, "audio": URL, "audio_sha256": SHA}]})
        media = FakeMedia(releases={EP: {f"{EP}.mp3": len(MP3)}})
        entry, _ = publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.names(), ["assets"])
        self.assertEqual((entry["audio"], entry["audio_sha256"]), (URL, SHA))

    def test_uploaded_when_sha_or_size_differ(self) -> None:
        make_job(self.job)
        cases = {
            "other sha": ("0" * 64, len(MP3)),
            "other size": (SHA, len(MP3) + 1),
            "no recorded sha": (None, len(MP3)),
        }
        for label, (recorded, size) in cases.items():
            with self.subTest(label):
                _write(self.site / "episodes.json", {"episodes": [{"id": EP, "audio": URL, "audio_sha256": recorded}]})
                media = FakeMedia(releases={EP: {f"{EP}.mp3": size}})
                publish.episode_entry(self.job, self.site, media=media)
                self.assertEqual(media.names(), ["assets", "replace"])

    def test_skip_checks_run_before_any_upload(self) -> None:
        make_job(self.job, private_use=True)
        media = FakeMedia()
        with self.assertRaises(publish.Skip):
            publish.episode_entry(self.job, self.site, media=media)
        make_job(self.job)
        _write(self.job / "request.json", {"publish": False})
        with self.assertRaises(publish.Skip):
            publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.calls, [])

    def test_stale_local_copy_is_left_to_main(self) -> None:
        make_job(self.job)
        stale = self.site / "episodes" / EP / "episode.mp3"
        _write(stale, "old bytes")
        entry, changed = publish.episode_entry(self.job, self.site, media=FakeMedia())
        self.assertTrue(stale.exists())
        self.assertNotIn(stale, changed)
        self.assertEqual(entry["audio"], URL)

    def run_main(self, media: FakeMedia, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.site))
            stack.enter_context(mock.patch.object(publish, "REPO", self.tmp))
            stack.enter_context(mock.patch.object(publish, "GhMedia", media))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_failed_upload_fails_the_job_and_keeps_the_index(self) -> None:
        make_job(self.job)
        index = {"version": 1, "episodes": [{"id": "older", "audio": "episodes/older/episode.mp3"}]}
        _write(self.site / "episodes.json", index)
        before = (self.site / "episodes.json").read_bytes()
        media = FakeMedia(fail=publish.UploadError("gh could not upload: HTTP 502"))
        code, report = self.run_main(media, str(self.job))
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"], [{"job": EP, "error": "gh could not upload: HTTP 502"}])
        self.assertEqual(report["published"], [])
        self.assertEqual((self.site / "episodes.json").read_bytes(), before)
        # Nothing half-written: not even the transcript was copied.
        self.assertFalse((self.site / "episodes" / EP).exists())

    def test_publish_writes_the_entry(self) -> None:
        make_job(self.job)
        code, report = self.run_main(FakeMedia(), str(self.job))
        self.assertEqual(code, 0, report)
        entry = json.loads((self.site / "episodes.json").read_text())["episodes"][0]
        self.assertEqual((entry["audio"], entry["size_bytes"], entry["audio_sha256"]), (URL, len(MP3), SHA))
        self.assertIn("docs/episodes.json", report["changed"])
        self.assertFalse([c for c in report["changed"] if c.endswith(".mp3")])


def site_with_local_audio(site: Path) -> dict:
    """An index with two episodes still in docs/ and one already moved."""
    episodes = []
    for n, ep_id in enumerate(("2026-11-01_a", "2026-11-02_b")):
        mp3 = site / "episodes" / ep_id / "episode.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(MP3 * (n + 1))
        episodes.append({"id": ep_id, "title": f"Episode {ep_id}", "show": "Build Wiz AI Show", "language": "en",
                         "format": "podcast-2host", "published": f"2026-11-0{n + 1}T10:00:00Z",
                         "duration_s": 60, "size_bytes": 1, "audio": f"episodes/{ep_id}/episode.mp3"})
    for ep_id, lang in (("2026-11-03_story-vi", "vi"), ("2026-11-03_story-de", "de")):
        mp3 = site / "episodes" / ep_id / "episode.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(MP3)
        episodes.append({"id": ep_id, "title": f"Story {lang}", "show": "Once Upon a Time Show", "language": lang,
                         "format": "bedtime-story", "published": "2026-11-03T10:00:00Z", "duration_s": 60,
                         "size_bytes": 1, "audio": f"episodes/{ep_id}/episode.mp3"})
    episodes.append({"id": EP, "title": "Moved", "audio": URL, "size_bytes": len(MP3), "audio_sha256": SHA})
    data = {"version": 1, "episodes": episodes}
    _write(site / "episodes.json", data)
    return data


class MigrateAudioTest(Tmp):
    def setUp(self) -> None:
        super().setUp()
        site_with_local_audio(self.site)
        self.removed: list[Path] = []

    def remove(self, path: Path) -> None:
        self.removed.append(path)
        path.unlink()

    def ok(self, url: str) -> dict:
        ep_id = url.rsplit("/", 1)[-1][:-4]
        return {"status": 200, "length": (self.site / "episodes" / ep_id / "episode.mp3").stat().st_size}

    def test_dry_run_lists_without_uploading(self) -> None:
        before = (self.site / "episodes.json").read_bytes()
        media = FakeMedia()
        report = publish.migrate_audio(self.site, media=media, verify=self.no_verify, remove=self.remove, dry_run=True)
        self.assertEqual(report["count"], 4)
        self.assertEqual(report["already_moved"], 1)
        self.assertEqual(report["total_bytes"], len(MP3) * 5)
        self.assertEqual([e["id"] for e in report["episodes"]],
                         ["2026-11-01_a", "2026-11-02_b", "2026-11-03_story-vi", "2026-11-03_story-de"])
        self.assertEqual(report["episodes"][0]["audio"],
                         "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/2026-11-01_a/2026-11-01_a.mp3")
        self.assertEqual([e["repo"] for e in report["episodes"][2:]],
                         ["luongnv89/once-upon-a-time-vi-media", "luongnv89/once-upon-a-time-en-media"])
        self.assertEqual(report["repos"], {
            BUILDWIZ: {"count": 2, "total_bytes": len(MP3) * 3},
            "luongnv89/once-upon-a-time-vi-media": {"count": 1, "total_bytes": len(MP3)},
            "luongnv89/once-upon-a-time-en-media": {"count": 1, "total_bytes": len(MP3)},
        })
        self.assertEqual(len(report["notes"]), 1)
        self.assertIn("2026-11-03_story-de", report["notes"][0])
        self.assertEqual(report["changed"], [])
        self.assertEqual(media.calls, [])
        self.assertEqual(self.removed, [])
        self.assertEqual((self.site / "episodes.json").read_bytes(), before)

    def no_verify(self, url: str) -> dict:  # a verify that must not be called
        raise AssertionError(f"verify called for {url}")

    def test_failed_verification_removes_nothing(self) -> None:
        before = (self.site / "episodes.json").read_bytes()
        media = FakeMedia()

        def wrong_length(url: str) -> dict:
            answer = self.ok(url)
            return dict(answer, length=answer["length"] - 1) if "2026-11-02_b" in url else answer

        for verify in (wrong_length, lambda url: {"status": 404, "length": None}):
            with self.subTest(verify=verify), self.assertRaisesRegex(publish.UploadError, "nothing removed"):
                publish.migrate_audio(self.site, media=media, verify=verify, remove=self.remove)
        self.assertEqual(self.removed, [])
        self.assertEqual((self.site / "episodes.json").read_bytes(), before)
        self.assertEqual(len(list(self.site.rglob("episode.mp3"))), 4)

    def test_failed_upload_verifies_and_removes_nothing(self) -> None:
        before = (self.site / "episodes.json").read_bytes()
        media = FakeMedia(fail=publish.UploadError("gh could not upload"))
        with self.assertRaises(publish.UploadError):
            publish.migrate_audio(self.site, media=media, verify=self.no_verify, remove=self.remove)
        self.assertEqual(self.removed, [])
        self.assertEqual((self.site / "episodes.json").read_bytes(), before)

    def test_migrates_then_changes_nothing_on_a_second_run(self) -> None:
        media = FakeMedia()
        checked: list[str] = []
        report = publish.migrate_audio(self.site, media=media, verify=lambda u: checked.append(u) or self.ok(u),
                                       remove=self.remove)
        self.assertEqual(report["count"], 4)
        self.assertEqual([c[0] for c in media.calls if c[0] == "upload"], ["upload"] * 4)
        self.assertEqual(media.repos, [BUILDWIZ, BUILDWIZ, "luongnv89/once-upon-a-time-vi-media",
                                       "luongnv89/once-upon-a-time-en-media"])
        self.assertEqual(len(checked), 4)
        data = json.loads((self.site / "episodes.json").read_text())
        a, b, vi, de, moved = data["episodes"]
        self.assertEqual(vi["audio"], "https://github.com/luongnv89/once-upon-a-time-vi-media/releases/download/"
                                      "2026-11-03_story-vi/2026-11-03_story-vi.mp3")
        self.assertTrue(de["audio"].startswith("https://github.com/luongnv89/once-upon-a-time-en-media/"))
        self.assertEqual(a["audio"], "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/2026-11-01_a/2026-11-01_a.mp3")
        self.assertEqual((a["size_bytes"], a["audio_sha256"]), (len(MP3), SHA))
        self.assertEqual(b["size_bytes"], len(MP3) * 2)
        self.assertEqual(b["audio_sha256"], hashlib.sha256(MP3 * 2).hexdigest())
        self.assertEqual(moved, {"id": EP, "title": "Moved", "audio": URL, "size_bytes": len(MP3), "audio_sha256": SHA})
        self.assertEqual(sorted(p.parent.name for p in self.removed),
                         ["2026-11-01_a", "2026-11-02_b", "2026-11-03_story-de", "2026-11-03_story-vi"])
        self.assertFalse(list(self.site.rglob("*.mp3")))
        # Idempotent: a second run uploads, checks, writes and removes nothing.
        after = (self.site / "episodes.json").read_bytes()
        media2 = FakeMedia()
        again = publish.migrate_audio(self.site, media=media2, verify=self.no_verify, remove=self.remove)
        self.assertEqual((again["count"], again["changed"], media2.calls), (0, [], []))
        self.assertEqual((self.site / "episodes.json").read_bytes(), after)
        self.assertEqual(len(self.removed), 4)

    def test_missing_local_file_is_an_error_before_any_upload(self) -> None:
        (self.site / "episodes" / "2026-11-02_b" / "episode.mp3").unlink()
        media = FakeMedia()
        with self.assertRaisesRegex(ValueError, "missing"):
            publish.migrate_audio(self.site, media=media, verify=self.no_verify, remove=self.remove)
        self.assertEqual(media.calls, [])

    def test_cli(self) -> None:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.site))
            stack.enter_context(mock.patch.object(publish, "REPO", self.tmp))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main(["--migrate-audio", "--dry-run"])
        report = json.loads(out.getvalue())
        self.assertEqual((code, report["count"], report["dry_run"], report["changed"]), (0, 4, True, []))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for argv in (["--dry-run"], ["--migrate-audio", "--dry-run", "--push"], ["--migrate-audio", "--all"],
                         ["--migrate-audio", "--backfill"], ["--migrate-audio", str(self.job)]):
                with self.subTest(argv=argv):
                    self.assertEqual(publish.main(argv), 2)


class FakeApi:
    """A stateful ``publish._gh`` for one release: assets with ids, upload, delete, rename."""

    def __init__(self, assets=None, fail=None, wrong_size=False):
        self.assets = [dict(a) for a in assets or []]
        self.next_id = 100
        self.fail = fail or set()
        self.wrong_size = wrong_size
        self.calls: list[list[str]] = []

    def __call__(self, *args, timeout=900):
        args = list(args)
        self.calls.append(args)
        ok = subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "api" and len(args) == 2:
            return subprocess.CompletedProcess(args, 0, json.dumps({"assets": self.assets}), "")
        if args[:2] == ["release", "upload"]:
            if "upload" in self.fail:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 502: upload failed")
            path = Path(args[3])
            size = path.stat().st_size + (1 if self.wrong_size else 0)
            self.assets.append({"id": self.next_id, "name": path.name, "size": size, "state": "uploaded"})
            self.next_id += 1
            return ok
        if args[:3] == ["api", "-X", "DELETE"]:
            if "delete" in self.fail:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 500")
            asset_id = int(args[3].rsplit("/", 1)[-1])
            self.assets = [a for a in self.assets if a["id"] != asset_id]
            return ok
        if args[:3] == ["api", "-X", "PATCH"]:
            if "rename" in self.fail:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 500: rename failed")
            asset_id = int(args[3].rsplit("/", 1)[-1])
            for a in self.assets:
                if a["id"] == asset_id:
                    a["name"] = args[5].split("=", 1)[1]
            return ok
        raise AssertionError(f"unexpected gh call {args}")

    def verbs(self) -> list[str]:
        return [c[2] if c[0] == "api" and len(c) > 2 else c[1] if c[0] == "release" else "read" for c in self.calls]


class GhReplaceTest(Tmp):
    """L2: a re-rendered episode replaces its asset under a staged name, never with --clobber."""

    REPO = "luongnv89/buildwiz-ai-show-media"

    def setUp(self) -> None:
        super().setUp()
        self.mp3 = self.tmp / "x.mp3"
        self.mp3.write_bytes(MP3 * 2)
        self.old = {"id": 1, "name": f"{EP}.mp3", "size": len(MP3), "state": "uploaded"}

    def publish_with(self, api: FakeApi) -> dict:
        with mock.patch.object(publish, "_gh", api):
            return publish.upload_audio(publish.GhMedia(self.REPO), EP, "Quiet hours", self.mp3,
                                        hashlib.sha256(MP3 * 2).hexdigest(), SHA)

    def test_staged_upload_then_delete_then_rename(self) -> None:
        api = FakeApi([self.old])
        self.assertEqual(self.publish_with(api)["uploaded"], True)
        self.assertEqual(api.verbs(), ["read", "read", "upload", "read", "DELETE", "PATCH"])
        upload = api.calls[2]
        self.assertTrue(upload[3].endswith(f"/{EP}.new.mp3"))
        self.assertNotIn("--clobber", upload)
        self.assertEqual(api.calls[4], ["api", "-X", "DELETE", f"repos/{self.REPO}/releases/assets/1"])
        self.assertEqual(api.calls[5], ["api", "-X", "PATCH", f"repos/{self.REPO}/releases/assets/100",
                                        "-f", f"name={EP}.mp3"])
        self.assertEqual(api.assets, [{"id": 100, "name": f"{EP}.mp3", "size": len(MP3) * 2, "state": "uploaded"}])
        self.assertEqual(publish.staged_name(f"{EP}.mp3"), f"{EP}.new.mp3")

    def test_failed_or_wrong_upload_keeps_the_live_asset(self) -> None:
        for api in (FakeApi([self.old], fail={"upload"}), FakeApi([self.old], wrong_size=True)):
            with self.subTest(api=api.fail or "wrong size"), self.assertRaises(publish.UploadError):
                self.publish_with(api)
            self.assertNotIn("DELETE", api.verbs())
            self.assertIn(self.old, api.assets)

    def test_failed_delete_keeps_the_live_asset(self) -> None:
        api = FakeApi([self.old], fail={"delete"})
        with self.assertRaisesRegex(publish.UploadError, "could not delete"):
            self.publish_with(api)
        self.assertIn(self.old, api.assets)

    def test_failed_rename_is_finished_by_a_rerun(self) -> None:
        api = FakeApi([self.old], fail={"rename"})
        with self.assertRaisesRegex(publish.UploadError, "run the publish again"):
            self.publish_with(api)
        self.assertEqual([a["name"] for a in api.assets], [f"{EP}.new.mp3"])
        api.fail = set()
        api.calls = []
        self.publish_with(api)
        # The leftover staged asset is deleted first, then the replacement goes through.
        self.assertEqual(api.verbs(), ["read", "read", "DELETE", "upload", "read", "PATCH"])
        self.assertEqual([(a["name"], a["size"]) for a in api.assets], [(f"{EP}.mp3", len(MP3) * 2)])


class AtomicIndexTest(Tmp):
    """L1: episodes.json is written to a temp file in its folder, then os.replace()d."""

    def test_keeps_the_mode_and_leaves_no_temp_file(self) -> None:
        path = self.site / "episodes.json"
        _write(path, {"episodes": []})
        path.chmod(0o640)
        publish._write_json(path, {"episodes": [{"id": "a"}]})
        self.assertEqual(json.loads(path.read_text())["episodes"], [{"id": "a"}])
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual([p.name for p in self.site.iterdir()], ["episodes.json"])

    def test_a_failed_write_keeps_the_old_index(self) -> None:
        path = self.site / "episodes.json"
        _write(path, {"episodes": [{"id": "old"}]})
        before = path.read_bytes()
        with mock.patch.object(publish.os, "replace", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            publish.update_index(self.site, [{"id": "new", "published": "2026-11-10"}])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([p.name for p in self.site.iterdir()], ["episodes.json"])

    def test_every_index_write_is_atomic(self) -> None:
        source = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
        self.assertNotIn("path.write_text(json.dumps", source)
        self.assertEqual(source.count("_write_json(path, data)"), 3)  # update_index, backfill, migrate


class StaleCopyTest(Tmp):
    """M3: a leftover docs/ MP3 goes only after the index update and a HEAD check."""

    def setUp(self) -> None:
        super().setUp()
        make_job(self.job)
        self.stale = self.site / "episodes" / EP / "episode.mp3"
        _write(self.stale, "old bytes")

    def run_main(self, verify) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.site))
            stack.enter_context(mock.patch.object(publish, "REPO", self.tmp))
            stack.enter_context(mock.patch.object(publish, "GhMedia", FakeMedia()))
            stack.enter_context(mock.patch.object(publish, "head_audio", verify))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main([str(self.job)])
        return code, json.loads(out.getvalue())

    def test_removed_after_the_index_and_a_good_head(self) -> None:
        checked = []
        code, report = self.run_main(lambda url: checked.append(url) or {"status": 200, "length": len(MP3)})
        self.assertEqual(code, 0, report)
        self.assertEqual(checked, [URL])
        self.assertFalse(self.stale.exists())
        self.assertIn(f"docs/episodes/{EP}/episode.mp3", report["changed"])
        self.assertEqual(json.loads((self.site / "episodes.json").read_text())["episodes"][0]["audio"], URL)

    def test_kept_when_head_fails(self) -> None:
        for answer in ({"status": 404, "length": None}, {"status": 200, "length": len(MP3) - 1}):
            with self.subTest(answer=answer):
                code, report = self.run_main(lambda url, a=answer: a)
                self.assertEqual(code, 0, report)
                self.assertTrue(self.stale.exists())
                self.assertNotIn(f"docs/episodes/{EP}/episode.mp3", report["changed"])
                self.assertTrue(any("kept the old" in n for n in report["notes"]))

    def test_kept_when_the_index_update_fails(self) -> None:
        def no_verify(url):
            raise AssertionError("verified before the index was written")

        with mock.patch.object(publish, "update_index", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            self.run_main(no_verify)
        self.assertTrue(self.stale.exists())

    def test_kept_when_the_rebuild_fails(self) -> None:
        # L-a: the copy goes only after a good rebuild, as in --migrate-audio.
        def no_verify(url):
            raise AssertionError("HEAD-checked (so maybe removed) before a good rebuild")

        for name, key in (("_rebuild_feeds", "feed_error"), ("_rebuild_pages", "pages_error")):
            with self.subTest(failing=name):
                def broken(report, site=None, key=key):
                    report[key] = "ValueError: bad template"
                    return []

                with mock.patch.object(publish, name, broken):
                    code, report = self.run_main(no_verify)
                self.assertEqual(code, 1)
                self.assertEqual(report["failed"][-1]["job"], "rebuild")
                self.assertIn("nothing pushed and no docs/ MP3 removed", report["failed"][-1]["error"])
                self.assertTrue(self.stale.exists())
                self.assertNotIn(f"docs/episodes/{EP}/episode.mp3", report["changed"])


CONFLICTED_INDEX = (
    '{"version": 1, "episodes": [\n'
    "<<<<<<< Updated upstream\n"
    '{"id": "older", "title": "Remote"}\n'
    "=======\n"
    '{"id": "older", "title": "Local"}\n'
    ">>>>>>> Stashed changes\n"
    "]}\n"
)


class UnreadableIndexTest(Tmp):
    """N1: an episodes.json that is there but cannot be parsed is never replaced by a new
    (one-episode) index; only a missing file starts one."""

    BROKEN: ClassVar[dict[str, str]] = {
        "conflict markers": CONFLICTED_INDEX,
        "truncated JSON": '{"version": 1, "episodes": [{"id": "older"',
        "no episodes list": '{"version": 1}',
        "not UTF-8": "\udcff",  # written with surrogateescape below: one invalid byte
    }

    def write_index(self, text: str) -> Path:
        path = self.site / "episodes.json"
        path.write_bytes(text.encode("utf-8", "surrogateescape"))
        return path

    def test_update_index_refuses_and_keeps_the_file(self) -> None:
        for name, text in self.BROKEN.items():
            with self.subTest(index=name):
                path = self.write_index(text)
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "episodes.json"):
                    publish.update_index(self.site, [{"id": EP, "published": "2026-11-05T10:00:00Z"}])
                self.assertEqual(path.read_bytes(), before)

    def test_conflict_markers_are_named(self) -> None:
        self.write_index(CONFLICTED_INDEX)
        with self.assertRaisesRegex(ValueError, "conflict markers"):
            publish.read_index(self.site / "episodes.json")

    def test_a_missing_index_still_starts_a_new_one(self) -> None:
        self.assertIsNone(publish.read_index(self.site / "episodes.json"))
        self.assertTrue(publish.update_index(self.site, [{"id": EP, "published": "2026-11-05T10:00:00Z"}]))
        self.assertEqual([e["id"] for e in publish.read_index(self.site / "episodes.json")["episodes"]], [EP])

    def test_publish_stops_before_any_upload(self) -> None:
        make_job(self.job)
        path = self.write_index(CONFLICTED_INDEX)
        media = FakeMedia()
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.site))
            stack.enter_context(mock.patch.object(publish, "REPO", self.tmp))
            stack.enter_context(mock.patch.object(publish, "GhMedia", media))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main([str(self.job)])
        report = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"][0]["job"], "episodes.json")
        self.assertIn("conflict markers", report["failed"][0]["error"])
        self.assertEqual((media.calls, report["published"]), ([], []))
        self.assertEqual(path.read_text(encoding="utf-8"), CONFLICTED_INDEX)
        self.assertFalse((self.site / "episodes" / EP).exists())

    def test_episode_entry_refuses_before_any_upload(self) -> None:
        make_job(self.job)
        self.write_index(CONFLICTED_INDEX)
        media = FakeMedia()
        with self.assertRaisesRegex(ValueError, "conflict markers"):
            publish.episode_entry(self.job, self.site, media=media)
        self.assertEqual(media.calls, [])

    def test_migrate_and_backfill_refuse(self) -> None:
        self.write_index('{"version": 1, "episodes": [')
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            publish.migrate_audio(self.site, media=FakeMedia(), dry_run=True)
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            publish.backfill(self.site, self.tmp / "jobs")


def _ok_for(site: Path):
    def ok(url: str) -> dict:
        ep_id = url.rsplit("/", 1)[-1][:-4]
        index = json.loads((site / "episodes.json").read_text())
        sizes = {e["id"]: e.get("size_bytes") for e in index["episodes"]}
        mp3 = site / "episodes" / ep_id / "episode.mp3"
        return {"status": 200, "length": mp3.stat().st_size if mp3.exists() else sizes[ep_id]}
    return ok


def _feed_urls(site: Path) -> list[str]:
    urls = []
    for meta in feed.FEEDS.values():
        path = site / meta["file"]
        if path.exists():
            urls += [e.get("url") for e in ET.parse(path).getroot().iter("enclosure")]
    return urls


class MigrationRecoveryTest(Tmp):
    """M1/M2: the rebuilt feeds are checked before anything is removed, and a run that stops
    half-way is finished by running it again."""

    def setUp(self) -> None:
        super().setUp()
        site_with_local_audio(self.site)
        publish._rebuild_site(self.site)  # feeds and pages of the pre-move site
        self.ok = _ok_for(self.site)

    def local_mp3s(self) -> list[str]:
        return sorted(p.parent.name for p in self.site.rglob("episode.mp3"))

    def test_failed_rebuild_removes_nothing(self) -> None:
        def broken(site):
            return [], {"feed_error": "ValueError: bad feed"}

        with self.assertRaisesRegex(publish.MigrationError, "nothing removed") as caught:
            publish.migrate_audio(self.site, media=FakeMedia(), verify=self.ok, remove=Path.unlink, rebuild=broken)
        self.assertEqual(caught.exception.report["feed_error"], "ValueError: bad feed")
        self.assertEqual(len(self.local_mp3s()), 4)

    def test_stale_feeds_remove_nothing(self) -> None:
        # A rebuild that "worked" but left the feeds on the docs/ copies.
        with self.assertRaisesRegex(publish.MigrationError, "do not use the release URLs") as caught:
            publish.migrate_audio(self.site, media=FakeMedia(), verify=self.ok, remove=Path.unlink,
                                  rebuild=lambda site: ([], {}))
        self.assertTrue(any("feed.xml" in p for p in caught.exception.report["release_problems"]))
        self.assertEqual(len(self.local_mp3s()), 4)
        # The next run sees the four leftovers, rebuilds for real and finishes.
        media = FakeMedia()
        report = publish.migrate_audio(self.site, media=media, verify=self.ok, remove=Path.unlink)
        self.assertEqual((report["count"], len(report["leftovers"]), media.calls), (0, 4, []))
        self.assertEqual(self.local_mp3s(), [])

    def test_third_removal_fails_then_a_rerun_finishes(self) -> None:
        removed = []

        def flaky(path: Path) -> None:
            if len(removed) == 2 and path.parent.name not in removed:
                removed.append("failed")
                raise OSError("git rm failed: index.lock exists")
            removed.append(path.parent.name)
            path.unlink()

        with self.assertRaisesRegex(publish.MigrationError, "1 local MP3") as caught:
            publish.migrate_audio(self.site, media=FakeMedia(), verify=self.ok, remove=flaky)
        report = caught.exception.report
        self.assertEqual(len(report["not_removed"]), 1)
        left = self.local_mp3s()
        self.assertEqual(len(left), 1)
        # Consistent in between: every entry is on its release URL and every feed says so.
        index = json.loads((self.site / "episodes.json").read_text())
        self.assertTrue(all(e["audio"].startswith("https://github.com/") for e in index["episodes"]))
        self.assertFalse([u for u in _feed_urls(self.site) if "/episodes/" in u and "github.com" not in u])
        # The re-run: no upload, a HEAD check of the leftover, then it goes.
        media, checked = FakeMedia(), []
        again = publish.migrate_audio(self.site, media=media, verify=lambda u: checked.append(u) or self.ok(u),
                                      remove=Path.unlink)
        self.assertEqual(media.calls, [])
        self.assertEqual([lo["id"] for lo in again["leftovers"]], left)
        self.assertEqual(len(checked), 1)
        self.assertEqual(self.local_mp3s(), [])
        # And a third run has nothing left to do.
        third = publish.migrate_audio(self.site, media=FakeMedia(), verify=self.no_verify, remove=Path.unlink)
        self.assertEqual((third["count"], third["leftovers"], third["changed"]), (0, [], []))

    def no_verify(self, url: str) -> dict:
        raise AssertionError(f"verify called for {url}")

    def test_leftover_not_matching_its_entry_is_kept(self) -> None:
        publish.migrate_audio(self.site, media=FakeMedia(), verify=self.ok, remove=Path.unlink)
        other = self.site / "episodes" / "2026-11-01_a" / "episode.mp3"
        other.write_bytes(b"another render")
        report = publish.migrate_audio(self.site, media=FakeMedia(), verify=self.no_verify, remove=Path.unlink)
        self.assertEqual(report["leftovers"], [])
        self.assertIn("2026-11-01_a", report["kept"][0])
        self.assertTrue(other.exists())

    def test_leftover_failing_head_is_kept(self) -> None:
        publish.migrate_audio(self.site, media=FakeMedia(), verify=self.ok, remove=Path.unlink)
        mp3 = self.site / "episodes" / "2026-11-01_a" / "episode.mp3"
        mp3.write_bytes(MP3)  # the uploaded bytes, back in docs/
        with self.assertRaisesRegex(publish.UploadError, "nothing removed"):
            publish.migrate_audio(self.site, media=FakeMedia(), verify=lambda u: {"status": 404, "length": None},
                                  remove=Path.unlink)
        self.assertTrue(mp3.exists())


def _git_in(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class MigrateCommandTest(Tmp):
    """The --migrate-audio --push command against a real (local) git repo and origin: it
    never pushes after a failure, and a re-run commits the whole move."""

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True)
        hooks = self.tmp / "no-hooks"
        hooks.mkdir()
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"),
                           ("core.hooksPath", str(hooks))):
            _git_in(self.work, "config", key, value)
        _git_in(self.work, "remote", "add", "origin", str(self.origin))
        self.wsite = self.work / "docs"
        site_with_local_audio(self.wsite)
        publish._rebuild_site(self.wsite)
        _git_in(self.work, "add", "-A")
        _git_in(self.work, "commit", "-q", "-m", "site before the move")
        _git_in(self.work, "push", "-q", "origin", "main")
        self.media = FakeMedia()

    def run_migrate(self, *argv: str, git_rm=None, git=None) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.wsite))
            stack.enter_context(mock.patch.object(publish, "REPO", self.work))
            stack.enter_context(mock.patch.object(publish, "GhMedia", self.media))
            stack.enter_context(mock.patch.object(publish, "head_audio", _ok_for(self.wsite)))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            if git_rm:
                stack.enter_context(mock.patch.object(publish, "_git_rm", git_rm))
            if git:
                stack.enter_context(mock.patch.object(publish, "_git", git))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main(["--migrate-audio", *argv])
        return code, json.loads(out.getvalue())

    def origin_head(self) -> str:
        return _git_in(self.origin, "rev-parse", "main").strip()

    def origin_files(self) -> list[str]:
        return _git_in(self.origin, "ls-tree", "-r", "--name-only", "main").split()

    def test_a_failed_rebuild_never_pushes(self) -> None:
        before = self.origin_head()

        def broken(report, site=None):
            report["feed_error"] = "ValueError: bad feed"
            return []

        with mock.patch.object(publish, "_rebuild_feeds", broken), \
                mock.patch.object(publish, "push", side_effect=AssertionError("pushed")):
            code, report = self.run_migrate("--push")
        self.assertEqual(code, 1)
        self.assertEqual(report["feed_error"], "ValueError: bad feed")
        self.assertIsNone(report["git"])
        self.assertEqual(self.origin_head(), before)
        self.assertEqual(len(list(self.wsite.rglob("episode.mp3"))), 4)

    def test_third_removal_fails_then_a_rerun_pushes_everything(self) -> None:
        before = self.origin_head()
        calls = []
        real_rm = publish._git_rm

        def flaky(path: Path) -> None:
            calls.append(path)
            if len(calls) == 3:
                raise OSError("git rm episode.mp3 failed: index.lock exists")
            real_rm(path)

        code, report = self.run_migrate("--push", git_rm=flaky)
        self.assertEqual(code, 1)
        self.assertIn("run --migrate-audio again", report["failed"][0]["error"])
        self.assertIsNone(report["git"])
        self.assertEqual(self.origin_head(), before)
        self.assertEqual(len(list(self.wsite.rglob("episode.mp3"))), 1)

        uploads = len(self.media.calls)
        code, report = self.run_migrate("--push")
        self.assertEqual(code, 0, report)
        self.assertEqual(len(self.media.calls), uploads)  # nothing uploaded again
        self.assertEqual((report["count"], len(report["leftovers"])), (0, 1))
        self.assertTrue(report["git"]["pushed"], report)
        self.assertNotEqual(self.origin_head(), before)
        files = self.origin_files()
        self.assertFalse([f for f in files if f.endswith(".mp3")])
        index = json.loads(_git_in(self.origin, "show", "main:docs/episodes.json"))
        self.assertTrue(all(e["audio"].startswith("https://github.com/") for e in index["episodes"]))
        feed_xml = _git_in(self.origin, "show", "main:docs/feed.xml")
        self.assertIn("https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/2026-11-01_a/", feed_xml)
        self.assertNotIn("episodes/2026-11-01_a/episode.mp3", feed_xml)
        self.assertEqual(_git_in(self.work, "status", "--porcelain"), "")
        # A third run: nothing to do, nothing pushed.
        head = self.origin_head()
        code, report = self.run_migrate("--push")
        self.assertEqual((code, report["count"], report["leftovers"], report["git"]), (0, 0, [], None))
        self.assertEqual(self.origin_head(), head)

    def test_failed_pull_stops_before_anything(self) -> None:
        def git(*args):
            if args[0] == "pull":
                return subprocess.CompletedProcess(args, 1, "", "error: cannot pull with rebase: conflict")
            if args[:2] == ("stash", "list"):  # read before the pull (N1)
                return subprocess.CompletedProcess(args, 0, "", "")
            raise AssertionError(f"git {args} after a failed pull")

        code, report = self.run_migrate("--push", git=git)
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"], [{"job": "git pull", "error": "error: cannot pull with rebase: conflict"}])
        self.assertEqual(self.media.calls, [])
        self.assertEqual(len(list(self.wsite.rglob("episode.mp3"))), 4)

    def test_conflicted_autostash_stops_before_anything(self) -> None:
        # N1: an interrupted run left episodes.json uncommitted, then a commit from another
        # checkout changed the same lines. `git pull --rebase --autostash` exits 0 here.
        index = self.wsite / "episodes.json"
        index.write_text(index.read_text().replace('"title": "Episode 2026-11-01_a"', '"title": "Local"'))
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True)
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"),
                           ("core.hooksPath", str(self.tmp / "no-hooks"))):
            _git_in(other, "config", key, value)
        theirs = other / "docs" / "episodes.json"
        theirs.write_text(theirs.read_text().replace('"title": "Episode 2026-11-01_a"', '"title": "Remote"'))
        _git_in(other, "commit", "-q", "-am", "retitle an episode")
        _git_in(other, "push", "-q", "origin", "main")
        remote_head = self.origin_head()
        stashes = _git_in(self.work, "stash", "list")

        with mock.patch.object(publish, "migrate_audio", side_effect=AssertionError("migrated")), \
                mock.patch.object(publish, "push", side_effect=AssertionError("pushed")):
            code, report = self.run_migrate("--push")
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"][0]["job"], "git pull")
        error = report["failed"][0]["error"]
        for words in ("autostash", "docs/episodes.json", "conflict markers", "Nothing was uploaded, pushed or removed",
                      "stash", "--migrate-audio --push again"):
            self.assertIn(words, error)
        self.assertIsNone(report["git"])
        self.assertEqual((self.media.calls, report["changed"]), ([], []))
        self.assertEqual(self.origin_head(), remote_head)
        self.assertEqual(len(list(self.wsite.rglob("episode.mp3"))), 4)
        # The run's own changes are still in the stash it names: nothing was dropped.
        left = _git_in(self.work, "stash", "list", "--format=%H").split()
        self.assertEqual(len(left), len(stashes.splitlines()) + 1)
        self.assertIn(left[0][:12], error)

        # A normal publish in this checkout now refuses the conflicted index instead of
        # rewriting it with only its own episode.
        make_job(self.job)
        conflicted = index.read_bytes()
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.wsite))
            stack.enter_context(mock.patch.object(publish, "REPO", self.work))
            stack.enter_context(mock.patch.object(publish, "GhMedia", self.media))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(mock.patch.object(publish, "push", side_effect=AssertionError("pushed")))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main([str(self.job), "--push"])
        self.assertEqual(code, 1)
        self.assertIn("conflict markers", json.loads(out.getvalue())["failed"][0]["error"])
        self.assertEqual(self.media.calls, [])
        self.assertEqual(index.read_bytes(), conflicted)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class PublishCommandTest(Tmp):
    """L-a: a normal publish --push against a real (local) git repo and origin. A failed
    rebuild keeps the old docs/ MP3 and pushes nothing; publishing again pushes it all."""

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True)
        hooks = self.tmp / "no-hooks"
        hooks.mkdir()
        for key, value in (("user.name", "Test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false"),
                           ("core.hooksPath", str(hooks))):
            _git_in(self.work, "config", key, value)
        _git_in(self.work, "remote", "add", "origin", str(self.origin))
        self.wsite = self.work / "docs"
        # The episode as published before the move: its MP3 in docs/.
        self.stale = self.wsite / "episodes" / EP / "episode.mp3"
        _write(self.stale, "old bytes")
        _write(self.wsite / "episodes.json", {"version": 1, "episodes": [{
            "id": EP, "title": "Quiet hours", "show": "Build Wiz AI Show", "language": "en",
            "format": "podcast-2host", "published": "2026-11-05T10:00:00Z", "duration_s": 300,
            "size_bytes": 9, "audio": f"episodes/{EP}/episode.mp3"}]})
        publish._rebuild_site(self.wsite)
        _git_in(self.work, "add", "-A")
        _git_in(self.work, "commit", "-q", "-m", "site before the move")
        _git_in(self.work, "push", "-q", "origin", "main")
        make_job(self.job)
        self.media = FakeMedia()

    def publish(self, verify) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.wsite))
            stack.enter_context(mock.patch.object(publish, "REPO", self.work))
            stack.enter_context(mock.patch.object(publish, "GhMedia", self.media))
            stack.enter_context(mock.patch.object(publish, "head_audio", verify))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main([str(self.job), "--push"])
        return code, json.loads(out.getvalue())

    def origin_head(self) -> str:
        return _git_in(self.origin, "rev-parse", "main").strip()

    def test_failed_rebuild_keeps_the_mp3_and_never_pushes_then_a_rerun_pushes_all(self) -> None:
        before = self.origin_head()

        def broken(report, site=None):
            report["pages_error"] = "ValueError: bad template"
            return []

        def no_verify(url):
            raise AssertionError("HEAD-checked before a good rebuild")

        with mock.patch.object(publish, "_rebuild_pages", broken), \
                mock.patch.object(publish, "push", side_effect=AssertionError("pushed")):
            code, report = self.publish(no_verify)
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"], [{
            "job": "rebuild",
            "error": "ValueError: bad template; nothing pushed and no docs/ MP3 removed: publish again"}])
        self.assertIsNone(report["git"])
        self.assertEqual(self.origin_head(), before)
        self.assertTrue(self.stale.exists())
        self.assertIn(f"episodes/{EP}/episode.mp3", _git_in(self.origin, "show", "main:docs/feed.xml"))

        # Publishing again: no second upload, the rebuild works, the copy goes, and the
        # commit holds what the failed run left uncommitted (the index, the transcript).
        uploads = [c for c in self.media.calls if c[0] in ("upload", "replace")]
        code, report = self.publish(lambda url: {"status": 200, "length": len(MP3)})
        self.assertEqual(code, 0, report)
        self.assertEqual([c for c in self.media.calls if c[0] in ("upload", "replace")], uploads)
        self.assertTrue(report["git"]["pushed"], report)
        self.assertFalse(self.stale.exists())
        files = _git_in(self.origin, "ls-tree", "-r", "--name-only", "main").split()
        self.assertFalse([f for f in files if f.endswith(".mp3")])
        self.assertIn(f"docs/episodes/{EP}/transcript.vtt", files)
        index = json.loads(_git_in(self.origin, "show", "main:docs/episodes.json"))
        self.assertEqual(index["episodes"][0]["audio"], URL)
        feed_xml = _git_in(self.origin, "show", "main:docs/feed.xml")
        self.assertIn(URL, feed_xml)
        self.assertNotIn(f"episodes/{EP}/episode.mp3", feed_xml)
        self.assertEqual(_git_in(self.work, "status", "--porcelain"), "")


class _Redirect(http.server.BaseHTTPRequestHandler):
    """/start redirects (302) to /file, which answers with a Content-Length (HEAD only)."""

    seen: ClassVar[list[tuple[str, str]]] = []

    def do_HEAD(self) -> None:
        type(self).seen.append((self.command, self.path))
        if self.path.startswith("/start"):
            self.send_response(302)
            self.send_header("Location", "/file?sig=1")
            self.send_header("Content-Length", "0")
        else:
            self.send_response(200)
            self.send_header("Content-Length", "1234")
        self.end_headers()

    def do_GET(self) -> None:
        type(self).seen.append((self.command, self.path))
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


class HeadAudioTest(unittest.TestCase):
    def test_redirects_are_followed_as_head(self) -> None:
        server = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _Redirect.seen = []
            got = publish.head_audio(f"http://127.0.0.1:{server.server_port}/start", timeout=10)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(got, {"status": 200, "length": 1234})
        self.assertEqual(_Redirect.seen, [("HEAD", "/start"), ("HEAD", "/file?sig=1")])


def podcast(audio: str, **extra) -> dict:
    entry = {"id": EP, "title": "Quiet hours", "show": "Build Wiz AI Show", "language": "en",
             "format": "podcast-2host", "published": "2026-11-05T10:00:00Z", "duration_s": 300,
             "size_bytes": len(MP3), "audio": audio, "description": "Hook.\n\nRest.",
             "source": {"title": "Why cities want quiet", "url": "https://example.com/quiet"}}
    entry.update(extra)
    return entry


class FeedAudioTest(Tmp):
    def item(self, ep: dict) -> ET.Element:
        xml = feed.render_feed({"episodes": [ep]}, "buildwiz", self.site, NOW)
        item = ET.fromstring(xml.encode("utf-8")).find("channel/item")
        assert item is not None
        return item

    def test_absolute_audio_and_version_from_sha(self) -> None:
        item = self.item(podcast(URL, audio_sha256=SHA))
        enclosure = item.find("enclosure")
        self.assertEqual(enclosure.get("url"), f"{URL}?v={SHA[:8]}")
        self.assertEqual(enclosure.get("length"), str(len(MP3)))
        self.assertEqual(enclosure.get("type"), "audio/mpeg")

    def test_version_and_guid_survive_the_move(self) -> None:
        local = self.site / "episodes" / EP / "episode.mp3"
        local.parent.mkdir(parents=True)
        local.write_bytes(MP3)
        before = self.item(podcast(f"episodes/{EP}/episode.mp3"))
        after = self.item(podcast(URL, audio_sha256=SHA))
        old_url = before.find("enclosure").get("url")
        self.assertEqual(old_url, f"https://luongnv.com/podcast/episodes/{EP}/episode.mp3?v={SHA[:8]}")
        self.assertEqual(after.find("enclosure").get("url").rsplit("?v=", 1)[1], old_url.rsplit("?v=", 1)[1])
        self.assertEqual(before.findtext("guid"), EP)
        self.assertEqual(after.findtext("guid"), before.findtext("guid"))
        self.assertEqual(after.find("guid").get("isPermaLink"), "false")
        self.assertEqual(after.find("enclosure").get("length"), before.find("enclosure").get("length"))

    def test_absolute_audio_without_sha_has_no_version(self) -> None:
        self.assertEqual(self.item(podcast(URL)).find("enclosure").get("url"), URL)
        bad = self.item(podcast(URL, audio_sha256="not-a-sha"))
        self.assertEqual(bad.find("enclosure").get("url"), URL)

    def test_relative_audio_unchanged(self) -> None:
        # No local file and no sha: BASE_URL + path, unversioned, as before.
        item = self.item(podcast(f"episodes/{EP}/episode.mp3"))
        self.assertEqual(item.find("enclosure").get("url"), f"https://luongnv.com/podcast/episodes/{EP}/episode.mp3")


class PagesAudioTest(Tmp):
    def test_absolute_audio_everywhere(self) -> None:
        ep = podcast(URL, audio_sha256=SHA, file_name="Build Wiz AI Show - Quiet hours (2026-11-05).mp3")
        html = pages.render_page(ep, [ep], self.site)
        self.assertIn(f'<audio controls preload="none" src="{URL}" aria-labelledby="title"></audio>', html)
        self.assertIn(f'<a class="btn" href="{URL}" download="Build Wiz AI Show - Quiet hours (2026-11-05).mp3">'
                      "Download MP3</a>", html)
        self.assertIn(f'<meta property="og:audio" content="{URL}">', html)
        ld = json.loads(re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', html, re.DOTALL).group(1))
        self.assertEqual(ld["associatedMedia"]["contentUrl"], URL)
        self.assertNotIn('"episode.mp3"', html)

    def test_relative_audio_keeps_the_old_output(self) -> None:
        ep = podcast(f"episodes/{EP}/episode.mp3")
        html = pages.render_page(ep, [ep], self.site)
        self.assertIn('<audio controls preload="none" src="episode.mp3" aria-labelledby="title"></audio>', html)
        self.assertIn(f'<a class="btn" href="episode.mp3" download="{EP}.mp3">Download MP3</a>', html)
        self.assertIn(f'<meta property="og:audio" content="https://luongnv.com/podcast/episodes/{EP}/episode.mp3">', html)
        # audio_sha256 alone changes nothing on a page.
        self.assertEqual(pages.render_page(dict(ep, audio_sha256=SHA), [ep], self.site), html)


class SiteAudioTest(unittest.TestCase):
    """site.js accepts the media repo's release URLs (and relative paths), nothing else."""

    def setUp(self) -> None:
        self.js = (ROOT / "docs" / "site.js").read_text(encoding="utf-8")

    def test_wiring(self) -> None:
        self.assertIn("const MEDIA_PATH = /^\\/luongnv89\\/(?:buildwiz-ai-show|once-upon-a-time-(?:en|fr|vi))"
                      "-media\\/releases\\/download\\/", self.js)
        self.assertIn('if (url.origin !== "https://github.com" || url.username || url.password) return null;', self.js)
        self.assertIn("e.audio = resolveAudio(e.audio);", self.js)
        self.assertIn("audio.src = ep.audio;", self.js)
        # L4: no playable audio, no Play button, and never audio.src = null.
        self.assertIn("if (!ep.audio) playBtn.hidden = true;", self.js)
        load = self.js[self.js.index("  function load(ep, at) {"):self.js.index("audio.src = ep.audio;")]
        self.assertIn("if (!ep || !ep.audio) return;", load)
        play = self.js[self.js.index("  function play(ep, at) {"):]
        self.assertIn("if (!ep || !ep.audio) return;", play[:200])
        # Download keeps its analytics event and download name.
        self.assertIn('if (ep.audio) actions.append(trackLink(el("a", { class: "btn", href: ep.audio, '
                      'download: fileName(ep) }', self.js)
        self.assertIn('"episode_download", ep));', self.js)
        self.assertIn('track("episode_play", epParams(current));', self.js)
        # site.js plays exactly the repos publish.py uploads to.
        prefix = re.compile(r"https://github\.com/luongnv89/(?:buildwiz-ai-show|once-upon-a-time-(?:en|fr|vi))-media/")
        for repo in publish.MEDIA_REPOS.values():
            self.assertTrue(prefix.match(f"https://github.com/{repo}/"), repo)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_resolve_audio_in_node(self) -> None:
        start = self.js.index("  const resolve = (path)")
        end = self.js.index("  if (!readUrl()) return;")
        script = (
            'const DATA_URL = new URL("https://luongnv.com/podcast/episodes.json");\n'
            + self.js[start:end]
            + """
console.log(JSON.stringify([
  "episodes/a/episode.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
  "https://github.com/luongnv89/once-upon-a-time-en-media/releases/download/a/a.mp3",
  "https://github.com/luongnv89/once-upon-a-time-fr-media/releases/download/a/a.mp3",
  "https://github.com/luongnv89/once-upon-a-time-vi-media/releases/download/a/a.mp3",
  "https://github.com/luongnv89/once-upon-a-time-de-media/releases/download/a/a.mp3",
  "https://github.com/luongnv89/podcast-media/releases/download/a/a.mp3",
  "https://github.com/someone/else/releases/download/a/a.mp3",
  "https://evil.example/a.mp3",
  "javascript:alert(1)",
  "data:audio/mpeg;base64,AAAA",
  "//evil.example/a.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/../../x",
  "",
  null,
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/%2e%2e/%2E%2E/x/a/a.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a%2fb/a.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a%2Fb/a.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/b.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3/x",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.wav",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/",
  "https://user:pw@github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
  "https://github.com:444/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
  "http://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
  "https://github.com\\\\luongnv89\\\\buildwiz-ai-show-media\\\\releases\\\\download\\\\a\\\\a.mp3",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3?x=1#t",
  "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/2026-11-05_quiet-hours/2026-11-05_quiet-hours.mp3",
].map(resolveAudio)));
"""
        )
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(out.stdout), [
            "https://luongnv.com/podcast/episodes/a/episode.mp3",
            "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
            "https://github.com/luongnv89/once-upon-a-time-en-media/releases/download/a/a.mp3",
            "https://github.com/luongnv89/once-upon-a-time-fr-media/releases/download/a/a.mp3",
            "https://github.com/luongnv89/once-upon-a-time-vi-media/releases/download/a/a.mp3",
            None, None, None, None, None, None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None,
            "https://github.com/luongnv89/buildwiz-ai-show-media/releases/download/a/a.mp3",
            f"https://github.com/{BUILDWIZ}/releases/download/{EP}/{EP}.mp3",
        ])


if __name__ == "__main__":
    unittest.main()
