# SIRALens

Job matching for Ethiopia: upload a CV, get ranked and explained matches from local portals,
Telegram channels, and NGO/international sources, in English and Amharic.

## Layout
- `backend/`  FastAPI API (auth boundary in `app/auth.py`)
- `db/migrations/`  SQL schema
- `crawlers/`  source adapters (phase 2)
- `frontend/`  React app (phase 5)

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
