"""Right panel: schedule-derived checks.

These checks summarize patterns in the generated schedule itself rather
than re-evaluating the configured solver rules. They are intended to
give a quick operational read on the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import streamlit as st

from src.models import ScheduleConfig, ScheduleResult


@dataclass(frozen=True)
class ScheduleCheck:
    """One schedule-derived check to show in the UI."""

    label: str
    value: int
    status: str
    detail: str


def render_checks_panel(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render the right-side schedule checks panel."""
    st.subheader("✅ Checks")

    if result is None:
        st.info("Generate a schedule to see derived checks.")
        return

    checks = build_schedule_checks(config, result)

    top_left, top_right, bottom_left, bottom_right = st.columns(4)
    top_left.metric("Call -> next NF", checks["call_before_night_float"].value)
    top_right.metric("CCU weeks > 2", checks["weeks_with_gt_two_ccu"].value)
    bottom_left.metric("Max CCU / week", checks["max_ccu_per_week"].value)
    bottom_right.metric("Call spread", checks["call_spread"].value)

    detail_left, detail_right = st.columns(2, gap="large")
    with detail_left:
        with st.container(border=True):
            st.markdown("#### Coverage & Call")
            _render_check_message(checks["call_before_night_float"])
            _render_check_message(checks["weeks_with_gt_two_ccu"])
            st.caption(checks["weeks_without_exactly_one_call"].detail)
    with detail_right:
        with st.container(border=True):
            st.markdown("#### PTO & Night Float")
            st.info(checks["max_concurrent_pto"].detail)
            st.info(checks["max_night_float_streak"].detail)
            st.info(checks["call_spread"].detail)


def build_schedule_checks(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> dict[str, ScheduleCheck]:
    """Return schedule-derived checks for the generated output."""
    night_float_conflicts: list[str] = []
    for f_idx, fellow in enumerate(config.fellows):
        for week in range(config.num_weeks - 1):
            if (
                result.call_assignments[f_idx][week]
                and result.assignments[f_idx][week + 1] == "Night Float"
            ):
                night_float_conflicts.append(
                    f"{fellow.name}: "
                    f"{_week_label(config, week)} -> {_week_label(config, week + 1)}"
                )

    ccu_counts: list[int] = []
    weeks_with_gt_two_ccu: list[int] = []
    for week in range(config.num_weeks):
        ccu_count = sum(
            1
            for f_idx in range(config.num_fellows)
            if result.assignments[f_idx][week] == "CCU"
        )
        ccu_counts.append(ccu_count)
        if ccu_count > 2:
            weeks_with_gt_two_ccu.append(week)

    call_counts_by_week: list[int] = [
        sum(
            1
            for f_idx in range(config.num_fellows)
            if result.call_assignments[f_idx][week]
        )
        for week in range(config.num_weeks)
    ]
    weeks_without_exactly_one_call: list[int] = [
        week
        for week, count in enumerate(call_counts_by_week)
        if count != 1
    ]

    pto_counts_by_week: list[int] = [
        sum(
            1
            for f_idx in range(config.num_fellows)
            if result.assignments[f_idx][week] == "PTO"
        )
        for week in range(config.num_weeks)
    ]

    counted_fellow_indices = (
        config.fellow_indices_for_years(config.call_eligible_years)
        if config.structured_call_rules_enabled
        else list(range(config.num_fellows))
    )
    call_counts_by_fellow: list[int] = [
        sum(calls)
        for fellow_idx, calls in enumerate(result.call_assignments)
        if fellow_idx in counted_fellow_indices
    ]

    return {
        "call_before_night_float": ScheduleCheck(
            label="24-hr call followed by next-week Night Float",
            value=len(night_float_conflicts),
            status="pass" if not night_float_conflicts else "error",
            detail=_detail_with_examples(
                len(night_float_conflicts),
                "No call to next-week Night Float conflicts found.",
                "Conflicts",
                night_float_conflicts,
            ),
        ),
        "weeks_with_gt_two_ccu": ScheduleCheck(
            label="Weeks with more than 2 fellows on CCU",
            value=len(weeks_with_gt_two_ccu),
            status="pass" if not weeks_with_gt_two_ccu else "error",
            detail=_detail_with_examples(
                len(weeks_with_gt_two_ccu),
                f"CCU never exceeds 2 fellows in a week. Max observed: {max(ccu_counts, default=0)}.",
                "Weeks",
                [_week_label(config, week) for week in weeks_with_gt_two_ccu],
            ),
        ),
        "max_ccu_per_week": ScheduleCheck(
            label="Maximum fellows on CCU in any week",
            value=max(ccu_counts, default=0),
            status="info",
            detail=(
                f"Peak CCU staffing in the created schedule: "
                f"{max(ccu_counts, default=0)} fellows."
            ),
        ),
        "weeks_without_exactly_one_call": ScheduleCheck(
            label="Weeks without exactly one 24-hr call assignment",
            value=len(weeks_without_exactly_one_call),
            status="pass" if not weeks_without_exactly_one_call else "warning",
            detail=_detail_with_examples(
                len(weeks_without_exactly_one_call),
                "Every week has exactly one 24-hr call assignment.",
                "Weeks",
                [_week_label(config, week) for week in weeks_without_exactly_one_call],
            ),
        ),
        "call_spread": ScheduleCheck(
            label="Difference between the most and fewest call assignments",
            value=(
                max(call_counts_by_fellow, default=0)
                - min(call_counts_by_fellow, default=0)
            ),
            status="info",
            detail=(
                f"Call counts by fellow range from "
                f"{min(call_counts_by_fellow, default=0)} to "
                f"{max(call_counts_by_fellow, default=0)}."
            ),
        ),
        "max_concurrent_pto": ScheduleCheck(
            label="Maximum concurrent PTO in any week",
            value=max(pto_counts_by_week, default=0),
            status="info",
            detail=(
                f"Peak concurrent PTO in the created schedule: "
                f"{max(pto_counts_by_week, default=0)} fellows."
            ),
        ),
        "max_night_float_streak": ScheduleCheck(
            label="Longest Night Float streak for any fellow",
            value=_max_night_float_streak(result),
            status="info",
            detail=(
                f"Longest run of consecutive Night Float weeks in the created "
                f"schedule: {_max_night_float_streak(result)}."
            ),
        ),
    }


def _render_check_message(check: ScheduleCheck) -> None:
    """Render one highlighted pass/fail check."""
    message = f"**{check.label}:** {check.value}"
    if check.status == "pass":
        st.success(message)
    elif check.status == "error":
        st.error(message)
    elif check.status == "warning":
        st.warning(message)
    else:
        st.info(message)

    st.caption(check.detail)


def _detail_with_examples(
    count: int,
    empty_message: str,
    prefix: str,
    examples: list[str],
    max_examples: int = 3,
) -> str:
    """Format a compact detail string for a check."""
    if count == 0:
        return empty_message

    shown = ", ".join(examples[:max_examples])
    if count > max_examples:
        shown += f", +{count - max_examples} more"
    return f"{prefix}: {shown}"


def _max_night_float_streak(result: ScheduleResult) -> int:
    """Return the longest consecutive Night Float streak in the schedule."""
    max_streak = 0
    for assignments in result.assignments:
        streak = 0
        for assignment in assignments:
            if assignment == "Night Float":
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
    return max_streak


def _week_label(config: ScheduleConfig, week: int) -> str:
    """Return a user-friendly week label."""
    week_date = config.start_date + timedelta(weeks=week)
    return f"W{week + 1} ({week_date.strftime('%m/%d')})"
