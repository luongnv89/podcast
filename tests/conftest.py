"""Test guards: no test reaches GitHub or the network.

The publisher uploads episode audio with ``gh`` (podcast #30); a test that forgot to pass a
fake would create real releases. So ``gh`` is refused here, and sockets may only connect to
loopback (a local test server is fine).

Since podcast #33 it pushes episode audio to the media repos with ``git`` over SSH, from
checkouts in ``$PODCAST_MEDIA_CHECKOUTS``. So every test gets that variable pointing at an
empty folder of its own (never the bot's checkouts), ``GIT_SSH_COMMAND=false`` (no git over
SSH at all) and ``PODCAST_MEDIA_WAIT=0``, and a ``git`` command naming github.com is refused.
(``media_fake`` sets the same variables for ``python3 -m unittest``, which has no conftest.)

``gh`` is refused by its basename (``gh``, ``/usr/bin/gh``, ``gh.exe``), as the program or
the ``executable``, and anywhere in a shell string (``shell=True``) as a word. The guard sits
on ``subprocess.Popen``, so ``run``, ``call``, ``check_output`` and ``Popen`` itself are all
covered.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess

import pytest

_LOOPBACK = ("127.0.0.1", "::1", "localhost")
# gh as a word of a shell string (by any path): "gh api", "cd x && /usr/bin/gh ...".
_SHELL_GH = re.compile(r"(?:^|[\s;&|()`$'\"])(?:[^\s;&|()`$'\"]*/)?gh(?:\.exe)?(?=$|[\s;&|()`'\"])")
_REFUSED = "tests must not call gh: pass a fake media object"
_REFUSED_GIT = "tests must not run git against github.com: use a local bare repo"


def _is_gh(program: object) -> bool:
    if isinstance(program, bytes):
        program = os.fsdecode(program)
    if not isinstance(program, (str, os.PathLike)):
        return False
    return os.path.basename(os.fspath(program).strip()) in ("gh", "gh.exe")


def _refuse_git_github(args: object, shell: bool) -> None:
    if isinstance(args, (str, bytes, os.PathLike)):
        words = [os.fsdecode(args)] if shell else []
    elif isinstance(args, (list, tuple)) and args and os.path.basename(os.fsdecode(args[0])) in ("git", "git.exe"):
        words = [os.fsdecode(a) for a in args if isinstance(a, (str, bytes, os.PathLike))]
    else:
        words = []
    if any("github.com" in w and (not shell or re.search(r"(?:^|[\s;&|/])git\s", w)) for w in words):
        raise OSError(_REFUSED_GIT)


def _refuse_gh(args: object, shell: bool, executable: object) -> None:
    if _is_gh(executable):
        raise OSError(_REFUSED)
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(args)
        if _is_gh(text) or (shell and _SHELL_GH.search(text)):
            raise OSError(_REFUSED)
    elif isinstance(args, (list, tuple)) and args:
        first = args[0]
        if _is_gh(first):
            raise OSError(_REFUSED)
        if shell and isinstance(first, (str, bytes)) and _SHELL_GH.search(os.fsdecode(first)):
            raise OSError(_REFUSED)


@pytest.fixture(autouse=True)
def _no_gh_no_network(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    real_popen = subprocess.Popen
    real_connect = socket.socket.connect

    class GuardedPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **kw):
            _refuse_gh(args, bool(kw.get("shell")), kw.get("executable"))
            _refuse_git_github(args, bool(kw.get("shell")))
            super().__init__(args, *a, **kw)

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOOPBACK and self.family != socket.AF_UNIX:
            raise OSError(f"tests must not connect to {host}")
        return real_connect(self, address)

    monkeypatch.setenv("PODCAST_MEDIA_CHECKOUTS", str(tmp_path_factory.mktemp("media-checkouts")))
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    monkeypatch.setenv("PODCAST_MEDIA_WAIT", "0")
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    monkeypatch.setattr(socket.socket, "connect", connect)
