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
  warm narrator (the `bedtime-story` and `storytelling` formats). Listen:
  **https://luongnv.com/podcast/stories/**

## How it updates

The site is static (`docs/`), deployed by GitHub Pages from `main`
(`.github/workflows/pages.yml`).

- `docs/index.html` — Build Wiz AI Show's page (tabs, search, player).
- `docs/stories/index.html` — Once Upon a Time Show's page (one list, search, player).
- `docs/site.js`, `docs/site.css` — the list and player both pages share. Each page sets
  `window.SHOW_PAGE` (its show, tabs and the path to `episodes.json`) before loading
  `site.js`; both read the same `docs/episodes.json` and list only their show's episodes.
  Both pages load them as `site.js?v=<version>` / `site.css?v=<version>`: bump the
  version on both pages whenever either file changes (GitHub Pages caches them for 10 min).
- `docs/episodes/<job id>/` — each episode's `episode.mp3`, `transcript.vtt` and its own
  page `index.html` (see "Descriptions, download names and episode pages").
- `docs/sitemap.xml`, `docs/robots.txt`, `docs/cover.jpg` — the sitemap of both show pages
  and every episode page, and Build Wiz AI Show's cover for share previews (rendered from
  `assets/cover/build-wiz-cover.html`, 1400 x 1400).
- `scripts/publish.py` — copies delivered DropCast jobs into `docs/`, updates
  `episodes.json`, rebuilds the story feeds, the episode pages and the sitemap, and (with
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
python3 scripts/publish.py --backfill [--push]   # descriptions, names, pages for old entries
```

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
<Show>: <tagline> luongnv.com/podcast                 (stories: luongnv.com/podcast/stories)
```

The publisher takes it from, in this order: the job's `description.txt` (written by Echo,
checked by DropCast; the publisher only refuses one that is empty, over 600 characters or
has Markdown/HTML, and then says so in its `notes`), the description already in
`episodes.json` (a hand fix survives a re-publish), else one generated from the entry
(`fallback_description()`: the first summary line plus one sentence on the hosts or the
length as the hook, the other summary lines as the points, the sources, the music credit,
then the show's tagline in the episode's language). A generated one is shortened until it
fits: authors only in `Sources`, without the added sentence, two points, fewer sources
named (`and N more`), and last the longest lines cut at a word boundary.

Every entry also has a `file_name`, the download name `<Show> - <Title> (<YYYY-MM-DD>).mp3`:
`run.json` `delivery.file_name` when DropCast wrote a clean one, else rebuilt with the same
rule (`episode_file_name()`: `\ / : * ? " < > |` and control characters dropped, spaces
collapsed, at most 150 characters before `.mp3`, the title cut at a word boundary; the
date is the published day in Europe/Paris). The MP3 on the site keeps its path
(`episodes/<id>/episode.mp3`); only the saved name changes.

On the site, **Download MP3** saves the file under `file_name` (else `<id>.mp3`), and each
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
name), the transcript and a link back to `#<id>` on the show page; a story's versions link
each other (`hreflang`). The list pages link each title to its page (a plain click still
opens the details; a middle or Ctrl/Cmd click opens the page). `docs/sitemap.xml` lists
the two show pages and every episode page. Pages and sitemap are rebuilt from
`episodes.json` on every publish and change only when an episode does. Crawlers read
`robots.txt` only at the domain root, which lives in the luongnv.com repository: add
`Sitemap: https://luongnv.com/podcast/sitemap.xml` there (or submit the sitemap in Search
Console); `docs/robots.txt` names it too.

**Backfill.** `python3 scripts/publish.py --backfill` gives every entry without one a
`description` and a `file_name` (a job folder still in `$DROPCAST_HOME/jobs` gives its
`description.txt` and `delivery.file_name`; otherwise they are generated from the entry),
then rebuilds the episode pages and the sitemap. Entries that have both are left alone,
so it is safe to run again; `--push` commits and pushes the result.

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
The pages apply the same rule (a story format is always on the story page), so an entry
never shows up on both. The top-level `shows` lists both shows and their pages.
Each page shows the counts and minutes of its own show only. Old links follow the
stories: `?tab=bedtime` and `#<story id>` on the main page open the story page.

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

