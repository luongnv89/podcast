#!/usr/bin/env python3
"""Publish DropCast episodes to this podcast site (docs/, served by GitHub Pages).

Usage:
    python3 scripts/publish.py JOB [JOB ...] [--push]   # one or more job folders
    python3 scripts/publish.py --all [--push]           # every job in $DROPCAST_HOME/jobs
    python3 scripts/publish.py --backfill [--push]      # descriptions + pages for old entries

For each delivered DropCast job it copies ``episode.mp3`` and ``transcript.vtt`` to
``docs/episodes/<job id>/`` and records the episode in ``docs/episodes.json``
(title, summary, source, duration, voices, show, category). Only public facts are copied: no
local paths, no source text, no keys.

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
import unicodedata
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
        "show": episode_show(job, script),  # routed by format, never an old brand
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
        "shows": SHOWS,
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


def push(paths: list[Path], titles: list[str], subject: str | None = None) -> dict[str, Any]:
    rel = sorted({str(p.relative_to(REPO)) for p in paths})
    add = _git("add", "--", *rel)
    if add.returncode != 0:
        return {"pushed": False, "error": add.stderr.strip()}
    if not _git("diff", "--cached", "--quiet").returncode:
        return {"pushed": False, "error": None, "note": "nothing to commit"}
    subject = subject or (
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


def _rebuild_feeds(report: dict[str, Any]) -> list[Path]:
    """Rewrite the story RSS feeds (scripts/feed.py); a failure never blocks a publish."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("feed", Path(__file__).with_name("feed.py"))
        if spec is None or spec.loader is None:
            raise ImportError("scripts/feed.py not found")
        feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(feed)
        return list(feed.write_feeds(SITE))
    except Exception as exc:  # noqa: BLE001 - the episode is still published
        report["feed_error"] = f"{type(exc).__name__}: {exc}"
        return []


def _rebuild_pages(report: dict[str, Any]) -> list[Path]:
    """Rewrite the episode pages and sitemap (scripts/pages.py); never blocks a publish."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("pages", Path(__file__).with_name("pages.py"))
        if spec is None or spec.loader is None:
            raise ImportError("scripts/pages.py not found")
        pages = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pages)
        return list(pages.write_pages(SITE))
    except Exception as exc:  # noqa: BLE001 - the episode is still published
        report["pages_error"] = f"{type(exc).__name__}: {exc}"
        return []


def backfill(site: Path, jobs_root: Path) -> tuple[bool, list[dict[str, Any]]]:
    """Give every ``episodes.json`` entry without one a ``description`` and a ``file_name``.

    A job folder still on this machine (``jobs_root/<id>``) gives its ``description.txt``
    and ``run.json`` ``delivery.file_name`` when usable; otherwise the description is
    ``fallback_description()`` of the entry and the name is rebuilt from its show, title
    and published date. Entries that already have both are left as they are.
    Returns (index changed, what was filled per entry).
    """
    path = site / INDEX
    data = _read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("episodes"), list):
        raise ValueError(f"{INDEX} is missing or unreadable")
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
        if len(done) > 1:
            filled.append(done)
    if not filled:
        return False, []
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, filled


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
        help="give every episodes.json entry a description and file_name, rebuild the episode pages",
    )
    parser.add_argument(
        "--category", choices=CATEGORIES, help="the site tab for this one job (default: guessed)"
    )
    args = parser.parse_args(argv)
    jobs = [Path(j).expanduser() for j in args.jobs]
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
            problems = entry.pop("_description_problems", None)
            if problems:
                report.setdefault("notes", []).append(
                    f"{job.name}: description.txt not used ({'; '.join(problems)}); kept the existing or a generated one"
                )
            entries.append(entry)
            changed += files
            report["published"].append({"id": entry["id"], "title": entry["title"]})
        if entries and update_index(SITE, entries):
            changed.append(SITE / INDEX)
        if entries:
            # The Once Upon a Time Show feeds (Spotify) follow episodes.json on their own.
            changed += _rebuild_feeds(report)
            # One static page per episode and the sitemap (search engines) follow it too.
            changed += _rebuild_pages(report)
        if args.push and changed:
            report["git"] = push(changed, [e["title"] for e in entries])
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] else 0


def _backfill_main(push_it: bool) -> int:
    report: dict[str, Any] = {"filled": [], "failed": [], "git": None}
    with _lock():
        if push_it:
            _git("pull", "--rebase", "origin", "main")
        try:
            index_changed, report["filled"] = backfill(SITE, _jobs_root())
        except (OSError, ValueError) as exc:
            report["failed"].append({"job": INDEX, "error": str(exc)})
            index_changed = False
        changed = [SITE / INDEX] if index_changed else []
        if not report["failed"]:
            changed += _rebuild_pages(report)
        if push_it and changed:
            report["git"] = push(changed, [], "feat(site): backfill episode descriptions and pages")
            if not report["git"].get("pushed") and report["git"].get("error"):
                report["failed"].append({"job": "git", "error": report["git"]["error"]})
        report["changed"] = [str(p.relative_to(REPO)) for p in changed]
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["failed"] or report.get("pages_error") else 0


if __name__ == "__main__":
    sys.exit(main())
