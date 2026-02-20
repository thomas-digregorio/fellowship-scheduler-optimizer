"""Fellowship Scheduler — Streamlit Dashboard.

This is the main entry point for the web application. Run with:
    streamlit run app/app.py

The dashboard has three panels:
    Left   → PTO Calendar (each fellow's vacation weeks)
    Center → Master Schedule (editable 52-week × 9-fellow grid)
    Right  → Fellow Cards (per-fellow breakdown with stats)

And a sidebar for all configuration and action buttons.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path so we can import src/ modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from components.config_sidebar import render_config_sidebar
from components.fellow_cards import render_fellow_cards
from components.master_schedule import render_master_schedule
from components.pto_calendar import render_pto_calendar
from state import get_config, get_issues, get_result, set_issues, set_result
from src.export import export_csv, export_pdf
from src.scheduler import check_feasibility, solve_schedule


# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Fellowship Scheduler",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Initialize session state
# ---------------------------------------------------------------------------

from state import init_state  # noqa: E402
init_state()


# ---------------------------------------------------------------------------
# Sidebar: configuration + action buttons
# ---------------------------------------------------------------------------

render_config_sidebar()

# Action buttons at the bottom of sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("🚀 Actions")

# --- Generate Schedule button ---
if st.sidebar.button(
    "🔄 Generate Schedule",
    use_container_width=True,
    type="primary",
):
    config = get_config()

    # Run feasibility check first
    issues = check_feasibility(config)
    set_issues(issues)

    if any("⚠️ Staffing conflict" in issue for issue in issues):
        st.sidebar.error("Cannot generate: fix staffing issues first.")
    else:
        with st.spinner("Solving... this may take up to 2 minutes."):
            result = solve_schedule(config)
            set_result(result)

        if result.solver_status.value in ("optimal", "feasible"):
            st.sidebar.success(
                f"✅ Schedule generated! "
                f"({result.solver_status.value}, "
                f"{result.solve_time_seconds:.1f}s)"
            )
        else:
            st.sidebar.error(
                f"❌ Solver returned: {result.solver_status.value}. "
                f"Try relaxing constraints."
            )
    st.rerun()

# --- Export buttons ---
col_csv, col_pdf = st.sidebar.columns(2)

with col_csv:
    if st.button("📄 CSV", use_container_width=True):
        result = get_result()
        if result:
            export_path = PROJECT_ROOT / "exports" / "schedule.csv"
            export_csv(result, get_config(), export_path)
            st.sidebar.success(f"Saved to {export_path}")
        else:
            st.sidebar.warning("Generate a schedule first.")

with col_pdf:
    if st.button("📑 PDF", use_container_width=True):
        result = get_result()
        if result:
            export_path = PROJECT_ROOT / "exports" / "schedule.pdf"
            export_pdf(result, get_config(), export_path)
            st.sidebar.success(f"Saved to {export_path}")
        else:
            st.sidebar.warning("Generate a schedule first.")

# --- Lock & Re-solve (for maternity leave) ---
st.sidebar.markdown("---")
with st.sidebar.expander("🔒 Lock & Re-solve (Maternity Leave)", expanded=False):
    st.caption(
        "Mark a fellow as unavailable for specific weeks, then re-run "
        "the solver. Already-completed weeks stay locked."
    )
    config = get_config()

    lock_fellow = st.selectbox(
        "Fellow",
        options=[f.name for f in config.fellows],
        key="lock_fellow",
    )
    lock_start = st.number_input(
        "Unavailable from week", min_value=1, max_value=52,
        value=1, key="lock_start",
    )
    lock_end = st.number_input(
        "Unavailable through week", min_value=lock_start, max_value=52,
        value=min(lock_start + 11, 52), key="lock_end",
    )

    if st.button("🔒 Apply & Re-solve", use_container_width=True):
        # Find the fellow index
        f_idx = next(
            i for i, f in enumerate(config.fellows)
            if f.name == lock_fellow
        )
        # Mark the weeks as unavailable
        config.fellows[f_idx].unavailable_weeks = list(
            range(lock_start - 1, lock_end)  # convert to 0-indexed
        )

        with st.spinner("Re-solving with locked weeks..."):
            result = solve_schedule(config)
            set_result(result)

        st.rerun()


# ---------------------------------------------------------------------------
# Show feasibility warnings
# ---------------------------------------------------------------------------

issues = get_issues()
if issues:
    for issue in issues:
        st.warning(issue)


# ---------------------------------------------------------------------------
# Main content: three-panel layout
# ---------------------------------------------------------------------------

st.title("🏥 Fellowship Schedule Dashboard")

config = get_config()
result = get_result()

# Three columns: PTO Calendar | Master Schedule | Fellow Cards
# Ratio: 1 : 3 : 1.5 (center panel is widest for the schedule grid)
left_col, center_col, right_col = st.columns([1, 3, 1.5])

with left_col:
    render_pto_calendar(config, result)

with center_col:
    render_master_schedule(config, result)

with right_col:
    render_fellow_cards(config, result)
