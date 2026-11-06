#!/usr/bin/env python3
"""Build the Once Upon a Time Show RSS feeds that Spotify and podcast apps read.

Usage:
    python3 scripts/feed.py build            # rewrite every feed from docs/episodes.json
    python3 scripts/feed.py list             # which episodes each feed holds

Spotify has no upload API: a show hosted elsewhere is submitted once as an RSS feed in
Spotify for Creators (Add a new show -> Find an existing show -> Somewhere else), and
Spotify then checks the feed on its own and adds new episodes (Spotify Podcast Delivery
Specification, "Supply Chain and Playout").

The stories are one show in three languages, and a Spotify show has one language, so
there is one feed per language (``FEEDS``): ``docs/stories/feed-en.xml``, ``-fr`` and
``-vi``, each with its own title, description and cover. A feed holds every episode of
Once Upon a Time Show in its language, automatically: ``publish.py`` rebuilds the feeds
after every publish, so a new story reaches Spotify with no manual step. An entry with
``"feed": false`` in ``episodes.json`` is left out (an episode removed from a feed is
unpublished on Spotify).

The ``<guid>`` of an episode is its job id, so it never changes. Spotify downloads an
audio file again only when its URL changes, so the enclosure URL carries
``?v=<first 8 hex of the MP3's SHA-256>``: a re-voiced episode keeps its guid and gets
the new audio.

A story with an illustration (``image.square`` in ``episodes.json``, the file under
``docs/art/``) gets ``<itunes:image>`` on its item, so podcast apps show the picture as the
episode artwork; the channel keeps the show's cover.

Standard library only. Prints one JSON object. Exit 0 ok, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs"
INDEX = "episodes.json"
BASE_URL = "https://luongnv.com/podcast/"
STORY_SHOW = "Once Upon a Time Show"
STORY_FORMATS = ("bedtime-story", "storytelling")
STORY_PAGE = "stories/"

# Shared by every story feed. The owner email is public: Spotify sends its ownership
# code to it when a feed is submitted.
COMMON = {
    "author": "Once Upon a Time Show",
    "owner_name": "Build Wiz AI",
    "owner_email": "buildwizai@gmail.com",
    "category": "Kids & Family",
    "subcategory": "Stories for Kids",
    "explicit": "false",
    "type": "episodic",
}

# One feed per language. Descriptions stay under Spotify's 600-character limit
# (tests/test_feed.py checks it).
FEEDS: dict[str, dict[str, str]] = {
    "en": {
        "file": "stories/feed-en.xml",
        "image": "stories/cover-en.jpg",
        "title": "Once Upon a Time Show: Bedtime Stories",
        "description": (
            "Gentle bedtime stories for children, told slowly by a warm narrator. Each "
            "episode retells a classic, public-domain tale (Cinderella, Hansel and Gretel, "
            "King Midas and more) in simple words, with soft music between the scenes and a "
            "calm goodnight at the end. The tales are adapted for bedtime, so nothing is too "
            "scary. Scripts and voices are made with AI, and every episode credits its source "
            "and its music. Also in French and Vietnamese."
        ),
        "source": "Source",
        "made_with": "Written and voiced with AI",
    },
    "fr": {
        "file": "stories/feed-fr.xml",
        "image": "stories/cover-fr.jpg",
        "title": "Once Upon a Time Show : histoires du soir",
        "description": (
            "Des histoires du soir tout en douceur pour les enfants, racontées lentement par "
            "une voix chaleureuse. Chaque épisode reprend un conte classique du domaine public "
            "(Cendrillon, Hansel et Gretel, le roi Midas et d'autres) avec des mots simples, "
            "une petite musique entre les scènes et une bonne nuit tout en calme. Les contes "
            "sont adaptés pour le coucher : rien de trop effrayant. Textes et voix sont créés "
            "avec l'IA, et chaque épisode cite sa source et sa musique. Aussi en anglais et "
            "en vietnamien."
        ),
        "source": "Source",
        "made_with": "Écrit et lu avec l'IA",
    },
    "vi": {
        "file": "stories/feed-vi.xml",
        "image": "stories/cover-vi.jpg",
        "title": "Once Upon a Time Show: Truyện kể trước giờ ngủ",
        "description": (
            "Những câu chuyện nhẹ nhàng trước giờ ngủ cho bé, được kể chậm rãi bằng một giọng "
            "kể ấm áp. Mỗi tập kể lại một truyện cổ kinh điển thuộc phạm vi công cộng (Cô bé "
            "Lọ Lem, Hansel và Gretel, Vua Midas và nhiều truyện khác) bằng lời lẽ đơn giản, "
            "có nhạc nhẹ giữa các cảnh và lời chúc ngủ ngon êm dịu ở cuối. Truyện được kể lại "
            "cho hợp với giờ đi ngủ, không có gì quá đáng sợ. Lời kể và giọng đọc được tạo "
            "bằng AI, và mỗi tập đều ghi rõ nguồn truyện và nhạc. Có cả bản tiếng Anh và "
            "tiếng Pháp."
        ),
        "source": "Nguồn",
        "made_with": "Viết và đọc bằng AI",
    },
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


def _rfc2822(stamp: str | None, fallback: datetime) -> str:
    """``2026-11-03T07:01:29Z`` -> ``Tue, 03 Nov 2026 07:01:29 +0000``."""
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        when = fallback
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return format_datetime(when.astimezone(timezone.utc))


def _audio_version(site: Path, audio: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with (site / audio).open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()[:8]


_ART_PATH = re.compile(r"art/[A-Za-z0-9][A-Za-z0-9._-]*/(?:wide|square|thumb)\.jpg")


def item_image(ep: dict[str, Any], site: Path = SITE) -> str | None:
    """The episode artwork's absolute URL (``BASE_URL`` + the story illustration's
    ``image.square``, a safe ``art/...jpg`` path whose file is on the site), else None.
    No query string: some directories want the artwork URL to end in ``.jpg``."""
    image = ep.get("image")
    square = image.get("square") if isinstance(image, dict) else None
    if not isinstance(square, str) or not _ART_PATH.fullmatch(square) or ".." in square:
        return None
    if not (site / square).is_file():
        return None
    return BASE_URL + square


def is_story(ep: dict[str, Any]) -> bool:
    if ep.get("show"):
        return ep.get("show") == STORY_SHOW
    return ep.get("format") in STORY_FORMATS


def feed_episodes(index: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    """The episodes of one language's feed, newest first."""
    chosen = [
        e
        for e in index.get("episodes") or []
        if isinstance(e, dict)
        and e.get("id")
        and e.get("audio")
        and is_story(e)
        and (e.get("language") or "en") == lang
        and e.get("feed") is not False
    ]
    return sorted(chosen, key=lambda e: e.get("published") or "", reverse=True)


