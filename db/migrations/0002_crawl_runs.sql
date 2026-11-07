-- Crawl run log + per-source health. Run once in the Supabase SQL editor, after 0001_init.sql.

create table if not exists crawl_runs (
  id              bigserial primary key,
  source_id       smallint not null references job_sources(id) on delete cascade,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  status          text not null check (status in ('ok','empty','partial','failed')),
  fetched         integer not null default 0,   -- items the crawler returned
  new_count       integer not null default 0,   -- inserted into job_raw
  changed_count   integer not null default 0,   -- existing item whose text changed
  unchanged_count integer not null default 0,
  requests        integer not null default 0,
  seconds         real,
  problems        jsonb not null default '[]'
);
create index if not exists crawl_runs_source_time on crawl_runs (source_id, started_at desc);
alter table crawl_runs enable row level security;

alter table job_sources add column if not exists last_status     text;
alter table job_sources add column if not exists last_success_at timestamptz;
