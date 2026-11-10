#!/usr/bin/env python3
"""Publish DropCast episodes to this podcast site (docs/, served by GitHub Pages).

Usage:
    python3 scripts/publish.py JOB [JOB ...] [--push]   # one or more job folders
    python3 scripts/publish.py --all [--push]           # every job in $DROPCAST_HOME/jobs
    python3 scripts/publish.py --backfill [--push]      # descriptions, art, feeds, pages
    python3 scripts/publish.py --migrate-audio [--dry-run | --push]  # MP3s to Releases

For each delivered DropCast job it uploads ``episode.mp3`` to GitHub Releases (podcast #30:
the asset ``<job id>.mp3`` of the release tagged ``<job id>`` in the media repo of its show
and language, ``MEDIA_REPOS``, or ``$PODCAST_MEDIA_REPO_OVERRIDE``, through ``gh``), copies ``transcript.vtt`` to
``docs/episodes/<job id>/`` and records the episode in ``docs/episodes.json`` (title,
summary, source, duration, voices, show, category; ``audio`` = the asset's URL,
``size_bytes`` and ``audio_sha256``). The MP3 is never copied into ``docs/``. A failed upload
fails that job and leaves ``episodes.json`` as it was. Only public facts are copied: no
local paths, no source text, no keys.

``--migrate-audio`` moves the MP3s already in ``docs/`` (entries whose ``audio`` is
``episodes/<id>/episode.mp3``) the same way, each to its show/language repo: upload all, check every URL with HEAD (200 and
the right length), and only then update ``episodes.json``, ``git rm`` the local files and
rebuild the feeds and pages. ``--dry-run`` lists the work without uploading.

An episode with extra sources presented by guests (DropCast #94) also gets ``sources``
(every source used, main first: ``title``, ``author``, ``url``) and ``guests``
(``name``, ``presents``: the titles of the sources they present); ``source`` stays the
main source. Other episodes get neither key, so their entries do not change.

An episode whose music needs attribution (``run.json`` ``music.credit``, e.g. a CC-BY
track) also gets ``music_credit``, that text trimmed; the site shows it under the episode.
Without a credit (the CC0 theme, older jobs) the key is left out.

A story told in several languages (DropCast #136) has the same ``script.json``
``story_group`` in every version; the publisher copies it as ``story_group`` (with each
version's ``language``, as for every episode), and the story page shows the versions as
one story with a language switch. Without it (older jobs) the key is left out.
``result.json`` is not read for it.

Each episode gets one ``show``: **Once Upon a Time Show** for a story (a ``bedtime-story``
or ``storytelling`` script, or a job whose ``script.json`` or ``brief.json`` names that
show or a story register), listed on ``docs/stories/``; else **Build Wiz AI Show**, listed
on ``docs/index.html``. The format wins over the name, so a story briefed before the
stories had their own show (its script says Build Wiz AI Show) still goes to the story
show. Any other job is Build Wiz AI Show unless its script or brief names the story show
or a story register (DropCast never writes that for a podcast). ``result.json``
is not read for it (DropCast runs the publisher before that file is final).

Each episode gets one ``category``, the site's tab: ``ai`` (AI podcast), ``bedtime``
(bedtime stories), ``marketing`` or ``others``. The first that applies wins:
``--category`` (when publishing one job), the job's ``category.txt`` (one word),
``bedtime`` for a ``bedtime-story`` script, the category already in ``episodes.json``
(so a hand fix survives a re-publish), then a keyword guess from the title and summary.

Each entry also gets ``description`` (the copy-paste podcast description, at most 600
characters: the job's ``description.txt``, else the one already in ``episodes.json``, else
one generated from the summary, sources and show tagline) and ``file_name`` (the download
name ``<Show> - <Title> (<YYYY-MM-DD>).mp3``: ``run.json`` ``delivery.file_name``, else
rebuilt with the same rule), DropCast #161/#163. After every publish the episode pages
(``docs/episodes/<id>/index.html``) and ``docs/sitemap.xml`` are rebuilt
(``scripts/pages.py``). ``--backfill`` fills both keys for older entries and rebuilds them.

A story's illustration (one per story, shared by its language versions) comes from the
job's ``illustration/`` folder (``wide.jpg``, ``square.jpg``, ``thumb.jpg``, optional
``alt.txt``), else from the job of the same ``story_group`` that has it. The jpgs are
copied to ``docs/art/<story group or id>/`` and the entry gets ``image`` (``square``,
``wide``, ``thumb`` paths and ``alt``); without one, an ``image`` already in
``episodes.json`` is kept. ``--backfill`` adds it to older entries and rebuilds the feeds.

A job is skipped (and reported) when it is not delivered yet, when its voices are for
private use only (edge-tts, ``run.json`` ``private_use``), or when the job opted out
(``request.json`` ``"publish": false``, from ``--no-publish`` or "don't publish").

``--push`` commits the changed files and pushes them; the Pages workflow then deploys
the site. Standard library only, so DropCast can call it as
``DROPCAST_PUBLISH_CMD="python3 /path/to/podcast/scripts/publish.py --push"``.

Prints one JSON object. Exit 0 = every job published or skipped on purpose,
1 = a job could not be published, 2 = usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs"
EPISODES_DIR = "episodes"
INDEX = "episodes.json"
SHOW = {
    "name": "Build Wiz AI Show",
    "tagline": "Big AI ideas, made clear for builders.",
    "hosts": ["Bob", "Alice"],
}
# The stories' show (DropCast #125/#129): its own page, docs/stories/.
STORY_SHOW = {
    "name": "Once Upon a Time Show",
    "tagline": "Gentle stories for bedtime and story time, told slowly by a warm narrator.",
    "page": "stories/",
}
SHOWS = [dict(SHOW, page=""), STORY_SHOW]
STORY_FORMATS = ("bedtime-story", "storytelling")
STORY_REGISTERS = ("story", "bedtime")
ENGINE_LABELS = {
    "voicecast": "VoiceCast",
    "elevenlabs": "ElevenLabs",
    "openrouter": "OpenRouter",
    "edgetts": "edge-tts",
}


CATEGORIES = ("ai", "bedtime", "marketing", "others")
# Keyword guess, used only when nothing else names the category. Lower-case, matched as
# whole words in the title (counted three times) and the summary.
AI_WORDS = (
    "ai", "a.i.", "agent", "agents", "agentic", "llm", "llms", "gpt", "chatgpt", "claude",
    "openai", "anthropic", "gemini", "model", "models", "machine learning", "neural",
    "prompt", "prompts", "copilot", "automation", "trí tuệ nhân tạo", "intelligence",
)
MARKETING_WORDS = (
    "marketing", "marketer", "brand", "branding", "growth", "audience", "funnel", "seo",
    "ads", "advertising", "campaign", "organic", "viral", "reels", "tiktok", "content",
    "copywriting", "conversion", "customers", "launch", "followers", "posting",
    "call to action", "calls to action", "go-to-market", "tiếp thị",
)


def _count(words: tuple[str, ...], text: str) -> int:
    return sum(len(re.findall(rf"(?<!\w){re.escape(w)}(?!\w)", text)) for w in words)


def guess_category(title: str, summary: list[str], fmt: str | None) -> str:
    """Best guess from the words alone: ``bedtime``, ``marketing``, ``ai`` or ``others``."""
    if fmt == "bedtime-story":
        return "bedtime"
    head = (title or "").lower()
    body = " ".join(summary).lower()
    ai = 3 * _count(AI_WORDS, head) + _count(AI_WORDS, body)
    marketing = 3 * _count(MARKETING_WORDS, head) + _count(MARKETING_WORDS, body)
    if marketing > ai:
        return "marketing"
    if ai:
        return "ai"
    return "others"


def _job_category(job: Path) -> str | None:
    try:
        word = (job / "category.txt").read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    if word not in CATEGORIES:
        raise ValueError(f"category.txt says {word!r}; use one of {', '.join(CATEGORIES)}")
    return word


def episode_show(job: Path, script: dict[str, Any]) -> str:
    """The show an episode is published under: ``STORY_SHOW`` or ``SHOW``'s name.

    A story format always goes to the story show (an older story's script still says
    Build Wiz AI Show). Otherwise the story show only when ``script.json`` ``show.name``
    or the job's ``brief.json`` (``show.name``, ``show.register``) says so, e.g. a future
    story format; anything else, including a show name this site does not know, is
    Build Wiz AI Show.
    """
    if script.get("format") in STORY_FORMATS:
        return STORY_SHOW["name"]
    brief = _mapping(_mapping(_read_json(job / "brief.json")).get("show"))
    named = (_mapping(script.get("show")).get("name"), brief.get("name"))
    if STORY_SHOW["name"] in named or brief.get("register") in STORY_REGISTERS:
        return STORY_SHOW["name"]
    return SHOW["name"]


class Skip(Exception):
    """The job is left out on purpose (not an error)."""


class NotReady(Skip):
    """The episode is not rendered yet: fine for ``--all``, an error for a named job."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: Any) -> None:
    """Write ``data`` as JSON atomically: a temp file in the same folder, then
    ``os.replace``, so a crash mid-write never leaves a half-written ``episodes.json``. An
    existing file keeps its mode (a new one gets 0666 less the umask, like ``write_text``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


# A line git writes around a conflict (a conflicted merge, rebase or stash pop).
_CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7})(?: |$)|^={7}$", re.MULTILINE)


def read_index(path: Path) -> dict[str, Any] | None:
    """``episodes.json`` at ``path``: a dict with an ``episodes`` list, or None when there is
    no file yet (a fresh site starts a new index). A file that is there but cannot be read
    or parsed (git conflict markers, say, after a conflicted ``git pull --autostash``)
    raises ``ValueError``: nothing may then replace it with a new, shorter index."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(f"{INDEX} cannot be read ({exc}); nothing was changed") from exc
    if _CONFLICT_MARKER.search(text):
        raise ValueError(
            f"{INDEX} has git conflict markers (a conflicted pull or stash pop); resolve it "
            "(git status, git stash list) before publishing; nothing was changed"
        )
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{INDEX} is not valid JSON ({exc}); fix or restore it before publishing; "
                         "nothing was changed") from exc
    if not isinstance(data, dict) or not isinstance(data.get("episodes"), list):
        raise ValueError(f"{INDEX} has no episodes list; fix or restore it before publishing; nothing was changed")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(src: Path, dest: Path) -> bool:
    """Copy when the bytes differ; ``True`` when ``dest`` changed."""
    if dest.exists() and _sha256(dest) == _sha256(src):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    os.chmod(dest, 0o644)
    return True


