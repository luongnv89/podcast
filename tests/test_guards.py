"""The conftest guard refuses gh however it is called (no real gh, ever)."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("args", [
    ["gh", "release", "list"],
    ["/usr/bin/gh", "release", "list"],
    ("/opt/homebrew/bin/gh",),
    "gh",
    "/usr/bin/gh",
])
def test_gh_is_refused_by_basename(args) -> None:
    with pytest.raises(OSError, match="must not call gh"):
        subprocess.run(args, capture_output=True, check=False)


@pytest.mark.parametrize("name", ["Popen", "call", "check_call", "check_output", "run"])
def test_every_subprocess_entry_point_is_guarded(name: str) -> None:
    with pytest.raises(OSError, match="must not call gh"):
        getattr(subprocess, name)(["/usr/bin/gh", "api", "user"])


@pytest.mark.parametrize("command", [
    "gh release upload x y",
    "cd /tmp && gh api user",
    "/usr/bin/gh api user",
    "true; gh",
    "echo $(gh auth token)",
])
def test_shell_strings_with_gh_are_refused(command: str) -> None:
    with pytest.raises(OSError, match="must not call gh"):
        subprocess.run(command, shell=True, capture_output=True, check=False)


def test_executable_gh_is_refused() -> None:
    with pytest.raises(OSError, match="must not call gh"):
        subprocess.run(["anything"], executable="/usr/bin/gh", capture_output=True, check=False)


def test_other_commands_still_run() -> None:
    out = subprocess.run("echo high; echo ghost", shell=True, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["high", "ghost"]
    out = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ok"
