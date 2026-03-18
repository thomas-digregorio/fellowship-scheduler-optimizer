"""Fellowship Scheduler dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.components.checks_panel import render_checks_panel
from app.components.fellow_cards import render_fellow_cards
from app.components.master_schedule import render_master_schedule
from app.components.pto_calendar import render_pto_calendar
from app.components.rules_tab import render_rules_tab
from app.state import (
    clear_notice,
    get_config,
    get_issues,
    get_notice,
    get_result,
    init_state,
    persist_config,
    set_issues,
    set_result,
)
from src.export import export_csv, export_pdf
from src.models import TrainingYear
from src.scheduler import check_feasibility, solve_schedule


st.set_page_config(
    page_title="Fellowship Scheduler",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_state()


def _has_fatal_feasibility_issue(issues: list[str]) -> bool:
    """Return True when the current config has a blocking issue."""

    fatal_prefixes = (
        "⚠️ Staffing conflict",
        "⚠️ Block capacity conflict",
        "⚠️ Coverage/minimum conflict",
        "⚠️ Block minimums conflict",
        "⚠️ No fellows configured",
    )
    return any(issue.startswith(fatal_prefixes) for issue in issues)


st.sidebar.title("🚀 Actions")
st.sidebar.caption("Configure the schedule from the **Rules** tab.")

if st.sidebar.button("🔄 Generate Schedule", use_container_width=True, type="primary"):
    config = get_config()
    issues = check_feasibility(config)
    set_issues(issues)

    if _has_fatal_feasibility_issue(issues):
        st.sidebar.error("Cannot generate: fix blocking configuration issues first.")
    else:
        with st.spinner("Solving... this may take up to 5 minutes."):
            result = solve_schedule(config)
            set_result(result)
        if result.solver_status.value in ("optimal", "feasible"):
            st.sidebar.success(
                f"✅ Schedule generated! ({result.solver_status.value}, "
                f"{result.solve_time_seconds:.1f}s)"
            )
        else:
            st.sidebar.error(
                f"❌ Solver returned: {result.solver_status.value}. Try relaxing constraints."
            )
    st.rerun()

csv_col, pdf_col = st.sidebar.columns(2)
with csv_col:
    if st.button("📄 CSV", use_container_width=True):
        result = get_result()
        if result:
            export_path = PROJECT_ROOT / "exports" / "schedule.csv"
            export_csv(result, get_config(), export_path)
            st.sidebar.success(f"Saved to {export_path}")
        else:
            st.sidebar.warning("Generate a schedule first.")

with pdf_col:
    if st.button("📑 PDF", use_container_width=True):
        result = get_result()
        if result:
            export_path = PROJECT_ROOT / "exports" / "schedule.pdf"
            export_pdf(result, get_config(), export_path)
            st.sidebar.success(f"Saved to {export_path}")
        else:
            st.sidebar.warning("Generate a schedule first.")

if st.sidebar.button("💾 Save Config", use_container_width=True):
    persist_config()
    st.sidebar.success("Configuration saved.")


st.title("🏥 Fellowship Schedule Dashboard")

notice = get_notice()
if notice:
    st.info(notice)
    clear_notice()

issues = get_issues()
if issues:
    for issue in issues:
        st.warning(issue)

config = get_config()
result = get_result()

rules_tab, schedule_tab, fellow_tab = st.tabs(
    ["Rules", "Master Schedule & Checks", "PTO & Fellows"]
)

with rules_tab:
    render_rules_tab(config)

with schedule_tab:
    filter_options = {
        "All Cohorts": None,
        TrainingYear.F1.value: TrainingYear.F1,
        TrainingYear.S2.value: TrainingYear.S2,
        TrainingYear.T3.value: TrainingYear.T3,
    }
    selected_label = st.selectbox(
        "Visible cohort in master schedule",
        options=list(filter_options.keys()),
        index=0,
        key="master_schedule_year_filter",
    )
    st.caption(
        "The cohort filter changes the displayed master schedule. Checks below "
        "still evaluate the full generated schedule."
    )
    render_master_schedule(config, result, filter_options[selected_label])
    st.markdown("---")
    render_checks_panel(config, result)

with fellow_tab:
    left_col, right_col = st.columns([1.2, 2.0])
    with left_col:
        render_pto_calendar(config, result)
    with right_col:
        render_fellow_cards(config, result)
