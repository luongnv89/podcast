<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/logo-full.svg">
    <img src="assets/logo/logo-black.svg" alt="Build Wiz AI Show" width="320">
  </picture>
</p>

# Build Wiz AI Show and Once Upon a Time Show — podcast

Episodes generated with [DropCast](https://github.com/luongnv89/dropcast). The site has
two shows, each on its own page:

- **Build Wiz AI Show**: a two-host conversation (Bob and Alice) about one public
  article, thread or paper, fact-checked against the source and credited in every
  episode. Listen: **https://luongnv.com/podcast/**
- **Once Upon a Time Show**: gentle stories for bedtime and story time, told slowly by a
  warm narrator (the `bedtime-story` and `storytelling` formats), one page per language:
  **https://luongnv.com/podcast/stories/en/**, **/fr/** and **/vi/**
  (https://luongnv.com/podcast/stories/ lets the visitor choose).

## How it updates

The site is static (`docs/`), deployed by GitHub Pages from `main`
(`.github/workflows/pages.yml`).

- `docs/index.html` — Build Wiz AI Show's page (tabs, search, player).
- `docs/stories/en/index.html`, `docs/stories/fr/index.html`, `docs/stories/vi/index.html` —
  Once Upon a Time Show's pages, one per language (one list, search, player), each written
  entirely in its language (see "Story language pages and the podcast switcher").
- `docs/stories/index.html` — the stories' chooser: the three languages and the listening
  links. It lists no stories; it forwards old links to the right language page.
- `docs/site.js`, `docs/site.css` — the list and player every page shares. Each page sets
  `window.SHOW_PAGE` (its show, its language for a story page, tabs, the path to
  `episodes.json` and the other pages) before loading `site.js`; they all read the same
  `docs/episodes.json` and list only their own episodes. All five pages load them as
  `site.js?v=<version>` / `site.css?v=<version>`: bump the version on all five whenever
  either file changes (GitHub Pages caches them for 10 min).
- `docs/episodes/<job id>/` — each episode's `transcript.vtt` and its own page
  `index.html` (see "Descriptions, download names and episode pages"). The MP3s are not in
  `docs/`: they are served by the media repos' own GitHub Pages sites (see "Where the audio
  lives").
- `docs/art/<story group>/` — each story's illustration (`wide.jpg`, `square.jpg`,
  `thumb.jpg`), copied by the publisher (see "Story illustrations").
- `docs/sitemap.xml`, `docs/robots.txt`, `docs/cover.jpg` — the sitemap of the show pages
  (Build Wiz AI Show, the stories' chooser and its three language pages) and every episode page, and Build Wiz AI Show's cover for share previews (rendered from
  `assets/cover/build-wiz-cover.html`, 1400 x 1400).
- `scripts/publish.py` — pushes each delivered DropCast job's MP3 to its media repo's
  GitHub Pages site and waits until it is served, copies its transcript and art into `docs/`, updates
  `episodes.json`, rebuilds the RSS feeds (stories and Build Wiz AI Show), the episode pages and the sitemap, and (with
  `--push`) commits and pushes. Standard library only.
- `scripts/pages.py` — writes the episode pages and the sitemap from `episodes.json`
  (`python3 scripts/pages.py build`; `publish.py` runs it on every publish).

DropCast calls the publisher after every delivered episode when this is set in its
`.env` (publishing is on by default; `--no-publish`, "don't publish" in the request, or
`DROPCAST_PUBLISH=0` turn it off):

```bash
DROPCAST_PUBLISH_CMD=python3 /path/to/podcast/scripts/publish.py --push
```

By hand:

```bash
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --push
python3 scripts/publish.py --all            # every delivered job, no git
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --category marketing
python3 scripts/publish.py --backfill [--push]   # descriptions, names, story art, feeds, pages
python3 scripts/publish.py --repoint-audio --dry-run   # list entries still on release URLs, check their Pages URLs
python3 scripts/publish.py --repoint-audio [--push]    # point them at the media sites
python3 scripts/publish.py --migrate-audio --dry-run   # list the MP3s still in docs/
python3 scripts/publish.py --migrate-audio [--push]    # move them to the media repos
```

## Where the audio lives

GitHub Pages deploys of the whole site (about 243 MB, 232 MB of it MP3s) ran into the
deploy's fixed 10-minute cap, so the episode audio lives in one public media repo per show
and language (`MEDIA_REPOS` in `scripts/publish.py`):

| Show | Language | Media repo | Audio URL |
|---|---|---|---|
| Build Wiz AI Show | any | [`luongnv89/buildwiz-ai-show-media`](https://github.com/luongnv89/buildwiz-ai-show-media) | `https://luongnv.com/buildwiz-ai-show-media/<id>.mp3` |
| Once Upon a Time Show | en | [`luongnv89/once-upon-a-time-en-media`](https://github.com/luongnv89/once-upon-a-time-en-media) | `https://luongnv.com/once-upon-a-time-en-media/<id>.mp3` |
| Once Upon a Time Show | fr | [`luongnv89/once-upon-a-time-fr-media`](https://github.com/luongnv89/once-upon-a-time-fr-media) | `https://luongnv.com/once-upon-a-time-fr-media/<id>.mp3` |
| Once Upon a Time Show | vi | [`luongnv89/once-upon-a-time-vi-media`](https://github.com/luongnv89/once-upon-a-time-vi-media) | `https://luongnv.com/once-upon-a-time-vi-media/<id>.mp3` |

A story in any other language goes to the English stories repo (the publish report says
so in `notes`). The show is picked as everywhere else (`episode_show()`: a story format is
always Once Upon a Time Show), plus the episode's `language`.

**GitHub Pages, not Releases (#33).** Each media repo is its own GitHub Pages site (branch
`main`, folder `/`, with a `.nojekyll`) holding every episode as `<episode id>.mp3` at its
root. luongnv.com is the custom domain of luongnv89's user site, so the project sites are
served under it (`pages_url()`, `scripts/publish.py:604,615`). GitHub Pages serves `.mp3`
as `audio/mp3` with `Access-Control-Allow-Origin: *`, so every browser plays it. From #30
to #33 the audio was served as GitHub Release assets
(`https://github.com/<repo>/releases/download/<id>/<id>.mp3`). GitHub serves those as an
`application/octet-stream` attachment with `nosniff` and no CORS, which Safari on iPhone
does not play ("Could not load audio"). Those releases are kept as they are. `GhMedia` (the
`gh` uploader) is still in `publish.py`, but it is no longer the default
(`MEDIA_BACKEND = PagesMedia`, `scripts/publish.py:851`).

- **Checkouts.** `publish.py` keeps one git checkout per media repo in
  `$PODCAST_MEDIA_CHECKOUTS/<repo name>`, default `~/workspace/media/<repo name>`
  (`media_checkouts()`, `scripts/publish.py:606,623`); on the bot's machine that is
  `/home/adminuser/workspace/media/`. A missing checkout is cloned over SSH from
  `git@github.com:<repo>.git` (`ssh_remote()`, `scripts/publish.py:629`). An existing one must
  be a checkout of its own, on `main`, with that `origin`, or the run stops
  (`PagesMedia.checkout()`, `scripts/publish.py:748`). Each run starts with
  `git pull --ff-only origin main`. If that fails because of the publisher's own earlier
  unpushed `feat: add|update <id>` commits, they are rebased onto origin once.
- **Publishing an episode** (`PagesMedia.publish()`, `scripts/publish.py:808`): copy
  `episode.mp3` to `<id>.mp3` in the checkout, unless the file there already has the same
  SHA-256. Then commit only that file (`feat: add <id>`, or `feat: update <id>` when it was
  already there) and push it to `main`, with the same care as the podcast's own push
  (`_push()`, `scripts/publish.py:789`): a rejected push is rebased onto origin once and
  pushed again, a failed rebase is aborted (the commit stays in the checkout), and the push
  counts only once a fetch of origin/main holds the commit. Any earlier unpushed commit is
  pushed too. The entry gets `audio` (its Pages URL), `size_bytes` and `audio_sha256`, and
  `episodes.json` is written atomically (temp file, then rename). The MP3 is never copied
  into `docs/`.
- **The verify rule** (`_verified()`, `scripts/publish.py:644`). An audio URL counts as
  live only when a HEAD (redirects followed) answers status 200, `Content-Length` =
  `size_bytes`, and `Content-Type` `audio/mpeg` or `audio/mp3` (parameters ignored,
  `AUDIO_TYPES`, `scripts/publish.py:610`). Anything else fails, including a release
  asset's `application/octet-stream`. A Pages deploy takes a minute or two, so after a push
  the publisher checks every 15 s, for at most `$PODCAST_MEDIA_WAIT` seconds (default 600,
  `wait_until_live()`, `scripts/publish.py:608-609,661`). Nothing in `docs/` or
  `episodes.json` changes before the check passes. When the wait runs out, that job fails
  with the last answer, and the podcast repo is left as it was.
- **Re-running.** Run the same command again: the file is already in the media repo with
  the same SHA-256, so nothing is committed twice. An unpushed commit is pushed, and the run
  only checks the URL again. A re-render (new bytes) is a new commit of the same
  `<id>.mp3`: the URL stays, and the feeds' `?v=` changes with `audio_sha256`.
- A leftover `docs/episodes/<id>/episode.mp3` from before #30 is removed only after the
  index update and a successful rebuild of the feeds and pages, and only once the new URL
  passes the verify rule. Otherwise it is kept, and the report's `notes` say so. A failed
  feed or page rebuild fails the run (`rebuild` in `failed`): nothing is removed or pushed,
  and publishing again rebuilds and pushes what that run left uncommitted.
- `--push` (publish, `--backfill`, `--migrate-audio` and `--repoint-audio` alike) starts
  with `git pull --rebase --autostash origin main`, so a re-run from a dirty tree builds on
  origin's latest commit. If that pull fails, or leaves conflicts, the run stops before any
  upload or write (a stopped rebase is aborted). `git.pushed` is `true` only once a fetch of
  origin/main shows it holds the run's commit. When the push is rejected and the rebase onto
  origin conflicts, the rebase is aborted, the commit stays on the local branch, and the run
  fails (`pushed: false`, exit 1). Resolve the conflict by hand
  (`git pull --rebase origin main`, then `git rebase --continue`) and run the same command
  again: it pushes that commit, even when nothing new changed.
- The push sends `HEAD:main`, so it carries every local commit ahead of origin/main. Before
  it commits and before every push (the retry after a rebase too), each of those commits must
  be the script's own: its commit subject, on `main`, files under `docs/` only
  (`_unpushed_commits(strict=True)` in `scripts/publish.py`). Any other commit (another
  branch, a hand-made commit, a change outside `docs/`), or a checkout not on `main`, fails
  the run (`pushed: false`, exit 1): nothing is pushed, and the run's own change is left
  uncommitted (staged). Push, move or drop that commit by hand, then run the same command
  again. With nothing new to commit, a hand-made commit is left alone and nothing is pushed.
  A checkout without an `origin/main` tracking ref cannot be checked, so it fails the same
  way (`git fetch origin` makes one).
- An `episodes.json` that is there but cannot be parsed (git conflict markers, say) stops
  every `publish.py` command before any upload or write, so it is never replaced by a new
  index; only a missing file starts a new one.
- Nothing private is uploaded: DropCast never hands a photo job (or a deck) to the
  publisher, and the publisher's own checks (not rendered yet, edge-tts voices for private
  use, `"publish": false`) run before any upload, so those jobs are still never published. A
  failed push or check fails that job with the error and leaves `episodes.json` and
  `docs/` unchanged.
- `PODCAST_MEDIA_REPO_OVERRIDE=owner/name` sends every upload to that one repo (tests,
  emergencies). Its checkout is `$PODCAST_MEDIA_CHECKOUTS/<name>`, with origin
  `git@github.com:owner/name.git`, and its URL is `https://<owner>.github.io/<name>/<id>.mp3`
  (or the owner's custom domain). The site's player only accepts the four repos above
  (`mediaUrl()`, `docs/site.js:1067`). After parsing, it accepts no credentials and only
  origin `https://luongnv.com` with a path that `PAGES_PATH` (`docs/site.js:1065`) matches
  exactly, `/<media repo>/<id>.mp3`. Until every entry is re-pointed, it also accepts the
  release URL (origin `https://github.com`, `MEDIA_PATH`,
  `/luongnv89/<repo>/releases/download/<id>/<id>.mp3`, with the same `<id>` twice). The URL
  is rebuilt from that origin and path, and `..`, backslashes and percent-encoded dots,
  slashes and backslashes are refused. So a change of repos needs a `site.js` change too.
  An episode whose audio is refused shows no Play or Download button.
- A cross-origin `download` attribute is ignored, so **Download MP3** saves the file under
  its URL name, `<id>.mp3`, not `file_name`. The feeds' enclosure keeps
  `type="audio/mpeg"`, its `length` and the episode's guid (see "Spotify and podcast apps").

**Re-pointing the release URLs (#33).** `python3 scripts/publish.py --repoint-audio`
(`repoint_audio()`, `scripts/publish.py:2237`) moves every entry whose `audio` is still a
release asset URL to the same file on that repo's Pages site. It runs in this order:

1. Check each Pages URL with the verify rule.
2. Put a missing file there and wait for it, as when publishing. The file comes from the
   media checkout, else the DropCast job's `episode.mp3`, else the release asset downloaded
   (`_repoint_source()`, `scripts/publish.py:2215`); its SHA-256 must equal `audio_sha256`.
3. Only when every URL passed: rewrite `audio` in `episodes.json` (`size_bytes`,
   `audio_sha256` and everything else unchanged).
4. Rebuild the feeds and pages, and check that every enclosure is on the Pages URL and that
   no feed or page still links a release URL (`link_problems()`,
   `scripts/publish.py:1996`).

A failed check leaves `episodes.json` untouched. A failed rebuild or feed check stops it
before the push. **Run the same command again to finish**: it finds nothing to move, sees
the wrong feeds or pages, and rebuilds them. With `--push` it commits all of it as one
commit (`fix(site): play episode audio from the media sites (#33)`, `REPOINT_SUBJECT`,
`scripts/publish.py:1660`) after the same start-of-run pull as above. A second run calls
nothing and changes nothing. `--dry-run` lists every entry (`from`, `to`, repo, size) and
HEAD-checks each Pages URL once (`live`, and `check` for a failing one): nothing is
uploaded, waited for or written.

**Migration.** `python3 scripts/publish.py --migrate-audio` moves the MP3s still in
`docs/` (entries whose `audio` is `episodes/<id>/episode.mp3`), each to its show/language
repo (its Pages site since #33), in this order: upload all of them; check every URL with
the verify rule above; update `episodes.json`; rebuild the feeds and pages
and check that every feed listing a moved episode has its enclosure on the new URL
(and no feed or page still links the `docs/` copy); only then `git rm` the local MP3s. A
failed upload or check stops it before anything changes; a failed rebuild, feed check or
removal stops it before the push, with every file still in place. **Run the same command
again to finish**: it also picks up leftovers, i.e. `docs/episodes/<id>/episode.mp3` files
whose entry already has its media URL and an `audio_sha256`/`size_bytes` matching the
file (other copies are kept and listed under `kept`), checks them with HEAD, rebuilds,
removes them and commits everything the earlier run left uncommitted. `--push` first runs
`git pull --rebase --autostash` (a failed pull stops it before any upload, and so does a
pull that exits 0 but leaves conflicts: unmerged paths, conflict markers in
`episodes.json` or the autostash left in `git stash list`; the error names the stash to
resolve by hand before running again; see `--push` above) and commits and
pushes all of it as one commit (`feat(site): move episode audio to GitHub Releases (#30)`),
only when nothing failed; without it the files change locally only (the uploads still
happen). `--dry-run` lists the episodes, leftovers, repos and bytes it would move and
uploads nothing. A run with nothing left to do calls nothing and changes nothing.
Old `docs/episodes/<id>/episode.mp3` links stop working once the files are removed; the
feeds, pages and player already point to the new URLs.

## Story illustrations

Each story has one hand-drawn illustration, shared by its EN/FR/VI versions. A DropCast job
may hold an `illustration/` folder:

| File | Size | Used for |
|---|---|---|
| `wide.jpg` | 1920 x 1080 | the episode page's hero, `og:image`/`twitter:image` (share cards), the expanded card on the site |
| `square.jpg` | 3000 x 3000 | the episode artwork in podcast apps (`<itunes:image>` per feed item), JSON-LD `image`, the player's lock-screen artwork |
| `thumb.jpg` | 640 x 640 | the thumbnail in the site's list (64 px, 52 px on phones) |
| `alt.txt` | one line | English alt text (optional; else `Illustration: <title>`) |

Only one job of a story group has it (the English one). The publisher takes the job's own
`illustration/` when all three jpgs are there, else the first job folder next to it
(sorted by name) whose `script.json` has the same `story_group` and a complete
`illustration/`. It copies the jpgs to `docs/art/<story group>/` (an episode without a
group uses its id; anything that is not a plain file name is refused and reported in
`notes`), rewriting a file only when its bytes change, and adds to the entry:

```json
"image": {"square": "art/<key>/square.jpg", "wide": "art/<key>/wide.jpg",
          "thumb": "art/<key>/thumb.jpg", "alt": "<alt.txt or null>"}
```

An entry gets `image` only when an illustration is found; when none is found, an `image`
already in `episodes.json` is kept, so a re-publish from a machine without the art does
not drop it. Podcasts and stories without art have no `image` and look exactly as before
(cards, pages and feeds).

## Descriptions, download names and episode pages

Every entry in `episodes.json` has a `description` (DropCast #161/#163): a copy-paste
podcast description, plain text, at most 600 characters (Spotify's limit, counted as
Python `len`), laid out as

```
<hook: 2-3 sentences>

In this episode:
- <2 to 4 points>

Sources: <each source's title by author, or author or title>
Music: Kevin MacLeod (incompetech.com), CC BY 4.0      (stories with credited music)
<tagline> luongnv.com/podcast                          (stories: luongnv.com/podcast/stories)
```

The labels and the last line are DropCast's, in the episode's language: French uses
`Dans cet épisode :`, `Sources :`, `Musique :` and Vietnamese `Trong tập này:`, `Nguồn:`,
`Nhạc:`; the last line is the show's `last_lines[<lang>]` (its tagline and link, no show
name). They live in `scripts/description_labels.json`, a copy of DropCast's
`python -m dropcast.description labels --json` (one source of truth, DropCast #164), which
`publish.py` loads at start. To refresh it after DropCast changes a label or tagline, run
from the DropCast checkout `uv run python -m dropcast.description labels --json >
<podcast>/scripts/description_labels.json`, run the tests, and regenerate the generated
descriptions (below).

The publisher takes it from, in this order: the job's `description.txt` (written by Echo,
checked by DropCast; the publisher only refuses one that is empty, over 600 characters or
has Markdown/HTML, and then says so in its `notes`), a hand-edited description already in
`episodes.json` (it survives a re-publish), else one generated from the entry. Each entry
records where its text came from in `description_source` (`description.txt` or
`generated`); a `generated` one is rebuilt on every publish, so it follows a changed
summary. To keep a hand edit, edit the text and delete its `description_source`. A
generated description (`fallback_description()`: the first summary line plus one sentence on the hosts or the
length as the hook, the other summary lines as the points, the sources, the music credit,
then the show's last line in the episode's language). A generated one is shortened until
it fits: authors only in `Sources`, then (when the first summary line is one sentence, so
the hook keeps two) three then two points, without the added sentence, two points, fewer
sources named (`and N more`), and last the longest lines cut at a word boundary.

Every entry also has a `file_name`, the download name `<Show> - <Title> (<YYYY-MM-DD>).mp3`:
`run.json` `delivery.file_name` when DropCast wrote a clean one, else rebuilt with the same
rule (`episode_file_name()`, a copy of DropCast's `delivery.episode_file_name`: `\ / : * ? " < > |` and format characters dropped, control characters as spaces, at most 250 UTF-8 bytes, spaces
collapsed, at most 150 characters before `.mp3`, the title cut at a word boundary; the
date is the published day in Europe/Paris). The MP3 keeps its URL; only the saved name
changes.

On the site, **Download MP3** saves the file under `file_name` (else `<id>.mp3`) while the
MP3 is on the site; for audio on a media repo's site (another origin) the browser uses the
file's own name, `<id>.mp3` (see "Where the audio lives"). Each
episode's details have a **Copy description** button: one click copies the description
exactly as in `episodes.json` (Clipboard API, else a hidden text area and
`execCommand("copy")`), shows "Copied" for a moment and sends `description_copy`. A story
in several languages copies the language on show. While a deep link (`#<id>`) is open,
the page's `<meta name="description">` is that episode's hook.

**Episode pages.** The show pages are single pages, so each episode also gets a small
static page, `docs/episodes/<id>/index.html` (`https://luongnv.com/podcast/episodes/<id>/`),
written by `scripts/pages.py`: title `<Title> | <Show>`, `<meta name="description">` = the
description's hook (its first paragraph), canonical URL, Open Graph and Twitter tags with
the show's cover (`docs/cover.jpg`, or the story cover of the episode's language),
`PodcastEpisode` JSON-LD, the audio player, the full description, Download MP3 (same
name), the transcript and a link back to `#<id>` on the page that lists it (a story's
language page, `stories/<lang>/`: `show_page()`, `scripts/pages.py:132`); a story's versions
link each other (`hreflang`). The list pages link each title to its page (a plain click still
opens the details; a middle or Ctrl/Cmd click opens the page). `docs/sitemap.xml` lists
Build Wiz AI Show's page, the stories' chooser, the three story language pages (each with
its newest story's day as `lastmod`) and every episode page (`render_sitemap()`,
`scripts/pages.py:406`). Pages and sitemap are rebuilt from
`episodes.json` on every publish and change only when an episode does. Crawlers read
`robots.txt` only at the domain root, which lives in the luongnv.com repository: add
`Sitemap: https://luongnv.com/podcast/sitemap.xml` there (or submit the sitemap in Search
Console); `docs/robots.txt` names it too.

**The page's language (#38).** A story's episode page is in the story's language: the
language of the page that lists it (`story_lang()`), so French and Vietnamese stories get
French and Vietnamese pages and a story in another language an English one. That covers
every word of the page around the episode's own text: the
duration ("7 min", "8 phút"), **Listen on Once Upon a Time Show** ("Écouter sur…", "Nghe
trên…"), **Download MP3**, **Transcript**, **Also in:**, **Based on … by …**, the picture's
fallback alt text and the footer. The words are `UI` (`scripts/pages.py:74`), picked by
`ui_of()` (`scripts/pages.py:138`); the ones the story pages also use (download,
transcript, based on, by, minutes, illustration) are site.js's `TEXT` word for word, and a
test keeps them in step. The show's name stays as it is, as on the story pages. The
episode's own text (title, description, source title and author, the picture's `alt` from
`image.alt`) is shown as `episodes.json` has it. Every Build Wiz AI Show page stays in
English, whatever the episode's language, and English story pages are byte for byte what
they were (`tests/fixtures/episode_pages_38/expected/`). `<html lang>` and `og:locale` are
the episode's own language, as before, so they match the words on every EN, FR and VI story
page.

**Backfill.** `python3 scripts/publish.py --backfill` gives every entry without one a
`description` and a `file_name` (a job folder still in `$DROPCAST_HOME/jobs` gives its
`description.txt` and `delivery.file_name`; otherwise they are generated from the entry)
and, for a story whose illustration is in `$DROPCAST_HOME/jobs` (its own job or one of the
same `story_group`, see "Story illustrations"), an `image` with the art copied to
`docs/art/`; then it rebuilds the story feeds, the episode pages and the sitemap. Its
report lists the filled entries (`filled`) and the ids that got art (`art`); with `--push`
the commit is `feat(site): backfill episode descriptions, pages and story art`. Entries that have both are left alone,
so it is safe to run again; `--push` commits and pushes the result. It does not rewrite a
description an entry already has: after the labels file changes, regenerate the generated
ones (every entry whose job has no usable `description.txt`) with `fallback_description()`
and rebuild the pages, as done for #163 when the labels moved to DropCast.
Backfill skips entries that already have an `image`: after a story is redrawn, re-publish its jobs
(`publish.py JOB --push`, which re-copies changed art), and note that podcast apps may keep the old
picture for a while because the art URLs do not change.

## Shows (publish routing)

Every episode in `episodes.json` has a `show`, which picks its page. The publisher sets
it, in this order:

1. a story format (`bedtime-story`, `storytelling`) → **Once Upon a Time Show**, whatever
   the script says (stories briefed before the stories got their own show still name
   Build Wiz AI Show in their `script.json`);
2. the job's `script.json` `show.name` or `brief.json` `show.name` naming Once Upon a
   Time Show, or a `brief.json` `show.register` of `story` or `bedtime` → Once Upon a
   Time Show;
3. otherwise **Build Wiz AI Show** (an older or unknown show name is not copied).

`result.json` is not read for it: DropCast runs the publisher before that file is final.
The pages apply the same rule (a story format is always on a story page), so an entry
never shows up on both shows. The top-level `shows` lists both shows and their pages (the
stories' page is the chooser, `stories/`). Each page shows the counts and minutes of its
own episodes only. Old links follow the stories: `?tab=bedtime` and `#<story id>` on the
main page open the story's language page.

## Story language pages and the podcast switcher

Once Upon a Time Show has one page per language (#35): `/podcast/stories/en/`, `/fr/` and
`/vi/`, and `/podcast/stories/` is a small chooser of the three.

- **Each language page is entirely in its language**: title, tagline, buttons, labels,
  player, empty states, `<html lang>`, meta description, Open Graph and Twitter tags (with
  the language's cover, `docs/stories/cover-<lang>.jpg`), `PodcastSeries` JSON-LD, the
  listening links (Spotify, Apple Podcasts and YouTube of that language only) and the feed
  link (`feed-<lang>.xml`). The static text is in the page; the text `site.js` writes
  (counts, sort labels, status, buttons, player labels, dates) comes from `TEXT`
  (`docs/site.js:20`), picked by `SHOW_PAGE.lang`; a page without one (Build Wiz AI Show)
  is in English, word for word as before. The taglines are DropCast's
  (`scripts/description_labels.json`).
- **What a language page lists**: the story-format entries (`showOf()`) whose `language`
  is the page's (`onPage()`, `docs/site.js:153`). A story in a language without a page is
  listed on the English one (`storyLang()`, `docs/site.js:152`; `story_lang()`,
  `scripts/pages.py:126`), as its audio goes to the English stories repo.
- **The chooser** shows the show, three large choices (the story icon with its badge, the
  language's own name and the tagline in that language) and the listening links of all
  three languages.
- **Old links keep working.** `/podcast/stories/` stays valid (it is the chooser). With a
  `#<episode id>` it loads `episodes.json` and sends the visitor on to the page that lists
  that episode, hash kept (`chooserTarget()`, `docs/site.js:175`, run before anything
  else, `docs/site.js:188`); a Build Wiz AI Show id goes to `../#<id>`. Only the query
  keys the old stories page read go along: `q`, `sort`, `order` and `tab` (`OLD_QUERY`,
  `docs/site.js:162`). A query with one of them and no known episode (`?q=pigs`, from a
  shared search) goes to the visitor's language page: the language last picked on the
  site (saved by a language switch; the language pages have none since #40), else the browser's first of English, French and Vietnamese, else English. A plain
  `/podcast/stories/`, an unknown id without such a key, or a link with only tracking tags
  (`?fbclid=…`, `?utm_source=…`, `?gclid=…`) stays on the chooser, so a shared or
  advertised link shows the three languages. The story feeds still link `/podcast/stories/`
  and `/podcast/stories/#<id>`, so they did not change.
- **The podcast switcher** is a bar at the top of every page (all five), in the page's
  markup: Build Wiz AI Show, then Once Upon a Time Show in English, Français and Tiếng
  Việt, each with its show's icon, the current page marked (`aria-current="page"`; the
  chooser marks none). Build Wiz AI Show's icon is its W-equalizer mark (green spark);
  the story icon is the open book with the gold star from `assets/cover/stories-cover.html`,
  with an **EN / FR / VI** badge (no flags): black on the story gold, about 12:1
  (`.badge`, `docs/site.css:106`). On a phone it is four equal columns, the icon over a
  short name. The icons are not on episode cards, favicons or feed art.

## Sources and guests

Every episode credits its source (`source` in `episodes.json`). DropCast episodes can
also bring in extra external sources, each presented by a fictional recurring guest
(Maya, Sam, Lena or Theo). For those episodes the publisher adds:

- `sources`: every source used, main first, as `{title, author, url}` (from the job's
  `result.json` `delivery.sources` when it matches the script, else from `script.json`
  `sources`, the fetched `sources/<id>/source.json` and the fact-check report);
- `guests`: `{name, presents}`, `presents` being the titles of the sources each guest
  presents.

The episode's details then list the sources and the guests. Episodes without extra
sources get neither key, so their entries are unchanged.

## Music credits

When an episode uses licensed music that requires attribution (e.g. a CC-BY track),
DropCast writes the credit in the job's `run.json` as `music.credit`. The publisher copies
it, trimmed, into the episode's entry as `music_credit` (it reads `run.json`, since
`result.json` is not final yet when DropCast calls it), and the episode's details show it
as a small line: "Music: <credit>". Episodes without a credit (the CC0 theme, older jobs)
get no `music_credit` key, so their entries are unchanged.

## One story in several languages

A bedtime story can come in English, French and Vietnamese (DropCast #134). Every
version's `script.json` carries the same `story_group` (a string) and its own `language`;
the publisher copies both into the version's `episodes.json` entry (`story_group` only
when set, so older entries are unchanged; `result.json` is not read for it).

Each story language page (#35) lists that language's version only. Its cards carry no
links to the story's other languages (#40): the podcast switcher at the top moves between
the language pages. The page still knows each story's other versions (`_alts`,
`linkVersions()`, `docs/site.js:341`), only so a version without its own illustration shows
the story's (`artSource()`, `docs/site.js:253`). Each episode page keeps its "Also in:"
links to the other versions. Every version keeps its own id, so `#<episode id>` opens that
version; given another language's id, a page sends the visitor on to that language's page.
Languages compare by their primary subtag (`en-US` is `en`).

`site.js` can still show the versions of one `story_group` as **one story** with an
in-place switch (the title, player, transcript and the rest follow it, a playing story
keeps playing): that is what a page without `SHOW_PAGE.lang` listing stories does. No page
does that since #35; the main page has no groups.

Tests (standard library, no network): `python3 -m unittest discover -s tests`.

## Spotify and podcast apps (story feeds)

Once Upon a Time Show reaches Spotify through **its own RSS feeds**, one per language,
because a Spotify show has a single language. Spotify has no upload API: a show hosted
elsewhere is submitted once as a feed, and Spotify checks the feed on its own and adds
new episodes.

| Language | Feed | Cover |
|---|---|---|
| English | https://luongnv.com/podcast/stories/feed-en.xml | `docs/stories/cover-en.jpg` |
| French | https://luongnv.com/podcast/stories/feed-fr.xml | `docs/stories/cover-fr.jpg` |
| Vietnamese | https://luongnv.com/podcast/stories/feed-vi.xml | `docs/stories/cover-vi.jpg` |

- `scripts/feed.py` builds them from `episodes.json` (`build`, `list`). A feed holds
  every Once Upon a Time Show episode in its language, newest first. `"feed": false` on
  an entry leaves it out, and removing an episode from a feed unpublishes it on Spotify.
- **Fully automatic:** `publish.py` rebuilds the feeds after every publish and commits
  them with the episode. A new story reaches Spotify with no manual step.
- Each item: guid = the job id (never changes); show notes = the summary, the source
  credit, the music credit (CC BY) and the AI-voice note; enclosure with size and
  duration; transcript (`podcast:transcript`). The enclosure URL ends in
  `?v=<sha8>` of the MP3 (from `audio_sha256`, else the local file), so a re-voiced episode
  is downloaded again under the same guid. An absolute `audio` (the media site, or a release asset before #33)
  is the enclosure URL as is; `length` is `size_bytes`. Moving an episode between hosts
  changes only the URL before `?v=`: guid, `length`, `type="audio/mpeg"` and `?v=` stay
  (`scripts/feed.py` `enclosure_url()`).
- Channel: category Kids & Family › Stories for Kids, not explicit, owner email
  `buildwizai@gmail.com` (public in the feed: Spotify emails its 8-digit code there).
  Titles and descriptions (each under Spotify's 600-character limit) are in `FEEDS` in
  `scripts/feed.py`.
- Covers are 3000 x 3000 JPEGs rendered from `assets/cover/stories-cover.html?lang=<lang>`
  with headless Chromium.
- Build Wiz AI Show stays hosted on Spotify for Creators and is not in these feeds; it has
  its own feed for YouTube (below).

**Submitting a feed (once per language):** creators.spotify.com → avatar or menu →
**Add a new show** → **Find an existing show** → **Somewhere else** → paste the feed URL →
enter the code emailed to buildwizai@gmail.com → check the details and submit.

## Build Wiz AI Show feed (YouTube)

https://luongnv.com/podcast/feed.xml holds every **English Build Wiz AI Show** episode on the
site, newest first (key `buildwiz` in `FEEDS`; Vietnamese episodes and stories are left
out). It is rebuilt with the story feeds on every publish, so a new episode reaches the
platforms that read it by itself.

- Channel: title Build Wiz AI Show, category Technology, not explicit, cover `docs/cover-3000.jpg`
  (3000 x 3000, the share cover rendered at 2.14x: `--force-device-scale-factor=2.142857`),
  owner email `buildwizai@gmail.com` (YouTube and Apple send verification codes there).
- Item notes: the three summary lines, every source (title, author, link) and the AI-voice note.
  Same guid and `?v=<sha8>` enclosure rules as the story feeds.
- **For YouTube only** (YouTube Studio → Create → New podcast → Submit RSS feed). Never submit
  it to Spotify: the show is hosted on Spotify for Creators (its own feed is
  `https://anchor.fm/s/101f7db20/podcast/rss`), and a second submission would make a
  duplicate show.
- YouTube does not update an episode whose audio is re-voiced later; use "Re-upload from RSS
  feed" on that video.

## Analytics (GA4 events)

Every page (Build Wiz AI Show, the stories' chooser and the three story language pages)
loads Google Analytics 4 (`G-FZV5YX8YPT`, the luongnv.com property) for page views. The shared `docs/site.js` also sends these events through the page's own `gtag`
(DropCast #138). There is no other tracker and no new cookie, and no personal data is
sent. Every call is guarded (`typeof gtag === "function"`, inside `try`), so a blocked,
missing or throwing `gtag` changes nothing on the page. "Once" means once per page view:
a reload counts again.

| Event | When | Extra parameters |
|---|---|---|
| `episode_play` | an episode starts playing for the first time in the page view (a resume after a pause is not counted) | |
| `episode_progress` | the player reaches 25, 50, 75 and 100 % of the episode (100: it played to the end), each once per episode, only after its `episode_play` (so loading a resume point sends nothing; seeking ahead does reach a milestone, and playing from a saved resume point counts the milestones already passed, so `percent` is the position reached, not proof it was all heard) | `percent` (25, 50, 75, 100) |
| `language_switch` | the visitor uses the in-place language switch (EN / FR / VI) of a story shown as one row in several languages; a deep link does not count. No page shows such a row since #35, and the language pages' cards have no language links since #40, so no current page sends it | `from_language`, `to_language` |
| `episode_download` | the "Download MP3" link (click or middle click) | |
| `source_click` | an outbound source link: "Based on …", "Read the source" and the Sources list | |
| `description_copy` | the "Copy description" button copied the description (not sent when copying failed) | |

Every event carries the episode it is about: `episode_id` (the job id), `episode_title`
(at most 100 characters, GA4's limit), `show` (Build Wiz AI Show or Once Upon a Time
Show), `episode_language` (the version's primary language, e.g. `fr`; not `language`, which GA4 reserves for the visitor's browser language), `category` (when set) and
`story_group` (only for a story in several languages). A language switch carries the new
version's parameters. Each language version has its own id, so switching languages while
a story plays counts as a new episode: `language_switch`, then `episode_play` (and later
its own progress) for the new version.

To see them in GA4: **Reports → Engagement → Events** lists each event and its count
(new events can take up to a day to appear there; **Reports → Realtime** shows them
within seconds). To break them down by episode, show or language, register
the parameters once as event-scoped custom dimensions in **Admin → Data display →
Custom definitions → Create custom dimension** (scope "Event"): at least `episode_id`,
`show` and `episode_language`, and optionally `episode_title`, `story_group`, `category`,
`percent`, `from_language` and `to_language`. Dimensions only fill in from the day they
are created; then use them in the event report or an **Explore** (e.g. rows
`episode_title`, columns `percent`, filter on `episode_progress`).

## Tabs (categories)

Build Wiz AI Show's page has four tabs: **AI podcast**, **Daily**, **Marketing** and
**Others** (the stories, once the **Bedtime stories** tab, are on their own page, linked
from the header). The story pages have no tabs. Each episode in `episodes.json` has one
`category`: `ai`, `daily`, `bedtime`, `marketing` or `others` (`bedtime` is kept for the
stories; on the main page an unknown category lands in Others). `daily` is the daily
AI-news roundup (about eight minutes, every morning): it shares Build Wiz AI Show's feed
(`docs/feed.xml`) and YouTube like the other tabs, and is never guessed, so a daily job
names it in its `category.txt` (or `--category daily`). The publisher picks it in this order:

1. `--category` (one job at a time);
2. a `category.txt` in the job folder, holding one of the five words;
3. `bedtime` for a `bedtime-story` script;
4. the category already in `episodes.json`, so a hand fix survives a re-publish;
5. a keyword guess from the title and summary (AI words → `ai`, more marketing words
   → `marketing`, neither → `others`; never `daily`).

To move a live episode, edit its `category` in `docs/episodes.json`. Links keep the tab
in the query (`?tab=marketing`); a shared episode link (`#<job id>`) opens its own tab.

Edit `docs/` in place (the publisher adds episodes there). `.github/pages-publish.json`
lists only the files of the first publish, so don't re-run a publish tool against a
separate staging folder: it could remove episodes it does not know about.

Episodes voiced with edge-tts are for private use only and are never published (nothing
is uploaded); a job created with `--no-publish` is skipped too.
