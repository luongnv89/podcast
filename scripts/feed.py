#!/usr/bin/env python3
"""Build the podcast RSS feed (docs/feed.xml) that Spotify and other apps read.

Usage:
    python3 scripts/feed.py build                 # rewrite docs/feed.xml from episodes.json
    python3 scripts/feed.py list                  # which episodes are in the feed, which could be
    python3 scripts/feed.py add ID [ID ...] [--push]
    python3 scripts/feed.py remove ID [ID ...] [--push]

Spotify has no upload API: a show hosted elsewhere is submitted once as an RSS feed in
Spotify for Creators, which then checks the feed several times an hour and adds new
episodes on its own (Spotify Podcast Delivery Specification v1.10, "Supply Chain").

The feed is opt-in, one episode at a time: an episode is in the feed only when its
entry in ``docs/episodes.json`` has ``"feed": true`` (set with ``add``; ``remove``
clears it, and an episode removed from the feed is unpublished on Spotify). Only
English episodes can be added (the show's language is ``en``). ``publish.py`` keeps the
flag when it re-publishes an episode and rebuilds the feed after every publish.

The ``<guid>`` of an episode is its job id, so it never changes. Spotify downloads an
audio file again only when its URL changes, so a re-rendered episode keeps its guid but
gets ``?v=<first 8 hex of its SHA-256>`` on the enclosure URL.

``--push`` commits ``docs/episodes.json`` and ``docs/feed.xml`` and pushes them to main.
Standard library only. Prints one JSON object. Exit 0 ok, 1 an ID could not be
added/removed or git failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs"
INDEX = "episodes.json"
FEED = "feed.xml"
BASE_URL = "https://luongnv.com/podcast/"
FEED_LANGUAGE = "en"

# The show as Spotify, Apple Podcasts and other apps see it. The owner email is public:
# Spotify sends its ownership code to it when the feed is submitted.
CHANNEL = {
    "title": "Build Wiz AI",
    "author": "Build Wiz AI",
    "owner_name": "Build Wiz AI",
    "owner_email": "buildwizai@gmail.com",
    "description": (
        "Build Wiz AI: two hosts, Bob and Alice, take one public source (an article, a "
        "thread or a paper) and pull out everything worth knowing, fact-checked against "
        "the source and credited in every episode. Episodes are written and voiced with "
        "AI using DropCast."
    ),
    "category": "Technology",
    "image": "cover.jpg",
    "explicit": "false",
    "type": "episodic",
}

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
    "podcast": "https://podcastindex.org/namespace/1.0",
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rfc2822(stamp: str | None) -> str:
    """``2026-11-03T07:01:29Z`` -> ``Tue, 03 Nov 2026 07:01:29 +0000``."""
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return format_datetime(when.astimezone(timezone.utc))


def _audio_version(site: Path, audio: str) -> str | None:
    try:
        data = (site / audio).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()[:8]


def feed_episodes(index: dict[str, Any]) -> list[dict[str, Any]]:
    """Episodes in the feed, newest first: opted in and in the feed's language."""
    episodes = [e for e in index.get("episodes") or [] if isinstance(e, dict)]
    chosen = [
        e for e in episodes
        if e.get("feed") is True and (e.get("language") or "en") == FEED_LANGUAGE
    ]
    return sorted(chosen, key=lambda e: e.get("published") or "", reverse=True)


