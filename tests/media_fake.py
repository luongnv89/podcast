"""A fake of publish.GhMedia (the media repo's releases) for the tests: no gh, no network."""

from __future__ import annotations

import hashlib
from pathlib import Path


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

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]
