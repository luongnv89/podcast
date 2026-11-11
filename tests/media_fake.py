"""Fakes of publish's media backends for the tests: no gh, no git over SSH, no network.

``FakeMedia`` stands for ``GhMedia`` (the media repo's releases, podcast #30),
``FakePagesMedia`` for ``PagesMedia`` (its GitHub Pages site, podcast #33) and ``FakeWeb``
for ``head_audio`` (what each URL answers).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Belt and braces for runs without tests/conftest.py (python3 -m unittest): a publish that
# forgot its fake media must never use the bot's media checkouts or git over SSH. A folder
# under /dev/null cannot be created, so such a publish fails before any git command.
os.environ["PODCAST_MEDIA_CHECKOUTS"] = "/dev/null/podcast-tests-use-a-fake-media"
os.environ["GIT_SSH_COMMAND"] = "false"
os.environ["PODCAST_MEDIA_WAIT"] = "0"


class FakeMedia:
    """Records every call; ``releases`` maps a tag to ``{asset name: size}``.

    It is also its own factory (``publish`` calls ``media(repo)``): calling it records the
    repo in ``repos``, sets ``repo`` and returns the same fake.

    ``fail`` (an exception) is raised by ``upload``; ``fail_create`` by ``create_release``.
    """

    def __init__(self, repo: str = "luongnv89/buildwiz-ai-show-media", releases=None, fail=None, fail_create=None):
        self.repo = repo
        self.repos: list[str] = []
        self.releases = {} if releases is None else releases
        self.fail = fail
        self.fail_create = fail_create
        self.calls: list[tuple] = []
        self.uploaded: dict[str, bytes] = {}

    def __call__(self, repo: str) -> FakeMedia:
        self.repos.append(repo)
        self.repo = repo
        return self

    def assets(self, tag: str):
        self.calls.append(("assets", tag))
        found = self.releases.get(tag)
        return dict(found) if found is not None else None

    def create_release(self, tag: str, title: str, notes: str) -> None:
        self.calls.append(("create_release", tag, title, notes))
        if self.fail_create:
            raise self.fail_create
        self.releases[tag] = {}

    def upload(self, tag: str, path: Path) -> None:
        data = Path(path).read_bytes()
        self.calls.append(("upload", tag, Path(path).name, len(data), hashlib.sha256(data).hexdigest()))
        if self.fail:
            raise self.fail
        self.releases.setdefault(tag, {})[Path(path).name] = len(data)
        self.uploaded[f"{tag}/{Path(path).name}"] = data

    def replace(self, tag: str, path: Path) -> None:
        """Like ``GhMedia.replace``: the asset named ``path.name`` now holds ``path``."""
        data = Path(path).read_bytes()
        self.calls.append(("replace", tag, Path(path).name, len(data), hashlib.sha256(data).hexdigest()))
        if self.fail:
            raise self.fail
        assets = self.releases.setdefault(tag, {})
        assets.pop(Path(path).name.replace(".mp3", ".new.mp3"), None)
        assets[Path(path).name] = len(data)
        self.uploaded[f"{tag}/{Path(path).name}"] = data

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def site_url(repo: str, episode_id: str) -> str:
    """publish.pages_url() for the tests' repos (luongnv89's custom domain, else github.io)."""
    owner, name = repo.split("/", 1)
    base = "https://luongnv.com/" if owner == "luongnv89" else f"https://{owner.lower()}.github.io/"
    return f"{base}{name}/{episode_id}.mp3"


class FakeWeb:
    """What each URL answers to HEAD (``publish.head_audio``): ``serve()`` an MP3 there (as
    GitHub Pages does: ``audio/mp3``), optionally only after ``after`` more checks (a Pages
    deploy in progress). Any other URL is a 404. ``calls`` lists every URL checked."""

    def __init__(self) -> None:
        self.files: dict[str, dict] = {}
        self.calls: list[str] = []

    def serve(self, url: str, length: int, type_: str = "audio/mp3", after: int = 0, status: int = 200) -> None:
        self.files[url] = {"status": status, "type": type_, "length": length, "after": after}

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        found = self.files.get(url)
        if not found:
            return {"status": 404, "type": "text/html", "length": None}
        if found["after"] > 0:
            found["after"] -= 1
            return {"status": 404, "type": "text/html", "length": None}
        return {"status": found["status"], "type": found["type"], "length": found["length"]}


class FakePagesMedia:
    """Like ``PagesMedia``: ``publish()`` "pushes" the file (``pushed``) and makes ``web``
    serve it, unless the same bytes are already there; ``fail`` (an exception) is raised by
    ``publish``. It is its own factory, like ``FakeMedia``. ``checkouts`` (a folder) holds
    ``<repo name>/<id>.mp3`` files for ``file()``."""

    def __init__(self, web: FakeWeb, checkouts: Path | None = None, fail=None, type_: str = "audio/mp3") -> None:
        self.web = web
        self.checkouts = checkouts
        self.fail = fail
        self.type = type_
        self.repo = ""
        self.repos: list[str] = []
        self.calls: list[tuple] = []
        self.pushed: dict[str, bytes] = {}

    def __call__(self, repo: str) -> FakePagesMedia:
        self.repos.append(repo)
        self.repo = repo
        return self

    def url(self, episode_id: str) -> str:
        return site_url(self.repo, episode_id)

    def file(self, episode_id: str) -> Path:
        root = self.checkouts or Path("/nonexistent")
        return root / self.repo.split("/", 1)[1] / f"{episode_id}.mp3"

    def checkout(self) -> None:
        self.calls.append(("checkout", self.repo))

    def publish(self, episode_id: str, mp3: Path, sha256: str) -> dict:
        data = Path(mp3).read_bytes()
        self.calls.append(("publish", self.repo, episode_id, len(data), sha256))
        if self.fail:
            raise self.fail
        key = f"{self.repo}/{episode_id}.mp3"
        same = key in self.pushed and hashlib.sha256(self.pushed[key]).hexdigest() == sha256
        self.pushed[key] = data
        self.web.serve(self.url(episode_id), len(data), self.type)
        return {"url": self.url(episode_id), "uploaded": not same, "commit": None if same else "f" * 40}

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]
