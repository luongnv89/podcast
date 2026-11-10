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
from datetime import datetime, timezone
from pathlib import Path
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
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


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
        self.assertEqual(calls[2][4:], ["-R", "luongnv89/buildwiz-ai-show-media", "--clobber"])

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
        self.assertEqual(media.names(), ["assets", "upload"])

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
                self.assertEqual(media.names(), ["assets", "upload"])

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

    def test_stale_local_copy_is_removed(self) -> None:
        make_job(self.job)
        stale = self.site / "episodes" / EP / "episode.mp3"
        _write(stale, "old bytes")
        entry, changed = publish.episode_entry(self.job, self.site, media=FakeMedia())
        self.assertFalse(stale.exists())
        self.assertIn(stale, changed)
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


class _Redirect(http.server.BaseHTTPRequestHandler):
    """/start redirects (302) to /file, which answers with a Content-Length (HEAD only)."""

    seen: list[tuple[str, str]] = []

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
        self.assertIn("const MEDIA_PREFIX = /^https:\\/\\/github\\.com\\/luongnv89\\/(?:buildwiz-ai-show|once-upon-a-time-(?:en|fr|vi))"
                      "-media\\/releases\\/download\\//;", self.js)
        self.assertIn("e.audio = resolveAudio(e.audio);", self.js)
        self.assertIn("audio.src = ep.audio;", self.js)
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
        ])


if __name__ == "__main__":
    unittest.main()
