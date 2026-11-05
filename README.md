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
- `docs/episodes/<job id>/` — each episode's `episode.mp3` and `transcript.vtt`.
- `scripts/publish.py` — copies delivered DropCast jobs into `docs/`, updates
  `episodes.json`, and (with `--push`) commits and pushes. Standard library only.

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
```

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

Tests (standard library, no network): `python3 -m unittest discover -s tests`.

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
