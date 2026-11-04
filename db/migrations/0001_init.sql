-- SIRALens schema v1. Run once in the Supabase SQL editor.
-- Design rules:
--   * `users` is OUR table. Auth provider IDs live in two plain columns, so swapping providers is cheap.
--   * No table references auth.users.
--   * RLS is enabled everywhere with no policies: the public (anon) key can read nothing.
--     The FastAPI backend connects with a server-side role and enforces ownership itself.

create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists pgcrypto;

-- ---------- Users ----------
create table users (
  id                 uuid primary key default gen_random_uuid(),
  auth_provider      text not null default 'supabase',
  auth_subject       text not null,
  email              text,
  display_name       text,
  preferred_language text not null default 'en' check (preferred_language in ('en','am')),
  consent_at         timestamptz,          -- explicit consent to process CV data
  created_at         timestamptz not null default now(),
  last_seen_at       timestamptz not null default now(),
  unique (auth_provider, auth_subject)
);

-- ---------- Job sources ----------
create table job_sources (
  id              smallserial primary key,
  slug            text not null unique,
  name            text not null,
  source_type     text not null check (source_type in ('portal','telegram','ngo','api','employer')),
  base_url        text not null,
  wave            smallint not null default 2,   -- rollout wave (1 = first)
  enabled         boolean not null default false,
  last_crawled_at timestamptz
);

-- ---------- Raw captures (pruned after ~30 days to respect the 500 MB free tier) ----------
create table job_raw (
  id           bigserial primary key,
  source_id    smallint not null references job_sources(id),
  external_id  text not null,                -- source's own ID, or URL/message ID
  url          text,
  raw_text     text not null,
  raw_meta     jsonb not null default '{}',
  content_hash text not null,
  fetched_at   timestamptz not null default now(),
  processed_at timestamptz,
  unique (source_id, external_id)
);
create index job_raw_unprocessed on job_raw (id) where processed_at is null;
create index job_raw_fetched on job_raw (fetched_at);

-- ---------- Jobs (normalized) ----------
create table jobs (
  id                   uuid primary key default gen_random_uuid(),
  source_id            smallint not null references job_sources(id),
  external_id          text not null,
  url                  text,
  title                text not null,
  employer_name        text,
  employer_id          uuid,                 -- v2: employer accounts. Unused in v1 (no FK yet).
  description          text,
  language             text check (language in ('en','am','mixed')),
  location_city        text,
  location_country     text,                 -- ISO-3166 alpha-2 where known, e.g. 'ET'
  work_mode            text check (work_mode in ('onsite','hybrid','remote')),
  job_type             text check (job_type in ('full_time','part_time','contract','freelance','internship','volunteer')),
  eligibility          text not null default 'unknown'
                         check (eligibility in ('ethiopians','worldwide','restricted','unknown')),
  eligibility_note     text,                 -- e.g. "US residents only"
  deadline             date,                 -- stored in Gregorian
  posted_at            timestamptz,
  education_level      text,
  experience_years_min smallint,
  apply_info           text,
  risk_score           smallint not null default 0,
  risk_flags           text[] not null default '{}',   -- e.g. {'upfront_fee','personal_contact_only'}
  content_hash         text,
  dedup_group_id       uuid,                 -- same job seen on several sources shares this
  is_canonical         boolean not null default true,
  status               text not null default 'open' check (status in ('open','expired','hidden')),
  embedding            vector(384),          -- multilingual-e5-small
  first_seen_at        timestamptz not null default now(),
  last_seen_at         timestamptz not null default now(),
  unique (source_id, external_id)
);
create index jobs_status_deadline on jobs (status, deadline);
create index jobs_dedup on jobs (dedup_group_id);
create index jobs_title_trgm on jobs using gin (title gin_trgm_ops);
create index jobs_embedding on jobs using hnsw (embedding vector_cosine_ops);

