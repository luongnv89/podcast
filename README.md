# Build Wiz AI — podcast

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
```

Episodes voiced with edge-tts are for private use only and are never published; a job
created with `--no-publish` is skipped too.
