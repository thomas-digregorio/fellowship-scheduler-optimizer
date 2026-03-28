# 🏥 Fellowship Scheduler

An automated scheduling system for 9 cardiology fellows over a 52-week academic year (July 1, 2026 – June 30, 2027).

## Features

- **CP-SAT Constraint Solver** (Google OR-Tools) — finds optimal schedules respecting ACGME rules, staffing requirements, and PTO preferences
- **14 Rotation Blocks** — Night Float, CCU, Consult SRC/Y/VA, Cath Y/SRC, EP, Echo Y, VA Echo, CHF, Nuc Y, VA Clinic, Research
- **24-Hour Saturday Call** — overlay scheduling with fair distribution
- **Interactive Streamlit Dashboard** — three-panel layout with editable schedule grid
- **PTO Optimization** — fellows rank 6 preferred weeks, algorithm grants best 4
- **PDF & CSV Export** — color-coded schedule for print and data

## Prerequisites

- Python 3.12
- Conda (for environment management)
- WSL (Windows Subsystem for Linux)

## Setup

```bash
# 1. Create and activate the conda environment
conda env create -f environment.yml
conda activate fellowship-scheduler

# 2. (Optional) Set up Weights & Biases for logging
#    Create a .env file with your WANDB_API_KEY

# 3. Run tests to verify installation
pytest tests/ -v

# 4. Launch the dashboard
streamlit run app/app.py
```

### Supabase Shared Config Setup

This app now uses Supabase as the shared published config store for Streamlit Community Cloud deployments.

1. Create the config tables in Supabase by running:

```sql
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
```

The same SQL is also committed in [sql/supabase_config_persistence.sql](sql/supabase_config_persistence.sql).

2. Configure Streamlit secrets with:

```toml
SUPABASE_URL = "https://bzzkogsksrgvopfywqme.supabase.co"
SUPABASE_KEY = "your-service-role-key"
```

For local development, place that content in `.streamlit/secrets.toml`.
For Streamlit Community Cloud, add the same keys in the app Secrets settings.

3. Shared config flow:
   - On startup, the app loads the current published config from Supabase.
   - If no published config exists yet, the app bootstraps Supabase from the repo seed config and writes an initial history row.
   - The existing `Save Config` action publishes the current config for everyone and appends a new history row.
   - `Reset to Published` restores the current session back to the latest shared published config.
   - Streamlit session state is still used for temporary per-user edits before saving.

## Project Structure

```
fellowship-scheduler/
├── src/                     # Core scheduling engine
│   ├── models.py            # Data models (BlockConfig, FellowConfig, etc.)
│   ├── config.py            # Default block definitions & colors
│   ├── scheduler.py         # CP-SAT solver orchestrator
│   ├── constraints.py       # Constraint builder functions
│   ├── acgme.py             # ACGME duty-hour enforcement
│   ├── call_scheduler.py    # 24-hr weekend call overlay
│   ├── config_store.py      # Supabase shared config persistence
│   ├── export.py            # PDF and CSV export
│   └── io_utils.py          # JSON persistence
├── app/                     # Streamlit dashboard
│   ├── app.py               # Main entry point
│   ├── state.py             # Session state manager
│   └── components/          # UI panels
│       ├── config_sidebar.py
│       ├── pto_calendar.py
│       ├── master_schedule.py
│       └── fellow_cards.py
├── tests/                   # pytest test suite
├── data/                    # Config files & solver output
├── environment.yml          # Conda environment
└── requirements.txt         # Pip dependencies
```

## Usage

1. **Configure** blocks, staffing, and PTO rankings in the sidebar
2. **Generate** the schedule with the solver button
3. **Edit** assignments by clicking cells in the master grid
4. **Export** to PDF or CSV for distribution
5. **Re-solve** mid-year for maternity leave via the Lock & Re-solve panel

## Constraints Enforced

| Constraint | Details |
|-----------|---------|
| One assignment per week | Each fellow on exactly 1 block or PTO |
| PTO count | Exactly 4 weeks per fellow |
| No consecutive same block | Cannot repeat a block back-to-back |
| Night Float limit | Max 2 consecutive NF weeks |
| Block completion | Every fellow completes all 14 blocks ≥1× |
| Staffing coverage | Configurable min fellows per block per week |
| 80-hour trailing average | ACGME 4-week rolling average ≤ 80 hrs |
| Concurrent PTO cap | Max 1 fellow on PTO per week (configurable) |
| Call exclusions | No call during Night Float or PTO |
| Call fairness | ~5-6 call shifts per fellow per year |