def _description(ep: dict[str, Any]) -> tuple[str, str]:
    """Plain-text and HTML show notes: the summary lines, then the source credit."""
    lines = [str(line) for line in ep.get("summary") or [] if line]
    source = ep.get("source") or {}
    credit = None
    if source.get("title") or source.get("url"):
        by = f" by {source['author']}" if source.get("author") else ""
        credit = f"Source: {source.get('title') or source.get('url')}{by}"
    plain = "\n\n".join(lines + ([f"{credit} ({source['url']})"] if credit and source.get("url")
                                 else [credit] if credit else []))
    html = "".join(f"<p>{escape(line)}</p>" for line in lines)
    if credit:
        if source.get("url"):
            html += f'<p>{escape(credit)}: <a href="{escape(source["url"])}">{escape(source["url"])}</a></p>'
        else:
            html += f"<p>{escape(credit)}</p>"
    return plain or str(ep.get("title") or ""), html


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def render_feed(index: dict[str, Any], site: Path = SITE, now: datetime | None = None) -> str:
    """The whole feed as an RSS 2.0 string (UTF-8, iTunes/Spotify tags)."""
    now = now or datetime.now(timezone.utc)
    episodes = feed_episodes(index)
    feed_url = BASE_URL + FEED
    image = BASE_URL + CHANNEL["image"]
    ns = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<rss version="2.0" {ns}>',
        "<channel>",
        f"  <title>{escape(CHANNEL['title'])}</title>",
        f"  <link>{escape(BASE_URL)}</link>",
        f'  <atom:link href={quoteattr(feed_url)} rel="self" type="application/rss+xml"/>',
        f"  <description>{escape(CHANNEL['description'])}</description>",
        f"  <language>{FEED_LANGUAGE}</language>",
        f"  <lastBuildDate>{format_datetime(now.astimezone(timezone.utc))}</lastBuildDate>",
        f"  <itunes:author>{escape(CHANNEL['author'])}</itunes:author>",
        "  <itunes:owner>",
        f"    <itunes:name>{escape(CHANNEL['owner_name'])}</itunes:name>",
        f"    <itunes:email>{escape(CHANNEL['owner_email'])}</itunes:email>",
        "  </itunes:owner>",
        f"  <itunes:image href={quoteattr(image)}/>",
        "  <image>",
        f"    <url>{escape(image)}</url>",
        f"    <title>{escape(CHANNEL['title'])}</title>",
        f"    <link>{escape(BASE_URL)}</link>",
        "  </image>",
        f"  <itunes:category text={quoteattr(CHANNEL['category'])}/>",
        f"  <itunes:explicit>{CHANNEL['explicit']}</itunes:explicit>",
        f"  <itunes:type>{CHANNEL['type']}</itunes:type>",
    ]
    for ep in episodes:
        audio = BASE_URL + str(ep["audio"])
        version = _audio_version(site, str(ep["audio"]))
        if version:
            audio += f"?v={version}"
        plain, html = _description(ep)
        page = f"{BASE_URL}#{ep['id']}"
        out += [
            "  <item>",
            f'    <guid isPermaLink="false">{escape(str(ep["id"]))}</guid>',
            f"    <title>{escape(str(ep.get('title') or ep['id']))}</title>",
            f"    <link>{escape(page)}</link>",
            f"    <description>{escape(plain)}</description>",
            f"    <content:encoded>{_cdata(html)}</content:encoded>",
            f"    <pubDate>{_rfc2822(ep.get('published'))}</pubDate>",
            f'    <enclosure url={quoteattr(audio)} length="{int(ep.get("size_bytes") or 0)}"'
            ' type="audio/mpeg"/>',
            f"    <itunes:duration>{round(float(ep.get('duration_s') or 0))}</itunes:duration>",
            f"    <itunes:explicit>{CHANNEL['explicit']}</itunes:explicit>",
            "    <itunes:episodeType>full</itunes:episodeType>",
        ]
        if ep.get("transcript"):
            out.append(
                f"    <podcast:transcript url={quoteattr(BASE_URL + str(ep['transcript']))}"
                ' type="text/vtt"/>'
            )
        out.append("  </item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def write_feed(site: Path = SITE) -> bool:
    """Rewrite ``feed.xml`` from ``episodes.json``; ``True`` when its content changed.

    ``lastBuildDate`` alone never counts as a change, so a rebuild with nothing new
    leaves the file (and git) untouched.
    """
    index = _read_json(site / INDEX) or {}
    path = site / FEED
    new = render_feed(index, site)
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = None

    def _strip(text: str) -> str:
        return "\n".join(l for l in text.splitlines() if "<lastBuildDate>" not in l)

    if old is not None and _strip(old) == _strip(new):
        return False
    path.write_text(new, encoding="utf-8")
    return True


def set_flag(site: Path, ids: list[str], on: bool) -> tuple[list[str], list[dict[str, str]]]:
    """Set or clear ``feed`` on episodes; returns the changed ids and the refusals."""
    path = site / INDEX
    index = _read_json(path)
    if not isinstance(index, dict):
        raise ValueError(f"{path} is missing or unreadable")
    by_id = {e.get("id"): e for e in index.get("episodes") or [] if isinstance(e, dict)}
    changed: list[str] = []
    errors: list[dict[str, str]] = []
    for episode_id in ids:
        ep = by_id.get(episode_id)
        if ep is None:
            errors.append({"id": episode_id, "error": "no such episode in episodes.json"})
            continue
        if on and (ep.get("language") or "en") != FEED_LANGUAGE:
            errors.append({
                "id": episode_id,
                "error": f"language {ep.get('language')!r}: the feed is {FEED_LANGUAGE} only",
            })
            continue
        if bool(ep.get("feed")) == on:
            continue
        if on:
            ep["feed"] = True
        else:
            ep.pop("feed", None)
        changed.append(episode_id)
    if changed:
        path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed, errors


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=300
    )


