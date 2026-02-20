"""Center panel: Master Schedule Grid.

Displays the full 52-week × 9-fellow schedule as an editable grid.
Users can click cells to change block assignments (overriding the
solver). Constraint violations are flagged with visual indicators.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult
from state import get_result, set_result


def render_master_schedule(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render the master schedule grid in the center panel.

    Parameters
    ----------
    config : ScheduleConfig
        Current configuration (for block names, fellow names, dates).
    result : ScheduleResult or None
        Solver output. If None, shows an empty placeholder.
    """
    st.subheader("📋 Master Schedule")

    if result is None:
        st.info(
            "No schedule generated yet. Configure settings in the "
            "sidebar and click **Generate Schedule**."
        )
        return

    # Show solver status banner
    _render_status_banner(result)

    # Build the schedule DataFrame
    df = _build_schedule_dataframe(config, result)

    # Render editable grid using st.data_editor
    # Each cell is a dropdown with all possible block assignments
    all_states: list[str] = config.all_states

    # Configure columns so each fellow column has a selectbox
    column_config: dict[str, st.column_config.Column] = {
        "Week": st.column_config.TextColumn("Week", disabled=True, width=80),
    }
    for fellow in config.fellows:
        column_config[fellow.name] = st.column_config.SelectboxColumn(
            fellow.name,
            options=all_states,
            width=90,
            required=True,
        )

    # Show the editable grid
    edited_df = st.data_editor(
        df,
        column_config=column_config,
        use_container_width=True,
        height=min(800, 35 * len(df) + 40),  # dynamic height
        num_rows="fixed",
        key="schedule_grid",
    )

    # Check if user made manual edits
    if not df.equals(edited_df):
        _apply_manual_edits(config, result, edited_df)
        st.rerun()

    # Render the call schedule overlay below the grid
    _render_call_overlay(config, result)

    # Color legend
    _render_legend()


def _render_status_banner(result: ScheduleResult) -> None:
    """Show a colored banner with the solver status."""
    status_colors: dict[str, str] = {
        "optimal": "success",
        "feasible": "warning",
        "infeasible": "error",
        "timeout": "warning",
        "error": "error",
    }
    status_name: str = result.solver_status.value
    msg = (
        f"**Solver status:** {status_name.upper()} | "
        f"**Solve time:** {result.solve_time_seconds:.1f}s | "
        f"**PTO score:** {result.objective_value:.0f}"
    )

    banner_func = getattr(st, status_colors.get(status_name, "info"))
    banner_func(msg)


def _build_schedule_dataframe(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> pd.DataFrame:
    """Build a DataFrame from the schedule result for display.

    Rows = weeks (W1, W2, ...), columns = fellow names.
    """
    fellow_names: list[str] = [f.name for f in config.fellows]

    # Week labels with dates
    week_labels: list[str] = []
    for w in range(config.num_weeks):
        week_date = config.start_date + timedelta(weeks=w)
        week_labels.append(f"W{w + 1} ({week_date.strftime('%m/%d')})")

    data: dict[str, list[str]] = {"Week": week_labels}
    for f_idx, fname in enumerate(fellow_names):
        data[fname] = list(result.assignments[f_idx])

    return pd.DataFrame(data)


def _apply_manual_edits(
    config: ScheduleConfig,
    result: ScheduleResult,
    edited_df: pd.DataFrame,
) -> None:
    """Apply user's manual edits from the data editor back to the result.

    This is called when the user changes a cell in the editable grid.
    The new assignment is saved to the result.
    """
    fellow_names: list[str] = [f.name for f in config.fellows]

    for f_idx, fname in enumerate(fellow_names):
        for w in range(config.num_weeks):
            new_val: str = edited_df.at[w, fname]
            if new_val != result.assignments[f_idx][w]:
                result.assignments[f_idx][w] = new_val

    # Persist the edited result
    set_result(result)


def _render_call_overlay(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> None:
    """Show 24-hr call assignments as a compact table below the grid."""
    if not any(
        any(row) for row in result.call_assignments
    ):
        return  # no call assignments

    st.markdown("---")
    st.markdown("**📞 24-Hr Call Assignments**")

    # Build a compact string per week showing who is on call
    call_data: list[dict[str, str]] = []
    for w in range(config.num_weeks):
        on_call: list[str] = []
        for f_idx, fellow in enumerate(config.fellows):
            if result.call_assignments[f_idx][w]:
                on_call.append(fellow.name)

        if on_call:
            week_date = config.start_date + timedelta(weeks=w)
            call_data.append({
                "Week": f"W{w + 1} ({week_date.strftime('%m/%d')})",
                "On Call": ", ".join(on_call),
                "Block": result.assignments[
                    next(
                        f for f in range(config.num_fellows)
                        if result.call_assignments[f][w]
                    )
                ][w] if on_call else "",
            })

    if call_data:
        st.dataframe(
            pd.DataFrame(call_data),
            use_container_width=True,
            height=200,
        )


def _render_legend() -> None:
    """Show a color legend for block names."""
    st.markdown("---")
    st.markdown("**🎨 Block Legend**")

    # Display as colored badges in a horizontal layout
    cols = st.columns(5)
    for i, (name, color) in enumerate(BLOCK_COLORS.items()):
        col = cols[i % 5]
        col.markdown(
            f'<span style="background-color:{color}; color:white; '
            f'padding:2px 8px; border-radius:4px; font-size:0.8em;">'
            f'{name}</span>',
            unsafe_allow_html=True,
        )