# ---------- Episode audio on GitHub Releases (podcast #30) ----------
# The MP3s are not in docs/ (Pages deploys of a ~240 MB site hit the 10-minute cap): each
# one is the asset ``<episode id>.mp3`` of the release tagged ``<episode id>`` in the media
# repo, and the entry's ``audio`` is the asset's absolute URL. GitHub rewrites asset names
# (spaces become dots, accents and parentheses are dropped), so the asset is named after the
# id, which it keeps as is. ``audio_sha256`` (the MP3's SHA-256) versions the feeds' URLs
# and lets a re-publish of the same bytes skip the upload.
# One media repo per show and language (Luong, 2026-11-10). A story in another language
# goes to the English stories repo (with a note). ``PODCAST_MEDIA_REPO_OVERRIDE`` sends
# every upload to one repo (tests, emergencies); site.js only plays the four repos below.
MEDIA_REPOS: dict[tuple[str, str | None], str] = {
    ("Build Wiz AI Show", None): "luongnv89/buildwiz-ai-show-media",  # every language
    ("Once Upon a Time Show", "en"): "luongnv89/once-upon-a-time-en-media",
    ("Once Upon a Time Show", "fr"): "luongnv89/once-upon-a-time-fr-media",
    ("Once Upon a Time Show", "vi"): "luongnv89/once-upon-a-time-vi-media",
}
MEDIA_FALLBACK = MEDIA_REPOS[("Once Upon a Time Show", "en")]
MEDIA_REPO_ENV = "PODCAST_MEDIA_REPO_OVERRIDE"
SITE_URL = "https://luongnv.com/podcast/"
_REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")
_LOCAL_AUDIO = re.compile(rf"{EPISODES_DIR}/([A-Za-z0-9][A-Za-z0-9._-]*)/episode\.mp3")


class UploadError(RuntimeError):
    """The episode audio could not be uploaded (or checked) on GitHub Releases."""


def _media_override() -> str | None:
    repo = (os.environ.get(MEDIA_REPO_ENV) or "").strip()
    if not repo:
        return None
    if not _REPO_NAME.fullmatch(repo) or ".." in repo:
        raise ValueError(f"{MEDIA_REPO_ENV} must be owner/name, not {repo[:80]!r}")
    return repo


def media_repo(show: Any, language: Any) -> tuple[str, str | None]:
    """``(owner/name, note)``: the media repo of a show (``STORY_SHOW`` or anything else,
    which is Build Wiz AI Show, as ``episode_show()`` routes) in ``language``. A story in a
    language without its own repo gets the English stories repo and a note. The override
    env var wins over everything."""
    override = _media_override()
    if override:
        return override, None
    if show != STORY_SHOW["name"]:
        return MEDIA_REPOS[(SHOW["name"], None)], None
    lang = str(language or "en").strip().lower().replace("_", "-").split("-")[0] or "en"
    repo = MEDIA_REPOS.get((STORY_SHOW["name"], lang))
    if repo:
        return repo, None
    return MEDIA_FALLBACK, f"no media repo for {STORY_SHOW['name']} in {lang!r}: uploaded to {MEDIA_FALLBACK}"


def entry_media_repo(entry: dict[str, Any]) -> tuple[str, str | None]:
    """``media_repo()`` of an ``episodes.json`` entry (a story format is always a story)."""
    story = entry.get("show") == STORY_SHOW["name"] or entry.get("format") in STORY_FORMATS
    return media_repo(STORY_SHOW["name"] if story else SHOW["name"], entry.get("language"))


def asset_name(episode_id: str) -> str:
    """The release asset's name: ``<episode id>.mp3`` (a safe id, kept as is by GitHub)."""
    return f"{art_key(episode_id)}.mp3"


def audio_url(repo: str, episode_id: str) -> str:
    """The asset's permanent URL (it redirects to release-assets.githubusercontent.com)."""
    return f"https://github.com/{repo}/releases/download/{art_key(episode_id)}/{asset_name(episode_id)}"


def local_audio_id(audio: Any) -> str | None:
    """The id in a local ``episodes/<id>/episode.mp3`` audio path, else None."""
    match = _LOCAL_AUDIO.fullmatch(audio) if isinstance(audio, str) else None
    return match.group(1) if match and ".." not in audio else None


def _gh(*args: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UploadError(f"gh {args[0]} failed: {type(exc).__name__}: {exc}"[:300]) from exc


def _gh_error(proc: subprocess.CompletedProcess[str]) -> str:
    text = (proc.stderr or proc.stdout or "").strip().splitlines()
    return text[-1][:300] if text else f"exit {proc.returncode}"


class GhMedia:
    """The media repo's releases through the GitHub CLI (``gh``, already logged in)."""

    def __init__(self, repo: str) -> None:
        if not _REPO_NAME.fullmatch(repo) or ".." in repo:
            raise ValueError(f"bad media repo {repo[:80]!r}")
        self.repo = repo

    def _release(self, tag: str) -> dict[str, Any] | None:
        """The release ``tag`` as the API returns it; None when there is no release."""
        proc = _gh("api", f"repos/{self.repo}/releases/tags/{tag}", timeout=120)
        if proc.returncode != 0:
            if "404" in (proc.stderr or "") or "Not Found" in (proc.stderr or ""):
                return None
            raise UploadError(f"gh could not read release {tag}: {_gh_error(proc)}")
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise UploadError(f"gh returned no JSON for release {tag}") from exc
        if not isinstance(data, dict):
            raise UploadError(f"gh returned no release object for {tag}")
        return data

    def _asset_list(self, tag: str) -> list[dict[str, Any]]:
        release = self._release(tag)
        if release is None:
            raise UploadError(f"release {tag} is missing")
        return [a for a in release.get("assets") or [] if isinstance(a, dict)]

    def assets(self, tag: str) -> dict[str, int] | None:
        """``{asset name: size}`` of the release ``tag``; None when there is no release."""
        release = self._release(tag)
        if release is None:
            return None
        return {
            str(a.get("name")): int(a.get("size") or 0)
            for a in release.get("assets") or []
            if isinstance(a, dict)
        }

    def create_release(self, tag: str, title: str, notes: str) -> None:
        proc = _gh(
            "release", "create", tag, "-R", self.repo, "--title", title, "--notes", notes,
            timeout=120,
        )
        if proc.returncode != 0:
            raise UploadError(f"gh could not create release {tag}: {_gh_error(proc)}")

    def upload(self, tag: str, path: Path) -> None:
        """Upload ``path`` (already named as the asset) to release ``tag`` as a new asset."""
        proc = _gh("release", "upload", tag, str(path), "-R", self.repo)
        if proc.returncode != 0:
            raise UploadError(f"gh could not upload {path.name} to release {tag}: {_gh_error(proc)}")

    def _delete_asset(self, tag: str, asset: dict[str, Any]) -> None:
        proc = _gh("api", "-X", "DELETE", f"repos/{self.repo}/releases/assets/{int(asset['id'])}", timeout=120)
        if proc.returncode != 0:
            raise UploadError(f"gh could not delete {asset.get('name')} from release {tag}: {_gh_error(proc)}")

    def replace(self, tag: str, path: Path) -> None:
        """Replace the asset named ``path.name`` with ``path`` without a window where a failed
        upload leaves nothing live: upload under ``staged_name()``, check its size and
        state, delete the old asset, then rename the new one (``PATCH .../assets/{id}``).

        A failure before the delete leaves the live asset untouched; a failed rename (the
        old one already deleted) is finished by running the publish again, which finds the
        staged asset (a leftover staged asset is deleted first)."""
        name = path.name
        staged = staged_name(name)
        size = path.stat().st_size
        for asset in self._asset_list(tag):
            if asset.get("name") == staged:
                self._delete_asset(tag, asset)
        with tempfile.TemporaryDirectory(prefix="podcast-audio-") as tmp:
            copy = Path(tmp) / staged
            shutil.copyfile(path, copy)
            self.upload(tag, copy)
        found = {a.get("name"): a for a in self._asset_list(tag)}
        new = found.get(staged)
        if not new or new.get("state", "uploaded") != "uploaded" or int(new.get("size") or 0) != size:
            raise UploadError(
                f"the uploaded {staged} on release {tag} did not check out "
                f"(size {new and new.get('size')}, expected {size}); the live {name} is unchanged"
            )
        old = found.get(name)
        if old:
            self._delete_asset(tag, old)
        proc = _gh(
            "api", "-X", "PATCH", f"repos/{self.repo}/releases/assets/{int(new['id'])}", "-f", f"name={name}",
            timeout=120,
        )
        if proc.returncode != 0:
            raise UploadError(
                f"gh could not rename {staged} to {name} on release {tag}: {_gh_error(proc)}; "
                "run the publish again to finish"
            )


def staged_name(name: str) -> str:
    """The temporary name of a replacement asset: ``<id>.mp3`` -> ``<id>.new.mp3``."""
    stem, dot, suffix = name.rpartition(".")
    return f"{stem}.new.{suffix}" if dot else f"{name}.new"


def upload_audio(
    media: Any,
    episode_id: str,
    title: str,
    mp3: Path,
    sha256: str,
    recorded_sha256: Any = None,
) -> dict[str, Any]:
    """Make the release ``<episode id>`` hold ``mp3`` as ``<episode id>.mp3``.

    The release is created when missing (title = the episode title, notes = "Audio for
    <page URL>"). The upload is skipped when the release already has an asset of that name
    and size and ``recorded_sha256`` (the entry's ``audio_sha256`` in episodes.json) is the
    file's SHA-256. An existing asset (or the staged one of an interrupted replace) is
    replaced with ``media.replace()``, which never leaves the live asset missing when the
    upload fails; otherwise ``media.upload()`` adds it. ``media`` is a ``GhMedia`` of the
    episode's repo (tests pass a fake). Returns ``{url, asset, uploaded}``; raises
    ``UploadError``.
    """
    name = asset_name(episode_id)
    size = mp3.stat().st_size
    url = audio_url(media.repo, episode_id)
    assets = media.assets(episode_id)
    if assets is not None and assets.get(name) == size and recorded_sha256 == sha256:
        return {"url": url, "asset": name, "uploaded": False}
    if assets is None:
        media.create_release(
            episode_id, str(title or episode_id)[:200], f"Audio for {SITE_URL}{EPISODES_DIR}/{episode_id}/"
        )
    # gh names the asset after the file, so upload a copy named <id>.mp3.
    with tempfile.TemporaryDirectory(prefix="podcast-audio-") as tmp:
        named = Path(tmp) / name
        shutil.copyfile(mp3, named)
        if assets and (name in assets or staged_name(name) in assets):
            media.replace(episode_id, named)
        else:
            media.upload(episode_id, named)
    return {"url": url, "asset": name, "uploaded": True}


def head_audio(url: str, timeout: int = 60) -> dict[str, Any]:
    """HEAD ``url``, following redirects as HEAD: ``{status, length}`` of the last answer."""

    class _Keep(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new is not None:
                new.method = "HEAD"
            return new

    opener = urllib.request.build_opener(_Keep)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "podcast-publish"})
    try:
        with opener.open(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            return {"status": response.status, "length": int(length) if length else None}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "length": None}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"status": None, "length": None, "error": f"{type(exc).__name__}: {exc}"[:200]}


# ---------- Story illustrations (Luong's decision 2026-11-06) ----------
# One hand-drawn illustration per story, shared by its language versions. A DropCast job
# may hold ``illustration/`` with ``wide.jpg`` (1920x1080, page hero and share cards),
# ``square.jpg`` (3000x3000, episode artwork in podcast apps), ``thumb.jpg`` (640x640, the
# site list) and optionally ``alt.txt`` (one line of English alt text). Only one version of
# a story group has it (the English one), so the others find it through ``story_group``.
ART_DIR = "art"
ART_FOLDER = "illustration"
ART_FILES = ("wide", "square", "thumb")
_SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def art_key(key: Any) -> str:
    """``key`` when it is a plain, safe path component (no ``/``, no ``..``), else ValueError."""
    text = key if isinstance(key, str) else ""
    if not _SAFE_KEY.fullmatch(text) or ".." in text or len(text) > 200:
        raise ValueError(f"unsafe illustration key {str(key)[:80]!r}")
    return text