The story page lists the versions of one `story_group` as **one story** with a language
switch (English / Français / Tiếng Việt, shortened to EN / FR / VI on a phone, each
labelled in its own language). Switching changes the title, summary, duration, player,
transcript, download, source link and music credit; a playing story keeps playing in the
new language. The version shown first is the visitor's last choice (remembered in the
browser), else the first browser language (`navigator.languages`) that has a version,
else English, else the first version. Every version keeps its own id, so `#<episode id>`
opens that version. A search matches a story when any of its versions matches; while
the search is on, the story shows its first matching version (unless the chosen one
matches, or was picked during that search), without remembering it, and clearing the
search brings the chosen version back. Languages compare by their primary subtag
(`en-US` is `en`), and an unknown language is labelled with its code (at most 3
letters, uppercased). The
counts count stories (one per group), and the minutes count the version shown first, so
a story in three languages counts once. Entries without `story_group` (and a second
version in a language the group already has) show as before; the main page has no
groups.

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
  `?v=<sha8>` of the MP3, so a re-voiced episode is downloaded again under the same guid.
- Channel: category Kids & Family › Stories for Kids, not explicit, owner email
  `buildwizai@gmail.com` (public in the feed: Spotify emails its 8-digit code there).
  Titles and descriptions (each under Spotify's 600-character limit) are in `FEEDS` in
  `scripts/feed.py`.
- Covers are 3000 x 3000 JPEGs rendered from `assets/cover/stories-cover.html?lang=<lang>`
  with headless Chromium.
- Build Wiz AI Show stays hosted on Spotify for Creators and is not in these feeds.

**Submitting a feed (once per language):** creators.spotify.com → avatar or menu →
**Add a new show** → **Find an existing show** → **Somewhere else** → paste the feed URL →
enter the code emailed to buildwizai@gmail.com → check the details and submit.

## Analytics (GA4 events)

Both pages load Google Analytics 4 (`G-FZV5YX8YPT`, the luongnv.com property) for page
views. The shared `docs/site.js` also sends these events through the page's own `gtag`
(DropCast #138). There is no other tracker and no new cookie, and no personal data is
sent. Every call is guarded (`typeof gtag === "function"`, inside `try`), so a blocked,
missing or throwing `gtag` changes nothing on the page. "Once" means once per page view:
a reload counts again.

| Event | When | Extra parameters |
|---|---|---|
| `episode_play` | an episode starts playing for the first time in the page view (a resume after a pause is not counted) | |
| `episode_progress` | the player reaches 25, 50, 75 and 100 % of the episode (100: it played to the end), each once per episode, only after its `episode_play` (so loading a resume point sends nothing; seeking ahead does reach a milestone, and playing from a saved resume point counts the milestones already passed, so `percent` is the position reached, not proof it was all heard) | `percent` (25, 50, 75, 100) |
| `language_switch` | the visitor picks another language of a story (EN / FR / VI); a deep link does not count | `from_language`, `to_language` |
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

Build Wiz AI Show's page has three tabs: **AI podcast**, **Marketing** and **Others**
(the stories, once the **Bedtime stories** tab, are on their own page, linked from the
header). The story page has no tabs. Each episode in `episodes.json` has one `category`:
`ai`, `bedtime`, `marketing` or `others` (`bedtime` is kept for the stories; on the main
page an unknown category lands in Others). The publisher picks it in this order:

1. `--category` (one job at a time);
2. a `category.txt` in the job folder, holding one of the four words;
3. `bedtime` for a `bedtime-story` script;
4. the category already in `episodes.json`, so a hand fix survives a re-publish;
5. a keyword guess from the title and summary (AI words → `ai`, more marketing words
   → `marketing`, neither → `others`).

To move a live episode, edit its `category` in `docs/episodes.json`. Links keep the tab
in the query (`?tab=marketing`); a shared episode link (`#<job id>`) opens its own tab.

Edit `docs/` in place (the publisher adds episodes there). `.github/pages-publish.json`
lists only the files of the first publish, so don't re-run a publish tool against a
separate staging folder: it could remove episodes it does not know about.

Episodes voiced with edge-tts are for private use only and are never published; a job
created with `--no-publish` is skipped too.
