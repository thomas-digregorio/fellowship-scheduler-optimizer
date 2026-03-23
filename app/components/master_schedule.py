"""Master schedule grid with optional cohort filtering."""

from __future__ import annotations

import colorsys
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
    *,
    edit_mode: bool = False,
) -> None:
    """Render the schedule grid, optionally filtered to one cohort."""

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

    fellow_schedule_df = _build_schedule_dataframe(config, result, visible_fellows)
    label = "All cohorts" if training_year_filter is None else training_year_filter.value

    with st.container(border=True):
        st.markdown("#### Schedule Grid")
        caption_col, toggle_col = st.columns([3, 2])
        with caption_col:
            st.caption(
                f"Showing schedule for **{label}**. Use edit mode from the workspace "
                f"header to override assignments for the displayed fellows."
            )
        with toggle_col:
            grid_view = st.radio(
                "Schedule grid layout",
                options=("Fellows as columns", "Rotations as columns"),
                horizontal=True,
                key=(
                    "schedule_grid_layout_"
                    f"{training_year_filter.value if training_year_filter else 'all'}"
                ),
            )

        if grid_view == "Rotations as columns":
            rotation_schedule_df = _build_rotation_schedule_dataframe(
                config,
                result,
                visible_fellows,
            )
            _render_rotation_schedule_grid(config, rotation_schedule_df, visible_fellows)
        else:
            _render_colored_schedule_grid(config, fellow_schedule_df, visible_fellows)

    with st.container(border=True):
        st.subheader("📋 Master Schedule")
        _render_status_banner(result)
        _render_objective_breakdown(result)

    if edit_mode:
        with st.container(border=True):
            st.markdown("#### Edit Mode")
            _render_manual_edit_mode(
                config,
                result,
                fellow_schedule_df,
                visible_fellows,
            )

    with st.container(border=True):
        _render_rotation_counts(config, result, visible_fellows)

    with st.container(border=True):
        _render_call_overlay(config, result, visible_fellows)


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

    status_name = result.solver_status.value
    metric_left, metric_middle, metric_right = st.columns(3)
    metric_left.metric("Solver status", status_name.upper())
    metric_middle.metric("Solve time", f"{result.solve_time_seconds:.1f}s")
    metric_right.metric("Objective", f"{result.objective_value:.0f}")


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


def _build_rotation_schedule_dataframe(
    config: ScheduleConfig,
    result: ScheduleResult,
    visible_fellows: list[int],
) -> pd.DataFrame:
    """Build a week-by-rotation DataFrame with fellow names as cell values."""

    week_labels = []
    for week in range(config.num_weeks):
        week_date = config.start_date + timedelta(weeks=week)
        week_labels.append(f"W{week + 1} ({week_date.strftime('%m/%d')})")

    data: dict[str, list[str]] = {"Week": week_labels}
    for state_name in config.all_states:
        state_assignments: list[str] = []
        for week in range(config.num_weeks):
            names = [
                config.fellows[fellow_idx].name
                for fellow_idx in visible_fellows
                if result.assignments[fellow_idx][week] == state_name
            ]
            state_assignments.append(", ".join(names))
        data[state_name] = state_assignments
    return pd.DataFrame(data)


