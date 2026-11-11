"""Tests for the episode audio on the media repos' GitHub Pages sites (podcast #33).

publish.py puts each MP3 in its media repo's checkout, commits and pushes it (here: local
bare repos, never GitHub), waits until the Pages URL serves it as audio (a fake web here:
no network), and ``--repoint-audio`` moves the entries still on GitHub Release asset URLs.
Standard library only (plus the fakes in media_fake.py).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from media_fake import FakePagesMedia, FakeWeb, site_url

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
STORIES_FR = "luongnv89/once-upon-a-time-fr-media"
PAGES_URL = f"https://luongnv.com/buildwiz-ai-show-media/{EP}.mp3"
RELEASE_URL = f"https://github.com/{BUILDWIZ}/releases/download/{EP}/{EP}.mp3"
MP3 = b"ID3\x04fake audio bytes" * 10
SHA = hashlib.sha256(MP3).hexdigest()
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
# A git identity and no signing or hooks for the commits PagesMedia makes in its clones.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.hooksPath", "GIT_CONFIG_VALUE_1": "/dev/null",
}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def _git_in(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def make_job(job: Path, mp3: bytes = MP3, **script_extra) -> None:
    _write(job / "script.json", {"title": "Quiet hours", "format": "podcast-2host", "language": "en",
                                 "show": {"hosts": {"host_a": "Bob", "host_b": "Alice"}}, **script_extra})
    _write(job / "source.json", {"title": "Why cities want quiet", "author": "Jane Example",
                                 "url": "https://example.com/quiet"})
    _write(job / "job.json", {"steps": {"render": {"status": "done"}}})
    _write(job / "run.json", {"engine": "openrouter", "episode": "episode.mp3", "transcript": "transcript.vtt",
                              "duration_s": 300, "finished": "2026-11-05T10:00:00Z"})
    (job / "summary.txt").write_text("Line one.\nLine two.\n", encoding="utf-8")
    (job / "transcript.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (job / "episode.mp3").write_bytes(mp3)


class Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.site = self.tmp / "docs"
        self.site.mkdir()
        self.job = self.tmp / "jobs" / EP
        env = mock.patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("PODCAST_MEDIA_REPO_OVERRIDE", None)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class VerifyRuleTest(unittest.TestCase):
    """Only an answer a browser plays counts: 200, the right length, an MP3 content type."""

    def test_audio_types_pass(self) -> None:
        for type_ in ("audio/mpeg", "audio/mp3", "audio/MPEG", "audio/mpeg; charset=binary", " audio/mp3 "):
            with self.subTest(type_=type_):
                self.assertTrue(publish._verified({"status": 200, "length": 9, "type": type_}, 9))

    def test_everything_else_fails(self) -> None:
        for answer in (
            {"status": 200, "length": 9, "type": "application/octet-stream"},  # a release asset
            {"status": 200, "length": 9, "type": "audio/mpegurl"},
            {"status": 200, "length": 9, "type": "text/html"},
            {"status": 200, "length": 9, "type": None},
            {"status": 200, "length": 9},
            {"status": 200, "length": 8, "type": "audio/mpeg"},
            {"status": 404, "length": 9, "type": "audio/mpeg"},
            {"status": None, "length": None, "type": None, "error": "URLError"},
        ):
            with self.subTest(answer=answer):
                self.assertFalse(publish._verified(answer, 9))
        self.assertFalse(publish._verified({"status": 200, "length": 9, "type": "audio/mpeg"}, None))


class Clock:
    """A fake monotonic clock that ``sleep`` moves forward."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class WaitTest(unittest.TestCase):
    """The bounded wait for a Pages deploy."""

    def test_returns_as_soon_as_the_url_is_live(self) -> None:
        web, clock = FakeWeb(), Clock()
        web.serve(PAGES_URL, len(MP3), after=3)  # the deploy finishes after three checks
        answer = publish.wait_until_live(PAGES_URL, len(MP3), web, 600, 15, clock.sleep, clock)
        self.assertEqual(answer, {"status": 200, "type": "audio/mp3", "length": len(MP3)})
        self.assertEqual(len(web.calls), 4)
        self.assertEqual(clock.slept, [15, 15, 15])

    def test_live_at_once_never_sleeps(self) -> None:
        web, clock = FakeWeb(), Clock()
        web.serve(PAGES_URL, len(MP3), "audio/mpeg")
        publish.wait_until_live(PAGES_URL, len(MP3), web, 600, 15, clock.sleep, clock)
        self.assertEqual((len(web.calls), clock.slept), (1, []))

    def test_gives_up_after_the_wait(self) -> None:
        web, clock = FakeWeb(), Clock()
        with self.assertRaises(publish.UploadError) as caught:
            publish.wait_until_live(PAGES_URL, len(MP3), web, 600, 15, clock.sleep, clock)
        self.assertEqual(clock.now - 1000.0, 600)  # never longer than the wait
        self.assertEqual(len(web.calls), 41)  # at 0, 15, ..., 600 s
        message = str(caught.exception)
        for words in (PAGES_URL, "not live after 600 s and 41 check(s)", "status 404",
                      "nothing was changed in the podcast repo", "run the same command again"):
            self.assertIn(words, message)

    def test_an_octet_stream_url_is_rejected(self) -> None:
        # What GitHub serves for a release asset: right status and length, wrong type.
        web, clock = FakeWeb(), Clock()
        web.serve(RELEASE_URL, len(MP3), "application/octet-stream")
        with self.assertRaisesRegex(publish.UploadError, "type application/octet-stream"):
            publish.wait_until_live(RELEASE_URL, len(MP3), web, 30, 15, clock.sleep, clock)
        self.assertEqual(len(web.calls), 3)

    def test_the_wait_comes_from_the_environment(self) -> None:
        web, clock = FakeWeb(), Clock()
        for value, expected in (("45", 45), ("0", 0), ("not a number", 600), ("", 600)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"PODCAST_MEDIA_WAIT": value}):
                start = clock.now
                with self.assertRaises(publish.UploadError):
                    publish.wait_until_live(PAGES_URL, 1, web, None, 15, clock.sleep, clock)
                self.assertEqual(clock.now - start, expected)


