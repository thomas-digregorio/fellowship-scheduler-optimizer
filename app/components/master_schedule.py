"""Master schedule grid with optional cohort filtering."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from app.state import set_result
from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult, TrainingYear


def render_master_schedule(
    config: ScheduleConfig,
    result: ScheduleResult | None,
    training_year_filter: TrainingYear | None = None,
) -> None:
    """Render the schedule grid, optionally filtered to one cohort."""

    st.subheader("📋 Master Schedule")

    if result is None:
        st.info(
            "No schedule generated yet. Configure settings in the Rules tab and "
            "click **Generate Schedule**."
        )
        return

    visible_fellows = _visible_fellow_indices(config, training_year_filter)
    if not visible_fellows:
        st.warning("No fellows match the selected training-year filter.")
        return

    _render_status_banner(result)
    _render_objective_breakdown(result)
    df = _build_schedule_dataframe(config, result, visible_fellows)
    label = "All cohorts" if training_year_filter is None else training_year_filter.value
    st.caption(
        f"Showing schedule for **{label}**. Open edit mode below to override "
        f"assignments for the displayed fellows."
    )

    _render_colored_schedule_grid(config, df, visible_fellows)
    _render_manual_edit_mode(config, result, df, visible_fellows)
    _render_rotation_counts(config, result, visible_fellows)
    _render_call_overlay(config, result, visible_fellows)
    _render_legend()


def _visible_fellow_indices(
    config: ScheduleConfig,
    training_year_filter: TrainingYear | None,
) -> list[int]:
    """Return fellow indices visible under the active filter."""

    if training_year_filter is None:
        return list(range(config.num_fellows))
    return [
        index
        for index, fellow in enumerate(config.fellows)
        if fellow.training_year == training_year_filter
    ]


def _render_status_banner(result: ScheduleResult) -> None:
    """Show a colored banner with the solver status."""

    status_colors = {
        "optimal": "success",
        "feasible": "warning",
        "infeasible": "error",
        "timeout": "warning",
        "error": "error",
    }
    status_name = result.solver_status.value
    message = (
        f"**Solver status:** {status_name.upper()} | "
        f"**Solve time:** {result.solve_time_seconds:.1f}s | "
        f"**Objective:** {result.objective_value:.0f}"
    )
    getattr(st, status_colors.get(status_name, "info"))(message)


def _render_objective_breakdown(result: ScheduleResult) -> None:
    """Show objective points by category and cohort under the status banner."""

    if not result.objective_breakdown:
        return

    breakdown_df = pd.DataFrame(result.objective_breakdown)
    ordered_columns = ["Category", "F1", "S2", "T3", "Total"]
    available_columns = [
        column for column in ordered_columns if column in breakdown_df.columns
    ]
    breakdown_df = breakdown_df[available_columns]

    st.caption("Objective breakdown from the last solver run, by category and cohort.")
    st.dataframe(
        breakdown_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Category": st.column_config.TextColumn("Category", width="large"),
            "F1": st.column_config.NumberColumn("F1", format="%d"),
            "S2": st.column_config.NumberColumn("S2", format="%d"),
            "T3": st.column_config.NumberColumn("T3", format="%d"),
            "Total": st.column_config.NumberColumn("Total", format="%d"),
        },
    )


def _build_schedule_dataframe(
    config: ScheduleConfig,
    result: ScheduleResult,
    visible_fellows: list[int],
) -> pd.DataFrame:
    """Build a DataFrame from the visible subset of the schedule."""

    week_labels = []
    for week in range(config.num_weeks):
        week_date = config.start_date + timedelta(weeks=week)
        week_labels.append(f"W{week + 1} ({week_date.strftime('%m/%d')})")

    data: dict[str, list[str]] = {"Week": week_labels}
    for fellow_idx in visible_fellows:
        fellow = config.fellows[fellow_idx]
        data[fellow.name] = list(result.assignments[fellow_idx])
    return pd.DataFrame(data)


def _render_colored_schedule_grid(
    config: ScheduleConfig,
    df: pd.DataFrame,
    visible_fellows: list[int],
) -> None:
    """Render the main schedule grid."""

    fellow_columns = [config.fellows[fellow_idx].name for fellow_idx in visible_fellows]
    styled_df = df.style.set_properties(
        subset=["Week"],
        **{
            "background-color": "#F7F9FB",
            "color": "#1F2933",
            "font-weight": "600",
        },
    )
    styled_df = styled_df.map(_style_block_cell, subset=fellow_columns)

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=min(800, 35 * len(df) + 40),
        column_config={
            "Week": st.column_config.TextColumn("Week", width="medium"),
            **{
                config.fellows[fellow_idx].name: st.column_config.TextColumn(
                    config.fellows[fellow_idx].name,
                    width="small",
                )
                for fellow_idx in visible_fellows
            },
        },
    )


def _render_manual_edit_mode(
    config: ScheduleConfig,
    result: ScheduleResult,
    df: pd.DataFrame,
    visible_fellows: list[int],
) -> None:
    """Render manual edit controls for the visible fellows."""

    with st.expander("✏️ Edit Displayed Assignments", expanded=False):
        st.caption(
            "Manual edits update the saved schedule directly. Constraint checks "
            "and soft-rule scoring are not recalculated after manual edits."
        )

        column_config: dict[str, st.column_config.Column] = {
            "Week": st.column_config.TextColumn(
                "Week",
                disabled=True,
                width="medium",
            ),
        }
        for fellow_idx in visible_fellows:
            fellow_name = config.fellows[fellow_idx].name
            column_config[fellow_name] = st.column_config.SelectboxColumn(
                fellow_name,
                options=config.all_states,
                width="small",
                required=True,
            )

        edited_df = st.data_editor(
            df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            height=min(800, 35 * len(df) + 40),
            num_rows="fixed",
            key=f"schedule_grid_editor_{'_'.join(str(idx) for idx in visible_fellows)}",
        )

        if not df.equals(edited_df):
            _apply_manual_edits(config, result, edited_df, visible_fellows)
            st.rerun()


def _apply_manual_edits(
    config: ScheduleConfig,
    result: ScheduleResult,
    edited_df: pd.DataFrame,
    visible_fellows: list[int],
) -> None:
    """Apply edited values back to the stored result."""

    for fellow_idx in visible_fellows:
        fellow_name = config.fellows[fellow_idx].name
        for week in range(config.num_weeks):
            new_value = edited_df.at[week, fellow_name]
            if new_value != result.assignments[fellow_idx][week]:
                result.assignments[fellow_idx][week] = new_value
    set_result(result)


def _build_rotation_counts_dataframe(
    config: ScheduleConfig,
    schedule_df: pd.DataFrame,
    visible_fellows: list[int],
) -> pd.DataFrame:
    """Return a per-rotation count table for the visible fellows."""

    rows: list[dict[str, int | str]] = []
    for block_name in config.block_names:
        row: dict[str, int | str] = {"Rotation": block_name}
        for fellow_idx in visible_fellows:
            fellow_name = config.fellows[fellow_idx].name
            row[fellow_name] = int((schedule_df[fellow_name] == block_name).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def _render_rotation_counts(
    config: ScheduleConfig,
    result: ScheduleResult,
    visible_fellows: list[int],
) -> None:
    """Render a standalone rotation-count summary for the visible fellows."""

    st.markdown("**Counts**")
    st.caption("Counts for the currently displayed schedule, by rotation and fellow.")
    st.dataframe(
        _build_rotation_counts_dataframe(
            config,
            _build_schedule_dataframe(config, result, visible_fellows),
            visible_fellows,
        ),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rotation": st.column_config.TextColumn("Rotation", width="large"),
            **{
                config.fellows[fellow_idx].name: st.column_config.NumberColumn(
                    config.fellows[fellow_idx].name,
                    format="%d",
                )
                for fellow_idx in visible_fellows
            },
        },
    )


def _style_block_cell(value: str) -> str:
    """Return CSS matching the block legend."""

    color = BLOCK_COLORS.get(value, "#FFFFFF")
    text_color = "#FFFFFF" if _is_dark_color(color) else "#1F2933"
    return (
        f"background-color: {color}; "
        f"color: {text_color}; "
        "font-weight: 600; "
        "text-align: center;"
    )


def _is_dark_color(hex_color: str) -> bool:
    """Return True when the color needs light foreground text."""

    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return False
    red = int(hex_color[0:2], 16)
    green = int(hex_color[2:4], 16)
    blue = int(hex_color[4:6], 16)
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    return brightness < 145


def _render_call_overlay(
    config: ScheduleConfig,
    result: ScheduleResult,
    visible_fellows: list[int],
) -> None:
    """Show call assignments for the displayed fellows."""

    if not any(
        result.call_assignments[fellow_idx][week]
        for fellow_idx in visible_fellows
        for week in range(config.num_weeks)
    ):
        return

    st.markdown("---")
    st.markdown("**📞 24-Hr Call Assignments (Displayed Cohort)**")

    call_rows: list[dict[str, str]] = []
    for week in range(config.num_weeks):
        on_call = [
            config.fellows[fellow_idx].name
            for fellow_idx in visible_fellows
            if result.call_assignments[fellow_idx][week]
        ]
        if not on_call:
            continue
        week_date = config.start_date + timedelta(weeks=week)
        fellow_idx = next(
            idx for idx in visible_fellows if result.call_assignments[idx][week]
        )
        call_rows.append(
            {
                "Week": f"W{week + 1} ({week_date.strftime('%m/%d')})",
                "On Call": ", ".join(on_call),
                "Block": result.assignments[fellow_idx][week],
            }
        )

    if call_rows:
        st.dataframe(
            pd.DataFrame(call_rows),
            use_container_width=True,
            height=220,
            hide_index=True,
        )


def _render_legend() -> None:
    """Show a color legend for block names."""

    st.markdown("---")
    st.markdown("**🎨 Block Legend**")
    columns = st.columns(5)
    for index, (name, color) in enumerate(BLOCK_COLORS.items()):
        column = columns[index % 5]
        column.markdown(
            f'<span style="background-color:{color}; color:white; '
            f'padding:2px 8px; border-radius:4px; font-size:0.8em;">'
            f"{name}</span>",
            unsafe_allow_html=True,
        )
