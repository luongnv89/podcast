"""Autoplay: the next unfinished episode in the list as shown (podcast #47).

Standard library only, no network: ``python3 -m unittest discover -s tests``. The checks that
run site.js's own code (the list's sort and filters, the choice of the next episode, the
remembered setting, a refused play) need ``node`` and are skipped without it; the rest read
the files. The behaviour in a browser (an episode ends and the next starts, a reload keeps
the switch on, 360 px) is checked with headless Chromium, see the PR.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
JS = (DOCS / "site.js").read_text(encoding="utf-8")
CSS = (DOCS / "site.css").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return JS[JS.index(start):JS.index(end)]


WORDS = block("  const TEXT = {", "  // ---------- end of words")
STORE = block("  const store = {", "  // ---------- Which page lists an episode")
FOLD = re.search(r"^  const fold = .*\n", JS, re.M).group(0)
SORT = block("  // ---------- Tab, search and sort state", "  function mark(")
CHOICE = block("  // ---------- Autoplay (podcast #47)", "  // ---------- end of autoplay choice")
SWITCH = block("  // ---------- Autoplay switch", "  // ---------- Toolbar wiring")

BUILD_TABS = [{"id": t, "label": t, "empty": "", "tagline": []} for t in ("ai", "daily", "marketing", "others")]


def ep(ep_id: str, title: str, day: int, dur: int | None, cat: str = "ai", source: str | None = None, audio: bool = True) -> dict:
    e = {"id": ep_id, "title": title, "category": cat, "published": f"2026-11-{day:02d}T08:00:00Z",
         "audio": f"https://luongnv.com/buildwiz-ai-show-media/{ep_id}.mp3" if audio else None}
    if dur is not None:
        e["duration_s"] = dur
    if source:
        e["source"] = {"published": source}
    return e


# Newest first (the default): n1 (no audio), a5, a4, a3, a2, a1; d1 is on the Daily tab.
EPS = [
    ep("a1", "Alpha", 1, 600, source="2026-10-01"),
    ep("a2", "Bravo", 2, 300, source="2026-09-01"),
    ep("a3", "Charlie", 3, 900),
    ep("a4", "Delta", 4, 120, source="2026-11-01"),
    ep("a5", "Echo", 5, 450, source="2026-08-01"),
    ep("d1", "Daily news", 6, 480, cat="daily"),
    ep("n1", "No audio", 7, None, audio=False),
]

HARNESS = """
const mem = new Map(Object.entries(__STORAGE__));
const broken = __BROKEN__;
globalThis.localStorage = {
  getItem(k) { if (broken) throw new Error("SecurityError"); return mem.has(k) ? mem.get(k) : null; },
  setItem(k, v) { if (broken) throw new Error("QuotaExceededError"); mem.set(k, String(v)); },
};
const PAGE = __PAGE__;
__WORDS____STORE____FOLD____SORT__
let units = [];
let current = null;
const calls = { load: [], sync: 0, savePos: [], showNext: 0, play: 0 };
let playResult = () => Promise.resolve();
const audio = { currentTime: 0, play() { calls.play++; return playResult(); } };
function load(ep) { current = ep; calls.load.push(ep.id); }
function sync() { calls.sync++; }
function savePos(t) { calls.savePos.push(t); }
function showNext() { calls.showNext++; }
__CHOICE__
const EPS = __EPS__;
const byId = Object.fromEntries(EPS.map((e) => [e.id, e]));
units = EPS.map((e) => {
  e._hay = fold(e.title);
  const u = { versions: [e], sel: e, chosen: e, grouped: false };
  e._unit = u;
  u._cat = catOf(e);
  return u;
});
// The next episode after `from` (an id, or null) with the list in the given state.
const nextId = (from, st = {}) => {
  Object.assign(state, { tab: "ai", q: "", sort: "published", dir: "desc" }, st);
  const n = nextUnfinished(shownEpisodes(), from ? byId[from] : null, isDone);
  return n ? n.id : null;
};
const shownIds = (st = {}) => {
  Object.assign(state, { tab: "ai", q: "", sort: "published", dir: "desc" }, st);
  return shownEpisodes().map((e) => e.id);
};
const done = (...ids) => { for (const id of ids) store.set(`done:${id}`, true); };
(async () => {
  const out = await (async () => { __BODY__ })();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AutoplayInNode(unittest.TestCase):
    """Run site.js's list order and autoplay choice in node."""

    def run_js(self, body: str, storage: dict | None = None, broken: bool = False, page: dict | None = None):
        page = page or {"tabs": BUILD_TABS, "legacyTabs": {}, "pages": {}}
        script = (HARNESS.replace("__STORAGE__", json.dumps(storage or {}))
                  .replace("__BROKEN__", json.dumps(broken))
                  .replace("__PAGE__", json.dumps(page))
                  .replace("__WORDS__", WORDS).replace("__STORE__", STORE).replace("__FOLD__", FOLD)
                  .replace("__SORT__", SORT).replace("__CHOICE__", CHOICE)
                  .replace("__EPS__", json.dumps(EPS)).replace("__BODY__", body))
        out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    # ---------- the next-episode choice ----------
    def test_newest_first_takes_the_next_row_and_skips_finished_ones(self) -> None:
        got = self.run_js("""
const order = shownIds();
const plain = [nextId("a5"), nextId("a3")];
done("a4");
return { order, plain, skip: nextId("a5") };
""")
        # n1 has no audio: listed, never played.
        self.assertEqual(got["order"], ["n1", "a5", "a4", "a3", "a2", "a1"])
        self.assertEqual(got["plain"], ["a4", "a2"])
        self.assertEqual(got["skip"], "a3")

    def test_every_sort_order_is_followed(self) -> None:
        got = self.run_js("""
return {
  oldest: [shownIds({ dir: "asc" }), nextId("a1", { dir: "asc" }), nextId("a5", { dir: "asc" })],
  longest: [shownIds({ sort: "duration" }), nextId("a1", { sort: "duration" })],
  shortest: [nextId("a4", { sort: "duration", dir: "asc" })],
  title: [shownIds({ sort: "title", dir: "asc" }), nextId("a3", { sort: "title", dir: "asc" }), nextId("a5", { sort: "title", dir: "desc" })],
  source: [shownIds({ sort: "source" }), nextId("a5", { sort: "source" })],
};
""")
        # Oldest first: after the newest playable one comes n1 (no audio), so nothing.
        self.assertEqual(got["oldest"], [["a1", "a2", "a3", "a4", "a5", "n1"], "a2", None])
        # Unknown values (n1's length) sink to the end in both directions.
        self.assertEqual(got["longest"], [["a3", "a1", "a5", "a2", "a4", "n1"], "a5"])
        self.assertEqual(got["shortest"], ["a2"])
        self.assertEqual(got["title"], [["a1", "a2", "a3", "a4", "a5", "n1"], "a4", "a4"])
        # Without a source date (a3, n1): last, newest first among them; n1 has no audio.
        self.assertEqual(got["source"], [["a4", "a1", "a2", "a5", "n1", "a3"], "a3"])

    def test_the_tab_and_the_search_filter_the_list(self) -> None:
        got = self.run_js("""
return {
  daily: [shownIds({ tab: "daily" }), nextId("a5", { tab: "daily" })],
  aiNeverDaily: EPS.filter((e) => e.category === "ai").map((e) => nextId(e.id)),
  search: [shownIds({ q: "ha" }), nextId("a3", { q: "ha" })],
};
""")
        # a5 is not on the Daily tab: from the top of that tab.
        self.assertEqual(got["daily"], [["d1"], "d1"])
        self.assertNotIn("d1", got["aiNeverDaily"])
        # "ha": Charlie and Alpha only.
        self.assertEqual(got["search"], [["a3", "a1"], "a1"])

    def test_current_not_in_the_list_starts_from_the_top(self) -> None:
        got = self.run_js("""
const hidden = nextId("a5", { q: "ha" });   // Echo is hidden by the search
done("a3");
return { hidden, topFinished: nextId("a5", { q: "ha" }), none: nextId(null) };
""")
        self.assertEqual(got["hidden"], "a3")
        self.assertEqual(got["topFinished"], "a1")
        self.assertEqual(got["none"], "a5")   # no current: the first playable one (n1 has no audio)

    def test_end_of_the_list_stops_without_wrapping(self) -> None:
        got = self.run_js("""
const last = nextId("a1");
done("a3", "a2", "a1");
return { last, restFinished: nextId("a4") };
""")
        self.assertIsNone(got["last"])
        self.assertIsNone(got["restFinished"])

    def test_a_started_episode_is_not_finished_and_finished_is_the_done_flag(self) -> None:
        got = self.run_js("""
store.set("pos:a4", 60);                       // started, not finished
const started = nextId("a5");
store.set("done:a4", true);                    // played to the end once
return { started, finished: nextId("a5") };
""")
        self.assertEqual(got, {"started": "a4", "finished": "a3"})

    def test_a_version_on_show_counts_as_its_row(self) -> None:
        # A story shown as one row in several languages: the version that played may not be
        # the one a search put on show; it is still that row.
        got = self.run_js("""
const fr = Object.assign({}, byId["a3"], { id: "a3-fr", _unit: byId["a3"]._unit });
byId["a3"]._unit.versions.push(fr);
return nextUnfinished(shownEpisodes(), fr, isDone).id;
""")
        self.assertEqual(got, "a2")

    # ---------- playNext: autoplay, a refused play, next track ----------
    def test_autoplay_starts_the_next_and_marks_it(self) -> None:
        got = self.run_js("""
current = byId["a5"];
const next = playNext(true);
return { next: next.id, current: current.id, auto: autoStarted && autoStarted.id, calls };
""")
        self.assertEqual(got["next"], "a4")
        self.assertEqual(got["current"], "a4")
        self.assertEqual(got["auto"], "a4")       # its episode_play carries trigger "autoplay"
        self.assertEqual(got["calls"]["load"], ["a4"])
        self.assertEqual(got["calls"]["play"], 1)
        self.assertEqual(got["calls"]["savePos"], [])   # the ended episode already saved 0

    def test_a_refused_play_stops_quietly_with_the_next_loaded(self) -> None:
        got = self.run_js("""
playResult = () => Promise.reject(Object.assign(new Error("not allowed"), { name: "NotAllowedError" }));
current = byId["a5"];
const next = playNext(true);
await new Promise((r) => setTimeout(r, 0));
return { next: next.id, current: current.id, auto: autoStarted, syncs: calls.sync };
""")
        # Loaded and shown in the player, paused; no error, no trigger left over for a later
        # click on Play.
        self.assertEqual(got["next"], "a4")
        self.assertEqual(got["current"], "a4")
        self.assertIsNone(got["auto"])
        self.assertEqual(got["syncs"], 2)

    def test_an_old_browser_without_a_play_promise(self) -> None:
        got = self.run_js("""
playResult = () => undefined;
current = byId["a5"];
return playNext(true).id;
""")
        self.assertEqual(got, "a4")

    def test_nothing_left_stops(self) -> None:
        got = self.run_js("""
current = byId["a1"];
const next = playNext(true);
return { next, current: current.id, calls };
""")
        self.assertIsNone(got["next"])
        self.assertEqual(got["current"], "a1")
        self.assertEqual((got["calls"]["load"], got["calls"]["play"], got["calls"]["showNext"]), ([], 0, 1))

    def test_next_track_keeps_the_resume_point_and_is_not_autoplay(self) -> None:
        got = self.run_js("""
current = byId["a5"];
audio.currentTime = 123.4;
const next = playNext(false);
return { next: next.id, auto: autoStarted, saved: calls.savePos };
""")
        self.assertEqual(got, {"next": "a4", "auto": None, "saved": [123.4]})

    # ---------- the remembered setting ----------
    def test_off_by_default(self) -> None:
        self.assertFalse(self.run_js("return autoplay;"))

    def test_remembered_per_visitor(self) -> None:
        got = self.run_js("""
const before = autoplay;
setAutoplay(true);
const on = [autoplay, localStorage.getItem("autoplay")];
setAutoplay(false);
return { before, on, off: [autoplay, localStorage.getItem("autoplay")] };
""")
        self.assertEqual(got, {"before": False, "on": [True, "true"], "off": [False, "false"]})
        # A reload reads it back.
        self.assertTrue(self.run_js("return autoplay;", storage={"autoplay": "true"}))
        self.assertFalse(self.run_js("return autoplay;", storage={"autoplay": "false"}))

    def test_only_a_stored_true_turns_it_on(self) -> None:
        for raw in ('"true"', "1", '"on"', "{", "null", "[true]"):
            with self.subTest(stored=raw):
                self.assertFalse(self.run_js("return autoplay;", storage={"autoplay": raw}))

    def test_storage_unavailable(self) -> None:
        # Off, never an exception; a switch turned on stays on for the page view.
        got = self.run_js("const before = autoplay; setAutoplay(true); return [before, autoplay];", broken=True)
        self.assertEqual(got, [False, True])

    # ---------- words ----------
    def test_words_in_each_language(self) -> None:
        got = {}
        for lang in ("en", "fr", "vi"):
            page = {"tabs": [], "legacyTabs": {}, "pages": {}, "lang": lang}
            got[lang] = self.run_js("return [T.autoplay, T.next];", page=page)
        self.assertEqual(got, {"en": ["Autoplay", "Next:"],
                               "fr": ["Lecture automatique", "Ensuite :"],
                               "vi": ["Tự động phát", "Tiếp theo:"]})


class AutoplayWiringTest(unittest.TestCase):
    """Static checks of the switch and the player wiring (behaviour: browser, see the PR)."""

    def test_only_a_natural_end_starts_the_next(self) -> None:
        ended = re.search(r'audio\.addEventListener\("ended", \(\) => \{(.*?)\n  \}\);', JS, re.S).group(1)
        self.assertIn("if (autoplay) playNext(true); else showNext();", ended)
        self.assertLess(ended.index('store.set(`done:${current.id}`, true)'), ended.index("playNext(true)"))
        for event in ("error", "pause"):
            line = re.search(rf'audio\.addEventListener\("{event}", .*\n', JS).group(0)
            self.assertNotIn("playNext", line, event)
        self.assertEqual(JS.count("playNext(true)"), 1)

    def test_episode_play_says_autoplay(self) -> None:
        playing = re.search(r'audio\.addEventListener\("playing", \(\) => \{(.*?)\n  \}\);', JS, re.S).group(1)
        self.assertIn('trigger: "autoplay"', playing)
        self.assertIn("autoStarted = null;", playing)
        # A play by the visitor is never counted as autoplay.
        play = re.search(r"  function play\(ep, at\) \{(.*?)\n  \}", JS, re.S).group(1)
        self.assertIn("autoStarted = null;", play)

    def test_the_switch(self) -> None:
        self.assertRegex(SWITCH, r'el\("button", \{ class: "autoplay", type: "button", role: "switch", id: "p-auto", "aria-checked": String\(autoplay\) \}')
        self.assertIn('autoBtn.setAttribute("aria-checked", String(autoplay));', SWITCH)
        self.assertIn('track("autoplay_toggle", { enabled: autoplay });', SWITCH)
        self.assertIn("text: T.autoplay", SWITCH)
        self.assertIn("text: T.next", SWITCH)
        # The lock screen's "next track" follows the same choice, only while autoplay is on.
        self.assertIn('setActionHandler("nexttrack", next ? () => playNext(false) : null)', SWITCH)
        self.assertIn("const next = autoplay && current ? nextUnfinished(shownEpisodes(), current, isDone) : null;", SWITCH)

    def test_next_follows_the_list(self) -> None:
        apply = re.search(r"  function apply\(\) \{(.*?)\n  \}\n", JS, re.S).group(1)
        self.assertTrue(apply.rstrip().endswith('showNext();   // "Next:" follows the list\'s new order'))
        load = re.search(r"  function load\(ep, at\) \{(.*?)\n  \}\n", JS, re.S).group(1)
        self.assertTrue(load.rstrip().endswith("showNext();"))

    def test_switch_fits_a_phone(self) -> None:
        self.assertIn(".p-side { display: flex; align-items: center; gap: 10px; }", CSS)
        phone = CSS[CSS.index("@media (max-width: 640px)"):]
        self.assertIn(".p-side { grid-column: 2; justify-self: end;", phone)
        self.assertIn(".p-next { font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }", CSS)

    def test_only_the_list_pages_have_it(self) -> None:
        # The chooser stops before the player is wired; episode pages do not load site.js.
        self.assertLess(JS.index("if (PAGE.chooser)"), JS.index("const autoBtn"))
        for page in (DOCS / "episodes").glob("*/index.html"):
            self.assertNotIn("site.js", page.read_text(encoding="utf-8"), page)

    def test_documented(self) -> None:
        self.assertIn("## Autoplay (#47)", README)
        self.assertIn("| `autoplay_toggle` |", README)
        self.assertIn("`trigger` (`autoplay`", README)


if __name__ == "__main__":
    unittest.main()
