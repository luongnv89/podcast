"""Test guards: no test reaches GitHub or the network.

The publisher uploads episode audio with ``gh`` (podcast #30); a test that forgot to pass a
fake would create real releases. So ``gh`` is refused here, and sockets may only connect to
loopback (a local test server is fine).
"""

from __future__ import annotations

import socket
import subprocess

import pytest

_LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture(autouse=True)
def _no_gh_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run
    real_connect = socket.socket.connect

    def run(args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and str(args[0]) == "gh":
            raise OSError("tests must not call gh: pass a fake media object")
        return real_run(args, *a, **kw)

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in _LOOPBACK and self.family != socket.AF_UNIX:
            raise OSError(f"tests must not connect to {host}")
        return real_connect(self, address)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(socket.socket, "connect", connect)
