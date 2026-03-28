create table if not exists app_config (
  id text primary key,
  config_json jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by text
);

create table if not exists config_history (
  version_id bigint generated always as identity primary key,
  config_id text not null,
  config_json jsonb not null,
  saved_at timestamptz not null default now(),
  saved_by text
);

create index if not exists idx_config_history_config_id_saved_at
on config_history(config_id, saved_at desc);