class UrlTest(Tmp):
    def test_pages_and_release_urls(self) -> None:
        self.assertEqual(publish.pages_url(BUILDWIZ, EP), PAGES_URL)
        self.assertEqual(publish.pages_url(STORIES_FR, "2026-11-04_the-golden-touch-fr"),
                         "https://luongnv.com/once-upon-a-time-fr-media/2026-11-04_the-golden-touch-fr.mp3")
        self.assertEqual(publish.pages_url("Someone/test-media", EP), f"https://someone.github.io/test-media/{EP}.mp3")
        for repo in publish.MEDIA_REPOS.values():
            self.assertEqual(publish.pages_audio(publish.pages_url(repo, EP)), (repo, EP))
            self.assertEqual(publish.release_audio(publish.audio_url(repo, EP)), (repo, EP))
            self.assertIsNone(publish.pages_audio(publish.audio_url(repo, EP)))
            self.assertIsNone(publish.release_audio(publish.pages_url(repo, EP)))
        self.assertEqual(publish.pages_audio(f"https://someone.github.io/test-media/{EP}.mp3"),
                         ("someone/test-media", EP))
        for bad in (f"https://github.com/{BUILDWIZ}/releases/download/a/b.mp3", "https://luongnv.com/x/../a.mp3",
                    f"https://luongnv.com/a/b/{EP}.mp3", f"episodes/{EP}/episode.mp3", None, 3):
            self.assertIsNone(publish.release_audio(bad), bad)
            self.assertIsNone(publish.pages_audio(bad), bad)
        with self.assertRaises(ValueError):
            publish.pages_url(BUILDWIZ, "../evil")

    def test_checkouts_folder_and_remote(self) -> None:
        with mock.patch.dict(os.environ, {"PODCAST_MEDIA_CHECKOUTS": str(self.tmp / "media")}):
            media = publish.PagesMedia(BUILDWIZ)
        self.assertEqual(media.path, self.tmp / "media" / "buildwiz-ai-show-media")
        self.assertEqual(media.remote, "git@github.com:luongnv89/buildwiz-ai-show-media.git")
        self.assertEqual(media.url(EP), PAGES_URL)
        with mock.patch.dict(os.environ, {"PODCAST_MEDIA_CHECKOUTS": ""}):
            self.assertEqual(publish.media_checkouts(), Path("~/workspace/media").expanduser())
        self.assertIs(publish.MEDIA_BACKEND, publish.PagesMedia)  # the default backend
        with self.assertRaises(ValueError):
            publish.PagesMedia("../x")


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class PagesMediaTest(Tmp):
    """PagesMedia against local bare repos standing for the media repos on GitHub."""

    def setUp(self) -> None:
        super().setUp()
        self.origins = self.tmp / "origins"
        self.checkouts = self.tmp / "media"
        self.web = FakeWeb()
        self.clock = Clock()
        self.mp3 = self.tmp / "episode.mp3"
        self.mp3.write_bytes(MP3)
        for repo in (BUILDWIZ, STORIES_FR, "someone/test-media"):
            self.make_origin(repo)

    def make_origin(self, repo: str) -> Path:
        """A bare repo holding what the real media repos hold: a README and .nojekyll."""
        origin = self.remote(repo)
        seed = self.tmp / "seed" / repo
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        _write(seed / "README.md", "media\n")
        _write(seed / ".nojekyll", "")
        _git_in(seed, "add", "-A")
        _git_in(seed, "commit", "-q", "-m", "docs: add README")
        _git_in(seed, "push", "-q", str(origin), "main")
        return origin

    def remote(self, repo: str) -> str:
        return str(self.origins / f"{repo}.git")

    def media(self, repo: str = BUILDWIZ, **kw) -> publish.PagesMedia:
        """PagesMedia whose pushes "deploy": the fake web serves what origin main holds."""
        options = dict(root=self.checkouts, remote=self.remote, verify=self.deployed, wait=60,
                       sleep=self.clock.sleep, clock=self.clock)
        options.update(kw)
        return publish.PagesMedia(repo, **options)

    def deployed(self, url: str) -> dict:
        """HEAD of a media site URL: the file on origin main, served as GitHub Pages does."""
        self.web.calls.append(url)
        repo, ep_id = publish.pages_audio(url)
        proc = subprocess.run(["git", "--git-dir", self.remote(repo), "cat-file", "-s", f"main:{ep_id}.mp3"],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return {"status": 404, "type": "text/html", "length": None}
        return {"status": 200, "type": "audio/mp3", "length": int(proc.stdout)}

    def origin_log(self, repo: str = BUILDWIZ) -> list[str]:
        return _git_in(Path(self.remote(repo)), "log", "--format=%s", "main").split("\n")[:-1]

    def origin_file(self, name: str, repo: str = BUILDWIZ) -> bytes:
        return subprocess.run(["git", "--git-dir", self.remote(repo), "show", f"main:{name}"], capture_output=True,
                              check=True).stdout

    def test_clones_commits_pushes_and_waits(self) -> None:
        result = self.media().publish(EP, self.mp3, SHA)
        self.assertEqual(result["url"], PAGES_URL)
        self.assertTrue(result["uploaded"])
        checkout = self.checkouts / "buildwiz-ai-show-media"
        self.assertEqual(_git_in(checkout, "remote", "get-url", "origin").strip(), self.remote(BUILDWIZ))
        self.assertEqual(self.origin_log(), [f"feat: add {EP}", "docs: add README"])
        self.assertEqual(self.origin_file(f"{EP}.mp3"), MP3)
        self.assertEqual(result["commit"], _git_in(Path(self.remote(BUILDWIZ)), "rev-parse", "main").strip())
        self.assertEqual(self.web.calls, [PAGES_URL])
        self.assertEqual(_git_in(checkout, "status", "--porcelain"), "")
        self.assertEqual(sorted(p.name for p in checkout.iterdir()), [".git", ".nojekyll", f"{EP}.mp3", "README.md"])

    def test_same_bytes_again_is_a_no_op(self) -> None:
        self.media().publish(EP, self.mp3, SHA)
        head = _git_in(Path(self.remote(BUILDWIZ)), "rev-parse", "main")
        again = self.media().publish(EP, self.mp3, SHA)
        self.assertEqual((again["uploaded"], again["commit"]), (False, None))
        self.assertEqual(_git_in(Path(self.remote(BUILDWIZ)), "rev-parse", "main"), head)
        self.assertEqual(self.web.calls, [PAGES_URL, PAGES_URL])  # still checked before use

    def test_new_bytes_are_an_update(self) -> None:
        self.media().publish(EP, self.mp3, SHA)
        self.mp3.write_bytes(MP3 * 2)
        result = self.media().publish(EP, self.mp3, hashlib.sha256(MP3 * 2).hexdigest())
        self.assertTrue(result["uploaded"])
        self.assertEqual(self.origin_log()[0], f"feat: update {EP}")
        self.assertEqual(self.origin_file(f"{EP}.mp3"), MP3 * 2)

    def test_pulls_what_others_pushed_first(self) -> None:
        self.media().publish(EP, self.mp3, SHA)
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", self.remote(BUILDWIZ), str(other)], check=True)
        _write(other / "README.md", "changed elsewhere\n")
        _git_in(other, "commit", "-q", "-am", "docs: change README")
        _git_in(other, "push", "-q", "origin", "main")
        self.media().publish("2026-11-06_other", self.mp3, SHA)
        self.assertEqual(self.origin_log()[:2], ["feat: add 2026-11-06_other", "docs: change README"])

    def test_a_rejected_push_is_rebased_once(self) -> None:
        media = self.media()
        media.checkout()
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", self.remote(BUILDWIZ), str(other)], check=True)
        real = publish._run_git
        moved = []

        def git(cwd, *args, **kw):
            if args[:1] == ("push",) and not moved:  # origin moves between the pull and the push
                _write(other / "README.md", "changed elsewhere\n")
                _git_in(other, "commit", "-q", "-am", "docs: change README")
                _git_in(other, "push", "-q", "origin", "main")
                moved.append(True)
            return real(cwd, *args, **kw)

        with mock.patch.object(publish, "_run_git", git):
            result = media.publish(EP, self.mp3, SHA)
        self.assertTrue(result["uploaded"])
        self.assertEqual(self.origin_log(), [f"feat: add {EP}", "docs: change README", "docs: add README"])

    def test_a_lost_rebase_fails_cleanly_and_a_rerun_after_the_fix_pushes(self) -> None:
        media = self.media()
        media.checkout()
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", self.remote(BUILDWIZ), str(other)], check=True)
        real = publish._run_git
        moved = []

        def git(cwd, *args, **kw):
            if args[:1] == ("push",) and not moved:  # someone pushes other bytes as the same file
                (other / f"{EP}.mp3").write_bytes(b"other bytes")
                _git_in(other, "add", "-A")
                _git_in(other, "commit", "-q", "-m", f"feat: add {EP}")
                _git_in(other, "push", "-q", "origin", "main")
                moved.append(True)
            return real(cwd, *args, **kw)

        with mock.patch.object(publish, "_run_git", git), self.assertRaises(publish.UploadError) as caught:
            media.publish(EP, self.mp3, SHA)
        for words in ("git pull --rebase origin main failed", "nothing was pushed", "run the same command again"):
            self.assertIn(words, str(caught.exception))
        self.assertEqual(self.origin_file(f"{EP}.mp3"), b"other bytes")
        checkout = media.path
        self.assertFalse((checkout / ".git" / "rebase-merge").exists() or (checkout / ".git" / "rebase-apply").exists())
        self.assertEqual(_git_in(checkout, "log", "-1", "--format=%s").strip(), f"feat: add {EP}")  # kept
        self.assertEqual(self.web.calls, [])  # never verified, so never recorded
        # Resolved by hand (this run's bytes win), then the same publish pushes it.
        _git_in(checkout, "pull", "-q", "--rebase", "-X", "theirs", "origin", "main")
        result = self.media().publish(EP, self.mp3, SHA)
        self.assertTrue(result["uploaded"])
        self.assertEqual(self.origin_file(f"{EP}.mp3"), MP3)

    def test_an_earlier_unpushed_commit_is_pushed_by_the_next_run(self) -> None:
        real = publish._run_git

        def no_push(cwd, *args, **kw):
            if args[:1] == ("push",):
                return subprocess.CompletedProcess(args, 1, "", "fatal: the remote end hung up unexpectedly")
            return real(cwd, *args, **kw)

        with mock.patch.object(publish, "_run_git", no_push), self.assertRaisesRegex(publish.UploadError, "hung up"):
            self.media().publish(EP, self.mp3, SHA)
        self.assertEqual(self.origin_log(), ["docs: add README"])
        result = self.media().publish(EP, self.mp3, SHA)  # same bytes: no new commit, but a push
        self.assertEqual((result["uploaded"], result["commit"]), (True, None))
        self.assertEqual(self.origin_log(), [f"feat: add {EP}", "docs: add README"])

    def test_a_push_that_exits_0_without_reaching_origin_fails(self) -> None:
        real = publish._run_git

        def fake_push(cwd, *args, **kw):
            if args[:1] == ("push",):
                return subprocess.CompletedProcess(args, 0, "", "Everything up-to-date")
            return real(cwd, *args, **kw)

        with mock.patch.object(publish, "_run_git", fake_push), \
                self.assertRaisesRegex(publish.UploadError, "origin/main does not hold"):
            self.media().publish(EP, self.mp3, SHA)

    def test_never_live_fails_after_the_bounded_wait(self) -> None:
        media = self.media(verify=lambda url: {"status": 404, "type": "text/html", "length": None})
        with self.assertRaisesRegex(publish.UploadError, "not live after 60 s"):
            media.publish(EP, self.mp3, SHA)
        self.assertEqual(self.clock.now - 1000.0, 60)
        # The push happened: a re-run once the site has deployed only checks again.
        again = self.media().publish(EP, self.mp3, SHA)
        self.assertEqual((again["uploaded"], again["commit"]), (False, None))

    def test_served_as_octet_stream_is_rejected(self) -> None:
        media = self.media(verify=lambda url: {"status": 200, "type": "application/octet-stream", "length": len(MP3)})
        with self.assertRaisesRegex(publish.UploadError, "type application/octet-stream"):
            media.publish(EP, self.mp3, SHA)

    def test_refuses_a_checkout_of_another_repo_or_branch(self) -> None:
        # An override repo with the same name as a real one must not push through its checkout.
        self.media().checkout()
        with self.assertRaisesRegex(publish.UploadError, "has origin"):
            self.media(remote=lambda repo: str(self.origins / "elsewhere.git")).publish(EP, self.mp3, SHA)
        _git_in(self.media().path, "checkout", "-q", "-b", "experiment")
        with self.assertRaisesRegex(publish.UploadError, "not main"):
            self.media().publish(EP, self.mp3, SHA)
        plain = self.checkouts / "once-upon-a-time-fr-media"
        plain.mkdir()
        with self.assertRaisesRegex(publish.UploadError, "not a git checkout of its own"):
            self.media(STORIES_FR).publish(EP, self.mp3, SHA)
        self.assertEqual(self.origin_log(), ["docs: add README"])

    def test_a_failed_clone_is_an_upload_error(self) -> None:
        with self.assertRaisesRegex(publish.UploadError, "git clone"):
            self.media(remote=lambda repo: str(self.origins / "missing.git")).publish(EP, self.mp3, SHA)

    def test_default_remote_is_ssh_and_never_reached_in_tests(self) -> None:
        media = publish.PagesMedia(BUILDWIZ, root=self.tmp / "fresh")
        self.assertEqual(media.remote, "git@github.com:luongnv89/buildwiz-ai-show-media.git")
        # conftest refuses git naming github.com; under unittest GIT_SSH_COMMAND=false fails it.
        with self.assertRaises((OSError, publish.UploadError)):
            media.checkout()

    # A whole publish: the entry is written only once the URL serves the file.

    def episode(self, **kw) -> tuple[dict, list]:
        make_job(self.job)
        return publish.episode_entry(self.job, self.site, media=functools.partial(self.media_for, **kw))

    def media_for(self, repo: str, **kw) -> publish.PagesMedia:
        return self.media(repo, **kw)

    def test_publish_writes_the_pages_url(self) -> None:
        entry, changed = self.episode()
        self.assertEqual((entry["audio"], entry["size_bytes"], entry["audio_sha256"]), (PAGES_URL, len(MP3), SHA))
        self.assertEqual(self.origin_file(f"{EP}.mp3"), MP3)
        self.assertFalse(list(self.site.rglob("*.mp3")))
        self.assertIn(self.site / "episodes" / EP / "transcript.vtt", changed)

    def test_a_story_goes_to_its_language_site(self) -> None:
        make_job(self.job, format="bedtime-story", language="fr")
        entry, _ = publish.episode_entry(self.job, self.site, media=self.media_for)
        self.assertEqual(entry["audio"], f"https://luongnv.com/once-upon-a-time-fr-media/{EP}.mp3")
        self.assertEqual(self.origin_file(f"{EP}.mp3", STORIES_FR), MP3)

    def test_override_repo_keeps_working(self) -> None:
        make_job(self.job)
        with mock.patch.dict(os.environ, {"PODCAST_MEDIA_REPO_OVERRIDE": "someone/test-media"}):
            entry, _ = publish.episode_entry(self.job, self.site, media=self.media_for)
        self.assertEqual(entry["audio"], f"https://someone.github.io/test-media/{EP}.mp3")
        self.assertEqual(self.origin_file(f"{EP}.mp3", "someone/test-media"), MP3)
        self.assertEqual(self.origin_log(), ["docs: add README"])  # the real repo's stand-in is untouched

    def test_a_publish_that_never_goes_live_changes_nothing_in_the_site(self) -> None:
        _write(self.site / "episodes.json", {"version": 1, "episodes": []})
        before = (self.site / "episodes.json").read_bytes()
        make_job(self.job)
        out = io.StringIO()
        factory = functools.partial(self.media_for, verify=lambda url: {"status": 404, "type": None, "length": None})
        with mock.patch.object(publish, "SITE", self.site), mock.patch.object(publish, "REPO", self.tmp), \
                mock.patch.object(publish, "MEDIA_BACKEND", factory), \
                mock.patch.object(publish, "_lock", contextlib.nullcontext), contextlib.redirect_stdout(out):
            code = publish.main([str(self.job)])
        report = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertIn("not live after 60 s", report["failed"][0]["error"])
        self.assertEqual((self.site / "episodes.json").read_bytes(), before)
        self.assertFalse((self.site / "episodes" / EP).exists())


# ---------- --repoint-audio ----------

EPISODES = (
    # id, show, language, format, repo
    ("2026-11-01_a", "Build Wiz AI Show", "en", "podcast-2host", BUILDWIZ),
    ("2026-11-02_b", "Build Wiz AI Show", "fr", "podcast-2host", BUILDWIZ),
    ("2026-11-03_story-fr", "Once Upon a Time Show", "fr", "bedtime-story", STORIES_FR),
)


def mp3_of(ep_id: str) -> bytes:
    return MP3 + ep_id.encode()


def site_on_releases(site: Path) -> dict:
    """An index as PR #31 left it: every entry on its release asset URL."""
    episodes = []
    for n, (ep_id, show, lang, fmt, repo) in enumerate(EPISODES):
        data = mp3_of(ep_id)
        episodes.append({
            "id": ep_id, "title": f"Episode {ep_id}", "summary": ["One.", "Two."], "show": show, "language": lang,
            "format": fmt, "published": f"2026-11-0{n + 1}T10:00:00Z", "duration_s": 60, "size_bytes": len(data),
            "audio": f"https://github.com/{repo}/releases/download/{ep_id}/{ep_id}.mp3",
            "audio_sha256": hashlib.sha256(data).hexdigest(), "description": "Hook.\n\nRest.",
            "source": {"title": "A source", "url": "https://example.com/a"},
        })
    data = {"version": 1, "episodes": episodes}
    _write(site / "episodes.json", data)
    publish._rebuild_site(site)
    return data


def _enclosures(site: Path) -> dict[str, tuple]:
    """guid -> (enclosure url, length, type) over every feed."""
    found = {}
    for meta in feed.FEEDS.values():
        path = site / meta["file"]
        if path.exists():
            for item in ET.parse(path).getroot().iter("item"):
                enc = item.find("enclosure")
                found[item.findtext("guid")] = (enc.get("url"), enc.get("length"), enc.get("type"))
    return found


def _site_text(site: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(site.rglob("*")) if p.suffix in (".xml", ".html"))


class RepointTest(Tmp):
    def setUp(self) -> None:
        super().setUp()
        site_on_releases(self.site)
        self.web = FakeWeb()
        for ep_id, *_rest, repo in EPISODES:
            self.web.serve(site_url(repo, ep_id), len(mp3_of(ep_id)))  # Echo already put them there
            self.web.serve(f"https://github.com/{repo}/releases/download/{ep_id}/{ep_id}.mp3", len(mp3_of(ep_id)),
                           "application/octet-stream")
        self.media = FakePagesMedia(self.web)
        self.before = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}

    def unchanged(self) -> bool:
        return {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()} == self.before

    def no_verify(self, url: str) -> dict:
        raise AssertionError(f"verify called for {url}")

    def run_repoint(self, **kw) -> dict:
        options = dict(media=self.media, verify=self.web, jobs_root=self.tmp / "jobs", fetch=self.no_fetch)
        options.update(kw)
        return publish.repoint_audio(self.site, **options)

    def no_fetch(self, url: str, dest: Path) -> None:
        raise AssertionError(f"downloaded {url}")

    def test_dry_run_lists_and_checks_without_writing(self) -> None:
        self.web.files[site_url(STORIES_FR, "2026-11-03_story-fr")]["type"] = "application/octet-stream"
        report = self.run_repoint(dry_run=True)
        self.assertEqual((report["count"], report["already_repointed"], report["live"]), (3, 0, 2))
        self.assertEqual(report["repos"], {BUILDWIZ: 2, STORIES_FR: 1})
        first = report["episodes"][0]
        self.assertEqual(first, {
            "id": "2026-11-01_a", "repo": BUILDWIZ, "size_bytes": len(mp3_of("2026-11-01_a")),
            "from": f"https://github.com/{BUILDWIZ}/releases/download/2026-11-01_a/2026-11-01_a.mp3",
            "to": "https://luongnv.com/buildwiz-ai-show-media/2026-11-01_a.mp3", "live": True,
        })
        self.assertFalse(report["episodes"][2]["live"])
        self.assertIn("type application/octet-stream", report["episodes"][2]["check"])
        self.assertEqual(self.web.calls, [e["to"] for e in report["episodes"]])  # one HEAD each, no wait
        self.assertEqual((report["changed"], self.media.calls), ([], []))
        self.assertTrue(self.unchanged())

    def test_repoints_then_a_second_run_is_a_no_op(self) -> None:
        old = _enclosures(self.site)
        report = self.run_repoint()
        self.assertEqual(report["count"], 3)
        self.assertEqual(self.media.calls, [])  # every file was already there: nothing uploaded
        self.assertEqual([e["uploaded"] for e in report["episodes"]], [False] * 3)
        index = json.loads((self.site / "episodes.json").read_text())
        for entry, (ep_id, *_rest, repo) in zip(index["episodes"], EPISODES):
            self.assertEqual(entry["audio"], site_url(repo, ep_id))
            self.assertEqual((entry["size_bytes"], entry["audio_sha256"]),
                             (len(mp3_of(ep_id)), hashlib.sha256(mp3_of(ep_id)).hexdigest()))
        self.assertIn(self.site / "episodes.json", report["changed"])
        self.assertIn(self.site / "feed.xml", report["changed"])
        # The feeds: same guids, lengths, type and ?v=, only the URL before ?v= moved.
        new = _enclosures(self.site)
        self.assertEqual(set(new), set(old))
        self.assertEqual(set(new), {"2026-11-01_a", "2026-11-03_story-fr"})  # the French podcast is in no feed
        for guid, (url, length, type_) in new.items():
            old_url, old_length, old_type = old[guid]
            base, version = url.split("?v=")
            self.assertTrue(base.startswith("https://luongnv.com/"), url)
            self.assertEqual(version, old_url.split("?v=")[1])
            self.assertEqual((length, type_), (old_length, old_type))
            self.assertEqual(type_, "audio/mpeg")
        text = _site_text(self.site)
        self.assertNotIn("/releases/download/", text)
        page = (self.site / "episodes" / "2026-11-01_a" / "index.html").read_text()
        self.assertIn('<audio controls preload="none" src="https://luongnv.com/buildwiz-ai-show-media/2026-11-01_a.mp3"',
                      page)
        # Second run: nothing to move, nothing checked, written or rebuilt.
        after = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        again = self.run_repoint(verify=self.no_verify, rebuild=lambda site: self.fail("rebuilt"))
        self.assertEqual((again["count"], again["already_repointed"], again["changed"]), (0, 3, []))
        self.assertEqual({p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}, after)

    def test_a_missing_file_is_put_there_from_the_job_then_waited_for(self) -> None:
        missing = site_url(BUILDWIZ, "2026-11-02_b")
        del self.web.files[missing]
        make_job(self.tmp / "jobs" / "2026-11-02_b", mp3_of("2026-11-02_b"))
        report = self.run_repoint()
        self.assertEqual(self.media.calls, [("checkout", BUILDWIZ), ("publish", BUILDWIZ, "2026-11-02_b",
                                            len(mp3_of("2026-11-02_b")),
                                            hashlib.sha256(mp3_of("2026-11-02_b")).hexdigest())])
        self.assertEqual([e["uploaded"] for e in report["episodes"]], [False, True, False])
        self.assertEqual(self.media.pushed[f"{BUILDWIZ}/2026-11-02_b.mp3"], mp3_of("2026-11-02_b"))

    def test_a_missing_file_comes_from_the_checkout_first(self) -> None:
        del self.web.files[site_url(STORIES_FR, "2026-11-03_story-fr")]
        local = self.tmp / "media" / "once-upon-a-time-fr-media" / "2026-11-03_story-fr.mp3"
        local.parent.mkdir(parents=True)
        local.write_bytes(mp3_of("2026-11-03_story-fr"))
        self.media.checkouts = self.tmp / "media"
        self.run_repoint()
        self.assertEqual(self.media.names(), ["checkout", "publish"])

    def test_a_missing_file_is_downloaded_from_its_release_last(self) -> None:
        del self.web.files[site_url(BUILDWIZ, "2026-11-01_a")]
        fetched = []

        def fetch(url: str, dest: Path) -> None:
            fetched.append(url)
            dest.write_bytes(mp3_of("2026-11-01_a"))

        self.run_repoint(fetch=fetch)
        self.assertEqual(fetched, [f"https://github.com/{BUILDWIZ}/releases/download/2026-11-01_a/2026-11-01_a.mp3"])
        self.assertEqual(self.media.pushed[f"{BUILDWIZ}/2026-11-01_a.mp3"], mp3_of("2026-11-01_a"))

    def test_wrong_bytes_are_never_uploaded(self) -> None:
        del self.web.files[site_url(BUILDWIZ, "2026-11-01_a")]
        make_job(self.tmp / "jobs" / "2026-11-01_a", b"a re-render with other bytes")
        with self.assertRaisesRegex(publish.UploadError, "not the file of audio_sha256"):
            self.run_repoint(fetch=lambda url, dest: dest.write_bytes(b"not it"))
        self.assertEqual(self.media.calls, [("checkout", BUILDWIZ)])
        self.assertTrue(self.unchanged())

    def test_a_url_that_never_serves_audio_changes_nothing(self) -> None:
        # Served, but as a release asset is: the check fails, the upload "succeeds" yet the
        # media backend's own wait fails it; episodes.json, feeds and pages stay as they were.
        self.web.files[site_url(BUILDWIZ, "2026-11-02_b")]["type"] = "application/octet-stream"
        make_job(self.tmp / "jobs" / "2026-11-02_b", mp3_of("2026-11-02_b"))
        self.media.fail = publish.UploadError("not live after 600 s")
        with self.assertRaisesRegex(publish.UploadError, r"1 media site URL\(s\) not ready, episodes.json not changed"):
            self.run_repoint()
        self.assertTrue(self.unchanged())

    def test_a_failed_rebuild_is_finished_by_a_rerun(self) -> None:
        with self.assertRaisesRegex(publish.MigrationError, "run --repoint-audio again"):
            self.run_repoint(rebuild=lambda site: ([], {"feed_error": "ValueError: bad feed"}))
        index = json.loads((self.site / "episodes.json").read_text())
        self.assertTrue(all(e["audio"].startswith("https://luongnv.com/") for e in index["episodes"]))
        self.assertIn("/releases/download/", (self.site / "feed.xml").read_text())  # still the old feed
        report = self.run_repoint(verify=self.no_verify)  # nothing to move, but feeds to fix
        self.assertEqual(report["count"], 0)
        self.assertIn(self.site / "feed.xml", report["changed"])
        self.assertNotIn("/releases/download/", _site_text(self.site))
        third = self.run_repoint(verify=self.no_verify)
        self.assertEqual(third["changed"], [])

    def test_a_rebuild_that_leaves_release_urls_is_caught(self) -> None:
        with self.assertRaisesRegex(publish.MigrationError, "do not use the media site URLs") as caught:
            self.run_repoint(rebuild=lambda site: ([], {}))
        self.assertTrue(any("feed.xml" in p for p in caught.exception.report["link_problems"]))

    def test_entries_without_a_sha_or_size_stop_before_anything(self) -> None:
        index = json.loads((self.site / "episodes.json").read_text())
        del index["episodes"][0]["audio_sha256"]
        _write(self.site / "episodes.json", index)
        with self.assertRaisesRegex(ValueError, "no size_bytes or audio_sha256"):
            self.run_repoint(verify=self.no_verify)

    def test_local_and_other_entries_are_left_alone(self) -> None:
        index = json.loads((self.site / "episodes.json").read_text())
        index["episodes"].append({"id": "old", "audio": "episodes/old/episode.mp3", "size_bytes": 1})
        index["episodes"].append({"id": "else", "audio": "https://example.com/else.mp3", "size_bytes": 1})
        _write(self.site / "episodes.json", index)
        report = self.run_repoint(dry_run=True)
        self.assertEqual(report["count"], 3)
        self.assertEqual(report["notes"], ["old: its MP3 is still in docs/ (run --migrate-audio)"])

    def run_cli(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.site))
            stack.enter_context(mock.patch.object(publish, "REPO", self.tmp))
            stack.enter_context(mock.patch.object(publish, "MEDIA_BACKEND", self.media))
            stack.enter_context(mock.patch.object(publish, "head_audio", self.web))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_cli(self) -> None:
        code, report = self.run_cli("--repoint-audio", "--dry-run")
        self.assertEqual((code, report["count"], report["live"], report["changed"], report["git"]), (0, 3, 3, [], None))
        self.assertTrue(self.unchanged())
        code, report = self.run_cli("--repoint-audio")
        self.assertEqual((code, report["count"], report["failed"]), (0, 3, []))
        self.assertIn("docs/episodes.json", report["changed"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for argv in (["--repoint-audio", "--dry-run", "--push"], ["--repoint-audio", "--all"],
                         ["--repoint-audio", "--backfill"], ["--repoint-audio", "--migrate-audio"],
                         ["--repoint-audio", str(self.job)], ["--repoint-audio", "--category", "ai"]):
                with self.subTest(argv=argv):
                    self.assertEqual(publish.main(argv), 2)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class RepointCommandTest(Tmp):
    """--repoint-audio --push against a local podcast repo and origin: one commit, pushed;
    the second run pushes nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True)
        _git_in(self.work, "remote", "add", "origin", str(self.origin))
        self.wsite = self.work / "docs"
        site_on_releases(self.wsite)
        _git_in(self.work, "add", "-A")
        _git_in(self.work, "commit", "-q", "-m", "site on release URLs")
        _git_in(self.work, "push", "-q", "origin", "main")
        self.web = FakeWeb()
        for ep_id, *_rest, repo in EPISODES:
            self.web.serve(site_url(repo, ep_id), len(mp3_of(ep_id)))
        self.media = FakePagesMedia(self.web)

    def run_cli(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(publish, "SITE", self.wsite))
            stack.enter_context(mock.patch.object(publish, "REPO", self.work))
            stack.enter_context(mock.patch.object(publish, "MEDIA_BACKEND", self.media))
            stack.enter_context(mock.patch.object(publish, "head_audio", self.web))
            stack.enter_context(mock.patch.object(publish, "_lock", contextlib.nullcontext))
            stack.enter_context(contextlib.redirect_stdout(out))
            code = publish.main(["--repoint-audio", *argv])
        return code, json.loads(out.getvalue())

    def test_push_then_a_second_run_pushes_nothing(self) -> None:
        code, report = self.run_cli("--push")
        self.assertEqual(code, 0, report)
        self.assertTrue(report["git"]["pushed"], report)
        self.assertEqual(_git_in(self.origin, "log", "-1", "--format=%s", "main").strip(), publish.REPOINT_SUBJECT)
        self.assertEqual(publish.REPOINT_SUBJECT, "fix(site): play episode audio from the media sites (#33)")
        committed = _git_in(self.origin, "show", "--name-only", "--format=", "main").split()
        self.assertIn("docs/episodes.json", committed)
        self.assertIn("docs/feed.xml", committed)
        self.assertTrue(all(p.startswith("docs/") for p in committed), committed)
        index = json.loads(_git_in(self.origin, "show", "main:docs/episodes.json"))
        self.assertTrue(all(e["audio"].startswith("https://luongnv.com/") for e in index["episodes"]))
        self.assertEqual(_git_in(self.work, "status", "--porcelain"), "")
        head = _git_in(self.origin, "rev-parse", "main")
        code, report = self.run_cli("--push")
        self.assertEqual((code, report["count"], report["git"], report["changed"]), (0, 0, None, []))
        self.assertEqual(_git_in(self.origin, "rev-parse", "main"), head)

    def test_a_failed_check_pushes_nothing(self) -> None:
        self.web.files[site_url(BUILDWIZ, "2026-11-01_a")]["type"] = "application/octet-stream"
        self.media.fail = publish.UploadError("not live")
        head = _git_in(self.origin, "rev-parse", "main")
        code, report = self.run_cli("--push")
        self.assertEqual(code, 1)
        self.assertEqual(report["failed"][0]["job"], "repoint-audio")
        self.assertIsNone(report["git"])
        self.assertEqual(_git_in(self.origin, "rev-parse", "main"), head)
        self.assertEqual(_git_in(self.work, "status", "--porcelain"), "")


class GuidStabilityTest(Tmp):
    """Moving an episode from its release URL to its media site changes only the URL."""

    def item(self, audio: str) -> ET.Element:
        ep = {"id": EP, "title": "Quiet hours", "show": "Build Wiz AI Show", "language": "en",
              "format": "podcast-2host", "published": "2026-11-05T10:00:00Z", "duration_s": 300,
              "size_bytes": len(MP3), "audio": audio, "audio_sha256": SHA, "description": "Hook.\n\nRest.",
              "source": {"title": "Why cities want quiet", "url": "https://example.com/quiet"}}
        xml = feed.render_feed({"episodes": [ep]}, "buildwiz", self.site, NOW)
        item = ET.fromstring(xml.encode("utf-8")).find("channel/item")
        assert item is not None
        return item

    def test_only_the_enclosure_url_changes(self) -> None:
        before, after = self.item(RELEASE_URL), self.item(PAGES_URL)
        self.assertEqual(before.findtext("guid"), EP)
        self.assertEqual(after.findtext("guid"), EP)
        self.assertEqual(after.find("guid").get("isPermaLink"), before.find("guid").get("isPermaLink"))
        self.assertEqual(after.find("enclosure").get("url"), f"{PAGES_URL}?v={SHA[:8]}")
        self.assertEqual(before.find("enclosure").get("url"), f"{RELEASE_URL}?v={SHA[:8]}")
        for key in ("length", "type"):
            self.assertEqual(after.find("enclosure").get(key), before.find("enclosure").get(key))
        self.assertEqual(after.find("enclosure").get("type"), "audio/mpeg")
        strip = lambda item: ET.tostring(item).replace(PAGES_URL.encode(), b"X").replace(RELEASE_URL.encode(), b"X")
        self.assertEqual(strip(after), strip(before))

    def test_the_page_plays_the_media_site(self) -> None:
        ep = {"id": EP, "title": "Quiet hours", "show": "Build Wiz AI Show", "language": "en",
              "published": "2026-11-05T10:00:00Z", "audio": PAGES_URL, "audio_sha256": SHA, "size_bytes": len(MP3)}
        html = pages.render_page(ep, [ep], self.site)
        self.assertIn(f'<audio controls preload="none" src="{PAGES_URL}" aria-labelledby="title"></audio>', html)
        self.assertIn(f'<meta property="og:audio" content="{PAGES_URL}">', html)


if __name__ == "__main__":
    unittest.main()