def push(subject: str) -> dict[str, Any]:
    files = [f"docs/{INDEX}", f"docs/{FEED}"]
    add = _git("add", "--", *files)
    if add.returncode != 0:
        return {"pushed": False, "error": add.stderr.strip()}
    if not _git("diff", "--cached", "--quiet").returncode:
        return {"pushed": False, "error": None, "note": "nothing to commit"}
    commit = _git("commit", "-m", subject[:120], "--", *files)
    if commit.returncode != 0:
        return {"pushed": False, "error": commit.stderr.strip() or commit.stdout.strip()}
    error = ""
    for attempt in range(2):
        pushed = _git("push", "origin", "HEAD:main")
        if pushed.returncode == 0:
            return {"pushed": True, "commit": _git("rev-parse", "HEAD").stdout.strip()}
        error = pushed.stderr.strip()
        if attempt == 0:
            _git("pull", "--rebase", "origin", "main")
    return {"pushed": False, "error": error}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="rewrite docs/feed.xml from docs/episodes.json")
    sub.add_parser("list", help="episodes in the feed and the ones that could be added")
    for name in ("add", "remove"):
        p = sub.add_parser(name, help=f"{name} episodes (by job id) to/from the feed")
        p.add_argument("ids", nargs="+", metavar="ID")
        p.add_argument("--push", action="store_true", help="commit and push to main")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"command": args.command}
    status = 0
    if args.command == "list":
        index = _read_json(SITE / INDEX) or {}
        in_feed = {e["id"] for e in feed_episodes(index)}
        report["in_feed"] = []
        report["can_add"] = []
        report["other_language"] = []
        for ep in index.get("episodes") or []:
            row = {"id": ep.get("id"), "title": ep.get("title"), "language": ep.get("language")}
            if ep.get("id") in in_feed:
                report["in_feed"].append(row)
            elif (ep.get("language") or "en") == FEED_LANGUAGE:
                report["can_add"].append(row)
            else:
                report["other_language"].append(row)
    elif args.command == "build":
        report["changed"] = write_feed(SITE)
        report["episodes"] = len(feed_episodes(_read_json(SITE / INDEX) or {}))
    else:
        import publish  # same lock as the publisher: both rewrite episodes.json

        with publish._lock():
            status = _change(args, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return status


def _change(args: argparse.Namespace, report: dict[str, Any]) -> int:
    """``add`` / ``remove``: set the flags, rebuild the feed, optionally push."""
    if args.push:
        _git("pull", "--rebase", "origin", "main")
    try:
        changed, errors = set_flag(SITE, args.ids, args.command == "add")
    except ValueError as exc:
        report["error"] = str(exc)
        return 1
    report["changed"] = changed
    report["errors"] = errors
    report["feed_changed"] = write_feed(SITE)
    report["episodes"] = len(feed_episodes(_read_json(SITE / INDEX) or {}))
    status = 1 if errors else 0
    if args.push and (changed or report["feed_changed"]):
        verb = "add to" if args.command == "add" else "remove from"
        what = changed[0] if len(changed) == 1 else f"{len(changed)} episodes"
        report["git"] = push(f"feat(feed): {verb} the feed: {what}")
        if not report["git"].get("pushed") and report["git"].get("error"):
            status = 1
    return status

if __name__ == "__main__":
    sys.exit(main())
