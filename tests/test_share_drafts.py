"""The share drafts panel (podcast #45): one X post and one short LinkedIn post per episode.

Standard library only, no network: ``python3 -m unittest discover -s tests``. ``docs/share.js``
runs in node (skipped without it). Luong's rules, checked on every live episode in
``docs/episodes.json`` and on made-up entries:

- the text comes only from the episode's own entry: no number the entry does not hold, every
  key point is one of its points or summary lines;
- X: one post within 280 characters as X counts them (a link is 23); LinkedIn: one short post,
  at most 400 characters besides the link, a few lines, at most two hashtags;
- X tags only a handle the data holds, an X source's author "Name (@handle)", and only as
  "based on a post by @handle"; LinkedIn names people in words; free text tags nobody;
- each draft in the episode's language (EN, FR, VI written natively), the panel's words in
  the page's;
- stories: a gentle bedtime (or story-time) framing and no tags at all;
- the X and LinkedIn links carry the draft fully encoded;
- GA4's episode_share is sent only on an action, with method x, linkedin or copy (and "More…"
  keeps #43's share_sheet / copy).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import unicodedata
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SHARE_JS = DOCS / "share.js"
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

STORY_FORMATS = ("bedtime-story", "storytelling")
# Words only each language's drafts use (the link line and the credit).
LISTEN = {"en": "🎧 Listen: ", "fr": "🎧 À écouter\u00a0: ", "vi": "🎧 Nghe tại: "}
BASED_ON_POST = {"en": "Based on a post by ", "fr": "D’après une publication de ", "vi": "Dựa trên bài đăng của "}
FRAME = {
    "en": {"bedtime-story": "A gentle story to listen to at bedtime:", "storytelling": "A gentle story to listen to at story time:"},
    "fr": {"bedtime-story": "Une histoire douce à écouter au moment du coucher\u00a0:", "storytelling": "Une histoire douce à écouter à l’heure du conte\u00a0:"},
    "vi": {"bedtime-story": "Một câu chuyện nhẹ nhàng để nghe trước giờ đi ngủ:", "storytelling": "Một câu chuyện nhẹ nhàng cho giờ kể chuyện:"},
}
ENGLISH_ONLY = ("Listen:", "Based on", "A gentle story")
HANDLE = re.compile(r"\(@([A-Za-z0-9_]{1,15})\)\s*$")


# ---------- X's count, written here independently of share.js ----------
_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def _weigh(text: str) -> int:
    return sum(1 if any(a <= ord(c) <= b for a, b in _LIGHT) else 2 for c in text)


def x_length(text: str) -> int:
    """twitter-text v3: light code points 1, others 2, an http(s) link 23; a bare domain at least 23."""
    text = unicodedata.normalize("NFC", text)
    n = pos = 0
    for m in re.finditer(r"https?://\S+|(?:[\w-]+\.)+[^\W\d_]{2,}(?:/\S*)?", text):
        n += _weigh(text[pos:m.start()]) + (23 if m.group().startswith("http") else max(23, _weigh(m.group())))
        pos = m.end()
    return n + _weigh(text[pos:])


def is_story(ep: dict) -> bool:
    return ep.get("format") in STORY_FORMATS or ep.get("show") == pages.STORY_SHOW


def lang_of(ep: dict) -> str:
    lang = pages._lang(ep)
    return lang if lang in LISTEN else "en"


def x_handle(ep: dict) -> str | None:
    """The only handle a draft may tag: the main source's, when it is an X source."""
    src = ep.get("source") or {}
    url = str(src.get("url") or "")
    is_x = src.get("kind") == "x" or re.match(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/", url, re.I)
    m = HANDLE.search(str(src.get("author") or ""))
    return m.group(1) if is_x and m else None


def entry_text(ep: dict) -> str:
    parts = [ep.get("id"), ep.get("title"), ep.get("description"), *(ep.get("summary") or [])]
    for src in [ep.get("source") or {}, *(ep.get("sources") or [])]:
        parts += [src.get("title"), src.get("author")]
    return "\n".join(str(p) for p in parts if p)


# A display name as a credit writes it: no handle, no emoji, no trailing "(ABBR)"; case kept.
_EMOJI = re.compile("[\u00a9\u00ae\u203c\u2049\u2122\u2139\u2194-\u21aa\u231a-\u23ff\u24c2\u25aa-\u27bf"
                    "\u2934\u2935\u2b05-\u2b55\u3030\u303d\u3297\u3299\U0001f000-\U0001faff\u200d\ufe0f\u20e3]")


def credit_name(author: str) -> str:
    name = re.sub(r"\s+", " ", _EMOJI.sub("", HANDLE.sub("", author))).strip()
    return re.sub(r"\s*\([A-Z0-9&.]{2,}\)$", "", name)


# A point's "His/Her/Their …:" opener, dropped when the draft has not named the person yet.
OPENER = re.compile(r"^(?:His|Her|Their)(?:\s+[^\s:]+){1,3}:\s+(?=\S)")


def without_opener(point: str) -> str:
    rest = OPENER.sub("", point)
    return rest[:1].upper() + rest[1:] if rest != point else point


def entry_points(ep: dict) -> list[str]:
    desc = str(ep.get("description") or "")
    bullets = [m.group(1) for m in re.finditer(r"^\s*[-•]\s+(.+)$", desc, re.M)]
    return [re.sub(r"\s+", " ", p).strip() for p in bullets + list(ep.get("summary") or [])]


# ---------- node ----------
def node(script: str) -> object:
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


LOAD = r"""
const window = {};
new Function("window", __CODE__)(window);
const P = window.PodcastShare;
"""


def run(body: str) -> object:
    return node(LOAD.replace("__CODE__", json.dumps(SHARE_JS.read_text(encoding="utf-8"))) + body)


def drafts_of(eps: list[dict]) -> dict:
    data = [{"ep": ep, "url": pages.page_url(ep["id"])} for ep in eps]
    return run(f"""
const out = {{}};
for (const {{ ep, url }} of {json.dumps(data)}) {{
  const d = P.drafts(ep, url);
  out[ep.id] = {{ ...d, xLen: P.xLength(d.x), liLen: P.linkedinLength(d.linkedin, url),
    xIntent: P.xIntent(d.x), liIntent: P.linkedinIntent(d.linkedin, url) }};
}}
console.log(JSON.stringify(out));
""")  # type: ignore[return-value]


def base(**kw: object) -> dict:
    ep = {
        "id": "2026-11-20_test", "title": "A test episode", "format": "podcast-2host", "show": pages.BUILD_SHOW,
        "language": "en", "category": "ai",
        "summary": ["First line of the summary.", "Second line.", "Third line."],
        "description": "Is this a question? Bob and Alice unpack it.\n\nIn this episode:\n- Point one\n- Point two\n- Point three\n\nSources: X\nBig AI ideas. luongnv.com/podcast",
        "source": {"title": "A source", "author": "Jane Doe (@janedoe)", "url": "https://x.com/janedoe/status/1", "kind": "x"},
    }
    ep.update(kw)
    return ep


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class LiveEpisodesTest(unittest.TestCase):
    """Every live episode's drafts follow every rule."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eps = pages.site_episodes(DOCS)
        cls.drafts = drafts_of(cls.eps)

    def each(self):
        assert self.eps
        for ep in self.eps:
            with self.subTest(id=ep["id"]):
                yield ep, self.drafts[ep["id"]], pages.page_url(ep["id"])

    def test_x_post_fits_280(self) -> None:
        for ep, d, url in self.each():
            self.assertLessEqual(x_length(d["x"]), 280, d["x"])
            self.assertEqual(d["xLen"], x_length(d["x"]))  # share.js counts as X does
            self.assertEqual(d["x"].count(url), 1)

    def test_linkedin_post_is_short(self) -> None:
        for ep, d, url in self.each():
            self.assertEqual(d["linkedin"].count(url), 1)
            self.assertLessEqual(len(d["linkedin"].replace(url, "")), 400, d["linkedin"])
            self.assertEqual(d["liLen"], len(d["linkedin"].replace(url, "")))
            lines = [line for line in d["linkedin"].split("\n") if line.strip()]
            self.assertLessEqual(len(lines), 6)   # hook, two points, link, credit (a story's link: two lines)
            self.assertLessEqual(len(re.findall(r"(?<!\S)#\w", d["linkedin"])), 2)

    def test_no_number_absent_from_the_entry(self) -> None:
        for ep, d, url in self.each():
            known = set(re.findall(r"\d+", entry_text(ep)))
            for text in (d["x"], d["linkedin"]):
                found = set(re.findall(r"\d+", text.replace(url, "")))
                self.assertLessEqual(found, known, text)

    def test_points_and_hook_come_from_the_entry(self) -> None:
        for ep, d, url in self.each():
            points = entry_points(ep)
            text = entry_text(ep)
            for draft in (d["x"], d["linkedin"]):
                for line in draft.split("\n"):
                    if line.startswith("→ "):
                        p = line[2:]
                        own = points + [without_opener(q) for q in points]
                        self.assertTrue(p in own or (p.endswith("…") and any(q.startswith(p[:-1].rstrip()) for q in own)), p)
                hook = draft.split("\n\n")[0]
                core = hook[:-1].rstrip() if hook.endswith("…") else hook
                self.assertIn(re.sub(r"\s+", " ", core), re.sub(r"\s+", " ", text))

    def test_handle_only_from_an_x_source_author(self) -> None:
        tagged = 0
        for ep, d, url in self.each():
            handle = x_handle(ep)
            self.assertNotIn("@", d["linkedin"])   # LinkedIn names people in words
            mentions = re.findall(r"@(\w+)", d["x"])
            if is_story(ep) or not handle:
                self.assertEqual(mentions, [])
                continue
            tagged += 1
            self.assertEqual(mentions, [handle])
            # Only "based on a post by @handle", the post's last line: no endorsement implied.
            last = d["x"].split("\n")[-1]
            self.assertEqual(last, BASED_ON_POST[d["lang"]] + "@" + handle)
            name = credit_name(ep["source"]["author"])
            self.assertIn(BASED_ON_POST[d["lang"]] + name + "\n", d["linkedin"])
        self.assertGreater(tagged, 5)

    def test_each_draft_in_the_episode_language(self) -> None:
        langs = set()
        for ep, d, url in self.each():
            lang = lang_of(ep)
            langs.add(lang)
            self.assertEqual(d["lang"], lang)
            for draft in (d["x"], d["linkedin"]):
                if is_story(ep):
                    self.assertIn(FRAME[lang][ep["format"]], draft)
                else:
                    self.assertIn(LISTEN[lang] + url, draft)
                if lang != "en":
                    for word in ENGLISH_ONLY:
                        self.assertNotIn(word, draft)
        self.assertEqual(langs, {"en", "fr", "vi"})

    def test_stories_are_framed_gently_without_tags(self) -> None:
        stories = 0
        for ep, d, url in self.each():
            if not is_story(ep):
                self.assertRegex(d["linkedin"], r"#\w+$")  # Build Wiz AI Show: topic hashtags at the end
                self.assertRegex(d["linkedin"].split("\n")[-1], r"^#\w+(?: #\w+)?$")  # on their own line
                self.assertNotIn("#", d["x"].replace(url, ""))
                continue
            stories += 1
            for draft in (d["x"], d["linkedin"]):
                self.assertNotIn("@", draft)
                self.assertNotIn("#", draft.replace(url, ""))
                self.assertIn("🌙 " + FRAME[d["lang"]][ep["format"]] + "\n" + url, draft)
        self.assertGreater(stories, 10)

    def test_linkedin_hashtags_on_their_own_line(self) -> None:
        for ep, d, url in self.each():
            if is_story(ep):
                continue
            lines = d["linkedin"].split("\n")
            self.assertRegex(lines[-1], r"^#\w+(?: #\w+)?$")
            self.assertNotRegex("\n".join(lines[:-1]), r"(?<!\S)#\w")   # no tag anywhere else
            credit = lines[-2]
            if credit.startswith(BASED_ON_POST[d["lang"]]):
                name = credit[len(BASED_ON_POST[d["lang"]]):]
                self.assertEqual(name, credit_name(ep["source"]["author"]))
                self.assertNotRegex(name, r"\([A-Z0-9&.]{2,}\)$|[\U0001f000-\U0001faff]")

    def test_no_pronoun_before_the_person_is_named(self) -> None:
        for ep, d, url in self.each():
            name = credit_name(str((ep.get("source") or {}).get("author") or "")).lower()
            for draft in (d["x"], d["linkedin"]):
                before = ""
                for line in draft.split("\n"):
                    if line.startswith("→ ") and re.match(r"(?:His|Her|Their)\b", line[2:]):
                        self.assertTrue(name and name in before.lower(), line)
                    before += line + "\n"

    # The five live drafts whose first point opened on "His …" with the person named only in the credit.
    PRONOUN_FIXES = {
        "2026-11-04_a-practical-guide-to-security-in-november-2026": "Years-old best practices still work, from passkeys",
        "2026-11-05_marketing-engineers-100x-more-experiments-with": "Write the business \"brain\" first, connect the data",
        "2026-11-05_marketing-engineers-solo-explainer": "Write the business \"brain\" first, connect the data",
        "2026-11-06_5t-opportunity-ai-roll-ups": "Buy the customers and trust, build a rulebook",
        "2026-11-03_the-most-lucrative-ai-business-to-start-in-2027": "Capturing attention is the top skill",
    }

    def test_the_five_his_openers_are_dropped(self) -> None:
        for id_, start in self.PRONOUN_FIXES.items():
            with self.subTest(id=id_):
                d = self.drafts[id_]
                for draft in (d["x"], d["linkedin"]):
                    self.assertIn("\n\n→ " + start, draft)
                    self.assertNotIn("→ His ", draft)

    def test_intent_urls_are_encoded(self) -> None:
        for ep, d, url in self.each():
            x = urlsplit(d["xIntent"])
            self.assertEqual((x.scheme, x.netloc, x.path), ("https", "x.com", "/intent/post"))
            self.assertNotRegex(x.query, r"[\s#+]")
            self.assertEqual(parse_qs(x.query, strict_parsing=True), {"text": [d["x"]]})
            li = urlsplit(d["liIntent"])
            self.assertEqual((li.scheme, li.netloc, li.path), ("https", "www.linkedin.com", "/feed/"))
            self.assertNotRegex(li.query, r"[\s#+]")
            self.assertEqual(parse_qs(li.query, strict_parsing=True), {"shareActive": ["true"], "text": [d["linkedin"]]})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class RulesTest(unittest.TestCase):
    """Made-up entries for the cases the live data does not have."""

    def drafts(self, **kw: object) -> dict:
        ep = base(**kw)
        return drafts_of([ep])[ep["id"]]

    def test_handle_only_from_an_x_source(self) -> None:
        d = self.drafts()
        self.assertTrue(d["x"].endswith("\nBased on a post by @janedoe"))
        self.assertTrue(d["linkedin"].endswith("\nBased on a post by Jane Doe\n#AI #Podcast"))
        # An article whose author has a handle: named, never tagged.
        d = self.drafts(source={"title": "T", "author": "Jane Doe (@janedoe)", "url": "https://example.com/a", "kind": "article"})
        self.assertNotIn("@", d["x"])
        self.assertTrue(d["x"].endswith("\nBased on an article by Jane Doe"))
        # An X post without a handle in the data: the name in words, no guessed handle.
        d = self.drafts(source={"title": "T", "author": "Jane Doe", "url": "https://x.com/janedoe/status/1", "kind": "x"})
        self.assertNotIn("@", d["x"])
        self.assertTrue(d["x"].endswith("\nBased on a post by Jane Doe"))
        # An x.com URL counts as an X source even with another kind.
        d = self.drafts(source={"title": "T", "author": "J (@j_1)", "url": "https://twitter.com/j_1/status/2", "kind": "thread"})
        self.assertTrue(d["x"].endswith("\nBased on a post by @j_1"))
        # Other kinds: "Source: name"; no author: the title; the show's own text: no credit.
        d = self.drafts(source={"title": "A talk", "author": "Lance Martin", "url": "https://www.youtube.com/watch?v=1", "kind": "text"})
        self.assertTrue(d["x"].endswith("\nSource: Lance Martin"))
        d = self.drafts(source={"title": "A talk", "author": None, "url": None, "kind": "text"})
        self.assertTrue(d["x"].endswith("\nBased on “A talk”"))
        d = self.drafts(source={"title": "Meet", "author": "Build Wiz AI Show", "url": None, "kind": "text"})
        self.assertTrue(d["x"].endswith("/2026-11-20_test/"))

    def test_credit_names_lose_their_decorations(self) -> None:
        d = self.drafts(source={"title": "T", "author": "The Startup Ideas Podcast (SIP) 🧃 (@startupideaspod)", "url": "https://x.com/startupideaspod/status/1", "kind": "x"})
        self.assertTrue(d["x"].endswith("\nBased on a post by @startupideaspod"))   # the handle untouched
        self.assertTrue(d["linkedin"].endswith("\nBased on a post by The Startup Ideas Podcast\n#AI #Podcast"))
        # All-caps and lowercase names stay as written; a handle's own case and digits too.
        d = self.drafts(source={"title": "T", "author": "GREG ISENBERG (@GregIsenberg_1)", "url": "https://x.com/a/status/1", "kind": "x"})
        self.assertTrue(d["x"].endswith("\nBased on a post by @GregIsenberg_1"))
        self.assertIn("\nBased on a post by GREG ISENBERG\n", d["linkedin"])
        d = self.drafts(source={"title": "T", "author": "dex 🚀👩🏽‍💻 (@dexhorthy)", "url": "https://x.com/a/status/1", "kind": "x"})
        self.assertIn("\nBased on a post by dex\n", d["linkedin"])
        # Without a handle, X names the cleaned name too; a "(…)" that is not an abbreviation stays.
        d = self.drafts(source={"title": "T", "author": "Jane Doe (AI) 🧃", "url": "https://example.com/a", "kind": "article"})
        self.assertTrue(d["x"].endswith("\nBased on an article by Jane Doe"))
        d = self.drafts(source={"title": "T", "author": "Jane Doe (she/her)", "url": "https://example.com/a", "kind": "article"})
        self.assertTrue(d["x"].endswith("\nBased on an article by Jane Doe (she/her)"))
        # A name of emoji only: the source's title instead.
        d = self.drafts(source={"title": "A talk", "author": "🧃 (@juice)", "url": "https://example.com/a", "kind": "article"})
        self.assertTrue(d["x"].endswith("\nBased on “A talk”"))

    def test_pronoun_openers(self) -> None:
        desc = "A statement.\n\nIn this episode:\n- {0}\n- Two\n"
        # Named only in the credit: the "His …:" opener goes, the rest is capitalised.
        d = self.drafts(description=desc.format("His playbook: buy the customers first."))
        for text in (d["x"], d["linkedin"]):
            self.assertIn("\n\n→ Buy the customers first.\n→ Two\n", text)
        d = self.drafts(description=desc.format("Their take on AI: it is early."))
        self.assertIn("→ It is early.", d["x"])
        # No "…:" opener: the pronoun becomes the author's name from the entry.
        d = self.drafts(description=desc.format("Her team shipped it in a week."))
        self.assertIn("→ Jane Doe’s team shipped it in a week.", d["x"])
        # Named in the hook already: the point is kept as written.
        d = self.drafts(title="Jane Doe on agents", description=desc.format("Her point: agents need tests."))
        self.assertIn("→ Her point: agents need tests.", d["x"])
        # Named in an earlier point: the later one keeps its pronoun.
        d = self.drafts(description="A statement.\n\nIn this episode:\n- Jane Doe built it.\n- His point: tests.\n")
        self.assertIn("→ Jane Doe built it.\n→ His point: tests.", d["linkedin"])
        # No author to name and no opener to drop: the point is left out.
        d = self.drafts(description=desc.format("His team shipped it."), source={"title": "T", "author": None, "url": None, "kind": "text"})
        self.assertNotIn("His", d["x"] + d["linkedin"])
        self.assertIn("→ Two", d["x"])
        # A word that only starts with the pronoun is not one.
        d = self.drafts(description=desc.format("Heroes are rare."))
        self.assertIn("→ Heroes are rare.", d["x"])

    def test_free_text_tags_nobody(self) -> None:
        d = self.drafts(description="Did @sama say it? Yes. #hype\n\nIn this episode:\n- Ask @pg and #yc\n- Two\n")
        self.assertEqual(re.findall(r"@\w+", d["x"]), ["@janedoe"])
        self.assertNotIn("@", d["linkedin"])
        for text in (d["x"], d["linkedin"]):
            self.assertNotIn("#hype", text)
            self.assertNotIn("#yc", text)
        self.assertIn("Did sama say it?", d["x"])

    def test_question_hook_else_title(self) -> None:
        self.assertTrue(self.drafts()["x"].startswith("Is this a question?\n\n→ Point one\n→ Point two\n\n"))
        d = self.drafts(description="A statement. Bob and Alice unpack it.\n\nIn this episode:\n- P1\n- P2\n")
        self.assertTrue(d["x"].startswith("A test episode\n\n→ P1\n→ P2\n\n"))
        # No points in the description: the summary after its first line.
        d = self.drafts(description="")
        self.assertTrue(d["x"].startswith("A test episode\n\n→ Second line.\n→ Third line.\n\n"))

    def test_long_text_is_cut_to_fit(self) -> None:
        long_point = " ".join(["word"] * 120)
        d = self.drafts(description=f"Why?\n\nIn this episode:\n- {long_point}\n- {long_point}\n", title="T " * 10)
        url = pages.page_url("2026-11-20_test")
        self.assertLessEqual(x_length(d["x"]), 280)
        self.assertLessEqual(len(d["linkedin"].replace(url, "")), 400)
        self.assertIn("…", d["x"])
        self.assertTrue(d["x"].endswith("Based on a post by @janedoe"))  # the credit always stays
        self.assertEqual(d["x"].count("→ "), 1)
        # A very long title alone: the hook is cut, the link and credit stay.
        d = self.drafts(title=" ".join(["title"] * 100), description="", summary=[])
        self.assertLessEqual(x_length(d["x"]), 280)
        self.assertIn(url, d["x"])

    def test_vietnamese_counts_double_on_x(self) -> None:
        self.assertEqual(x_length("ệ"), 2)
        self.assertEqual(x_length("e"), 1)
        self.assertEqual(x_length("https://luongnv.com/podcast/episodes/a-very-long-id/"), 23)
        got = run('console.log(JSON.stringify([P.xLength("ệ"), P.xLength("🧃"), P.xLength("→"), P.xLength("https://luongnv.com/podcast/episodes/a-very-long-id/"), P.xLength("see a16z.news")]))')
        self.assertEqual(got, [2, 2, 2, 23, 27])
        vi = " ".join(["Nhà rơm, nhà gỗ và nhà gạch ở thị trấn ven sông."] * 12)
        d = self.drafts(language="vi", description=f"{vi}\n\nTrong tập này:\n- {vi}\n- Hai\n")
        self.assertLessEqual(x_length(d["x"]), 280)

    def test_languages(self) -> None:
        fr = self.drafts(language="fr", source={"title": "T", "author": "Olivia Moore", "url": "https://a16z.news/p", "kind": "article"})
        self.assertIn("🎧 À écouter\u00a0: https://", fr["x"])
        self.assertTrue(fr["x"].endswith("\nD’après un article d’Olivia Moore"))  # elided before a vowel
        fr = self.drafts(language="fr-FR", source={"title": "T", "author": "Lenny Rachitsky", "url": "https://a.b/p", "kind": "article"})
        self.assertTrue(fr["x"].endswith("\nD’après un article de Lenny Rachitsky"))
        self.assertEqual(fr["lang"], "fr")
        vi = self.drafts(language="vi")
        self.assertIn("🎧 Nghe tại: https://", vi["x"])
        self.assertTrue(vi["x"].endswith("\nDựa trên bài đăng của @janedoe"))
        de = self.drafts(language="de")   # no templates for German: English
        self.assertEqual(de["lang"], "en")
        self.assertIn("🎧 Listen: https://", de["x"])

    def test_story_framing(self) -> None:
        story = dict(format="bedtime-story", show=pages.STORY_SHOW, category="bedtime", language="fr",
                     source={"title": "Three Little Pigs", "author": None, "url": "https://sites.pitt.edu/~dash/type0124.html", "kind": "article"},
                     description="Une douce histoire. Personne n'a de mal.\n\nDans cet épisode :\n- Des maisons\n- Un loup\n\nSources : Three Little Pigs, Joseph Jacobs (@jj)\nMusique : X")
        d = self.drafts(**story)
        url = pages.page_url("2026-11-20_test")
        for text in (d["x"], d["linkedin"]):
            self.assertIn("🌙 Une histoire douce à écouter au moment du coucher\u00a0:\n" + url, text)
            self.assertNotIn("@", text)
            self.assertNotIn("#", text)
        self.assertTrue(d["linkedin"].endswith("\nSources : Three Little Pigs, Joseph Jacobs"))
        d = self.drafts(**{**story, "format": "storytelling", "language": "en"})
        self.assertIn("🌙 A gentle story to listen to at story time:\n" + url, d["x"])
        # A story's X handle in its source is never tagged.
        d = self.drafts(**{**story, "source": {"title": "T", "author": "A (@a)", "url": "https://x.com/a/status/1", "kind": "x"}})
        self.assertNotIn("@", d["x"] + d["linkedin"])

    def test_linkedin_falls_back_to_the_link_only(self) -> None:
        got = run('console.log(JSON.stringify([P.linkedinIntent("  ", "https://luongnv.com/podcast/episodes/a b/"), P.linkedinIntent("x".repeat(9000), "https://u/")]))')
        self.assertEqual(got[0], "https://www.linkedin.com/sharing/share-offsite/?url=https%3A%2F%2Fluongnv.com%2Fpodcast%2Fepisodes%2Fa%20b%2F")
        self.assertEqual(got[1], "https://www.linkedin.com/sharing/share-offsite/?url=https%3A%2F%2Fu%2F")


# A small DOM for the panel: elements, events, focus, and the document's key and pointer events.
DOM = r"""
let doc;
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null; this.attrs = {}; this.listeners = {};
    this.hidden = false; this._text = ""; this.style = {}; this.className = ""; this.id = "";
    const cls = new Set();
    this.classList = { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
      toggle: (c, on) => ((on === undefined ? !cls.has(c) : on) ? cls.add(c) : cls.delete(c)) };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  append(...kids) { for (let n of kids) { if (typeof n === "string") { const t = new El("#text"); t._text = n; n = t; } n.parentNode = this; this.children.push(n); } }
  after(n) { const p = this.parentNode; n.parentNode = p; p.children.splice(p.children.indexOf(this) + 1, 0, n); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, e = {}) { return Promise.all((this.listeners[t] || []).map((f) => f({ button: 0, target: this, preventDefault() {}, ...e }))); }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  focus() { doc.activeElement = this; }
  scrollIntoView() {}
  all() { return [this, ...this.children.flatMap((c) => c.all())]; }
  find(attr, val) { return this.all().find((n) => n.attrs[attr] === val); }
}
const docListeners = {};
doc = {
  head: new El("head"), body: new El("body"), activeElement: null,
  createElement: (t) => new El(t),
  getElementById: (id) => doc.head.all().find((n) => n.id === id) || null,
  addEventListener: (t, f) => (docListeners[t] = docListeners[t] || []).push(f),
};
const fireDoc = (t, e) => (docListeners[t] || []).forEach((f) => f({ preventDefault() {}, ...e }));
const timers = [];
const window = {};
new Function("window", "document", "setTimeout", "clearTimeout", __CODE__)(window, doc, (f) => timers.push(f), () => {});
const P = window.PodcastShare;
"""

PANEL_RUN = r"""
(async () => {
  const actions = new El("p"); doc.body.append(actions);
  const button = new El("button"); actions.append(button);
  const outside = new El("div"); doc.body.append(outside);
  const log = { events: [], copies: [], more: [] };
  let copyOk = true;
  const o = {
    ep: __EP__, url: "https://luongnv.com/podcast/episodes/__ID__/", lang: __LANG__, button, after: actions,
    track: (m) => log.events.push(m),
    copy: async (t) => { log.copies.push(t); return copyOk; },
    more: (b, l, rest) => log.more.push([b.attrs["data-share-action"], l.textContent, rest]),
  };
  const out = {};
  const panel = P.toggle(o);
  out.opened = { expanded: button.getAttribute("aria-expanded"), controls: button.getAttribute("aria-controls") === panel.id,
    after: actions.parentNode.children.indexOf(panel) === actions.parentNode.children.indexOf(actions) + 1,
    focus: doc.activeElement === panel._heading, events: log.events.slice(), style: !!doc.getElementById("share-panel-style") };
  const q = (a) => panel.find("data-share-action", a);
  const ta = (k) => panel.find("data-draft", k);
  out.words = { heading: panel._heading.textContent, x: q("x").textContent, linkedin: q("linkedin").textContent,
    copy: q("copy-x").textContent, more: q("more").textContent, close: q("close").getAttribute("aria-label"),
    lang: ta("x").getAttribute("lang") };
  out.drafts = { x: ta("x").value, linkedin: ta("linkedin").value };
  out.hrefs = { x: q("x").href, linkedin: q("linkedin").href };
  out.count = panel.all().find((n) => n.className === "sp-count").textContent;

  await q("x").fire("click");
  await q("x").fire("auxclick", { button: 2 });   // a right click is not a share
  await q("x").fire("auxclick", { button: 1 });
  await q("linkedin").fire("click");
  await q("copy-x").fire("click");
  out.copyLabel = q("copy-x").textContent;
  copyOk = false;
  await q("copy-linkedin").fire("click");
  out.failLabel = q("copy-linkedin").textContent;
  timers.splice(0).forEach((f) => f());
  out.copyAfter = q("copy-x").textContent;
  await q("more").fire("click");

  ta("x").value = "Edited & #1 + ?";
  await ta("x").fire("input");
  out.edited = q("x").href;
  ta("x").value = "é".repeat(300);
  await ta("x").fire("input");
  const count = panel.all().find((n) => n.className === "sp-count");
  out.over = [count.textContent, count.classList.contains("is-over")];

  fireDoc("keydown", { key: "Escape" });
  out.esc = { hidden: panel.hidden, expanded: button.getAttribute("aria-expanded"), focus: doc.activeElement === button };
  P.toggle(o);
  out.reopened = { same: !panel.hidden, kept: ta("x").value === "é".repeat(300) };
  fireDoc("pointerdown", { target: ta("linkedin") });
  out.insideClick = panel.hidden;
  fireDoc("pointerdown", { target: outside });
  out.outsideClick = panel.hidden;
  P.toggle(o); await q("close").fire("click");
  out.closeBtn = { hidden: panel.hidden, focus: doc.activeElement === button };
  P.toggle(o); P.toggle(o);
  out.toggledShut = panel.hidden;
  out.log = log;
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class PanelTest(unittest.TestCase):
    """The panel in a small DOM: its words, its links, what it sends to GA4, how it closes."""

    def panel(self, ep: dict, lang: str) -> dict:
        code = json.dumps(SHARE_JS.read_text(encoding="utf-8"))
        script = DOM.replace("__CODE__", code) + PANEL_RUN.replace("__EP__", json.dumps(ep)).replace(
            "__ID__", ep["id"]).replace("__LANG__", json.dumps(lang))
        return node(script)  # type: ignore[return-value]

    def test_build_wiz_episode(self) -> None:
        ep = next(e for e in pages.site_episodes(DOCS) if e["id"] == "2026-11-10_become-a-cracked-marketer")
        got = self.panel(ep, "en")
        self.assertEqual(got["opened"], {"expanded": "true", "controls": True, "after": True, "focus": True, "events": [], "style": True})
        self.assertEqual(got["words"], {"heading": "Share this episode", "x": "Post on X", "linkedin": "Post on LinkedIn",
                                        "copy": "Copy", "more": "More…", "close": "Close", "lang": "en"})
        drafts = drafts_of([ep])[ep["id"]]
        self.assertEqual(got["drafts"], {"x": drafts["x"], "linkedin": drafts["linkedin"]})
        self.assertEqual(got["hrefs"], {"x": drafts["xIntent"], "linkedin": drafts["liIntent"]})
        self.assertEqual(got["count"], f"{x_length(drafts['x'])}/280")
        # GA4: only actions, each with its method; a failed copy sends nothing.
        self.assertEqual(got["log"]["events"], ["x", "x", "linkedin", "copy"])
        # LinkedIn's button also copies its text (pasted if LinkedIn opens empty).
        self.assertEqual(got["log"]["copies"], [drafts["linkedin"], drafts["x"], drafts["linkedin"]])
        self.assertEqual((got["copyLabel"], got["failLabel"], got["copyAfter"]), ("Copied", "Copy failed", "Copy"))
        self.assertEqual(got["log"]["more"], [["more", "More…", "More…"]])  # #43's share sheet / copy
        # An edit goes straight into the link, encoded.
        self.assertEqual(got["edited"], "https://x.com/intent/post?text=Edited%20%26%20%231%20%2B%20%3F")
        self.assertEqual(got["over"], ["300/280, too long for X", True])
        self.assertEqual(got["esc"], {"hidden": True, "expanded": "false", "focus": True})
        self.assertEqual(got["reopened"], {"same": True, "kept": True})
        self.assertEqual((got["insideClick"], got["outsideClick"]), (False, True))
        self.assertEqual(got["closeBtn"], {"hidden": True, "focus": True})
        self.assertTrue(got["toggledShut"])

    def test_french_story_page(self) -> None:
        ep = next(e for e in pages.site_episodes(DOCS) if e["id"] == "2026-11-10_three-little-pigs-fr")
        got = self.panel(ep, "fr")
        self.assertEqual(got["words"], {"heading": "Partager cette histoire", "x": "Publier sur X", "linkedin": "Publier sur LinkedIn",
                                        "copy": "Copier", "more": "Autres options…", "close": "Fermer", "lang": "fr"})
        self.assertEqual((got["copyLabel"], got["failLabel"]), ("Copié", "Échec de la copie"))
        self.assertEqual(got["over"], ["300/280, trop long pour X", True])
        self.assertEqual(got["log"]["events"], ["x", "x", "linkedin", "copy"])

    def test_panel_words_follow_the_page_drafts_the_episode(self) -> None:
        # A Vietnamese Build Wiz AI Show episode on the English page: English words, Vietnamese drafts.
        ep = next(e for e in pages.site_episodes(DOCS) if e["id"] == "2026-11-04_critical-thinking-when-agents-do-the-work")
        got = self.panel(ep, "en")
        self.assertEqual((got["words"]["heading"], got["words"]["lang"]), ("Share this episode", "vi"))
        self.assertIn("🎧 Nghe tại: ", got["drafts"]["x"])
        got = self.panel(next(e for e in pages.site_episodes(DOCS) if e["id"] == "2026-11-06_little-red-cap-vi"), "vi")
        self.assertEqual((got["words"]["heading"], got["words"]["x"], got["words"]["more"]), ("Chia sẻ truyện này", "Đăng lên X", "Cách khác…"))

    def test_every_language_has_every_word(self) -> None:
        got = run("console.log(JSON.stringify(Object.fromEntries(Object.entries(P.WORDS).map(([l, w]) => [l, Object.keys(w).sort()]))))")
        self.assertEqual(set(got), {"en", "fr", "vi"})
        self.assertEqual(got["fr"], got["en"])
        self.assertEqual(got["vi"], got["en"])


class EpisodePageDataTest(unittest.TestCase):
    """Each episode page loads share.js and carries the fields the drafts are written from."""

    def test_live_pages(self) -> None:
        for ep in pages.site_episodes(DOCS):
            with self.subTest(id=ep["id"]):
                html = (DOCS / "episodes" / ep["id"] / "index.html").read_text(encoding="utf-8")
                self.assertEqual(html.count(f'<script src="../../share.js?v={pages.ASSET_VERSION}"></script>\n<script>\n(() => {{\n  const S = '), 1)
                data = json.loads(re.search(r"\n  const S = (\{.*?\});\n", html).group(1))
                self.assertEqual(data["lang"], pages.story_lang(ep) if is_story(ep) else "en")
                for key in ("id", "title", "summary", "description", "format", "language"):
                    self.assertEqual(data["ep"][key], ep[key])
                src = {k: v for k, v in ep["source"].items() if k in ("title", "author", "url", "kind") and v is not None}
                self.assertEqual(data["ep"]["source"], src)
                self.assertNotIn("audio", data["ep"])

    def test_only_a_web_source_url(self) -> None:
        ep = {"id": "z", "title": "T", "source": {"title": "S", "author": None, "url": "javascript:alert(1)", "kind": "x"}}
        self.assertEqual(pages.share_data(ep)["ep"]["source"], {"title": "S", "kind": "x"})


if __name__ == "__main__":
    unittest.main()
