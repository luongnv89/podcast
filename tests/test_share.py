"""The Share button on every episode (podcast #43).

Standard library only, no network: ``python3 -m unittest discover -s tests``. The behaviour
runs in node (skipped without it) with a stubbed browser: ``navigator.share``, the Clipboard
API, ``execCommand`` and ``gtag``. Both copies are run: ``shareEpisode()`` in
``docs/site.js`` (the list pages' cards) and the script ``scripts/pages.py`` writes into each
episode page.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
_spec = importlib.util.spec_from_file_location("pages", ROOT / "scripts" / "pages.py")
assert _spec is not None and _spec.loader is not None
pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pages)

# Luong's words (issue #43): label and confirmation per page language.
WORDS = {"en": ("Share", "Link copied"), "fr": ("Partager", "Lien copié"), "vi": ("Chia sẻ", "Đã sao chép liên kết")}
LIST_PAGES = {
    "build": DOCS / "index.html",
    "en": DOCS / "stories" / "en" / "index.html",
    "fr": DOCS / "stories" / "fr" / "index.html",
    "vi": DOCS / "stories" / "vi" / "index.html",
}


def site_js() -> str:
    return (DOCS / "site.js").read_text(encoding="utf-8")


def between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def text_block(lang: str) -> str:
    match = re.search(rf"\n    {lang}: \{{\n(.*?)\n    \}},", site_js(), re.S)
    assert match, f"no {lang} block in site.js TEXT"
    return match.group(1)


def page_script(html: str) -> str:
    match = re.search(r"<script>\n(\(\(\) => \{\n  const S = .*?\n\}\)\(\);)\n</script>\n</body>", html, re.S)
    assert match, "no share script on the page"
    return match.group(1)


def page_data(html: str) -> dict:
    match = re.search(r"\n  const S = (\{.*?\});\n", html)
    assert match, "no share data on the page"
    return json.loads(match.group(1))


# A stubbed browser for one click. opts: share ("ok", "abort", "fail" or absent), canShare
# (false: refuses the data), clipboard ("ok", "fail" or absent), secure (isSecureContext),
# exec (execCommand's answer), twice (a second click while the first share is pending).
# Prints what happened: the share() and writeText() calls, the textarea fallback, the GA4
# events, the label after the click and after the confirmation's timer, the button's state.
HARNESS = r"""
const SCENARIOS = __SCENARIOS__;
function env(o) {
  const log = { share: [], clip: [], exec: [], events: [], timers: 0, focused: 0 };
  const classes = new Set();
  const label = { textContent: o.label };
  const btn = {
    hidden: true, _click: null, label,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), has: (c) => classes.has(c) },
    addEventListener: (type, fn) => { if (type === "click") btn._click = fn; },
    querySelector: (sel) => (sel === "span" ? label : null),
    focus: () => { log.focused++; },
  };
  let release = null;
  const navigator = {};
  if (o.share) navigator.share = (data) => {
    log.share.push(data);
    if (o.share === "ok") return o.twice ? new Promise((r) => { release = r; }) : Promise.resolve();
    const err = new Error("no"); err.name = o.share === "abort" ? "AbortError" : "NotAllowedError";
    return Promise.reject(err);
  };
  if (o.canShare === false) navigator.canShare = () => false;
  if (o.clipboard) navigator.clipboard = { writeText: (t) => { log.clip.push(t); return o.clipboard === "ok" ? Promise.resolve() : Promise.reject(new Error("denied")); } };
  const window = { isSecureContext: o.secure !== false, gtag: (kind, name, params) => log.events.push([kind, name, params]) };
  const textarea = () => ({ style: {}, setAttribute() {}, select() {}, remove() { log.removed = true; } });
  const document = {
    activeElement: btn,
    body: { append: (n) => { log.appended = n.value; } },
    createElement: () => textarea(),
    execCommand: (c) => { log.exec.push(c); return !!o.exec; },
    getElementById: (id) => (id === "share" ? btn : null),
  };
  const timers = [];
  const setTimeout = (fn) => { timers.push(fn); return timers.length; };
  const clearTimeout = () => {};
  const finish = () => {
    log.label = label.textContent;
    log.done = classes.has("is-done");
    log.timers = timers.length;
    timers.splice(0).forEach((fn) => fn());
    log.after = label.textContent;
    log.doneAfter = classes.has("is-done");
    log.hidden = btn.hidden;
    return log;
  };
  return { log, btn, label, navigator, window, document, setTimeout, clearTimeout, finish, release: () => release && release() };
}
async function run(click, e, o) {
  const first = click();
  if (o.twice) { await click(); e.release(); }
  await first;
  return e.finish();
}
"""

SITE_RUN = r"""
const SITE = __CODE__;
const T = __T__;
(async () => {
  const out = {};
  for (const [name, o] of Object.entries(SCENARIOS)) {
    const e = env({ ...o, label: T.share });
    const track = (n, p) => e.window.gtag("event", n, p);
    const epParams = (ep) => ({ episode_id: ep.id });
    const el = (tag, props) => Object.assign({ style: {}, setAttribute() {}, select() {}, remove() { e.log.removed = true; } }, props);
    const mod = new Function("navigator", "window", "document", "setTimeout", "clearTimeout", "T", "track", "epParams", "el",
      SITE + "\nreturn { shareEpisode, shareUrl };")(e.navigator, e.window, e.document, e.setTimeout, e.clearTimeout, T, track, epParams, el);
    const ep = { id: "2026-11-10_three-little-pigs-fr", title: "Les trois petits cochons" };
    out[name] = await run(() => mod.shareEpisode(ep, e.btn, e.label), e, o);
  }
  console.log(JSON.stringify(out));
})();
"""

PAGE_RUN = r"""
const PAGE = __CODE__;
(async () => {
  const out = {};
  for (const [name, o] of Object.entries(SCENARIOS)) {
    const e = env({ ...o, label: __LABEL__ });
    new Function("navigator", "window", "document", "setTimeout", "clearTimeout", PAGE)(e.navigator, e.window, e.document, e.setTimeout, e.clearTimeout);
    out[name] = await run(() => e.btn._click(), e, o);
  }
  console.log(JSON.stringify(out));
})();
"""

SCENARIOS = {
    "sheet": {"share": "ok", "clipboard": "ok"},
    "cancelled": {"share": "abort", "clipboard": "ok"},
    "sheet_fails": {"share": "fail", "clipboard": "ok"},
    "refused_data": {"share": "ok", "canShare": False, "clipboard": "ok"},
    "copy": {"clipboard": "ok"},
    "copy_fallback": {"clipboard": "fail", "exec": True},
    "insecure_fallback": {"clipboard": "ok", "secure": False, "exec": True},
    "copy_fails": {"clipboard": "fail", "exec": False},
    "double_click": {"share": "ok", "twice": True},
}


def node(script: str) -> dict:
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def harness(run: str, **subs: str) -> str:
    script = HARNESS.replace("__SCENARIOS__", json.dumps(SCENARIOS)) + run
    for key, value in subs.items():
        script = script.replace(f"__{key}__", value)
    return script


class WordsTest(unittest.TestCase):
    def test_site_js_words_per_language(self) -> None:
        for lang, (share, copied) in WORDS.items():
            with self.subTest(lang=lang):
                block = text_block(lang)
                self.assertIn(f'share: "{share}",', block)
                self.assertIn(f'linkCopied: "{copied}"', block)

    def test_episode_page_words_per_language(self) -> None:
        for lang, (share, copied) in WORDS.items():
            with self.subTest(lang=lang):
                self.assertEqual((pages.UI[lang]["share"], pages.UI[lang]["link_copied"]), (share, copied))


class CardTest(unittest.TestCase):
    """The list pages' cards: a real button in each episode's actions."""

    def test_card_has_a_share_button(self) -> None:
        js = site_js()
        self.assertIn('const shareBtn = el("button", { class: "btn", type: "button", "data-share": "episode", "aria-expanded": "false" }, [svg([', js)
        self.assertIn('const shareLabel = el("span", { text: T.share, "aria-live": "polite" });', js)
        # Since #45 it opens the drafts panel (share.js); shareEpisode() is the panel's "More…"
        # and the fallback without share.js.
        self.assertIn("shareBtn.addEventListener(\"click\", () => openShare(ep, shareBtn, shareLabel, actions));", js)
        self.assertIn("if (!P || typeof P.toggle !== \"function\") { shareEpisode(ep, btn, label); return; }", js)
        self.assertIn("more: (b, l, rest) => shareEpisode(ep, b, l, rest),", js)
        self.assertIn("actions.append(shareBtn);", js)

    def test_copy_link_button_is_gone(self) -> None:
        # Luong's answer on PR #44: Share replaces the cards' old Copy link button.
        js = site_js()
        for gone in ("copyLink", "linkInBar", "linkBtn", "linkLabel", "Copy link", "Copier le lien",
                     "Link in address bar", "barre d’adresse", "thanh địa chỉ"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, js)
        # linkCopied stays: it is Share's confirmation (WordsTest).

    def test_card_actions_keep_copy_description_after_share(self) -> None:
        js = site_js()
        actions = between(js, '    const actions = el("div", { class: "actions" });', "    const detail = el(")
        self.assertEqual(actions.count('el("button", { class: "btn", type: "button"'), 3)   # transcript, share, description
        self.assertIn('"data-copy": "description"', actions)
        self.assertIn("copyDescription(ep, descBtn, descLabel)", actions)
        self.assertLess(actions.index("actions.append(shareBtn);"), actions.index("actions.append(descBtn);"))

    def test_every_list_page_loads_the_new_site_js(self) -> None:
        # The five pages share one version, bumped with each change (checked in test_story_pages):
        # 202611122200 added Share, 202611122300 dropped Copy link, 202611130100 added share.js
        # (the drafts panel, #45), loaded just before site.js with the same version, as on the
        # episode pages (pages.ASSET_VERSION); 202611130200: hashtags on their own line, clean
        # credits and openers in the drafts.
        self.assertEqual(pages.ASSET_VERSION, "202611130200")
        for name, path in LIST_PAGES.items():
            with self.subTest(page=name):
                html = path.read_text(encoding="utf-8")
                for old in ("202611112100", "202611122200", "202611122300", "202611130100"):
                    self.assertNotIn(f"site.js?v={old}", html)
                    self.assertNotIn(f"site.css?v={old}", html)
                self.assertIn("site.js?v=202611130200", html)
                self.assertIn("site.css?v=202611130200", html)
                prefix = "" if name == "build" else "../../"
                self.assertIn(f'<script src="{prefix}share.js?v=202611130200"></script>\n<script src="{prefix}site.js?v=202611130200"></script>', html)


class EpisodePageTest(unittest.TestCase):
    """Every live episode page has one Share button sharing its own URL, in its language."""

    def test_live_pages(self) -> None:
        eps = pages.site_episodes(DOCS)
        self.assertGreater(len(eps), 0)
        for ep in eps:
            with self.subTest(id=ep["id"]):
                html = (DOCS / "episodes" / ep["id"] / "index.html").read_text(encoding="utf-8")
                lang = pages.story_lang(ep) if pages.show_of(ep) == pages.STORY_SHOW else "en"
                share, copied = WORDS[lang]
                self.assertEqual(html.count('id="share"'), 1)
                self.assertIn(f'<button class="btn" type="button" id="share" hidden><span aria-live="polite">{share}</span></button>', html)
                data = page_data(html)
                self.assertEqual(data["url"], f"https://luongnv.com/podcast/episodes/{ep['id']}/")
                self.assertEqual(data["url"], pages.page_url(ep["id"]))
                self.assertEqual((data["label"], data["copied"]), (share, copied))
                self.assertEqual(data["title"], ep["title"])
                self.assertEqual(data["params"], pages.share_data(ep)["params"])
                self.assertEqual(data["params"]["episode_id"], ep["id"])
                self.assertEqual(data["params"]["show"], pages.show_of(ep))
                # The page is current: rebuilt from episodes.json with this renderer.
                self.assertEqual(html, pages.render_page(ep, eps, DOCS))

    def test_share_data_parameters(self) -> None:
        ep = {"id": "x", "title": "T" * 150, "show": pages.STORY_SHOW, "format": "bedtime-story", "language": "fr-FR",
              "story_group": " g ", "category": "bedtime"}
        self.assertEqual(pages.share_data(ep)["params"], {
            "episode_id": "x", "episode_title": "T" * 100, "show": pages.STORY_SHOW, "episode_language": "fr",
            "story_group": "g", "category": "bedtime"})
        plain = pages.share_data({"id": "y", "title": "Pod", "story_group": "  ", "category": ""})["params"]
        self.assertEqual(plain, {"episode_id": "y", "episode_title": "Pod", "show": pages.BUILD_SHOW, "episode_language": "en"})

    def test_title_cannot_close_the_script(self) -> None:
        ep = {"id": "z", "title": "</script><b>&", "description": "d"}
        html = pages.render_page(ep, [ep], DOCS)
        self.assertEqual(html.count("</script>"), 5)  # gtag loader, gtag, JSON-LD, share.js, share
        self.assertEqual(page_data(html)["title"], "</script><b>&")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BehaviourTest(unittest.TestCase):
    """Both copies of the share logic, run in node with a stubbed browser."""

    url = "https://luongnv.com/podcast/episodes/2026-11-10_three-little-pigs-fr/"

    def check(self, got: dict, copied: str, failed: str, label: str, title: str) -> None:
        url = self.url
        sheet = got["sheet"]
        self.assertEqual(sheet["share"], [{"title": title, "url": url}])  # once, title and url only
        self.assertEqual(sheet["clip"], [])
        self.assertEqual([(n, p["method"]) for _, n, p in sheet["events"]], [("episode_share", "share_sheet")])
        self.assertEqual(sheet["events"][0][2]["episode_id"], "2026-11-10_three-little-pigs-fr")
        self.assertEqual((sheet["label"], sheet["timers"]), (label, 0))

        cancelled = got["cancelled"]  # AbortError: nothing at all
        self.assertEqual(len(cancelled["share"]), 1)
        self.assertEqual((cancelled["clip"], cancelled["exec"], cancelled["events"], cancelled["label"], cancelled["timers"]),
                         ([], [], [], label, 0))

        for name in ("sheet_fails", "refused_data", "copy"):  # the link copied with the Clipboard API
            with self.subTest(case=name):
                g = got[name]
                self.assertEqual(g["clip"], [url])
                self.assertEqual(g["exec"], [])
                self.assertEqual((g["label"], g["done"]), (copied, True))
                self.assertEqual([(n, p["method"]) for _, n, p in g["events"]], [("episode_share", "copy")])
                self.assertEqual((g["after"], g["doneAfter"]), (label, False))
        self.assertEqual(len(got["sheet_fails"]["share"]), 1)
        self.assertEqual(got["refused_data"]["share"], [])  # canShare() said no: no sheet

        for name in ("copy_fallback", "insecure_fallback"):  # the hidden textarea and execCommand
            with self.subTest(case=name):
                g = got[name]
                self.assertEqual((g["appended"], g["exec"], g["removed"]), (url, ["copy"], True))
                self.assertEqual(g["label"], copied)
                self.assertEqual([p["method"] for _, _, p in g["events"]], ["copy"])
        self.assertEqual(got["insecure_fallback"]["clip"], [])

        fails = got["copy_fails"]
        self.assertEqual((fails["label"], fails["done"], fails["events"], fails["after"]), (failed, False, [], label))

        twice = got["double_click"]  # a second click while the sheet is open does nothing
        self.assertEqual(len(twice["share"]), 1)
        self.assertEqual(len(twice["events"]), 1)

    def test_site_js(self) -> None:
        js = site_js()
        code = between(js, "  // Clipboard API, else a hidden textarea", "  async function copyDescription") + between(
            js, "  // ---------- Share (podcast #43)", "  // ---------- end of share ----------")
        for lang in WORDS:
            with self.subTest(lang=lang):
                words = {k: v for k, v in pages.UI[lang].items() if k in ("share", "link_copied", "copy_failed")}
                t = json.dumps({"share": words["share"], "linkCopied": words["link_copied"], "copyFailed": words["copy_failed"]})
                got = node(harness(SITE_RUN, CODE=json.dumps(code), T=t))
                self.check(got, words["link_copied"], words["copy_failed"], words["share"], "Les trois petits cochons")

    def test_site_js_share_url_is_the_episode_page_for_every_episode(self) -> None:
        code = between(site_js(), "  const SITE_URL", "  // Where navigator.share exists")
        ids = [ep["id"] for ep in pages.site_episodes(DOCS)] + ["a b/c"]
        got = node(code + f"\nconsole.log(JSON.stringify({json.dumps(ids)}.map((id) => shareUrl({{ id }}))));")
        self.assertEqual(got[:-1], [pages.page_url(i) for i in ids[:-1]])
        self.assertEqual(got[-1], "https://luongnv.com/podcast/episodes/a%20b%2Fc/")

    def test_episode_pages(self) -> None:
        eps = {ep["id"]: ep for ep in pages.site_episodes(DOCS)}
        for ep_id, lang in (("2026-11-10_three-little-pigs-fr", "fr"), ("2026-11-10_three-little-pigs-vi", "vi"),
                            ("2026-11-12_welcome-to-the-b2a-economy", "en")):
            with self.subTest(id=ep_id):
                ep = dict(eps[ep_id], id="2026-11-10_three-little-pigs-fr", title="Les trois petits cochons")
                html = pages.render_page(ep, [ep], DOCS)
                ui = pages.UI[lang]
                got = node(harness(PAGE_RUN, CODE=json.dumps(page_script(html)), LABEL=json.dumps(ui["share"])))
                self.check(got, ui["link_copied"], ui["copy_failed"], ui["share"], "Les trois petits cochons")
                self.assertFalse(got["sheet"]["hidden"])  # shown once the script runs
                params = got["copy"]["events"][0][2]
                self.assertEqual(params, {**pages.share_data(ep)["params"], "method": "copy"})


if __name__ == "__main__":
    unittest.main()