def _art_complete(folder: Path) -> bool:
    """An ``illustration/`` folder with all three jpgs as regular files (no symlinks)."""
    if folder.is_symlink() or not folder.is_dir():
        return False
    return all(
        not (folder / f"{name}.jpg").is_symlink() and (folder / f"{name}.jpg").is_file()
        for name in ART_FILES
    )


def _story_group_of(job: Path) -> str | None:
    return _text(_mapping(_read_json(job / "script.json")).get("story_group"))


def find_illustration(
    job: Path, story_group: str | None = None, siblings: Path | None = None
) -> Path | None:
    """The ``illustration/`` folder for ``job``: its own when complete, else the first
    complete one (sorted by folder name) among the job folders in ``siblings`` (default
    ``job.parent``) whose ``script.json`` has the same ``story_group``. ``story_group``
    defaults to the job's own; ``None`` when nothing is found."""
    own = job / ART_FOLDER
    if _art_complete(own):
        return own
    group = _text(story_group) or (_story_group_of(job) if job.is_dir() else None)
    if not group:
        return None
    root = siblings if siblings is not None else job.parent
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return None
    for folder in folders:
        if folder == job or _story_group_of(folder) != group:
            continue
        if _art_complete(folder / ART_FOLDER):
            return folder / ART_FOLDER
    return None


def _alt_text(folder: Path) -> str | None:
    path = folder / "alt.txt"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return _text(re.sub(r"\s+", " ", text)[:500])


def copy_illustration(folder: Path, site: Path, key: str) -> tuple[dict[str, Any], list[Path]]:
    """Copy the three jpgs to ``site/art/<key>/`` (only the ones whose bytes changed) and
    return the entry's ``image`` field and the changed files."""
    key = art_key(key)
    dest = site / ART_DIR / key
    changed = []
    for name in ART_FILES:
        if _copy(folder / f"{name}.jpg", dest / f"{name}.jpg"):
            changed.append(dest / f"{name}.jpg")
    image: dict[str, Any] = {name: f"{ART_DIR}/{key}/{name}.jpg" for name in ("square", "wide", "thumb")}
    image["alt"] = _alt_text(folder)
    return image, changed


_ART_PATH = re.compile(r"art/[A-Za-z0-9][A-Za-z0-9._-]*/(?:wide|square|thumb)\.jpg")


def _valid_image(value: Any) -> dict[str, Any] | None:
    """An ``image`` field already in ``episodes.json`` when its paths are safe, else None."""
    image = _mapping(value)
    paths = [image.get(name) for name in ("square", "wide", "thumb")]
    if not all(isinstance(p, str) and _ART_PATH.fullmatch(p) and ".." not in p for p in paths):
        return None
    return image


def episode_image(
    job: Path, site: Path, episode_id: str, story_group: str | None, siblings: Path | None = None
) -> tuple[dict[str, Any] | None, list[Path]]:
    """Find, copy and describe a job's illustration: ``(image field or None, changed)``.
    The art folder is named after the story group (shared by its versions), else the id."""
    folder = find_illustration(job, story_group, siblings)
    if folder is None:
        return None, []
    return copy_illustration(folder, site, story_group or episode_id)


def _summary(job: Path) -> list[str]:
    try:
        lines = (job / "summary.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()][:3]


# ---------- Description and download name (DropCast #161/#163) ----------
# The shared contract: ``JOB/description.txt`` is plain text of at most 600 characters
# (Python ``len``; Spotify's limit): a 2-3 sentence hook / blank line / ``In this
# episode:`` and 2-4 ``- `` lines / blank line / ``Sources:`` / the music credit (stories)
# / the show's tagline and link. Without one, ``fallback_description()`` builds the same
# layout from the summary, the sources and the show's tagline.
DESCRIPTION_MAX = 600
# The labels (per language) and each show's link, taglines and last line come from
# DropCast, one source of truth: scripts/description_labels.json is a copy of
# ``python -m dropcast.description labels --json`` (README, "Descriptions").
LABELS_FILE = Path(__file__).resolve().with_name("description_labels.json")


def _load_labels(path: Path = LABELS_FILE) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("labels"), dict) or "en" not in data["labels"]:
        raise ValueError(f"{path.name}: no English labels")
    for name, show in (data.get("shows") or {}).items():
        if not show.get("link") or "en" not in (show.get("last_lines") or {}):
            raise ValueError(f"{path.name}: {name} has no link or English last line")
    return data


DESCRIPTION_STRINGS = _load_labels()
LABELS: dict[str, dict[str, str]] = DESCRIPTION_STRINGS["labels"]
SHOW_TEXTS: dict[str, dict[str, Any]] = DESCRIPTION_STRINGS["shows"]
SHOW_LINKS = {name: show["link"] for name, show in SHOW_TEXTS.items()}
# How a source is credited and the rest counted, per language (site-side wording).
_BY = {"en": "{t} by {a}", "fr": "{t} de {a}", "vi": "{t} của {a}"}
_MORE = {"en": "and {n} more", "fr": "et {n} autres", "vi": "và {n} nguồn khác"}


def labels(lang: str) -> dict[str, str]:
    """The description labels in ``lang`` (English for a language without its own)."""
    return LABELS.get(lang) or LABELS["en"]


def last_line(show: str, lang: str) -> str:
    """The show's last line in ``lang``: its tagline and link, exactly as DropCast's."""
    lines = SHOW_TEXTS[show]["last_lines"]
    return lines.get(lang) or lines["en"]


# The one sentence the fallback adds to the hook (facts from the entry only).
_HOOK_PODCAST = {
    "en": ("{a} and {b} unpack it in {n} minutes.", "{a} unpacks it in {n} minutes.",
           "Unpacked in {n} minutes."),
    "fr": ("{a} et {b} le décortiquent en {n} minutes.", "{a} le décortique en {n} minutes.",
           "Décortiqué en {n} minutes."),
    "vi": ("{a} và {b} cùng phân tích trong {n} phút.", "{a} phân tích trong {n} phút.",
           "Phân tích trong {n} phút."),
}
_HOOK_STORY = {
    "en": ("A {n}-minute listen, with soft music between the scenes.", "A {n}-minute listen."),
    "fr": ("{n} minutes d'écoute, avec une petite musique entre les scènes.", "{n} minutes d'écoute."),
    "vi": ("{n} phút nghe, có nhạc nhẹ giữa các cảnh.", "{n} phút nghe."),
}
MUSIC_SHORT = "Kevin MacLeod (incompetech.com), CC BY 4.0"
_MARKUP = re.compile(r"<[A-Za-z/!][^>]*>|\*\*|__|\]\(|^\s{0,3}#{1,6}\s|^\s*[*+]\s", re.MULTILINE)
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|]')


def _lang(entry: dict[str, Any]) -> str:
    lang = str(entry.get("language") or "en").strip().lower().split("-")[0].split("_")[0]
    return lang if lang in ("en", "fr", "vi") else "en"


def _tidy(text: Any) -> str:
    """One line: whitespace collapsed; an ALL-CAPS name or title in title case."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    name, handle = re.match(r"(.*?)(\s*\(@\w+\))?$", text).groups()
    if sum(c.isalpha() for c in name) >= 4 and name.upper() == name:
        name = re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), name.lower())
    return name + (handle or "")


def _credit_names(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """``(title, author)`` of every source, main first, cleaned for one line."""
    listed = entry.get("sources") if isinstance(entry.get("sources"), list) else None
    items = listed or [_mapping(entry.get("source"))]
    out = []
    for item in items:
        item = _mapping(item)
        title = _tidy(item.get("title")).rstrip(" .")
        author = _tidy(item.get("author"))
        if title or author:
            out.append((title, author))
    return out


def _music_line(credit: Any, lang: str = "en") -> str | None:
    credit = _text(credit)
    if not credit:
        return None
    label = labels(lang)["music"]
    if "Kevin MacLeod" in credit and re.search(r"Attribution 4\.0|CC[ -]BY 4\.0", credit):
        return f"{label} {MUSIC_SHORT}"
    return f"{label} {_cut(credit, 120)}"


def _cut(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word boundary with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{cut}…"


def _hook_sentences(entry: dict[str, Any], show: str, lang: str) -> list[str]:
    """The sentence the fallback may add to the hook, longest first."""
    try:
        n = max(1, round(float(entry.get("duration_s") or 0) / 60))
    except (TypeError, ValueError):
        return []
    if show == STORY_SHOW["name"]:
        music, plain = _HOOK_STORY[lang]
        if lang == "en" and (str(n).startswith("8") or n in (11, 18)):
            music, plain = (t.replace("A {n}", "An {n}", 1) for t in (music, plain))
        return [music.format(n=n), plain.format(n=n)] if _text(entry.get("music_credit")) else [plain.format(n=n)]
    return [_host_sentence(entry, lang, n)]


def _host_sentence(entry: dict[str, Any], lang: str, n: int) -> str:
    # Only a two-host conversation names both hosts (a solo explainer has one voice, and
    # the entry's hosts are the show's pair either way).
    hosts = [h for h in entry.get("hosts") or [] if isinstance(h, str) and h.strip()]
    if entry.get("format") not in (None, "podcast-2host"):
        hosts = []
    two, one, none = _HOOK_PODCAST[lang]
    if len(hosts) >= 2:
        return two.format(a=hosts[0], b=hosts[1], n=n)
    return one.format(a=hosts[0], n=n) if hosts else none.format(n=n)


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"(?<=[.!?…])\s+", text.strip()) if part])


def fallback_description(entry: dict[str, Any], limit: int = DESCRIPTION_MAX) -> str:
    """The contract's layout built from an index entry: hook (the first summary line and
    one sentence on the hosts or length), the other summary lines as ``In this episode``,
    the sources (title by author), the music credit, then the show's last line (tagline
    and link). Labels and last line are DropCast's, in the entry's language.

    Shortened step by step until it fits ``limit`` characters: sources by author (or
    title) only, then (when the first summary line is a single sentence, so the hook keeps
    two) three then two bullets, then without the added hook sentence, at most two
    bullets, fewer sources named, and last the longest lines cut at a word boundary.
    """
    show = str(entry.get("show")) if entry.get("show") in SHOW_TEXTS else SHOW["name"]
    lang = _lang(entry)
    names_of = labels(lang)
    summary = [_tidy(s) for s in entry.get("summary") or [] if isinstance(s, str) and s.strip()]
    first = summary[0] if summary else _tidy(entry.get("title")).rstrip(".") + "."
    bullets = summary[1:5]
    credits = _credit_names(entry)
    music = _music_line(entry.get("music_credit"), lang)
    last = last_line(show, lang)
    extras = _hook_sentences(entry, show, lang)

    def build(full_credits: bool, with_extra: int, n_bullets: int, n_sources: int,
              hook: str, items: list[str]) -> str:
        """``with_extra``: 0 = no added sentence, 1 = the shortest, 2 = the longest."""
        names = [
            (_BY[lang].format(t=t, a=a) if t and a else t or a) if full_credits
            else (re.sub(r"\s*\(@\w+\)$", "", a) or t)
            for t, a in credits[:n_sources]
        ]
        if len(credits) > n_sources:
            names.append(_MORE[lang].format(n=len(credits) - n_sources))
        extra = extras[0 if with_extra == 2 else -1] if extras and with_extra else ""
        blocks = [f"{hook} {extra}" if extra else hook]
        if items[:n_bullets]:
            point_lines = "\n".join(f"- {b}" for b in items[:n_bullets])
            blocks.append(f"{names_of['in_this_episode']}\n{point_lines}")
        tail = [f"{names_of['sources']} {'; '.join(names)}"] if names else []
        tail += [music] if music else []
        tail.append(last)
        blocks.append("\n".join(tail))
        return "\n\n".join(blocks)

    n_src = len(credits)
    steps: list[dict[str, Any]] = [
        dict(full_credits=True, with_extra=2, n_bullets=4),
        dict(full_credits=True, with_extra=1, n_bullets=4),
        dict(full_credits=False, with_extra=2, n_bullets=4),
        dict(full_credits=False, with_extra=1, n_bullets=4),
    ]
    if extras and _sentence_count(first) < 2:
        # Without the added sentence the hook would be one sentence: drop bullets first.
        steps += [dict(full_credits=fc, with_extra=1, n_bullets=n)
                  for n in (3, 2) for fc in (True, False)]
    steps += [
        dict(full_credits=True, with_extra=0, n_bullets=4),
        dict(full_credits=False, with_extra=0, n_bullets=4),
        dict(full_credits=False, with_extra=0, n_bullets=2),
    ]
    for step in steps:
        text = build(n_sources=n_src, hook=first, items=bullets, **step)
        if len(text) <= limit:
            return text
    for n in range(n_src - 1, 0, -1):
        text = build(False, 0, 2, n, first, bullets)
        if len(text) <= limit:
            return text
    # Last resort: cut the longest lines a little at a time (word boundaries).
    hook, items = first, bullets[:2]
    while True:
        text = build(False, 0, 2, min(1, n_src), hook, items)
        over = len(text) - limit
        if over <= 0:
            return text
        lines = [hook, *items]
        i = max(range(len(lines)), key=lambda k: len(lines[k]))
        if len(lines[i]) <= 40:
            return text[:limit]
        lines[i] = _cut(lines[i], max(40, len(lines[i]) - over - 1))
        hook, items = lines[0], lines[1:]


def description_problems(text: str) -> list[str]:
    """Why a ``description.txt`` breaks the contract's hard rules ([] = usable)."""
    problems = []
    if not text.strip():
        problems.append("empty")
    if len(text) > DESCRIPTION_MAX:
        problems.append(f"{len(text)} characters (at most {DESCRIPTION_MAX})")
    if _MARKUP.search(text):
        problems.append("contains Markdown or HTML")
    return problems