def _render_rotation_schedule_grid(
    config: ScheduleConfig,
    df: pd.DataFrame,
    visible_fellows: list[int],
) -> None:
    """Render the alternate grid with rotations as columns."""

    fellow_colors = _build_fellow_color_map(config, visible_fellows)
    state_columns = [column for column in df.columns if column != "Week"]
    styled_df = df.style.set_properties(
        subset=["Week"],
        **{
            "background-color": "#F7F9FB",
            "color": "#1F2933",
            "font-weight": "600",
        },
    )
    styled_df = styled_df.map(
        lambda value: _style_fellow_assignment_cell(value, fellow_colors),
        subset=state_columns,
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=min(800, 35 * len(df) + 40),
        column_config={
            "Week": st.column_config.TextColumn("Week", width="medium"),
            **{
                state_name: st.column_config.TextColumn(state_name, width="small")
                for state_name in state_columns
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

    st.caption(
        "Manual edits update the saved schedule directly. Constraint checks and "
        "soft-rule scoring are not recalculated after manual edits."
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

    st.markdown("#### Counts")
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


def _build_fellow_color_map(
    config: ScheduleConfig,
    visible_fellows: list[int],
) -> dict[str, str]:
    """Return a deterministic pastel color for each visible fellow."""

    return {
        config.fellows[fellow_idx].name: _fellow_color(fellow_idx)
        for fellow_idx in visible_fellows
    }


def _fellow_color(seed: int) -> str:
    """Generate a readable pastel color from a fellow index."""

    hue = (seed * 0.61803398875) % 1.0
    red, green, blue = colorsys.hls_to_rgb(hue, 0.82, 0.55)
    return "#{:02X}{:02X}{:02X}".format(
        int(red * 255),
        int(green * 255),
        int(blue * 255),
    )


def _style_fellow_assignment_cell(
    value: str,
    fellow_colors: dict[str, str],
) -> str:
    """Return CSS for rotation-view cells using fellow-based colors."""

    if not value:
        return (
            "background-color: #FFFFFF; "
            "color: #94A3B8; "
            "text-align: center;"
        )

    names = [name.strip() for name in value.split(",") if name.strip()]
    colors = [fellow_colors.get(name, "#E2E8F0") for name in names]
    text_color = "#102A43"
    background_style = (
        f"background-color: {colors[0]}; "
        if len(colors) == 1
        else f"background: {_build_color_gradient(colors)}; "
    )
    return (
        f"{background_style}"
        f"color: {text_color}; "
        "font-weight: 600; "
        "text-align: center; "
        "white-space: normal;"
    )


def _build_color_gradient(colors: list[str]) -> str:
    """Return a left-to-right gradient splitting the cell by fellow color."""

    stop_size = 100 / len(colors)
    stops: list[str] = []
    for index, color in enumerate(colors):
        start = index * stop_size
        end = (index + 1) * stop_size
        stops.append(f"{color} {start:.2f}%")
        stops.append(f"{color} {end:.2f}%")
    return f"linear-gradient(90deg, {', '.join(stops)})"


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
    """Show the 24-hour call schedule."""

    if config.structured_call_rules_enabled:
        _render_structured_call_calendar(config, result)
        return

    st.markdown("#### 24-Hr Call Assignments")
    if not any(
        result.call_assignments[fellow_idx][week]
        for fellow_idx in visible_fellows
        for week in range(config.num_weeks)
    ):
        st.caption("No displayed fellows are assigned 24-hr call in this schedule view.")
        return

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


def _render_structured_call_calendar(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> None:
    """Render a calendar-style overlay view for structured 24-hour call."""

    eligible_fellows = config.fellow_indices_for_years(config.call_eligible_years)
    st.markdown("#### 24-Hr Call Calendar")
    st.caption(
        "Weekend call is displayed separately from the rotation grid because it is an "
        "overlay assignment, not a standalone rotation block."
    )
    if not eligible_fellows:
        st.caption("No cohorts are currently eligible for 24-hour call.")
        return

    call_df = _build_call_calendar_dataframe(config, result, eligible_fellows)
    fellow_colors = _build_fellow_color_map(config, eligible_fellows)
    styled_df = call_df.style.set_properties(
        subset=["Week", "Weekend", "Assigned Rotation"],
        **{
            "background-color": "#F7F9FB",
            "color": "#1F2933",
            "font-weight": "600",
        },
    )
    for fellow_idx in eligible_fellows:
        fellow_name = config.fellows[fellow_idx].name
        styled_df = styled_df.map(
            lambda value, color=fellow_colors[fellow_name]: _style_call_calendar_cell(
                value,
                color,
            ),
            subset=[fellow_name],
        )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=min(800, 35 * len(call_df) + 40),
        column_config={
            "Week": st.column_config.TextColumn("Week", width="medium"),
            "Weekend": st.column_config.TextColumn("Weekend", width="medium"),
            "Assigned Rotation": st.column_config.TextColumn("Assigned Rotation", width="medium"),
            **{
                config.fellows[fellow_idx].name: st.column_config.TextColumn(
                    config.fellows[fellow_idx].name,
                    width="small",
                )
                for fellow_idx in eligible_fellows
            },
        },
    )


def _build_call_calendar_dataframe(
    config: ScheduleConfig,
    result: ScheduleResult,
    eligible_fellows: list[int],
) -> pd.DataFrame:
    """Return a week-by-week call calendar for the eligible fellows."""

    rows: list[dict[str, str]] = []
    for week in range(config.num_weeks):
        week_date = config.start_date + timedelta(weeks=week)
        call_date = _call_date_for_week(config, week)
        on_call_indices = [
            fellow_idx
            for fellow_idx in eligible_fellows
            if result.call_assignments[fellow_idx][week]
        ]
        assigned_rotation = (
            result.assignments[on_call_indices[0]][week] if on_call_indices else ""
        )
        row: dict[str, str] = {
            "Week": f"W{week + 1} ({week_date.strftime('%m/%d')})",
            "Weekend": call_date.strftime("%a %m/%d"),
            "Assigned Rotation": assigned_rotation,
        }
        for fellow_idx in eligible_fellows:
            row[config.fellows[fellow_idx].name] = (
                "CALL" if result.call_assignments[fellow_idx][week] else ""
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _style_call_calendar_cell(value: str, color: str) -> str:
    """Return CSS for one structured call-calendar cell."""

    if value != "CALL":
        return "background-color: #FFFFFF; color: #94A3B8; text-align: center;"
    text_color = "#FFFFFF" if _is_dark_color(color) else "#102A43"
    return (
        f"background-color: {color}; "
        f"color: {text_color}; "
        "font-weight: 700; "
        "text-align: center;"
    )


def _call_date_for_week(config: ScheduleConfig, week: int):
    """Return the calendar date for the configured call day in one schedule week."""

    offsets = {
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    return config.start_date + timedelta(weeks=week, days=offsets.get(config.call_day, 5))