def _notes(ep: dict[str, Any], words: dict[str, str]) -> tuple[str, str]:
    """Plain-text and HTML show notes: summary, source credit, music credit, AI note."""
    lines = [str(line) for line in ep.get("summary") or [] if line]
    source = ep.get("source") or {}
    url = source.get("url") if str(source.get("url") or "").startswith(("http://", "https://")) else None
    credit = None
    if source.get("title") or url:
        by = f", {source['author']}" if source.get("author") else ""
        credit = f"{words['source']}: {source.get('title') or url}{by}"
    music = str(ep.get("music_credit") or "").strip()
    voices = str(ep.get("voices") or "").strip()
    made = f"{words['made_with']} ({voices})." if voices else f"{words['made_with']}."

    plain = list(lines)
    html = [f"<p>{escape(line)}</p>" for line in lines]
    if credit:
        plain.append(f"{credit} ({url})" if url else credit)
        html.append(
            f'<p>{escape(credit)}: <a href="{escape(url)}">{escape(url)}</a></p>'
            if url
            else f"<p>{escape(credit)}</p>"
        )
    if music:
        plain.append(music)
        html.append(f"<p>{escape(music)}</p>")
    plain.append(made)
    html.append(f"<p>{escape(made)}</p>")
    return "\n\n".join(plain), "".join(html)


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def render_feed(index: dict[str, Any], lang: str, site: Path = SITE, now: datetime | None = None) -> str:
    """One language's feed as an RSS 2.0 string (UTF-8, iTunes/Spotify tags)."""
    now = now or datetime.now(timezone.utc)
    meta = FEEDS[lang]
    page = BASE_URL + STORY_PAGE
    image = BASE_URL + meta["image"]
    ns = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items())
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<rss version="2.0" {ns}>',
        "<channel>",
        f"  <title>{escape(meta['title'])}</title>",
        f"  <link>{escape(page)}</link>",
        f'  <atom:link href={quoteattr(BASE_URL + meta["file"])} rel="self" type="application/rss+xml"/>',
        f"  <description>{escape(meta['description'])}</description>",
        f"  <itunes:summary>{escape(meta['description'])}</itunes:summary>",
        f"  <language>{lang}</language>",
        f"  <lastBuildDate>{format_datetime(now.astimezone(timezone.utc))}</lastBuildDate>",
        f"  <itunes:author>{escape(COMMON['author'])}</itunes:author>",
        "  <itunes:owner>",
        f"    <itunes:name>{escape(COMMON['owner_name'])}</itunes:name>",
        f"    <itunes:email>{escape(COMMON['owner_email'])}</itunes:email>",
        "  </itunes:owner>",
        f"  <itunes:image href={quoteattr(image)}/>",
        "  <image>",
        f"    <url>{escape(image)}</url>",
        f"    <title>{escape(meta['title'])}</title>",
        f"    <link>{escape(page)}</link>",
        "  </image>",
        f"  <itunes:category text={quoteattr(COMMON['category'])}>",
        f"    <itunes:category text={quoteattr(COMMON['subcategory'])}/>",
        "  </itunes:category>",
        f"  <itunes:explicit>{COMMON['explicit']}</itunes:explicit>",
        f"  <itunes:type>{COMMON['type']}</itunes:type>",
    ]
    for ep in feed_episodes(index, lang):
        audio = BASE_URL + str(ep["audio"])
        version = _audio_version(site, str(ep["audio"]))
        if version:
            audio += f"?v={version}"
        plain, html = _notes(ep, meta)
        out += [
            "  <item>",
            f'    <guid isPermaLink="false">{escape(str(ep["id"]))}</guid>',
            f"    <title>{escape(str(ep.get('title') or ep['id']))}</title>",
            f"    <link>{escape(page + '#' + str(ep['id']))}</link>",
            f"    <description>{escape(plain)}</description>",
            f"    <content:encoded>{_cdata(html)}</content:encoded>",
            f"    <pubDate>{_rfc2822(ep.get('published'), now)}</pubDate>",
            f'    <enclosure url={quoteattr(audio)} length="{int(ep.get("size_bytes") or 0)}"'
            ' type="audio/mpeg"/>',
            f"    <itunes:duration>{round(float(ep.get('duration_s') or 0))}</itunes:duration>",
            f"    <itunes:explicit>{COMMON['explicit']}</itunes:explicit>",
            "    <itunes:episodeType>full</itunes:episodeType>",
        ]
        artwork = item_image(ep, site)
        if artwork:
            # The story's illustration as the episode's artwork (Apple Podcasts, Spotify).
            out.append(f"    <itunes:image href={quoteattr(artwork)}/>")
        if ep.get("transcript"):
            out.append(
                f"    <podcast:transcript url={quoteattr(BASE_URL + str(ep['transcript']))}"
                ' type="text/vtt"/>'
            )
        out.append("  </item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def _strip(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "<lastBuildDate>" not in line)


def write_feeds(site: Path = SITE, now: datetime | None = None) -> list[Path]:
    """Rewrite every feed from ``episodes.json``; returns the files whose content changed.

    ``lastBuildDate`` alone never counts as a change, so a rebuild with nothing new
    leaves the files (and git) untouched.
    """
    index = _read_json(site / INDEX) or {}
    changed: list[Path] = []
    for lang, meta in FEEDS.items():
        path = site / meta["file"]
        new = render_feed(index, lang, site, now)
        try:
            old = path.read_text(encoding="utf-8")
        except OSError:
            old = None
        if old is not None and _strip(old) == _strip(new):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="rewrite every feed from docs/episodes.json")
    sub.add_parser("list", help="the episodes each feed holds")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"command": args.command}
    if args.command == "build":
        report["changed"] = [str(p.relative_to(REPO)) for p in write_feeds(SITE)]
    index = _read_json(SITE / INDEX) or {}
    report["feeds"] = {
        lang: {
            "url": BASE_URL + meta["file"],
            "episodes": [
                {"id": e["id"], "title": e.get("title")} for e in feed_episodes(index, lang)
            ],
        }
        for lang, meta in FEEDS.items()
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