def job_description(job: Path) -> tuple[str | None, list[str]]:
    """``JOB/description.txt`` when it is usable, else ``(None, problems)``."""
    path = job / "description.txt"
    if path.is_symlink() or not path.is_file():
        return None, []
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"unreadable: {type(exc).__name__}"]
    problems = description_problems(text)
    return (None, problems) if problems else (text, [])


def description_hook(text: Any) -> str:
    """The first paragraph of a description: the page's ``<meta name=\"description\">``."""
    return re.sub(r"\s+", " ", str(text or "").strip().split("\n\n", 1)[0]).strip()


def _clean_name(text: Any) -> str:
    """As DropCast's ``delivery._clean_name_part``: NFC, control characters become spaces,
    format characters (``Cf``: bidi overrides, zero-width) are dropped, then ``\\/:*?"<>|``."""
    text = unicodedata.normalize("NFC", str(text or ""))
    text = "".join(
        " " if unicodedata.category(c) == "Cc" else c for c in text if unicodedata.category(c) != "Cf"
    )
    text = _UNSAFE_NAME.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


FILE_NAME_MAX = 150
FILE_NAME_MAX_BYTES = 250


def _cut_words(text: str, limit: int) -> str:
    """As DropCast's ``delivery._cut_words``: at most ``limit`` characters, at a word
    boundary (inside a word longer than ``limit``), without trailing punctuation."""
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    cut = text[: limit + 1]
    space = cut.rfind(" ")
    cut = cut[:space] if space > 0 else text[:limit]
    return re.sub(r"[\s,;:.\-\u2013\u2014]+$", "", cut) or text[:limit].strip()


def _name_bytes(name: str, tail: str) -> int:
    return len(f"{name}{tail}.mp3".encode())


def episode_file_name(show: str, title: str, date: str) -> str:
    """The download name ``<Show> - <Title> (<YYYY-MM-DD>).mp3`` (the contract's rule, as
    DropCast's ``delivery.episode_file_name``): ``\\/:*?\"<>|`` and control characters
    dropped, spaces collapsed, at most 150 characters before ``.mp3`` (the title is cut at
    a word boundary)."""
    head = f"{_clean_name(show)} - "
    title = _clean_name(title) or "Episode"
    tail = f" ({_clean_name(date)})"
    room = FILE_NAME_MAX - len(head) - len(tail)
    if room >= 1:
        cut = _cut_words(title, room)
        while _name_bytes(head + cut, tail) > FILE_NAME_MAX_BYTES and len(cut) > 1:
            cut = _cut_words(cut, len(cut) - 1)
        if _name_bytes(head + cut, tail) <= FILE_NAME_MAX_BYTES:
            return f"{head}{cut}{tail}.mp3"
    name = _cut_words(f"{head}{title}", FILE_NAME_MAX - len(tail))
    while _name_bytes(name, tail) > FILE_NAME_MAX_BYTES and len(name) > 1:
        name = _cut_words(name, len(name) - 1)
    return f"{name}{tail}.mp3"


def paris_date(stamp: Any) -> str | None:
    """The calendar date (Europe/Paris) of an ISO time stamp, or None."""
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        when = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return stamp.strip()[:10] if re.match(r"\d{4}-\d{2}-\d{2}", stamp.strip()) else None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        when = when.astimezone(ZoneInfo("Europe/Paris"))
    except Exception:  # noqa: BLE001 - no tz database: the UTC date
        pass
    return when.date().isoformat()


def entry_file_name(entry: dict[str, Any], delivered: Any = None) -> str:
    """``run.json`` ``delivery.file_name`` when it is a clean ``.mp3`` name, else rebuilt
    from the entry's show, title and published date."""
    given = _text(delivered)
    if (
        given
        and given.lower().endswith(".mp3")
        and _clean_name(given) == given
        and len(given) <= FILE_NAME_MAX + 4
        and len(given.encode()) <= FILE_NAME_MAX_BYTES
    ):
        return given
    day = paris_date(entry.get("published")) or "undated"
    return episode_file_name(str(entry.get("show") or SHOW["name"]), str(entry.get("title") or entry.get("id")), day)


