#!/usr/bin/env python3
"""Publish DropCast episodes to this podcast site (docs/, served by GitHub Pages).

Usage:
    python3 scripts/publish.py JOB [JOB ...] [--push]   # one or more job folders
    python3 scripts/publish.py --all [--push]           # every job in $DROPCAST_HOME/jobs

For each delivered DropCast job it copies ``episode.mp3`` and ``transcript.vtt`` to
``docs/episodes/<job id>/`` and records the episode in ``docs/episodes.json``
(title, summary, source, duration, voices, category). Only public facts are copied: no
local paths, no source text, no keys.

Each episode gets one ``category``, the site's tab: ``ai`` (AI podcast), ``bedtime``
(bedtime stories), ``marketing`` or ``others``. The first that applies wins:
``--category`` (when publishing one job), the job's ``category.txt`` (one word),
``bedtime`` for a ``bedtime-story`` script, the category already in ``episodes.json``
(so a hand fix survives a re-publish), then a keyword guess from the title and summary.

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
import subprocess
import sys
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


class Skip(Exception):
    """The job is left out on purpose (not an error)."""


class NotReady(Skip):
    """The episode is not rendered yet: fine for ``--all``, an error for a named job."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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


def _summary(job: Path) -> list[str]:
    try:
        lines = (job / "summary.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()][:3]


def _voice_label(run: dict[str, Any]) -> str:
    engine = str(run.get("engine") or "")
    label = ENGINE_LABELS.get(engine, engine or "unknown")
    model = run.get("model")
    if engine == "voicecast":
        model = model or run.get("voicecast_engine") or run.get("engine_id")
    return f"{label} · {model}" if model else label


def episode_entry(
    job: Path, site: Path, category: str | None = None
) -> tuple[dict[str, Any], list[Path]]:
    """Copy one job's media into ``site`` and return its index entry and changed files."""
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

    episode_id = job.name
    dest = site / EPISODES_DIR / episode_id
    changed: list[Path] = []
    if _copy(episode, dest / "episode.mp3"):
        changed.append(dest / "episode.mp3")
    transcript = None
    if run.get("transcript") and (job / run["transcript"]).is_file():
        if _copy(job / run["transcript"], dest / "transcript.vtt"):
            changed.append(dest / "transcript.vtt")
        transcript = f"{EPISODES_DIR}/{episode_id}/transcript.vtt"

    hosts = (script.get("show") or {}).get("hosts") or {}
    title = script.get("title") or source.get("title") or episode_id
    summary = _summary(job)
    known = {e.get("id"): e for e in (_read_json(site / INDEX) or {}).get("episodes") or []
             if isinstance(e, dict)}
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
        "show": SHOW["name"],  # one brand on the site, whatever older scripts said
        "hosts": [name for name in (hosts.get("host_a"), hosts.get("host_b")) if name],
        "language": script.get("language") or "en",
        "format": script.get("format"),
        "published": run.get("finished") or run.get("started"),
        "duration_s": run.get("duration_s"),
        "size_bytes": (dest / "episode.mp3").stat().st_size,
        "audio": f"{EPISODES_DIR}/{episode_id}/episode.mp3",
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
    return entry, changed


def update_index(site: Path, entries: list[dict[str, Any]]) -> bool:
    path = site / INDEX
    current = _read_json(path) or {}
    episodes = {e["id"]: e for e in current.get("episodes") or [] if isinstance(e, dict)}
    for entry in entries:
        episodes[entry["id"]] = entry
    ordered = sorted(episodes.values(), key=lambda e: e.get("published") or "", reverse=True)
    if ordered == current.get("episodes"):
        return False
    data = {
        "version": 1,
        "show": SHOW,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episodes": ordered,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=300
    )


def push(paths: list[Path], titles: list[str]) -> dict[str, Any]:
    rel = [str(p.relative_to(REPO)) for p in paths]
    add = _git("add", "--", *rel)
    if add.returncode != 0:
        return {"pushed": False, "error": add.stderr.strip()}
    if not _git("diff", "--cached", "--quiet").returncode:
        return {"pushed": False, "error": None, "note": "nothing to commit"}
    subject = (
        f"feat(episodes): publish {titles[0]}"
        if len(titles) == 1
        else f"feat(episodes): publish {len(titles)} episodes"
    )
    commit = _git("commit", "-m", subject[:120], "--", *rel)
    if commit.returncode != 0:
        return {"pushed": False, "error": commit.stderr.strip() or commit.stdout.strip()}
    for attempt in range(2):
        pushed = _git("push", "origin", "HEAD:main")
        if pushed.returncode == 0:
            return {"pushed": True, "commit": _git("rev-parse", "HEAD").stdout.strip()}
        if attempt == 0:
            _git("pull", "--rebase", "origin", "main")
    return {"pushed": False, "error": pushed.stderr.strip()}


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


def _jobs_root() -> Path:
    home = os.environ.get("DROPCAST_HOME") or "~/dropcast"
    return Path(home).expanduser() / "jobs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("jobs", nargs="*", metavar="JOB", help="DropCast job folder(s)")
    parser.add_argument("--all", action="store_true", help="every job in $DROPCAST_HOME/jobs")
    parser.add_argument("--push", action="store_true", help="commit and push the changes")
    parser.add_argument(
        "--category", choices=CATEGORIES, help="the site tab for this one job (default: guessed)"
    )
    args = parser.parse_args(argv)
    jobs = [Path(j).expanduser() for j in args.jobs]
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
        if args.push:
            _git("pull", "--rebase", "origin", "main")
        entries: list[dict[str, Any]] = []
        changed: list[Path] = []
        named = set(args.jobs and [Path(j).expanduser().resolve() for j in args.jobs])
        for job in jobs:
            try:
                entry, files = episode_entry(job.resolve(), SITE, args.category)
            except NotReady as why:
                bucket = "failed" if job.resolve() in named else "skipped"
                key = "error" if bucket == "failed" else "reason"
                report[bucket].append({"job": job.name, key: str(why)})
                continue
            except Skip as why:
                report["skipped"].append({"job": job.name, "reason": str(why)})
                continue
            except (OSError, ValueError) as exc:
                report["failed"].append({"job": job.name, "error": str(exc)})
                continue
            entries.append(entry)
            changed += files
            report["published"].append({"id": entry["id"], "title": entry["title"]})
        if entries and update_index(SITE, entries):
            changed.append(SITE / INDEX)
        if args.push and changed:
            report["git"] = push(changed, [e["title"] for e in entries])
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
