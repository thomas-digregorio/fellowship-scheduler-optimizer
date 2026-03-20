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
    is_dirty,
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


def _inject_design_system() -> None:
    """Apply a lighter, card-based visual system."""

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 30%),
                linear-gradient(180deg, #f5f7fb 0%, #edf2f7 100%);
        }

        [data-testid="stSidebar"] {
            background: #fbfcfe;
            border-right: 1px solid #dbe4ee;
        }

        [data-testid="stHeader"] {
            background: rgba(245, 247, 251, 0.75);
            backdrop-filter: blur(10px);
        }

        .app-eyebrow {
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.72rem;
            font-weight: 700;
            color: #64748b;
            margin-bottom: 0.4rem;
        }

        .app-hero h1 {
            margin: 0;
            color: #102a43;
            font-size: 2.35rem;
            line-height: 1.05;
            letter-spacing: -0.03em;
        }

        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #d9e2ec;
            border-radius: 18px;
            padding: 0.85rem 1rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }

        div[data-testid="stMetricLabel"] {
            color: #52606d;
        }

        div[data-testid="stMetricValue"] {
            color: #102a43;
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stExpander"] {
            border-radius: 18px;
            overflow: hidden;
        }

        div.stButton > button {
            border-radius: 999px;
            border: 1px solid #d9e2ec;
            min-height: 2.75rem;
            font-weight: 600;
        }

        div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #0f766e 0%, #155e75 100%);
            color: #ffffff;
            border: none;
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button {
            justify-content: flex-start;
            width: 100%;
            min-height: 3.15rem;
            border-radius: 16px;
            border: 1px solid #d9e2ec;
            background: rgba(255, 255, 255, 0.72);
            box-shadow: none;
            color: #102a43;
            padding: 0.7rem 0.95rem;
            margin-bottom: 0.35rem;
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
            border-color: #9fb3c8;
            background: #ffffff;
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button:focus,
        [data-testid="stSidebar"] div[data-testid="stButton"] > button:focus-visible {
            border-color: #9fb3c8;
            background: #ffffff;
            color: #102a43;
            outline: none;
            box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.12);
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
            border-color: #9fb3c8;
            background: #f8fbfd;
            color: #102a43;
            box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.08);
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] {
            background: linear-gradient(135deg, #0f766e 0%, #155e75 100%);
            color: #ffffff;
            border: none;
            box-shadow: 0 10px 24px rgba(15, 118, 110, 0.18);
        }

        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover,
        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:focus,
        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:focus-visible,
        [data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:active {
            background: linear-gradient(135deg, #0f766e 0%, #155e75 100%);
            color: #ffffff;
            border: none;
            box-shadow: 0 10px 24px rgba(15, 118, 110, 0.18);
            outline: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def _render_sidebar_nav() -> str:
    """Render the app-level navigation rail."""

    options = ["Overview", "Rules", "Master Schedule", "PTO & Fellows"]
    labels = {
        "Overview": "Overview",
        "Rules": "Set Rules",
        "Master Schedule": "Generate Schedule",
        "PTO & Fellows": "Fellow Breakdown",
    }
    current_page = st.session_state.get("workspace_page", options[0])

    for option in options:
        is_active = current_page == option
        if st.sidebar.button(
            labels[option],
            key=f"workspace_page_{option.lower().replace(' ', '_').replace('&', 'and')}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            if current_page != option:
                st.session_state["workspace_page"] = option
                st.rerun()

    st.session_state.setdefault("workspace_page", current_page)
    return st.session_state["workspace_page"]


def _render_action_bar() -> None:
    """Render the primary action buttons."""

    config = get_config()
    result = get_result()
    issues = get_issues()
    dirty = is_dirty()

    action_feedback: tuple[str, str] | None = None
    generate_col, save_col, csv_col, pdf_col = st.columns(4)
    with generate_col:
        if st.button("🔄 Generate Schedule", use_container_width=True, type="primary"):
            issues = check_feasibility(config)
            set_issues(issues)
            if _has_fatal_feasibility_issue(issues):
                action_feedback = (
                    "error",
                    "Cannot generate until the blocking validation issues are resolved.",
                )
            else:
                with st.spinner("Solving... this may take up to 1 minute."):
                    result = solve_schedule(config)
                    set_result(result)
                if result.solver_status.value in ("optimal", "feasible"):
                    action_feedback = (
                        "success",
                        f"Schedule generated successfully in {result.solve_time_seconds:.1f}s.",
                    )
                else:
                    action_feedback = (
                        "error",
                        f"Solver returned {result.solver_status.value}. Relax constraints and try again.",
                    )

    with save_col:
        if st.button(
            "💾 Save Config",
            use_container_width=True,
            disabled=not dirty,
        ):
            persist_config()
            action_feedback = ("success", "Configuration saved.")

    with csv_col:
        if st.button(
            "📄 Export CSV",
            use_container_width=True,
            disabled=result is None,
        ):
            export_path = PROJECT_ROOT / "exports" / "schedule.csv"
            export_csv(result, config, export_path)
            action_feedback = ("success", f"CSV exported to {export_path}.")

    with pdf_col:
        if st.button(
            "📑 Export PDF",
            use_container_width=True,
            disabled=result is None,
        ):
            export_path = PROJECT_ROOT / "exports" / "schedule.pdf"
            export_pdf(result, config, export_path)
            action_feedback = ("success", f"PDF exported to {export_path}.")

    if action_feedback is not None:
        getattr(st, action_feedback[0])(action_feedback[1])


def _render_command_center(page: str) -> None:
    """Render the top-level status area."""

    with st.container(border=True):
        st.markdown('<div class="app-eyebrow">Schedule Optimization Workspace</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="app-hero"><h1>🏥 Fellowship Schedule Dashboard</h1></div>',
            unsafe_allow_html=True,
        )

        if page == "Master Schedule":
            _render_action_bar()


def _render_validation_center() -> None:
    """Render grouped notices and feasibility issues."""

    notice = get_notice()
    issues = get_issues()
    fatal_issues = [issue for issue in issues if _has_fatal_feasibility_issue([issue])]
    advisory_issues = [issue for issue in issues if issue not in fatal_issues]

    if not notice and not issues:
        return

    with st.container(border=True):
        st.subheader("🧭 Validation Center")
        top_left, top_middle, top_right = st.columns(3)
        top_left.metric("Blocking issues", len(fatal_issues))
        top_middle.metric("Advisories", len(advisory_issues))
        top_right.metric("Migration notices", 1 if notice else 0)

        if notice:
            st.info(notice)
            clear_notice()

        if fatal_issues:
            st.error("Blocking issues currently prevent schedule generation.")
            with st.expander("View blocking issues", expanded=True):
                for issue in fatal_issues:
                    st.markdown(f"- {issue}")

        if advisory_issues:
            st.warning("Advisories will not block solving, but they are worth reviewing.")
            with st.expander("View advisories", expanded=False):
                for issue in advisory_issues:
                    st.markdown(f"- {issue}")


def _render_overview() -> None:
    """Render the run-center overview page."""

    config = get_config()
    result = get_result()

    st.subheader("🏁 Overview")

    with st.container(border=True):
        st.markdown("#### Program Snapshot")
        stat_one, stat_two, stat_three, stat_four = st.columns(4)
        stat_one.metric("F1", config.cohort_counts[TrainingYear.F1])
        stat_two.metric("S2", config.cohort_counts[TrainingYear.S2])
        stat_three.metric("T3", config.cohort_counts[TrainingYear.T3])
        stat_four.metric("Weeks", config.num_weeks)

    readiness_col, solve_col = st.columns([1.1, 1.3])
    with readiness_col:
        with st.container(border=True):
            st.markdown("#### Workflow Map")
            st.markdown(
                "1. `Rules` for configuration and rule editing\n"
                "2. `Master Schedule` for generated output and checks\n"
                "3. `PTO & Fellows` for request satisfaction and person-level review"
            )
    with solve_col:
        with st.container(border=True):
            st.markdown("#### Latest Solve")
            if result is None:
                st.caption("No solver result yet.")
            else:
                metric_one, metric_two, metric_three = st.columns(3)
                metric_one.metric("Status", result.solver_status.value.upper())
                metric_two.metric("Objective", f"{result.objective_value:.0f}")
                metric_three.metric("Solve time", f"{result.solve_time_seconds:.1f}s")
                if result.objective_breakdown:
                    st.caption("Objective breakdown by category and cohort.")
                    st.dataframe(result.objective_breakdown, use_container_width=True, hide_index=True)


def _render_master_schedule_workspace() -> None:
    """Render the master schedule workspace with stronger controls hierarchy."""

    config = get_config()
    result = get_result()

    with st.container(border=True):
        st.subheader("📋 Master Schedule Workspace")
        st.caption(
            "Filter the visible cohort, switch into edit mode when needed, and review "
            "the generated schedule alongside derived operational checks."
        )
        filter_options = {
            "All Cohorts": None,
            TrainingYear.F1.value: TrainingYear.F1,
            TrainingYear.S2.value: TrainingYear.S2,
            TrainingYear.T3.value: TrainingYear.T3,
        }
        control_left, control_middle = st.columns([1.4, 1.0])
        selected_label = control_left.selectbox(
            "Visible cohort",
            options=list(filter_options.keys()),
            index=0,
            key="master_schedule_year_filter",
        )
        edit_mode = control_middle.toggle(
            "Edit displayed assignments",
            value=False,
            key="master_schedule_edit_mode",
        )
        st.caption(
            "Checks below always evaluate the full schedule, even when the master grid is filtered."
        )

    render_master_schedule(
        config,
        result,
        filter_options[selected_label],
        edit_mode=edit_mode,
    )

    with st.container(border=True):
        render_checks_panel(config, result)


def _render_pto_and_fellows_workspace() -> None:
    """Render the PTO and fellow-detail workspace."""

    config = get_config()
    result = get_result()

    left_col, right_col = st.columns([1.05, 1.95], gap="large")
    with left_col:
        with st.container(border=True):
            render_pto_calendar(config, result)
    with right_col:
        with st.container(border=True):
            render_fellow_cards(config, result)


_inject_design_system()

page = _render_sidebar_nav()
_render_command_center(page)
if page == "Rules":
    _render_validation_center()

if page == "Overview":
    _render_overview()
elif page == "Rules":
    render_rules_tab(get_config())
elif page == "Master Schedule":
    _render_master_schedule_workspace()
else:
    _render_pto_and_fellows_workspace()