def _voice_label(run: dict[str, Any]) -> str:
    engine = str(run.get("engine") or "")
    label = ENGINE_LABELS.get(engine, engine or "unknown")
    model = run.get("model")
    if engine == "voicecast":
        model = model or run.get("voicecast_engine") or run.get("engine_id")
    return f"{label} · {model}" if model else label


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _web_url(value: Any) -> str | None:
    """A public http(s) link, or None (never a javascript:, data: or file: URL)."""
    url = _text(value)
    return url if url and re.match(r"https?://[^/\s]", url, re.IGNORECASE) else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fetched_extra(job: Path, source_id: str) -> dict[str, Any]:
    """An extra source's fetched ``sources/<id>/source.json`` (a regular file inside the
    job, no symlink), or ``{}``."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source_id):
        return {}
    root = job / "sources"
    folder = root / source_id
    path = folder / "source.json"
    if root.is_symlink() or folder.is_symlink() or path.is_symlink() or not path.is_file():
        return {}
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def episode_sources(
    job: Path, script: dict[str, Any], source: dict[str, Any], result: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every source the episode used, main first: ``[{id, title, author, url}]``.

    The extra sources are the objects in ``script.json`` ``sources``. Their credit comes
    from ``result.json`` ``delivery.sources`` when it lists the same sources (DropCast
    usually runs the publisher before it writes the delivered result, so it may be
    missing or from an earlier run), else from the listed title and author, filled from
    the fetched ``sources/<id>/source.json`` and then ``fact_check_pass.sources``. The
    main source is read from ``source.json``. Only public fields are kept: no ``label``
    (it can name a local file).
    """
    listed = [
        item
        for item in (script.get("sources") if isinstance(script.get("sources"), list) else [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] != "main"
    ]
    main = {
        "id": "main",
        "title": _text(source.get("title")),
        "author": _text(source.get("author")),
        "url": _web_url(source.get("url")),
    }
    checked = {
        s.get("id"): s
        for s in (_mapping(script.get("fact_check_pass")).get("sources") or [])
        if isinstance(s, dict)
    }
    by_id = {item["id"]: item for item in listed}

    def complete(source_id: str, given: dict[str, Any]) -> dict[str, Any]:
        """Fill a credit's missing fields from the listed entry, the fetched page and
        the fact-check report, in that order."""
        fetched = _fetched_extra(job, source_id)
        report = _mapping(checked.get(source_id))
        item = by_id.get(source_id, {})
        credit: dict[str, Any] = {"id": source_id}
        for field in ("title", "author", "url"):
            pick = _web_url if field == "url" else _text
            credit[field] = (
                pick(given.get(field))
                or pick(item.get(field))
                or pick(fetched.get(field))
                or pick(report.get(field))
            )
        credit["title"] = credit["title"] or source_id
        return credit

    delivered = _mapping(_mapping(result).get("delivery")).get("sources")
    if isinstance(delivered, list) and all(isinstance(s, dict) for s in delivered):
        ids = [s.get("id") for s in delivered]
        if ids == ["main", *(item["id"] for item in listed)]:
            # The main source's title in result.json falls back to a label ("file x.md");
            # source.json is what the site already credits.
            return [main, *(complete(s["id"], s) for s in delivered[1:])]
    return [main, *(complete(item["id"], {}) for item in listed)]


def episode_credits(
    job: Path, script: dict[str, Any], source: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """The ``sources`` and ``guests`` keys of an index entry, only for an episode with
    extra sources or guests (so an older episode's entry is unchanged)."""
    credits = episode_sources(job, script, source, result)
    titles = {c["id"]: c["title"] for c in credits}
    guests = []
    for speaker in script.get("speakers") or []:
        if not isinstance(speaker, dict) or not str(speaker.get("role") or "").startswith(
            "guest-"
        ):
            continue
        name = _text(speaker.get("name"))
        if not name:
            continue
        presents_ids = speaker.get("presents")
        presents = [
            titles[i]
            for i in (presents_ids if isinstance(presents_ids, list) else [])
            if isinstance(i, str) and i in titles
        ]
        guests.append({"name": name, "presents": presents})
    extra: dict[str, Any] = {}
    if len(credits) > 1:
        extra["sources"] = [{k: c[k] for k in ("title", "author", "url")} for c in credits]
    if guests:
        extra["guests"] = guests
    return extra


def episode_entry(
    job: Path, site: Path, category: str | None = None, media: Any = None
) -> tuple[dict[str, Any], list[Path]]:
    """Upload one job's MP3 to the releases of its show/language media repo (``media`` is a
    factory ``repo -> media``, default ``GhMedia``; ``media_repo()`` picks the repo),
    copy its transcript and art into ``site``, and return its index entry and changed files.

    The skip checks (not rendered, private voices, opted out) run before any upload, and the
    upload runs before anything is written to ``site``: a failed upload raises
    ``UploadError`` and leaves the site and ``episodes.json`` as they were."""
    result = _read_json(job / "result.json") or {}
    run = _read_json(job / "run.json")
    script = _read_json(job / "script.json")
    source = _read_json(job / "source.json") or {}
    request = _read_json(job / "request.json") or {}
    state = _read_json(job / "job.json") or {}
    rendered = ((state.get("steps") or {}).get("render") or {}).get("status") == "done"
    # DropCast runs the publisher inside its reply step, before result.json says
    # "delivered", so a finished render step is what marks the episode as ready.
    if not (rendered or result.get("status") == "delivered") or not isinstance(run, dict):
        raise NotReady("not rendered yet")
    if run.get("private_use"):
        raise Skip("voices are for private use only (edge-tts)")
    if request.get("publish") is False:
        raise Skip("the job opted out of publishing")
    if not isinstance(script, dict):
        raise ValueError("script.json is missing or unreadable")
    episode = job / str(run.get("episode") or "episode.mp3")
    if not episode.is_file():
        raise ValueError(f"{episode.name} is missing")

    episode_id = art_key(job.name)
    dest = site / EPISODES_DIR / episode_id
    title = script.get("title") or source.get("title") or episode_id
    # An index that is there but unreadable stops the job here, before any upload.
    known = {e.get("id"): e for e in (read_index(site / INDEX) or {}).get("episodes") or []
             if isinstance(e, dict)}
    # The MP3 goes to GitHub Releases (podcast #30), never into docs/: the repo of the
    # episode's show and language.
    show = episode_show(job, script)
    repo, media_note = media_repo(show, script.get("language") or "en")
    audio_sha256 = _sha256(episode)
    uploaded = upload_audio(
        (media or GhMedia)(repo),
        episode_id,
        title,
        episode,
        audio_sha256,
        (known.get(episode_id) or {}).get("audio_sha256"),
    )
    changed: list[Path] = []
    transcript = None
    if run.get("transcript") and (job / run["transcript"]).is_file():
        if _copy(job / run["transcript"], dest / "transcript.vtt"):
            changed.append(dest / "transcript.vtt")
        transcript = f"{EPISODES_DIR}/{episode_id}/transcript.vtt"

    hosts = (script.get("show") or {}).get("hosts") or {}
    summary = _summary(job)
    previous = (known.get(episode_id) or {}).get("category")
    chosen = category or _job_category(job)
    if not chosen:
        chosen = (
            "bedtime"
            if script.get("format") == "bedtime-story"
            else previous if previous in CATEGORIES
            else guess_category(title, summary, script.get("format"))
        )
    entry = {
        "id": episode_id,
        "title": title,
        "summary": summary,
        "category": chosen,
        "show": show,  # routed by format, never an old brand
        "hosts": [name for name in (hosts.get("host_a"), hosts.get("host_b")) if name],
        "language": script.get("language") or "en",
        "format": script.get("format"),
        "published": run.get("finished") or run.get("started"),
        "duration_s": run.get("duration_s"),
        "size_bytes": episode.stat().st_size,
        "audio": uploaded["url"],
        "audio_sha256": audio_sha256,
        "transcript": transcript,
        "voices": _voice_label(run),
        "source": {
            "title": source.get("title"),
            "author": source.get("author"),
            "url": source.get("url"),
            "published": source.get("published"),
            "kind": source.get("kind"),
        },
    }
    # Every source used and the guests who presented them (DropCast #94): added only
    # when the episode has extra sources or guests, so other entries stay as they were.
    entry.update(episode_credits(job, script, source, result))
    # Licensed music that needs attribution (e.g. CC-BY): DropCast writes the credit in
    # run.json ``music.credit`` (null for the CC0 theme). Added only when it is set, so
    # other entries stay as they were.
    music_credit = _text(_mapping(run.get("music")).get("credit"))
    if music_credit:
        entry["music_credit"] = music_credit
    # One story in several languages (DropCast #136): every version's script.json carries
    # the same ``story_group`` and its own ``language`` (copied above); the story page
    # lists the versions as one story with a language switch. Added only when set, so
    # other entries stay as they were.
    story_group = _text(script.get("story_group"))
    if story_group:
        entry["story_group"] = story_group
    # The story's illustration (one per story group): copied to docs/art/<key>/ and named
    # in ``image``. Without one here (e.g. a re-publish from a machine without the art), an
    # image already in episodes.json is kept. Added only when set, so other entries stay
    # as they were.
    try:
        image, art_files = episode_image(job, site, episode_id, story_group)
    except ValueError as exc:
        image, art_files = None, []
        entry["_art_problems"] = [str(exc)]
    changed += art_files
    image = image or _valid_image((known.get(episode_id) or {}).get("image"))
    if image:
        entry["image"] = image
    # The copy-paste description and the download name (DropCast #161/#163): the job's
    # description.txt, else a hand-edited one already in episodes.json (it survives a
    # re-publish), else one built from the summary, sources and tagline. A generated one
    # is marked ``description_source: "generated"`` and rebuilt on every publish, so it
    # follows a changed summary; delete the marker to keep a hand edit.
    written, problems = job_description(job)
    if problems:
        entry["_description_problems"] = problems
    previous = known.get(episode_id) or {}
    previous_text = _text(previous.get("description"))
    if previous_text and (
        description_problems(previous_text) or previous.get("description_source") == "generated"
    ):
        previous_text = None
    if written:
        entry["description"], entry["description_source"] = written, "description.txt"
    elif previous_text:
        entry["description"] = previous_text
        if previous.get("description_source"):
            entry["description_source"] = previous["description_source"]
    else:
        entry["description"], entry["description_source"] = fallback_description(entry), "generated"
    entry["file_name"] = entry_file_name(entry, _mapping(run.get("delivery")).get("file_name"))
    if media_note:
        entry["_media_note"] = media_note
    # A copy left in docs/ from before the move (podcast #30) is removed by main() only
    # after the index update and a HEAD check of the new URL (remove_stale_audio()).
    return entry, changed


def remove_stale_audio(
    site: Path, entries: list[dict[str, Any]], verify: Any = None
) -> tuple[list[Path], list[str]]:
    """Remove ``site/episodes/<id>/episode.mp3`` left from before the move (podcast #30)
    for each published entry, once its release URL answers HEAD with status 200 and a
    length equal to ``size_bytes`` (``verify``, default ``head_audio``). Call it only after
    ``update_index()`` succeeded. A copy that fails the check is kept and noted.
    Returns (removed files, notes)."""
    verify = verify or head_audio
    removed: list[Path] = []
    notes: list[str] = []
    for entry in entries:
        stale = site / EPISODES_DIR / art_key(entry["id"]) / "episode.mp3"
        url = entry.get("audio")
        if stale.is_symlink() or not stale.is_file() or not _is_release_url(url):
            continue
        answer = verify(url)
        if _verified(answer, entry.get("size_bytes")):
            stale.unlink()
            removed.append(stale)
        else:
            notes.append(
                f"{entry['id']}: kept the old {EPISODES_DIR}/{entry['id']}/episode.mp3: HEAD {url} gave status "
                f"{answer.get('status')}, length {answer.get('length')} (expected 200, {entry.get('size_bytes')}); "
                "publish again to retry"
            )
    return removed, notes


def _is_release_url(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _verified(answer: dict[str, Any], size: Any) -> bool:
    """A HEAD answer (``head_audio()``) of a live asset of ``size`` bytes."""
    return answer.get("status") == 200 and isinstance(size, int) and answer.get("length") == size


def update_index(site: Path, entries: list[dict[str, Any]]) -> bool:
    """Add or replace ``entries`` in ``episodes.json``; True when the file changed. A new
    index is started only when there is no file; one that cannot be parsed raises
    ``ValueError`` and is left as it is (``read_index()``)."""
    path = site / INDEX
    current = read_index(path) or {}
    episodes = {e["id"]: e for e in current.get("episodes") or [] if isinstance(e, dict)}
    for entry in entries:
        episodes[entry["id"]] = entry
    ordered = sorted(episodes.values(), key=lambda e: e.get("published") or "", reverse=True)
    if ordered == current.get("episodes"):
        return False
    data = {
        "version": 1,
        "show": SHOW,
        "shows": SHOWS,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episodes": ordered,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, data)
    return True


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=300
    )


PUBLISH_SUBJECT = "feat(episodes): publish "
MIGRATE_SUBJECT = "feat(site): move episode audio to GitHub Releases (#30)"
BACKFILL_SUBJECT = "feat(site): backfill episode descriptions, pages and story art"
ORIGIN_MAIN = "refs/remotes/origin/main"


# The lines of git's output that say what failed and where: a failed rebase names the
# conflicting files only in its CONFLICT lines, which git prints on stdout, not stderr.
_GIT_KEY_LINE = re.compile(r"(?:CONFLICT\b|error:|fatal:|could not apply\b)", re.IGNORECASE)
GIT_ERROR_LIMIT = 800


def _git_error(proc: subprocess.CompletedProcess[str], limit: int = GIT_ERROR_LIMIT) -> str:
    """What a failed git command said, at most ``limit`` characters: its first line, every
    CONFLICT/error/fatal/could-not-apply line (stderr and stdout), and its last line. git's
    ``hint:`` lines are dropped when the whole text does not fit."""
    err, out = (proc.stderr or "").strip(), (proc.stdout or "").strip()
    text = err or out
    if not text:
        return f"exit {proc.returncode}"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    extra = [line.strip() for line in (out.splitlines() if err else []) if _GIT_KEY_LINE.match(line.strip())]
    if len(text) <= limit and not extra:
        return text
    useful = [line for line in lines if not line.startswith("hint:")] or lines
    key = [line for line in useful[1:-1] if _GIT_KEY_LINE.match(line)]
    picked: list[str] = []
    for line in [useful[0], *key, *extra, useful[-1]]:
        if line not in picked:
            picked.append(line)
    kept: list[str] = []
    size = 0
    for line in picked:
        line = line if len(line) <= 240 else line[:239] + "…"
        if size + len(line) + 1 > limit:
            kept.append("…")
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept)


def _rebase_in_progress() -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        path = _git("rev-parse", "--git-path", name).stdout.strip()
        if path and (REPO / path).exists():
            return True
    return False


def _abort_rebase() -> str:
    """Abort a rebase that a failed ``git pull --rebase`` left stopped (it would leave
    ``HEAD`` on origin's commit, without this run's), so the local branch and its commit
    are back as they were. Returns a sentence for the error ('' when there was none)."""
    if not _rebase_in_progress():
        return ""
    aborted = _git("rebase", "--abort")
    if aborted.returncode != 0 or _rebase_in_progress():
        return (f" git rebase --abort failed too ({_git_error(aborted)}): this checkout is still"
                " mid-rebase; run git rebase --abort by hand before anything else.")
    return " The stopped rebase was aborted (git rebase --abort)."


def _unpushed_commits() -> tuple[list[str], str | None]:
    """``(shas, refusal)`` for the commits on HEAD that origin/main (as last fetched) does
    not have: what an earlier run committed but could not push.

    ``shas`` is non-empty only when every one of them is this script's own: its commit
    subject, on branch ``main``, changing files under the site folder (``docs/``) only.
    Commits with other subjects (someone's local work) give ``([], None)``: they are left
    alone, silently. Script-titled commits that fail the branch or file check give
    ``([], refusal)``: they are not pushed either, and ``refusal`` says why, so the run
    fails and a person looks."""
    proc = _git("log", "--format=%H %s", f"{ORIGIN_MAIN}..HEAD")
    if proc.returncode != 0:
        return [], None
    commits = [line.partition(" ") for line in proc.stdout.splitlines() if line.strip()]
    if not commits or not all(s.startswith((PUBLISH_SUBJECT, MIGRATE_SUBJECT, BACKFILL_SUBJECT))
                              for _, _, s in commits):
        return [], None
    shas = [sha for sha, _, _ in commits]
    listed = ", ".join(sha[:12] for sha in shas[:5]) + (", …" if len(shas) > 5 else "")
    refused = (f"{len(shas)} earlier unpushed commit(s) with this script's commit subject ({listed}) were not"
               " pushed: {why}. Look at them (git log --stat origin/main..HEAD), then push or drop them by hand.")
    branch = _git("symbolic-ref", "-q", "--short", "HEAD")
    name = branch.stdout.strip() if branch.returncode == 0 else ""
    if name != "main":
        where = f"branch {name!r}" if name else "a detached HEAD"
        return [], refused.format(why=f"this checkout is on {where}, not main")
    site = SITE.resolve().relative_to(REPO.resolve()).as_posix().rstrip("/") + "/"
    outside: list[str] = []
    for sha in shas:
        files = _git("diff-tree", "-r", "-m", "--root", "--no-commit-id", "--no-renames", "--name-only", "-z", sha)
        if files.returncode != 0:
            return [], refused.format(why=f"git diff-tree {sha[:12]} failed ({_git_error(files)})")
        outside += [p for p in files.stdout.split("\0") if p and not p.startswith(site) and p not in outside]
    if outside:
        shown = ", ".join(outside[:10]) + (", …" if len(outside) > 10 else "")
        return [], refused.format(why=f"they change files outside {site} ({shown})")
    return shas, None


def _has_unpushed() -> bool:
    """Whether ``push()`` has earlier commits to push, or to refuse (``_unpushed_commits()``)."""
    shas, refusal = _unpushed_commits()
    return bool(shas or refusal)


def _confirm_pushed(sha: str, note: str | None = None) -> dict[str, Any]:
    """``git push`` exited 0: fetch origin/main and report ``pushed`` only if it holds
    ``sha`` (a push from a stopped rebase "succeeds" with origin's own commit)."""
    result: dict[str, Any] = {"pushed": False, "commit": sha}
    if note:
        result["note"] = note
    fetched = _git("fetch", "-q", "origin", f"+refs/heads/main:{ORIGIN_MAIN}")
    if fetched.returncode != 0:
        result["error"] = (f"git push exited 0 but origin/main could not be fetched to check that it holds"
                           f" {sha[:12]} ({_git_error(fetched)}); check origin before publishing again")
        return result
    if _git("merge-base", "--is-ancestor", sha, ORIGIN_MAIN).returncode != 0:
        result["error"] = (f"git push exited 0 but origin/main does not hold this run's commit {sha[:12]}:"
                           " it did not reach origin. The commit is kept on the local branch; run the same"
                           " command again to push it")
        return result
    result["pushed"] = True
    return result


def push(paths: list[Path], titles: list[str], subject: str | None = None) -> dict[str, Any]:
    """Commit ``paths`` (only those: nothing else staged in the index) and push to origin
    main. With no change of its own, it pushes only the earlier commits
    ``_unpushed_commits()`` accepts, and fails on the ones it refuses. ``pushed`` is True
    only once origin/main holds the commit; a rejected push is rebased onto origin once,
    and a rebase that fails is aborted (the local commit is kept) and reported as an error."""
    rel = sorted({str(p.relative_to(REPO)) for p in paths})
    present = [r for r in rel if (REPO / r).exists()]
    gone = [r for r in rel if r not in present]
    add = _git("add", "--", *present) if present else None
    if add is not None and add.returncode != 0:
        return {"pushed": False, "error": add.stderr.strip()}
    if gone:
        # Files removed from docs/ (e.g. an episode MP3 moved to GitHub Releases).
        removed = _git("rm", "-q", "--cached", "--ignore-unmatch", "--", *gone)
        if removed.returncode != 0:
            return {"pushed": False, "error": removed.stderr.strip()}
    note = None
    # Only this run's own paths: anything else staged in the index (someone's work) is
    # never looked at, committed or pushed. No paths of its own means no commit at all.
    own: list[str] = []
    if rel:
        staged = _git("--literal-pathspecs", "diff", "--cached", "--name-only", "-z", "--no-renames", "--", *rel)
        if staged.returncode != 0:
            return {"pushed": False, "error": f"git diff --cached failed: {_git_error(staged)}"}
        own = sorted({p for p in staged.stdout.split("\0") if p})
    if not own:
        earlier, refusal = _unpushed_commits()
        if refusal:
            return {"pushed": False, "error": refusal}
        if not earlier:
            return {"pushed": False, "error": None, "note": "nothing to commit"}
        # An earlier run committed but could not push (e.g. a lost rebase, resolved since).
        note = f"nothing new to commit; pushing {len(earlier)} earlier unpushed commit(s)"
    else:
        subject = subject or (
            f"{PUBLISH_SUBJECT}{titles[0]}"
            if len(titles) == 1
            else f"{PUBLISH_SUBJECT}{len(titles)} episodes"
        )
        # --only with the run's own changed paths: the rest of the index stays as it was.
        commit = _git("--literal-pathspecs", "commit", "--only", "-m", subject[:120], "--", *own)
        if commit.returncode != 0:
            return {"pushed": False, "error": commit.stderr.strip() or commit.stdout.strip()}
    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        return {"pushed": False, "error": f"git rev-parse HEAD failed: {_git_error(head)}"}
    sha = head.stdout.strip()
    pushed = _git("push", "origin", "HEAD:main")
    if pushed.returncode == 0:
        return _confirm_pushed(sha, note)
    # Rejected (origin moved on): replay this commit on origin/main once, then push again.
    pulled = _git("pull", "--rebase", "origin", "main")
    if pulled.returncode != 0:
        aborted = _abort_rebase()
        kept = _git("rev-parse", "HEAD").stdout.strip()
        where = (f"this run's commit {sha[:12]} is kept on the local branch" if kept == sha
                 else f"HEAD is now {kept[:12] or 'unknown'}, not this run's commit {sha[:12]}")
        return {"pushed": False, "commit": sha, "error": (
            f"git push was rejected (origin/main moved) and git pull --rebase origin main failed"
            f" ({_git_error(pulled)}).{aborted} Nothing was pushed; {where}. Resolve it by hand"
            " (git pull --rebase origin main, fix the conflicts, git add, git rebase --continue),"
            " then run the same command again: it pushes that commit."
        )}
    head = _git("rev-parse", "HEAD")
    sha = head.stdout.strip()
    if head.returncode != 0 or not _git("log", "-1", "--format=%H", f"{ORIGIN_MAIN}..HEAD").stdout.strip():
        return {"pushed": False, "commit": sha or None, "error": (
            "git pull --rebase origin main left no local commit to push (origin/main may already"
            " have the same changes); nothing was pushed: check origin/main")}
    pushed = _git("push", "origin", "HEAD:main")
    if pushed.returncode != 0:
        return {"pushed": False, "commit": sha, "error": _git_error(pushed)}
    return _confirm_pushed(sha, note)


@contextlib.contextmanager
def _lock():
    """One publisher at a time (two episodes can finish together)."""
    # The shared git dir, so a linked worktree (where .git is a file) locks the same file.
    common = _git("rev-parse", "--git-common-dir").stdout.strip() or ".git"
    path = (REPO / common).resolve() / "podcast-publish.lock"
    with path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _load_script(name: str) -> Any:
    """A sibling script (``scripts/<name>.py``) as a module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"scripts/{name}.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rebuild_feeds(report: dict[str, Any], site: Path | None = None) -> list[Path]:
    """Rewrite the RSS feeds (scripts/feed.py); a failure is recorded as ``feed_error``
    (never raised); a publish then removes and pushes nothing."""
    try:
        return list(_load_script("feed").write_feeds(site or SITE))
    except Exception as exc:  # noqa: BLE001 - the episode is still published
        report["feed_error"] = f"{type(exc).__name__}: {exc}"
        return []


def _rebuild_pages(report: dict[str, Any], site: Path | None = None) -> list[Path]:
    """Rewrite the episode pages and sitemap (scripts/pages.py); a failure is recorded as
    ``pages_error`` (never raised); a publish then removes and pushes nothing."""
    try:
        return list(_load_script("pages").write_pages(site or SITE))
    except Exception as exc:  # noqa: BLE001 - the episode is still published
        report["pages_error"] = f"{type(exc).__name__}: {exc}"
        return []


def backfill(
    site: Path, jobs_root: Path, art_changed: list[Path] | None = None
) -> tuple[bool, list[dict[str, Any]]]:
    """Give every ``episodes.json`` entry without one a ``description``, a ``file_name``
    and (when its story has one) an ``image``.

    A job folder still on this machine (``jobs_root/<id>``) gives its ``description.txt``
    and ``run.json`` ``delivery.file_name`` when usable; otherwise the description is
    ``fallback_description()`` of the entry and the name is rebuilt from its show, title
    and published date. The illustration is found as when publishing
    (``find_illustration()``: the job's own ``illustration/``, else a job in ``jobs_root``
    of the same ``story_group``), copied to ``site/art/<key>/`` and the copied files are
    appended to ``art_changed``. Entries that already have them are left as they are.
    Returns (index changed, what was filled per entry).
    """
    art: list[Path] = []
    path = site / INDEX
    data = read_index(path)
    if data is None:
        raise ValueError(f"{INDEX} is missing")
    filled = []
    for entry in data["episodes"]:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        job = jobs_root / str(entry["id"])
        done: dict[str, Any] = {"id": entry["id"]}
        if not _text(entry.get("description")):
            written, problems = job_description(job) if job.is_dir() else (None, [])
            entry["description"] = written or fallback_description(entry)
            done["description"] = entry["description_source"] = (
                "description.txt" if written else "generated"
            )
            if problems:
                done["description_problems"] = problems
        if not _text(entry.get("file_name")):
            run = _mapping(_read_json(job / "run.json")) if job.is_dir() else {}
            entry["file_name"] = entry_file_name(entry, _mapping(run.get("delivery")).get("file_name"))
            done["file_name"] = entry["file_name"]
        if not entry.get("image"):
            group = _text(entry.get("story_group")) or (_story_group_of(job) if job.is_dir() else None)
            try:
                image, files = episode_image(job, site, str(entry["id"]), group, jobs_root)
            except ValueError as exc:
                image, files = None, []
                done["image_problems"] = [str(exc)]
            if image:
                entry["image"] = image
                done["image"] = image["wide"].rsplit("/", 1)[0]
                art.extend(f for f in files if f not in art)
        if len(done) > 1:
            filled.append(done)
    if art_changed is not None:
        art_changed.extend(art)
    if not any(set(f) - {"id", "image_problems"} for f in filled):
        return False, filled
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_json(path, data)
    return True, filled


class MigrationError(RuntimeError):
    """The migration stopped after ``episodes.json`` was updated; running it again finishes
    it. ``report`` is the migration report so far."""

    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


def _rebuild_site(site: Path) -> tuple[list[Path], dict[str, str]]:
    """Rebuild the feeds and pages of ``site``: (changed files, ``feed_error``/``pages_error``)."""
    errors: dict[str, Any] = {}
    files = _rebuild_feeds(errors, site) + _rebuild_pages(errors, site)
    return files, errors


def release_problems(site: Path, entries: list[dict[str, Any]]) -> list[str]:
    """What still points at the docs/ copy of ``entries`` (each with its release ``audio``):
    every feed that lists an entry must have its enclosure on the release URL (any ``?v=``),
    no feed may link ``episodes/<id>/episode.mp3`` of one of them, and no episode page may
    either. Empty when the rebuilt site is ready for the local MP3s to go."""
    feed = _load_script("feed")
    pages = _load_script("pages")
    index = read_index(site / INDEX) or {}
    wanted = {str(e["id"]): str(e["audio"]) for e in entries}
    local = {ep_id: f"{EPISODES_DIR}/{ep_id}/episode.mp3" for ep_id in wanted}
    problems: list[str] = []
    for key, meta in feed.FEEDS.items():
        listed = [str(e["id"]) for e in feed.feed_episodes(index, key) if str(e.get("id")) in wanted]
        path = site / meta["file"]
        if not listed and not path.exists():
            continue
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            problems.append(f"{meta['file']}: unreadable ({type(exc).__name__})")
            continue
        urls = [str(enc.get("url") or "") for enc in root.iter("enclosure")]
        bare = {u.split("?", 1)[0] for u in urls}
        problems += [f"{meta['file']}: no enclosure at {wanted[i]} for {i}" for i in listed if wanted[i] not in bare]
        problems += [
            f"{meta['file']}: {i} still links {local[i]}" for i in wanted if any(local[i] in u for u in urls)
        ]
    for ep_id in wanted:
        page = site / pages.page_path(ep_id) / "index.html"
        try:
            html = page.read_text(encoding="utf-8")
        except OSError:
            continue
        if local[ep_id] in html:
            problems.append(f"{pages.page_path(ep_id)}index.html still links {local[ep_id]}")
    return problems


def migrate_audio(
    site: Path,
    media: Any = None,
    verify: Any = None,
    remove: Any = None,
    dry_run: bool = False,
    rebuild: Any = None,
) -> dict[str, Any]:
    """Move every MP3 still in ``site`` to the releases of its show/language media repo
    (``entry_media_repo()``; podcast #30), in an order where every state in between is
    consistent and running it again finishes the job:

    1. Find the work: entries whose ``audio`` is a local ``episodes/<id>/episode.mp3``
       (to move), and leftovers of an interrupted run: a ``site/episodes/<id>/episode.mp3``
       whose entry already has its release URL and an ``audio_sha256`` and ``size_bytes``
       matching the file (any other copy is kept and noted in ``kept``).
    2. Upload each file to move as ``upload_audio()`` does when publishing (``media`` is a
       factory ``repo -> media``, default ``GhMedia``).
    3. Check every URL (moved and leftover): ``verify(url)`` (default ``head_audio``: HEAD,
       redirects followed) must answer status 200 with a length equal to the size.
    4. Set each moved entry's ``audio`` (the release URL), ``size_bytes`` and
       ``audio_sha256`` and write ``episodes.json`` (atomically).
    5. Rebuild the feeds and pages (``rebuild(site)`` -> (changed files, errors), default
       feed.py and pages.py) and check them with ``release_problems()``.
    6. Only then ``remove(path)`` each local MP3 (default: ``git rm``).

    A failure in 2-3 raises ``UploadError`` with nothing changed. A failure in 5-6 raises
    ``MigrationError`` (with the report so far); the local files are still there, so the
    entries are leftovers that the next run verifies, rebuilds and removes. ``dry_run``
    lists the work (ids, repos, sizes, target URLs) and uploads nothing. With nothing to
    do, nothing is called or written. Returns the report (``changed`` lists the files
    written or removed); raises ``UploadError``, ``MigrationError`` or ``ValueError``.
    """
    verify = verify or head_audio
    path = site / INDEX
    data = read_index(path)
    if data is None:
        raise ValueError(f"{INDEX} is missing")
    todo = []
    leftovers = []
    kept = []
    for entry in data["episodes"]:
        if not isinstance(entry, dict):
            continue
        local_id = local_audio_id(entry.get("audio"))
        if local_id is None:
            found = _leftover(site, entry)
            if isinstance(found, str):
                kept.append(found)
            elif found is not None:
                leftovers.append((entry, found))
            continue
        if local_id != entry.get("id"):
            raise ValueError(f"{entry.get('id')}: audio {entry['audio']!r} names another episode")
        mp3 = site / entry["audio"]
        if mp3.is_symlink() or not mp3.is_file():
            raise ValueError(f"{entry['id']}: {entry['audio']} is missing")
        repo, note = entry_media_repo(entry)
        todo.append((entry, mp3, repo, note))
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "already_moved": sum(
            1 for e in data["episodes"] if isinstance(e, dict) and e.get("audio") and not local_audio_id(e.get("audio"))
        ),
        "count": len(todo),
        "total_bytes": sum(mp3.stat().st_size for _, mp3, _, _ in todo),
        "repos": {},
        "episodes": [],
        "leftovers": [{"id": e["id"], "file": str(mp3.relative_to(site)), "audio": e["audio"]} for e, mp3 in leftovers],
        "changed": [],
    }
    if kept:
        report["kept"] = kept
    for entry, mp3, repo, note in todo:
        size = mp3.stat().st_size
        per_repo = report["repos"].setdefault(repo, {"count": 0, "total_bytes": 0})
        per_repo["count"] += 1
        per_repo["total_bytes"] += size
        item = {"id": entry["id"], "repo": repo, "file": entry["audio"], "size_bytes": size,
                "audio": audio_url(repo, entry["id"])}
        if note:
            item["note"] = note
            report.setdefault("notes", []).append(f"{entry['id']}: {note}")
        report["episodes"].append(item)
    if dry_run or not (todo or leftovers):
        return report
    factory = media or GhMedia
    done = []
    for (entry, mp3, repo, _note), item in zip(todo, report["episodes"]):
        sha = _sha256(mp3)
        result = upload_audio(factory(repo), entry["id"], entry.get("title") or entry["id"], mp3, sha,
                              entry.get("audio_sha256"))
        item["uploaded"] = result["uploaded"]
        item["audio_sha256"] = sha
        done.append((entry, mp3, result["url"], sha, mp3.stat().st_size))
    checks = [(e["id"], url, size) for e, _mp3, url, _sha, size in done]
    checks += [(e["id"], e["audio"], e["size_bytes"]) for e, _mp3 in leftovers]
    failures = []
    for ep_id, url, size in checks:
        answer = verify(url)
        if not _verified(answer, size):
            failures.append(
                f"{ep_id}: HEAD {url} gave status {answer.get('status')}, "
                f"length {answer.get('length')} (expected 200, {size})"
            )
    if failures:
        raise UploadError("verification failed, nothing removed: " + "; ".join(failures))
    if done:
        for entry, _mp3, url, sha, size in done:
            entry["audio"], entry["size_bytes"], entry["audio_sha256"] = url, size, sha
        data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_json(path, data)
        report["changed"].append(path)
    files, errors = (rebuild or _rebuild_site)(site)
    report["changed"] += [f for f in files if f not in report["changed"]]
    if errors:
        report.update(errors)
        raise MigrationError(
            "feeds or pages were not rebuilt, nothing removed (run --migrate-audio again): "
            + "; ".join(errors.values()), report
        )
    moving = [e for e, *_ in done] + [e for e, _mp3 in leftovers]
    problems = release_problems(site, moving)
    if problems:
        report["release_problems"] = problems
        raise MigrationError(
            "the rebuilt feeds or pages do not use the release URLs, nothing removed: " + "; ".join(problems[:5]),
            report,
        )
    remove = remove or _git_rm
    not_removed = []
    for mp3 in [m for _e, m, *_ in done] + [m for _e, m in leftovers]:
        try:
            remove(mp3)
        except OSError as exc:
            not_removed.append(f"{mp3.relative_to(site)}: {exc}")
            continue
        report["changed"].append(mp3)
    if not_removed:
        report["not_removed"] = not_removed
        raise MigrationError(
            f"{len(not_removed)} local MP3(s) not removed (run --migrate-audio again to finish): "
            + "; ".join(not_removed[:5]),
            report,
        )
    return report


def _leftover(site: Path, entry: dict[str, Any]) -> Path | str | None:
    """The docs/ MP3 of an entry already on its release URL when it is the uploaded file
    (``audio_sha256`` and ``size_bytes`` match), a note when a copy is there but is not,
    else None."""
    try:
        ep_id = art_key(entry.get("id"))
    except ValueError:
        return None
    mp3 = site / EPISODES_DIR / ep_id / "episode.mp3"
    if not _is_release_url(entry.get("audio")) or mp3.is_symlink() or not mp3.is_file():
        return None
    where = f"{EPISODES_DIR}/{ep_id}/episode.mp3"
    if entry["audio"] != audio_url(entry_media_repo(entry)[0], ep_id):
        return f"{ep_id}: kept {where}: audio {entry['audio']} is not its release URL"
    if entry.get("size_bytes") != mp3.stat().st_size or entry.get("audio_sha256") != _sha256(mp3):
        return f"{ep_id}: kept {where}: it is not the file of audio_sha256/size_bytes"
    return mp3


def _git_rm(path: Path) -> None:
    """``git rm`` one file of the site (a file git does not track is just deleted)."""
    removed = _git("rm", "-q", "--", str(path.relative_to(REPO)))
    if removed.returncode != 0:
        if _git("ls-files", "--error-unmatch", "--", str(path.relative_to(REPO))).returncode == 0:
            raise OSError(f"git rm {path.name} failed: {removed.stderr.strip()}")
        path.unlink(missing_ok=True)


def _jobs_root() -> Path:
    home = os.environ.get("DROPCAST_HOME") or "~/dropcast"
    return Path(home).expanduser() / "jobs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("jobs", nargs="*", metavar="JOB", help="DropCast job folder(s)")
    parser.add_argument("--all", action="store_true", help="every job in $DROPCAST_HOME/jobs")
    parser.add_argument("--push", action="store_true", help="commit and push the changes")
    parser.add_argument(
        "--backfill", action="store_true",
        help="give every episodes.json entry a description, file_name and story art; rebuild feeds and pages",
    )
    parser.add_argument(
        "--category", choices=CATEGORIES, help="the site tab for this one job (default: guessed)"
    )
    parser.add_argument(
        "--migrate-audio", action="store_true",
        help="move the MP3s still in docs/ to GitHub Releases (uploads, checks, then git rm)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="with --migrate-audio: list the work, upload nothing"
    )
    args = parser.parse_args(argv)
    jobs = [Path(j).expanduser() for j in args.jobs]
    if args.dry_run and not args.migrate_audio:
        parser.print_usage(sys.stderr)
        print("error: --dry-run goes with --migrate-audio", file=sys.stderr)
        return 2
    if args.migrate_audio:
        if args.all or jobs or args.category or args.backfill or (args.dry_run and args.push):
            parser.print_usage(sys.stderr)
            print("error: --migrate-audio takes only --push or --dry-run", file=sys.stderr)
            return 2
        return _migrate_main(args.push, args.dry_run)
    if args.backfill and (args.all or jobs or args.category):
        parser.print_usage(sys.stderr)
        print("error: --backfill takes no job folder, --all or --category", file=sys.stderr)
        return 2
    if args.backfill:
        return _backfill_main(args.push)
    if args.category and (args.all or len(jobs) != 1):
        parser.print_usage(sys.stderr)
        print("error: --category needs exactly one job folder", file=sys.stderr)
        return 2
    if args.all:
        root = _jobs_root()
        jobs += sorted(p for p in root.glob("*") if p.is_dir())
    if not jobs:
        parser.print_usage(sys.stderr)
        print("error: give a job folder or --all", file=sys.stderr)
        return 2

    report: dict[str, Any] = {"published": [], "skipped": [], "failed": [], "git": None}
    with _lock():
        if args.push and not _start_pull(report, "the same publish"):
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        try:
            # An index that is there but unreadable (e.g. conflict markers) stops the run
            # before any upload: it is never replaced by a new one-episode index.
            read_index(SITE / INDEX)
        except ValueError as exc:
            report["failed"].append({"job": INDEX, "error": str(exc)})
            report["changed"] = []
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        entries: list[dict[str, Any]] = []
        changed: list[Path] = []
        named = set(args.jobs and [Path(j).expanduser().resolve() for j in args.jobs])
        for job in jobs:
            try:
                entry, files = episode_entry(job.resolve(), SITE, args.category, GhMedia)
            except NotReady as why:
                bucket = "failed" if job.resolve() in named else "skipped"
                key = "error" if bucket == "failed" else "reason"
                report[bucket].append({"job": job.name, key: str(why)})
                continue
            except Skip as why:
                report["skipped"].append({"job": job.name, "reason": str(why)})
                continue
            except (OSError, ValueError, UploadError) as exc:
                report["failed"].append({"job": job.name, "error": str(exc)})
                continue
            problems = entry.pop("_description_problems", None)
            if problems:
                report.setdefault("notes", []).append(
                    f"{job.name}: description.txt not used ({'; '.join(problems)}); kept the existing or a generated one"
                )
            note = entry.pop("_media_note", None)
            if note:
                report.setdefault("notes", []).append(f"{job.name}: {note}")
            for problem in entry.pop("_art_problems", None) or []:
                report.setdefault("notes", []).append(f"{job.name}: illustration not published ({problem})")
            entries.append(entry)
            changed += files
            report["published"].append({"id": entry["id"], "title": entry["title"]})
        blocked = False
        if entries:
            try:
                if update_index(SITE, entries):
                    changed.append(SITE / INDEX)
            except ValueError as exc:
                report["failed"].append({"job": INDEX, "error": str(exc)})
                blocked = True
        if entries and not blocked:
            # The Once Upon a Time Show feeds (Spotify) follow episodes.json on their own.
            changed += _rebuild_feeds(report)
            # One static page per episode and the sitemap (search engines) follow it too.
            changed += _rebuild_pages(report)
            error = report.get("feed_error") or report.get("pages_error")
            if error:
                # Same rule as --migrate-audio: never remove a docs/ copy or push while a feed
                # or page may still link it. The changes stay in the work tree; publishing
                # again rebuilds and pushes them (_pending_publish()).
                report["failed"].append({
                    "job": "rebuild",
                    "error": f"{error}; nothing pushed and no docs/ MP3 removed: publish again",
                })
                blocked = True
            else:
                # Leftover docs/ copies go only now: after the index update and a good
                # rebuild, once HEAD checks out.
                removed, notes = remove_stale_audio(SITE, entries, head_audio)
                changed += removed
                if notes:
                    report.setdefault("notes", []).extend(notes)
        if args.push and entries and not blocked:
            # What an earlier run left uncommitted (e.g. a failed rebuild) goes in too.
            try:
                changed += [p for p in _pending_publish(SITE) if p not in changed]
            except OSError as exc:
                report["failed"].append({"job": "git", "error": str(exc)})
                blocked = True
        if args.push and not blocked and (changed or _has_unpushed()):
            report["git"] = push(changed, [e["title"] for e in entries])
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] else 0


def _pending_migration(site: Path) -> list[Path]:
    """The migration's files that differ from HEAD (git status): ``episodes.json``, the
    feeds, the sitemap, the episode pages, and episode MP3s removed from the work tree.
    A run that stopped after some of its changes (e.g. a failed removal) leaves them
    uncommitted, so the next ``--push`` run commits them with its own."""
    return _pending_site(site)


def _pending_publish(site: Path) -> list[Path]:
    """``_pending_migration()`` plus the episode transcripts and the story art: what a
    publish that stopped before its push (a failed rebuild) left uncommitted, so the next
    ``--push`` run commits it with its own."""
    rel = site.resolve().relative_to(REPO.resolve()).as_posix()
    return _pending_site(site, f":(glob){rel}/{EPISODES_DIR}/*/transcript.vtt", f"{rel}/{ART_DIR}")


def _pending_site(site: Path, *extra: str) -> list[Path]:
    feed = _load_script("feed")
    pages = _load_script("pages")
    rel = site.resolve().relative_to(REPO.resolve()).as_posix()
    specs = [f"{rel}/{INDEX}", f"{rel}/{pages.SITEMAP}", *(f"{rel}/{m['file']}" for m in feed.FEEDS.values()),
             f":(glob){rel}/{EPISODES_DIR}/*/index.html", f":(glob){rel}/{EPISODES_DIR}/*/episode.mp3", *extra]
    proc = _git("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all", "--", *specs)
    if proc.returncode != 0:
        raise OSError(f"git status failed: {(proc.stderr or '').strip()[:300]}")
    found = []
    for record in proc.stdout.split("\0"):
        if len(record) < 4:
            continue
        path = REPO / record[3:]
        if path.suffix == ".mp3" and path.exists():
            continue  # only the removal of an MP3 is ever committed
        found.append(path)
    return found


def _stashes() -> list[tuple[str, str]]:
    """``git stash list`` as (commit sha, subject), newest first."""
    proc = _git("stash", "list", "--format=%H %gs")
    found = []
    for line in (proc.stdout or "").splitlines():
        sha, _, subject = line.strip().partition(" ")
        if sha:
            found.append((sha, subject))
    return found


def _conflicted_autostash(stashes_before: list[tuple[str, str]], pulled: subprocess.CompletedProcess[str],
                          again: str = "--migrate-audio --push") -> str | None:
    """Why the work tree is not safe to publish or migrate after ``git pull --rebase
    --autostash`` (which exits 0 even when putting the stashed changes back conflicts), or
    None: unmerged paths, conflict markers in ``episodes.json``, a stash this pull left
    behind, or git saying so. ``again`` names the command to run once it is resolved."""
    unmerged = [p for p in (_git("diff", "--name-only", "--diff-filter=U", "-z").stdout or "").split("\0") if p]
    known = {sha for sha, _ in stashes_before}
    left = [(sha, subject) for sha, subject in _stashes() if sha not in known]
    output = f"{pulled.stdout or ''}\n{pulled.stderr or ''}"
    said = "resulted in conflicts" in output
    try:
        marked = bool(_CONFLICT_MARKER.search((SITE / INDEX).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        marked = False
    if not (unmerged or left or said or marked):
        return None
    found = []
    if unmerged:
        found.append("unmerged paths " + ", ".join(unmerged[:10]))
    if marked:
        found.append(f"conflict markers in {SITE.name}/{INDEX}")
    if left and not found:
        found.append("the autostash was not applied")
    where = (f"stash {left[0][0][:12]} ({left[0][1] or 'autostash'})" if left else "the stash (git stash list)")
    return (
        "git pull --rebase --autostash could not put this checkout's uncommitted changes back"
        f" ({'; '.join(found) or 'git reported conflicts'}). Nothing was uploaded, pushed or removed."
        f" The interrupted run's changes are kept in {where}. Resolve the conflicts by hand"
        " (git status; git stash show -p shows the stashed changes), git add the files, drop that stash"
        f" once its changes are in the work tree, then run {again} again."
        " Hold the publish cron in this checkout until git status is clean."
    )


def _start_pull(report: dict[str, Any], again: str) -> bool:
    """The pull every ``--push`` command runs first: ``git pull --rebase --autostash``
    (a re-run after a failed or interrupted run starts from a dirty tree, which a plain pull
    refuses, and would then commit on a stale base). False, with the error in ``report``,
    when this checkout is not on origin/main with its own changes back in place: the run
    must stop before any upload, write or commit."""
    stashes = _stashes()
    pulled = _git("pull", "--rebase", "--autostash", "origin", "main")
    if pulled.returncode != 0:
        error = _git_error(pulled).rstrip(".")
        aborted = _abort_rebase()
        if aborted:
            # A commit an earlier run could not push conflicts with origin/main.
            error += (f".{aborted} Nothing was uploaded, pushed or removed. A local commit conflicts with"
                      " origin/main: resolve it by hand (git pull --rebase origin main, fix the conflicts,"
                      f" git add, git rebase --continue), then run {again} again.")
    else:
        # It exits 0 even when the autostash does not apply cleanly (git 2.43).
        error = _conflicted_autostash(stashes, pulled, again)
    if not error:
        return True
    report["failed"].append({"job": "git pull", "error": error})
    report["git"] = {"pushed": False, "error": error}
    report["changed"] = []
    return False


def _migrate_main(push_it: bool, dry_run: bool) -> int:
    report: dict[str, Any] = {"failed": [], "git": None}
    changed: list[Path] = []
    with _lock():
        if push_it and not _start_pull(report, "--migrate-audio --push"):
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        try:
            report.update(migrate_audio(SITE, media=GhMedia, verify=head_audio, remove=_git_rm, dry_run=dry_run))
        except MigrationError as exc:
            report.update(exc.report)
            report["failed"].append({"job": "migrate-audio", "error": str(exc)})
        except (OSError, ValueError, UploadError) as exc:
            report["failed"].append({"job": "migrate-audio", "error": str(exc)})
        changed = list(report.pop("changed", []))
        if (report.get("feed_error") or report.get("pages_error")) and not report["failed"]:
            # Never push a removal while a feed or page may still link the docs/ copy.
            error = report.get("feed_error") or report.get("pages_error")
            report["failed"].append({"job": "rebuild", "error": error})
        if push_it and not report["failed"]:
            try:
                changed += [p for p in _pending_migration(SITE) if p not in changed]
            except OSError as exc:
                report["failed"].append({"job": "git", "error": str(exc)})
        if push_it and not report["failed"] and (changed or _has_unpushed()):
            report["git"] = push(changed, [], MIGRATE_SUBJECT)
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] else 0


def _backfill_main(push_it: bool) -> int:
    report: dict[str, Any] = {"filled": [], "failed": [], "git": None}
    art: list[Path] = []
    with _lock():
        if push_it and not _start_pull(report, "--backfill --push"):
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 1
        try:
            index_changed, report["filled"] = backfill(SITE, _jobs_root(), art)
        except (OSError, ValueError) as exc:
            report["failed"].append({"job": INDEX, "error": str(exc)})
            index_changed = False
        changed = [SITE / INDEX] if index_changed else []
        changed += art
        if not report["failed"]:
            # The story feeds carry the episode artwork too (itunes:image per item).
            changed += _rebuild_feeds(report)
            changed += _rebuild_pages(report)
        if push_it and (changed or _has_unpushed()):
            report["git"] = push(changed, [], BACKFILL_SUBJECT)
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    report["art"] = sorted({f["id"] for f in report["filled"] if f.get("image")})
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] or report.get("pages_error") else 0


if __name__ == "__main__":
    sys.exit(main())
