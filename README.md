<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/logo-full.svg">
    <img src="assets/logo/logo-black.svg" alt="The AI Show" width="320">
  </picture>
</p>

# The AI Show — podcast

Episodes generated with [DropCast](https://github.com/luongnv89/dropcast): a two-host
conversation (Bob and Alice) about one public article, thread or paper, fact-checked
against the source and credited in every episode.

Listen: **https://luongnv.com/podcast/**

## How it updates

The site is static (`docs/`), deployed by GitHub Pages from `main`
(`.github/workflows/pages.yml`).

- `docs/index.html` — the listing page and player; it reads `docs/episodes.json`.
- `docs/episodes/<job id>/` — each episode's `episode.mp3` and `transcript.vtt`.
- `scripts/publish.py` — copies delivered DropCast jobs into `docs/`, updates
  `episodes.json`, and (with `--push`) commits and pushes. Standard library only.

DropCast calls the publisher after every delivered episode when this is set in its
`.env` (publishing is on by default; `--no-publish`, "don't publish" in the request, or
`DROPCAST_PUBLISH=0` turn it off):

```bash
DROPCAST_PUBLISH_CMD="python3 /path/to/podcast/scripts/publish.py --push"
```

By hand:

```bash
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --push
python3 scripts/publish.py --all            # every delivered job, no git
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --category marketing
```

## Tabs (categories)

The page has four tabs: **AI podcast**, **Bedtime stories**, **Marketing** and
**Others**. Each episode in `episodes.json` has one `category`: `ai`, `bedtime`,
`marketing` or `others`. The publisher picks it in this order:

1. `--category` (one job at a time);
2. a `category.txt` in the job folder, holding one of the four words;
3. `bedtime` for a `bedtime-story` script;
4. the category already in `episodes.json`, so a hand fix survives a re-publish;
5. a keyword guess from the title and summary (AI words → `ai`, more marketing words
   → `marketing`, neither → `others`).

To move a live episode, edit its `category` in `docs/episodes.json`. Links keep the tab
in the query (`?tab=bedtime`); a shared episode link (`#<job id>`) opens its own tab.

Edit `docs/` in place (the publisher adds episodes there). `.github/pages-publish.json`
lists only the files of the first publish, so don't re-run a publish tool against a
separate staging folder: it could remove episodes it does not know about.

Episodes voiced with edge-tts are for private use only and are never published; a job
created with `--no-publish` is skipped too.

## Podcast feed (Spotify and other apps)

`docs/feed.xml` (https://luongnv.com/podcast/feed.xml) is the show's RSS feed, as
**Build Wiz AI** (`en`, cover art `docs/cover.jpg`, made from `assets/cover/cover.html`).
Spotify has no upload API: the feed is submitted once in Spotify for Creators (Add a new
show → Find an existing show → Somewhere else → the feed URL, then the 8-digit code sent
to the feed's owner email, `buildwizai@gmail.com`). After that, Spotify checks the feed
several times an hour and adds new feed episodes on its own.

The feed is opt-in per episode and English only: an episode is listed when its
`episodes.json` entry has `"feed": true`.

```bash
python3 scripts/feed.py list                      # in the feed / can be added
python3 scripts/feed.py add <job id> --push       # list an episode (English only)
python3 scripts/feed.py remove <job id> --push    # unlist it (Spotify unpublishes it)
python3 scripts/feed.py build                     # rewrite feed.xml from episodes.json
```

`publish.py` keeps the `feed` flag when it re-publishes an episode and rebuilds the
feed after every publish; a re-rendered episode gets a new `?v=` audio URL so apps
download it again. Tests: `python3 -m unittest discover tests`.
