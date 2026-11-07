# crawlers

Everything we crawl is listed in **`sources.yaml`**. The runner loops over that file and picks a generic
**engine** for each entry. Adding a job portal or a Telegram channel means adding a few lines of YAML, not code.

```
sources.yaml --> runner.py --> engines/<type>.py --> job_raw (Postgres)
   (what)        (loop)        (how, generic)         (what we found)
```

## Engines
| engine | use for | main options |
|---|---|---|
| `html` | any website with job detail pages | `discovery.list_urls`, `discovery.sitemaps`, `discovery.link_pattern`, `css` |
| `feed` | RSS, Atom, WordPress `/feed/` | `feed_urls` |
| `telegram` | a public channel (web preview) | `channel` |
| `json_api` | a site that loads jobs from a JSON endpoint | `url`, `items_path`, `id_path`, `fields` |
| `reliefweb` | the official ReliefWeb API | `queries` (needs `RELIEFWEB_APPNAME`) |

## Commands (run from the project root, the folder containing `backend/` and `crawlers/`)
```
pip install -r crawlers/requirements.txt
python -m crawlers.runner --list                 # show all sources
python -m crawlers.runner --check geezjobs       # dry run: no database, shows links found, samples, problems
python -m crawlers.runner                        # crawl every enabled source into the database
python -m crawlers.runner --only geezjobs        # crawl just these
python -m crawlers.runner --sync                 # copy sources.yaml into the job_sources table
```
`DATABASE_URL` is read from `backend/.env`. `--check` and `--list` do not need it.

## Add a new source
1. Add an entry to `sources.yaml` (copy a similar one). Keep `enabled: false`.
2. `python -m crawlers.runner --check <slug>`. Read the samples and the PROBLEM lines.
3. Fix the entry until the samples look right (`link_pattern`, `list_urls`, `css`...). Then set `enabled: true`.

## What the runner guarantees
- Honest user agent, `robots.txt` respected, 2 seconds between requests to the same site (all sources share this).
- One failing source never stops the others. A source that finds nothing is reported, not silently "successful".
- Each item is saved on its own savepoint, so one bad row never ruins the rest.
- Items already stored are not fetched again. Changed items are updated.
- Every run is logged in `crawl_runs`, and `job_sources.last_status` shows each source's health.
- It is a one-shot command: schedule it with Task Scheduler, cron or a CI schedule. There is no sleeping loop.

## Tests
```
cd crawlers && pytest -q                                   # 52 tests, no network, no database
TEST_DATABASE_URL=postgresql://... pytest -q               # +5 tests against a THROWAWAY Postgres (never your real one)
```
`tools/probe.py` is a stand-alone inspector for a NEW site: `python -m crawlers.tools.probe <slug>`.