create table job_skills (
  job_id uuid not null references jobs(id) on delete cascade,
  skill  text not null,                      -- canonical English name; Amharic aliases live in the skills dictionary
  primary key (job_id, skill)
);
create index job_skills_skill on job_skills (skill);

-- ---------- CVs ----------
create table cv_profiles (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references users(id) on delete cascade,
  storage_path      text,                    -- file in Supabase Storage
  original_filename text,
  language          text,
  redacted_text     text,                    -- PII removed; this is what may be sent to the LLM
  profile           jsonb not null default '{}',   -- extracted skills, education, experience
  embedding         vector(384),
  is_active         boolean not null default true,
  created_at        timestamptz not null default now()
);
create index cv_profiles_user on cv_profiles (user_id);

-- ---------- User activity ----------
create table saved_jobs (
  user_id  uuid not null references users(id) on delete cascade,
  job_id   uuid not null references jobs(id) on delete cascade,
  saved_at timestamptz not null default now(),
  primary key (user_id, job_id)
);

create table interactions (
  id         bigserial primary key,
  user_id    uuid not null references users(id) on delete cascade,
  job_id     uuid not null references jobs(id) on delete cascade,
  kind       text not null check (kind in ('view','save','apply_click','dismiss')),
  created_at timestamptz not null default now()
);
create index interactions_user on interactions (user_id, created_at desc);

create table match_cache (
  cv_profile_id uuid not null references cv_profiles(id) on delete cascade,
  job_id        uuid not null references jobs(id) on delete cascade,
  score         real not null,
  skill_overlap real,
  explanation   jsonb,                       -- {"en": "...", "am": "..."} filled lazily, top matches only
  computed_at   timestamptz not null default now(),
  primary key (cv_profile_id, job_id)
);

-- ---------- Row-level security: on, no policies = anon/public key sees nothing ----------
alter table users          enable row level security;
alter table job_sources    enable row level security;
alter table job_raw        enable row level security;
alter table jobs           enable row level security;
alter table job_skills     enable row level security;
alter table cv_profiles    enable row level security;
alter table saved_jobs     enable row level security;
alter table interactions   enable row level security;
alter table match_cache    enable row level security;

-- ---------- Seed sources ----------
insert into job_sources (slug, name, source_type, base_url, wave, enabled) values
  ('ethiojobs',      'EthioJobs',               'portal',   'https://ethiojobs.net/',                  1, true),
  ('reliefweb',      'ReliefWeb',               'ngo',      'https://reliefweb.int/',                  1, true),
  ('tg_abayjobs21',  'Telegram: abayjobs21',    'telegram', 'https://t.me/s/abayjobs21',               1, true),
  ('hahu',           'Hahu Jobs',               'portal',   'https://www.hahu.jobs/',                  2, false),
  ('ethiopianreporter','Ethiopian Reporter Jobs','portal',  'https://www.ethiopianreporterjobs.com/',  2, false),
  ('geezjobs',       'GeezJobs',                'portal',   'https://geezjobs.com/',                   2, false),
  ('ethiopiawork',   'EthiopiaWork',            'portal',   'https://www.ethiopiawork.com/',           2, false),
  ('palmjobs',       'PalmJobs',                'portal',   'https://palmjobs.et/',                    2, false),
  ('muyalogy',       'Muyalogy',                'portal',   'https://muyalogy.com/',                   2, false),
  ('ethiongojobs',   'EthioNGOJobs',            'portal',   'https://www.ethiongojobs.com/',           2, false),
  ('tg_josad',       'Telegram: josad_software','telegram', 'https://t.me/s/josad_software',           3, false),
  ('tg_freelance',   'Telegram: freelance_ethio','telegram','https://t.me/s/freelance_ethio',          3, false),
  ('unjobs',         'UNjobs',                  'ngo',      'https://unjobs.org/',                     3, false),
  ('impactpool',     'Impactpool',              'ngo',      'https://www.impactpool.org/',             3, false);
