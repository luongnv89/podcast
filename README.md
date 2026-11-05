<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/logo-full.svg">
    <img src="assets/logo/logo-black.svg" alt="Build Wiz AI Show" width="320">
  </picture>
</p>

# Build Wiz AI Show — podcast

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
DROPCAST_PUBLISH_CMD=python3 /path/to/podcast/scripts/publish.py --push
```

By hand:

```bash
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --push
python3 scripts/publish.py --all            # every delivered job, no git
python3 scripts/publish.py ~/dropcast/jobs/2026-11-03_some-episode --category marketing
```

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
it, as is, into the episode's entry as `music_credit` (it reads `run.json`, since
`result.json` is not final yet when DropCast calls it), and the episode's details show it
as a small line: "Music: <credit>". Episodes without a credit (the CC0 theme, older jobs)
get no `music_credit` key, so their entries are unchanged.

Tests (standard library, no network): `python3 -m unittest discover -s tests`.

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
