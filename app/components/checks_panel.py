"""Right panel: schedule-derived checks.

These checks summarize patterns in the generated schedule itself rather
than re-evaluating the configured solver rules. They are intended to
give a quick operational read on the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import streamlit as st

from src.models import ScheduleConfig, ScheduleResult, TrainingYear


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

    audit_left, audit_middle, audit_right = st.columns(3)
    audit_left.metric("24-hr hard issues", checks["call_rule_hard_violations"].value)
    audit_middle.metric("SRC/VA hard issues", checks["srcva_rule_hard_violations"].value)
    audit_right.metric("Call soft exceptions", checks["call_rule_soft_exceptions"].value)

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

    with st.container(border=True):
        st.markdown("#### Call Rule Audit")
        _render_check_message(checks["call_rule_hard_violations"])
        _render_check_message(checks["srcva_rule_hard_violations"])
        _render_check_message(checks["call_rule_soft_exceptions"])


def build_schedule_checks(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> dict[str, ScheduleCheck]:
    """Return schedule-derived checks for the generated output."""
    call_rule_hard_violations, srcva_rule_hard_violations, call_rule_soft_exceptions = (
        _build_call_rule_audit(config, result)
    )
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
        "call_rule_hard_violations": ScheduleCheck(
            label="24-hr call hard-rule violations",
            value=len(call_rule_hard_violations),
            status="pass" if not call_rule_hard_violations else "error",
            detail=_detail_with_examples(
                len(call_rule_hard_violations),
                "No 24-hr hard-rule violations found in the saved schedule.",
                "Violations",
                call_rule_hard_violations,
                max_examples=4,
            ),
        ),
        "srcva_rule_hard_violations": ScheduleCheck(
            label="SRC/VA call hard-rule violations",
            value=len(srcva_rule_hard_violations),
            status="pass" if not srcva_rule_hard_violations else "error",
            detail=_detail_with_examples(
                len(srcva_rule_hard_violations),
                "No SRC/VA hard-rule violations found in the saved schedule.",
                "Violations",
                srcva_rule_hard_violations,
                max_examples=4,
            ),
        ),
        "call_rule_soft_exceptions": ScheduleCheck(
            label="Call soft-rule exceptions",
            value=len(call_rule_soft_exceptions),
            status="pass" if not call_rule_soft_exceptions else "warning",
            detail=_detail_with_examples(
                len(call_rule_soft_exceptions),
                "No soft call-rule exceptions found in the saved schedule.",
                "Exceptions",
                call_rule_soft_exceptions,
                max_examples=4,
            ),
        ),
    }


def _build_call_rule_audit(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> tuple[list[str], list[str], list[str]]:
    """Return hard and soft call-rule exceptions for the current schedule."""

    weekend_call = _normalized_weekend_calls(config, result)
    weekday_call = _normalized_weekday_calls(config, result)

    hard_24hr_issues: list[str] = []
    hard_srcva_issues: list[str] = []
    soft_issues: list[str] = []

    for week in range(config.num_weeks):
        if (
            config.structured_call_rules_enabled
            and sum(result.call_assignments[f_idx][week] for f_idx in range(config.num_fellows)) != 1
        ):
            hard_24hr_issues.append(
                f"{_week_label(config, week)} has "
                f"{sum(result.call_assignments[f_idx][week] for f_idx in range(config.num_fellows))} "
                "24-hr assignments."
            )
        if (
            config.srcva_weekend_call_enabled
            and sum(weekend_call[f_idx][week] for f_idx in range(config.num_fellows)) != 1
        ):
            hard_srcva_issues.append(
                f"{_week_label(config, week)} has "
                f"{sum(weekend_call[f_idx][week] for f_idx in range(config.num_fellows))} "
                "SRC/VA weekend assignments."
            )
        for day_idx in range(4):
            if (
                config.srcva_weekday_call_enabled
                and sum(weekday_call[f_idx][week][day_idx] for f_idx in range(config.num_fellows)) != 1
            ):
                hard_srcva_issues.append(
                    f"{_week_label(config, week)} day {day_idx + 1} has "
                    f"{sum(weekday_call[f_idx][week][day_idx] for f_idx in range(config.num_fellows))} "
                    "SRC/VA weekday assignments."
                )

    for fellow_idx, fellow in enumerate(config.fellows):
        total_calls = sum(result.call_assignments[fellow_idx])
        total_weekend_calls = sum(weekend_call[fellow_idx])
        total_weekday_calls = sum(
            sum(days) for days in weekday_call[fellow_idx]
        )

        if config.structured_call_rules_enabled and fellow.training_year == TrainingYear.F1:
            if not config.call_min_per_fellow <= total_calls <= config.call_max_per_fellow:
                hard_24hr_issues.append(
                    f"{fellow.name} has {total_calls} 24-hr calls "
                    f"(expected {config.call_min_per_fellow}-{config.call_max_per_fellow})."
                )
        elif config.structured_call_rules_enabled and total_calls != 0:
            hard_24hr_issues.append(
                f"{fellow.name} is {fellow.training_year.value} and has {total_calls} 24-hr calls."
            )

        if fellow.training_year == TrainingYear.F1:
            if (
                config.srcva_weekend_call_enabled
                and not config.srcva_weekend_call_f1_min <= total_weekend_calls <= config.srcva_weekend_call_f1_max
            ):
                hard_srcva_issues.append(
                    f"{fellow.name} has {total_weekend_calls} weekend SRC/VA calls "
                    f"(expected {config.srcva_weekend_call_f1_min}-{config.srcva_weekend_call_f1_max})."
                )
            if (
                config.srcva_weekday_call_enabled
                and not config.srcva_weekday_call_f1_min <= total_weekday_calls <= config.srcva_weekday_call_f1_max
            ):
                hard_srcva_issues.append(
                    f"{fellow.name} has {total_weekday_calls} weekday SRC/VA calls "
                    f"(expected {config.srcva_weekday_call_f1_min}-{config.srcva_weekday_call_f1_max})."
                )
            if config.srcva_weekend_call_enabled and config.structured_call_rules_enabled:
                total_combined_calls = total_calls + total_weekend_calls
                if not config.srcva_total_call_f1_min <= total_combined_calls <= config.srcva_total_call_f1_max:
                    hard_srcva_issues.append(
                        f"{fellow.name} has {total_combined_calls} combined 24-hr + weekend SRC/VA calls "
                        f"(expected {config.srcva_total_call_f1_min}-{config.srcva_total_call_f1_max})."
                    )
        elif fellow.training_year == TrainingYear.S2:
            if (
                config.srcva_weekend_call_enabled
                and not config.srcva_weekend_call_s2_min <= total_weekend_calls <= config.srcva_weekend_call_s2_max
            ):
                hard_srcva_issues.append(
                    f"{fellow.name} has {total_weekend_calls} weekend SRC/VA calls "
                    f"(expected {config.srcva_weekend_call_s2_min}-{config.srcva_weekend_call_s2_max})."
                )
            if (
                config.srcva_weekday_call_enabled
                and not config.srcva_weekday_call_s2_min <= total_weekday_calls <= config.srcva_weekday_call_s2_max
            ):
                hard_srcva_issues.append(
                    f"{fellow.name} has {total_weekday_calls} weekday SRC/VA calls "
                    f"(expected {config.srcva_weekday_call_s2_min}-{config.srcva_weekday_call_s2_max})."
                )
        elif total_weekend_calls or total_weekday_calls:
            hard_srcva_issues.append(
                f"{fellow.name} is {fellow.training_year.value} and has "
                f"{total_weekend_calls} weekend / {total_weekday_calls} weekday SRC/VA calls."
            )

        for week in range(config.num_weeks):
            if config.structured_call_rules_enabled and result.call_assignments[fellow_idx][week]:
                current_block = result.assignments[fellow_idx][week]
                if current_block in config.call_excluded_blocks:
                    hard_24hr_issues.append(
                        f"{fellow.name} has 24-hr call on excluded block {current_block} in {_week_label(config, week)}."
                    )
                if current_block not in config.call_allowed_block_names:
                    hard_24hr_issues.append(
                        f"{fellow.name} has 24-hr call on non-eligible block {current_block} in {_week_label(config, week)}."
                    )
                if week < config.num_weeks - 1:
                    next_block = result.assignments[fellow_idx][week + 1]
                    if next_block in config.call_forbidden_following_blocks:
                        hard_24hr_issues.append(
                            f"{fellow.name} has 24-hr call in {_week_label(config, week)} before next-week {next_block}."
                        )
                    if (
                        config.call_soft_forbidden_next_week_weight != 0
                        and next_block in config.call_soft_forbidden_next_week_blocks
                    ):
                        soft_issues.append(
                            f"{fellow.name} has 24-hr call in {_week_label(config, week)} before next-week {next_block}."
                        )
                if (
                    config.call_soft_disfavored_current_weight != 0
                    and current_block in config.call_soft_disfavored_current_blocks
                ):
                    soft_issues.append(
                        f"{fellow.name} has 24-hr call on {current_block} in {_week_label(config, week)}."
                    )

            if config.srcva_weekend_call_enabled and weekend_call[fellow_idx][week]:
                current_block = result.assignments[fellow_idx][week]
                if current_block not in config.srcva_weekend_call_allowed_block_names:
                    hard_srcva_issues.append(
                        f"{fellow.name} has weekend SRC/VA call on non-eligible block {current_block} in {_week_label(config, week)}."
                    )
                if (
                    fellow.training_year == TrainingYear.F1
                    and config.srcva_weekend_call_f1_start_week is not None
                    and week < config.srcva_weekend_call_f1_start_week
                ):
                    hard_srcva_issues.append(
                        f"{fellow.name} has F1 weekend SRC/VA before the January start in {_week_label(config, week)}."
                    )
                if config.structured_call_rules_enabled and result.call_assignments[fellow_idx][week]:
                    hard_srcva_issues.append(
                        f"{fellow.name} has weekend SRC/VA and 24-hr call in {_week_label(config, week)}."
                    )
                if week < config.num_weeks - 1:
                    next_block = result.assignments[fellow_idx][week + 1]
                    if (
                        config.srcva_weekend_soft_forbidden_next_week_weight != 0
                        and next_block in config.srcva_weekend_soft_forbidden_next_week_blocks
                    ):
                        soft_issues.append(
                            f"{fellow.name} has weekend SRC/VA in {_week_label(config, week)} before next-week {next_block}."
                        )

            if (
                config.srcva_weekday_call_enabled
                and fellow.training_year == TrainingYear.F1
                and config.srcva_weekday_call_f1_start_week is not None
            ):
                if week < config.srcva_weekday_call_f1_start_week and any(weekday_call[fellow_idx][week]):
                    hard_srcva_issues.append(
                        f"{fellow.name} has F1 weekday SRC/VA before the January start in {_week_label(config, week)}."
                    )

            for day_idx in range(4):
                if config.srcva_weekday_call_enabled and weekday_call[fellow_idx][week][day_idx]:
                    current_block = result.assignments[fellow_idx][week]
                    if current_block not in config.srcva_weekday_call_allowed_block_names:
                        hard_srcva_issues.append(
                            f"{fellow.name} has weekday SRC/VA on non-eligible block {current_block} in {_week_label(config, week)}."
                        )

            for day_idx in range(3):
                if (
                    config.srcva_weekday_call_enabled
                    and weekday_call[fellow_idx][week][day_idx]
                    and weekday_call[fellow_idx][week][day_idx + 1]
                ):
                    hard_srcva_issues.append(
                        f"{fellow.name} has consecutive weekday SRC/VA calls in {_week_label(config, week)}."
                    )

            weekday_calls_this_week = sum(weekday_call[fellow_idx][week])
            if (
                config.srcva_weekday_call_enabled
                and
                config.srcva_weekday_max_one_per_week_weight != 0
                and weekday_calls_this_week + weekend_call[fellow_idx][week] > 1
            ):
                soft_issues.append(
                    f"{fellow.name} has {weekday_calls_this_week} weekday and "
                    f"{1 if weekend_call[fellow_idx][week] else 0} weekend SRC/VA calls in {_week_label(config, week)}."
                )
            if (
                config.srcva_weekday_call_enabled
                and config.structured_call_rules_enabled
                and
                config.srcva_weekday_same_week_as_24hr_weight != 0
                and weekday_calls_this_week
                and result.call_assignments[fellow_idx][week]
            ):
                soft_issues.append(
                    f"{fellow.name} has weekday SRC/VA and 24-hr call in {_week_label(config, week)}."
                )

        for week in range(config.num_weeks - 1):
            if (
                config.structured_call_rules_enabled
                and result.call_assignments[fellow_idx][week]
                and result.call_assignments[fellow_idx][week + 1]
            ):
                hard_24hr_issues.append(
                    f"{fellow.name} has consecutive 24-hr calls in {_week_label(config, week)} and {_week_label(config, week + 1)}."
                )
            if (
                config.structured_call_rules_enabled
                and config.srcva_weekend_call_enabled
                and config.srcva_weekend_exclude_adjacent_24hr_weeks
            ):
                if weekend_call[fellow_idx][week] and result.call_assignments[fellow_idx][week + 1]:
                    hard_srcva_issues.append(
                        f"{fellow.name} has weekend SRC/VA in {_week_label(config, week)} immediately before 24-hr call in {_week_label(config, week + 1)}."
                    )
                if result.call_assignments[fellow_idx][week] and weekend_call[fellow_idx][week + 1]:
                    hard_srcva_issues.append(
                        f"{fellow.name} has 24-hr call in {_week_label(config, week)} immediately before weekend SRC/VA in {_week_label(config, week + 1)}."
                    )

        if (
            config.structured_call_rules_enabled
            and
            config.call_max_calls_in_window_weeks > 0
            and config.call_max_calls_in_window_count > 0
            and config.num_weeks >= config.call_max_calls_in_window_weeks
        ):
            window = config.call_max_calls_in_window_weeks
            max_calls = config.call_max_calls_in_window_count
            for start_week in range(config.num_weeks - window + 1):
                total_window_calls = sum(
                    result.call_assignments[fellow_idx][week]
                    for week in range(start_week, start_week + window)
                )
                if total_window_calls > max_calls:
                    hard_24hr_issues.append(
                        f"{fellow.name} has {total_window_calls} 24-hr calls in "
                        f"{_week_label(config, start_week)}-{_week_label(config, start_week + window - 1)}."
                    )

        if (
            config.structured_call_rules_enabled
            and config.srcva_weekend_call_enabled
            and
            config.srcva_combined_call_window_weeks > 0
            and config.srcva_combined_call_window_max > 0
            and config.num_weeks >= config.srcva_combined_call_window_weeks
        ):
            window = config.srcva_combined_call_window_weeks
            max_calls = config.srcva_combined_call_window_max
            for start_week in range(config.num_weeks - window + 1):
                total_window_calls = sum(
                    result.call_assignments[fellow_idx][week] + weekend_call[fellow_idx][week]
                    for week in range(start_week, start_week + window)
                )
                if total_window_calls > max_calls:
                    hard_srcva_issues.append(
                        f"{fellow.name} has {total_window_calls} combined 24-hr + weekend SRC/VA calls in "
                        f"{_week_label(config, start_week)}-{_week_label(config, start_week + window - 1)}."
                    )

    return hard_24hr_issues, hard_srcva_issues, soft_issues


def _normalized_weekend_calls(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> list[list[bool]]:
    """Return weekend call assignments with a stable zero-filled fallback."""

    weekend_call = result.srcva_weekend_call_assignments
    if len(weekend_call) == config.num_fellows and all(
        len(assignments) == config.num_weeks for assignments in weekend_call
    ):
        return weekend_call
    return [[False for _ in range(config.num_weeks)] for _ in range(config.num_fellows)]


def _normalized_weekday_calls(
    config: ScheduleConfig,
    result: ScheduleResult,
) -> list[list[list[bool]]]:
    """Return weekday call assignments with a stable zero-filled fallback."""

    weekday_call = result.srcva_weekday_call_assignments
    if len(weekday_call) == config.num_fellows and all(
        len(weeks) == config.num_weeks and all(len(days) == 4 for days in weeks)
        for weeks in weekday_call
    ):
        return weekday_call
    return [
        [[False for _ in range(4)] for _ in range(config.num_weeks)]
        for _ in range(config.num_fellows)
    ]


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
