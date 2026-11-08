# SIRALens

Job matching for Ethiopia: upload a CV, get ranked and explained matches from local portals,
Telegram channels, and NGO/international sources, in English and Amharic.

## Layout
- `backend/`  FastAPI API (auth boundary in `app/auth.py`)
- `db/migrations/`  SQL schema
- `crawlers/`  source adapters & multi-engine scrapers (Phase 1)
- `normalizer/`  normalization pipeline, calendar converter, skill tagger & scam detector (Phase 2)
- `frontend/`  React app (Phase 5)

## Normalization Pipeline (Phase 2)
Consumes raw listings from `job_raw`, cleans text, converts Ethiopian Calendar to Gregorian dates, extracts fields (title, employer, location, work mode, job type, education, experience, apply info), attaches canonical skills, flags scam jobs, deduplicates, and writes to `jobs` and `job_skills`.

```bash
# Dry run: preview extracted fields without writing to the database
python -m normalizer.runner --dry-run

# Run normalization on all pending jobs
python -m normalizer.runner

# Normalize up to 200 items
python -m normalizer.runner --limit 200

# View current database counts and stats
python -m normalizer.runner --stats

## Automated Nightly Pipeline
A unified pipeline that automatically runs every midnight:
1. Crawls all enabled sources (websites, RSS feeds, Telegram channels) incrementally.
2. Normalizes raw listings, extracts bilingual titles, maps skills, and assesses scam risks.
3. Automatically marks expired jobs whose deadline has passed (`status = 'expired'`).

### Cloud Automation (GitHub Actions - Recommended)
Runs completely serverless in the cloud at **00:00 East Africa Time** every night (even when your PC is turned off).
- Configuration: [nightly_crawl.yml](file:///.github/workflows/nightly_crawl.yml)
- Set up: Go to GitHub Repo -> **Settings** -> **Secrets and variables** -> **Actions** -> Add `DATABASE_URL`.

### Local Windows Automation (Task Scheduler)
To run automatically on your Windows PC every midnight:
```cmd
schtasks /create /tn "SiraLens_Nightly_Pipeline" /tr "C:\Users\liche\Desktop\SiraLens\siralens-phase1\siralens\scripts\run_nightly.bat" /sc daily /st 00:00
```

## Setup (phase 1)
1. Create a free project at supabase.com.
2. SQL editor -> paste and run `db/migrations/0001_init.sql`.
3. Project Settings -> Database -> copy the **Session pooler** connection string into `DATABASE_URL`.
4. Project Settings -> API -> copy the project URL into `SUPABASE_URL`.
   If the project shows a legacy JWT secret, put it in `SUPABASE_JWT_SECRET`; otherwise leave it empty.
5. `cp .env.example backend/.env` and fill it in.
6. Run:
   ```
   cd backend
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   pytest -q
   uvicorn app.main:app --reload
   ```
7. Open http://localhost:8000/docs. `GET /health` should return ok.

## Rules that keep auth swappable
1. Our own `users` table; the provider's ID is just two columns.
2. Only `app/auth.py` touches Supabase tokens; everything else uses `get_current_user`.
3. Ownership is checked in our SQL (`where user_id = ...`); RLS is a second layer.
4. No Supabase-only features in matching or ingestion code.
