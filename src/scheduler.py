"""Main scheduling engine — orchestrates the CP-SAT solver."""

from __future__ import annotations

import os
import time

from ortools.sat.python import cp_model

from src.acgme import add_trailing_hours_cap
from src.call_scheduler import add_call_constraints, add_srcva_call_constraints
from src.constraints import (
    add_block_completion,
    add_cohort_limit_rules,
    add_contiguous_block_rules,
    add_consecutive_state_limit_rules,
    add_coverage_rules,
    add_eligibility_rules,
    add_first_assignment_run_limit_rules,
    add_first_assignment_pairing_rules,
    add_forbidden_transition_rules,
    add_individual_fellow_requirement_rules,
    add_linked_fellow_state_rules,
    add_max_concurrent_pto,
    add_min_max_weeks_per_block,
    add_night_float_consecutive_limit,
    add_one_assignment_per_week,
    add_prerequisite_rules,
    add_pto_count,
    add_rolling_window_rules,
    add_staffing_coverage,
    add_unavailable_weeks,
    add_week_count_rules,
)
from src.models import (
    ScheduleConfig,
    ScheduleResult,
    SoftFixedWeekPairRule,
    SoftRuleDirection,
    SoftSingleWeekBlockRule,
    SolverStatus,
    TrainingYear,
)


def _recommended_solver_worker_count() -> int:
    """Return a conservative CP-SAT worker count for shared deployments."""

    cpu_count = os.cpu_count() or 1
    return max(1, min(2, cpu_count))


def _sync_num_fellows(config: ScheduleConfig) -> None:
    """Keep the legacy ``num_fellows`` field aligned with the roster."""

    config.num_fellows = len(config.fellows)


def _resolve_rule_end_week(end_week: int | None, num_weeks: int) -> int:
    """Clamp a rule window to the schedule length."""

    return num_weeks - 1 if end_week is None else min(end_week, num_weeks - 1)


def _add_fixed_assignments(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    fixed_assignments: list[list[str]],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Pin the master schedule to a provided assignment matrix."""

    if len(fixed_assignments) != config.num_fellows:
        raise ValueError("Fixed assignments must include one row per fellow.")

    for fellow_idx, fellow_assignments in enumerate(fixed_assignments):
        if len(fellow_assignments) != config.num_weeks:
            raise ValueError(
                f"Fixed assignments for fellow index {fellow_idx} must include one entry per week."
            )
        for week, state_name in enumerate(fellow_assignments):
            if state_name not in block_name_to_idx:
                raise ValueError(
                    f"Fixed assignments reference unknown state '{state_name}' at fellow {fellow_idx}, week {week}."
                )
            model.Add(assign[fellow_idx, week, block_name_to_idx[state_name]] == 1)


def _add_fixed_weekly_binary_assignments(
    model: cp_model.CpModel,
    weekly_values: dict[tuple[int, int], cp_model.IntVar],
    fixed_assignments: list[list[bool]],
    config: ScheduleConfig,
    label: str,
) -> None:
    """Pin a weekly boolean overlay matrix to provided values."""

    if len(fixed_assignments) != config.num_fellows:
        raise ValueError(f"Fixed {label} assignments must include one row per fellow.")

    for fellow_idx, fellow_assignments in enumerate(fixed_assignments):
        if len(fellow_assignments) != config.num_weeks:
            raise ValueError(
                f"Fixed {label} assignments for fellow index {fellow_idx} must include one entry per week."
            )
        for week, assigned in enumerate(fellow_assignments):
            model.Add(weekly_values[fellow_idx, week] == int(bool(assigned)))


def check_feasibility(config: ScheduleConfig) -> list[str]:
    """Run quick sanity checks on the config before invoking the solver."""

    _sync_num_fellows(config)
    issues: list[str] = []
    active_blocks = config.active_blocks
    block_names = {block.name for block in config.blocks}

    if config.num_fellows == 0:
        issues.append("⚠️ No fellows configured. Add at least one fellow.")
        return issues

    unavailable_excess = [
        fellow.name
        for fellow in config.fellows
        if len(fellow.unavailable_weeks) > config.pto_weeks_granted
    ]
    for fellow_name in unavailable_excess:
        issues.append(
            f"⚠️ '{fellow_name}' has more unavailable weeks than PTO granted. "
            f"Unavailable weeks are currently forced to PTO."
        )

    if config.coverage_rules:
        available = config.num_fellows
        min_required_by_week = [0] * config.num_weeks
        for rule in config.coverage_rules:
            if not rule.is_active:
                continue
            if rule.block_name not in block_names:
                issues.append(
                    f"⚠️ Coverage rule '{rule.name}' references unknown block "
                    f"'{rule.block_name}'."
                )
                continue
            eligible_count = len(config.fellow_indices_for_years(rule.eligible_years))
            if rule.min_fellows > eligible_count:
                issues.append(
                    f"⚠️ Coverage rule '{rule.name}' needs {rule.min_fellows} "
                    f"fellows but only {eligible_count} eligible fellows exist."
                )
            if rule.max_fellows is not None and rule.max_fellows < rule.min_fellows:
                issues.append(
                    f"⚠️ Coverage rule '{rule.name}' has max_fellows < min_fellows."
                )
            end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
            for week in range(max(0, rule.start_week), end_week + 1):
                min_required_by_week[week] += rule.min_fellows

        peak_required = max(min_required_by_week, default=0)
        if peak_required > available:
            issues.append(
                f"⚠️ Staffing conflict: structured coverage rules require up to "
                f"{peak_required} fellows in a week but only {available} total "
                f"fellows exist."
            )
    else:
        total_needed = sum(block.fellows_needed for block in active_blocks)
        available = config.num_fellows
        if total_needed > available:
            issues.append(
                f"⚠️ Staffing conflict: blocks need {total_needed} fellows/week "
                f"but only {available} total fellows exist. Reduce fellows_needed "
                f"on some blocks."
            )
        for block in active_blocks:
            required_staffed_weeks = block.fellows_needed * config.num_weeks
            max_assignable_weeks = config.num_fellows * block.max_weeks
            if required_staffed_weeks > max_assignable_weeks:
                issues.append(
                    f"⚠️ Block capacity conflict: '{block.name}' needs "
                    f"{required_staffed_weeks} staffed weeks, but fellows can "
                    f"cover at most {max_assignable_weeks} given max_weeks="
                    f"{block.max_weeks}. Reduce staffing or raise max_weeks."
                )

    if config.week_count_rules:
        for rule in config.week_count_rules:
            if not rule.is_active:
                continue
            unknown_blocks = [name for name in rule.block_names if name != "PTO" and name not in block_names]
            if unknown_blocks:
                issues.append(
                    f"⚠️ Week-count rule '{rule.name}' references unknown blocks: "
                    f"{', '.join(unknown_blocks)}."
                )
            if rule.max_weeks < rule.min_weeks:
                issues.append(
                    f"⚠️ Week-count rule '{rule.name}' has max_weeks < min_weeks."
                )
            working_window = (
                _resolve_rule_end_week(rule.end_week, config.num_weeks)
                - max(0, rule.start_week)
                + 1
            )
            if rule.min_weeks > max(0, working_window):
                issues.append(
                    f"⚠️ Week-count rule '{rule.name}' requires {rule.min_weeks} "
                    f"weeks in a window of only {max(0, working_window)} weeks."
                )
    else:
        working_weeks = config.num_weeks - config.pto_weeks_granted
        total_required_weeks = sum(max(block.min_weeks, 1) for block in active_blocks)
        if total_required_weeks > working_weeks:
            issues.append(
                f"⚠️ Block minimums conflict: each fellow must cover at least "
                f"{total_required_weeks} block-weeks (counting the once-per-block "
                f"requirement), but only {working_weeks} working weeks remain "
                f"after PTO. Reduce active blocks or per-block minimums."
            )
        total_required_assignments = sum(
            max(
                block.fellows_needed * config.num_weeks,
                config.num_fellows * max(block.min_weeks, 1),
            )
            for block in active_blocks
        )
        total_available_assignments = (
            config.num_fellows * config.num_weeks
            - config.num_fellows * config.pto_weeks_granted
        )
        if total_required_assignments > total_available_assignments:
            issues.append(
                f"⚠️ Coverage/minimum conflict: active blocks require at least "
                f"{total_required_assignments} total assignments, but only "
                f"{total_available_assignments} working fellow-weeks are "
                f"available after PTO. Loosen staffing or reduce required blocks."
            )

    for rule in config.eligibility_rules:
        if not rule.is_active:
            continue
        unknown_blocks = [name for name in rule.block_names if name not in block_names]
        if unknown_blocks:
            issues.append(
                f"⚠️ Eligibility rule '{rule.name}' references unknown blocks: "
                f"{', '.join(unknown_blocks)}."
            )
        if not config.fellow_indices_for_years(rule.allowed_years):
            issues.append(
                f"⚠️ Eligibility rule '{rule.name}' has no fellows in the allowed cohorts."
            )

    for rule in config.cohort_limit_rules:
        if not rule.is_active:
            continue
        if rule.state_name != "PTO" and rule.state_name not in block_names:
            issues.append(
                f"⚠️ Cohort limit rule '{rule.name}' references unknown state "
                f"'{rule.state_name}'."
            )

    for rule in config.rolling_window_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in rule.state_names
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Rolling-window rule '{rule.name}' references unknown states: "
                f"{', '.join(sorted(set(unknown_states)))}."
            )
        if rule.window_size_weeks <= 0:
            issues.append(
                f"⚠️ Rolling-window rule '{rule.name}' must use a positive window size."
            )
        if rule.max_weeks_in_window < 0:
            issues.append(
                f"⚠️ Rolling-window rule '{rule.name}' must use a non-negative max."
            )
        if (
            rule.window_size_weeks > 0
            and rule.max_weeks_in_window > rule.window_size_weeks
        ):
            issues.append(
                f"⚠️ Rolling-window rule '{rule.name}' allows more weeks than fit "
                "in its window."
            )
        if not config.fellow_indices_for_years(rule.applicable_years):
            issues.append(
                f"⚠️ Rolling-window rule '{rule.name}' has no fellows in the selected cohorts."
            )

    for rule in config.consecutive_state_limit_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in rule.state_names
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Consecutive-state rule '{rule.name}' references unknown states: "
                f"{', '.join(sorted(set(unknown_states)))}."
            )
        if rule.max_consecutive_weeks < 1:
            issues.append(
                f"⚠️ Consecutive-state rule '{rule.name}' must allow at least 1 week."
            )
        if not config.fellow_indices_for_years(rule.applicable_years):
            issues.append(
                f"⚠️ Consecutive-state rule '{rule.name}' has no matching fellows."
            )

    for rule in config.first_assignment_run_limit_rules:
        if not rule.is_active:
            continue
        if rule.block_name not in block_names:
            issues.append(
                f"⚠️ First-assignment run rule '{rule.name}' references unknown block "
                f"'{rule.block_name}'."
            )
        if rule.max_run_length_weeks < 1:
            issues.append(
                f"⚠️ First-assignment run rule '{rule.name}' must allow at least 1 week."
            )
        if not config.fellow_indices_for_years(rule.applicable_years):
            issues.append(
                f"⚠️ First-assignment run rule '{rule.name}' has no matching fellows."
            )

    for rule in config.contiguous_block_rules:
        if not rule.is_active:
            continue
        if rule.block_name not in block_names:
            issues.append(
                f"⚠️ Contiguous block rule '{rule.name}' references unknown block "
                f"'{rule.block_name}'."
            )
        if not config.fellow_indices_for_years(rule.applicable_years):
            issues.append(
                f"⚠️ Contiguous block rule '{rule.name}' has no matching fellows."
            )

    for rule in config.first_assignment_pairing_rules:
        if not rule.is_active:
            continue
        if rule.block_name not in block_names:
            issues.append(
                f"⚠️ Pairing rule '{rule.name}' references unknown block "
                f"'{rule.block_name}'."
            )
        if not config.fellow_indices_for_years(rule.trainee_years):
            issues.append(
                f"⚠️ Pairing rule '{rule.name}' has no trainee fellows in the selected cohorts."
            )
        if not config.fellow_indices_for_years(rule.mentor_years):
            issues.append(
                f"⚠️ Pairing rule '{rule.name}' has no mentor fellows in the selected cohorts."
            )
        if rule.required_prior_weeks < 1:
            issues.append(
                f"⚠️ Pairing rule '{rule.name}' must require at least one prior week."
            )

    for rule in config.individual_fellow_requirement_rules:
        if not rule.is_active:
            continue
        if rule.block_name not in block_names:
            issues.append(
                f"⚠️ Individual fellow rule for '{rule.fellow_name}' references "
                f"unknown block '{rule.block_name}'."
            )
        if rule.max_weeks < rule.min_weeks:
            issues.append(
                f"⚠️ Individual fellow rule for '{rule.fellow_name}' has "
                "max_weeks < min_weeks."
            )
        matching_fellows = [
            fellow
            for fellow in config.fellows
            if fellow.training_year == rule.training_year
            and fellow.name == rule.fellow_name
        ]
        if not matching_fellows:
            issues.append(
                f"⚠️ Individual fellow rule for '{rule.fellow_name}' has no "
                f"matching fellow in cohort {rule.training_year.value}."
            )
        elif len(matching_fellows) > 1:
            issues.append(
                f"⚠️ Individual fellow rule for '{rule.fellow_name}' is ambiguous "
                f"because cohort {rule.training_year.value} has duplicate names."
            )

    for rule in config.linked_fellow_state_rules:
        if not rule.is_active:
            continue
        if rule.state_name != "PTO" and rule.state_name not in block_names:
            issues.append(
                f"⚠️ Linked fellow state rule '{rule.first_fellow_name} / "
                f"{rule.second_fellow_name}' references unknown state "
                f"'{rule.state_name}'."
            )
        first_matches = [
            fellow
            for fellow in config.fellows
            if fellow.training_year == rule.training_year
            and fellow.name == rule.first_fellow_name
        ]
        second_matches = [
            fellow
            for fellow in config.fellows
            if fellow.training_year == rule.training_year
            and fellow.name == rule.second_fellow_name
        ]
        if not first_matches:
            issues.append(
                f"⚠️ Linked fellow state rule references missing fellow "
                f"'{rule.first_fellow_name}' in cohort {rule.training_year.value}."
            )
        elif len(first_matches) > 1:
            issues.append(
                f"⚠️ Linked fellow state rule for '{rule.first_fellow_name}' is "
                f"ambiguous because cohort {rule.training_year.value} has duplicate names."
            )
        if not second_matches:
            issues.append(
                f"⚠️ Linked fellow state rule references missing fellow "
                f"'{rule.second_fellow_name}' in cohort {rule.training_year.value}."
            )
        elif len(second_matches) > 1:
            issues.append(
                f"⚠️ Linked fellow state rule for '{rule.second_fellow_name}' is "
                f"ambiguous because cohort {rule.training_year.value} has duplicate names."
            )
        if rule.first_fellow_name == rule.second_fellow_name:
            issues.append(
                f"⚠️ Linked fellow state rule '{rule.first_fellow_name}' must reference "
                "two distinct fellows."
            )

    for rule in config.prerequisite_rules:
        if not rule.is_active:
            continue
        if rule.target_block not in block_names:
            issues.append(
                f"⚠️ Prerequisite rule '{rule.name}' references unknown target "
                f"block '{rule.target_block}'."
            )
        unknown_prereqs = [
            name for name in rule.prerequisite_blocks if name not in block_names
        ]
        if unknown_prereqs:
            issues.append(
                f"⚠️ Prerequisite rule '{rule.name}' references unknown blocks: "
                f"{', '.join(unknown_prereqs)}."
            )

    for rule in config.forbidden_transition_rules:
        if not rule.is_active:
            continue
        if rule.target_block not in block_names:
            issues.append(
                f"⚠️ Transition rule '{rule.name}' references unknown target "
                f"block '{rule.target_block}'."
            )
        unknown_previous = [
            name
            for name in rule.forbidden_previous_blocks
            if name != "PTO" and name not in block_names
        ]
        if unknown_previous:
            issues.append(
                f"⚠️ Transition rule '{rule.name}' references unknown previous "
                f"blocks: {', '.join(unknown_previous)}."
            )

    if config.structured_call_rules_enabled:
        eligible_fellows = config.fellow_indices_for_years(config.call_eligible_years)
        if not eligible_fellows:
            issues.append("⚠️ Structured 24-hour call rules have no eligible fellows.")

        if config.call_min_per_fellow > config.call_max_per_fellow:
            issues.append(
                "⚠️ Structured 24-hour call rules have min calls per fellow greater "
                "than max calls per fellow."
            )

        if eligible_fellows:
            min_total_call_capacity = len(eligible_fellows) * config.call_min_per_fellow
            max_total_call_capacity = len(eligible_fellows) * config.call_max_per_fellow
            if min_total_call_capacity > config.num_weeks:
                issues.append(
                    f"⚠️ Structured 24-hour call minimums require at least "
                    f"{min_total_call_capacity} call weeks, but only {config.num_weeks} "
                    "weekends exist."
                )
            if max_total_call_capacity < config.num_weeks:
                issues.append(
                    f"⚠️ Structured 24-hour call maximums cover only "
                    f"{max_total_call_capacity} weekends, but {config.num_weeks} "
                    "weekends need call coverage."
                )

        unknown_call_allowed_blocks = [
            block_name
            for block_name in config.call_allowed_block_names
            if block_name not in block_names
        ]
        if unknown_call_allowed_blocks:
            issues.append(
                "⚠️ Structured 24-hour call eligible rotations reference unknown "
                f"blocks: {', '.join(sorted(set(unknown_call_allowed_blocks)))}."
            )

        unknown_call_exclusions = [
            block_name
            for block_name in config.call_excluded_blocks
            if block_name != "PTO" and block_name not in block_names
        ]
        if unknown_call_exclusions:
            issues.append(
                "⚠️ Structured 24-hour call excluded states reference unknown "
                f"blocks: {', '.join(sorted(set(unknown_call_exclusions)))}."
            )

        unknown_call_following_blocks = [
            block_name
            for block_name in config.call_forbidden_following_blocks
            if block_name != "PTO" and block_name not in block_names
        ]
        if unknown_call_following_blocks:
            issues.append(
                "⚠️ Structured 24-hour call next-week exclusions reference unknown "
                f"blocks: {', '.join(sorted(set(unknown_call_following_blocks)))}."
            )

        unknown_first_call_preferences = [
            block_name
            for block_name in config.call_first_call_preferred_blocks
            if block_name not in block_names
        ]
        if unknown_first_call_preferences:
            issues.append(
                "⚠️ Structured 24-hour call first-call preferred blocks reference "
                f"unknown blocks: {', '.join(sorted(set(unknown_first_call_preferences)))}."
            )

        unknown_first_call_prereqs = [
            block_name
            for block_name in config.call_first_call_prerequisite_blocks
            if block_name not in block_names
        ]
        if unknown_first_call_prereqs:
            issues.append(
                "⚠️ Structured 24-hour call first-call prerequisites reference "
                f"unknown blocks: {', '.join(sorted(set(unknown_first_call_prereqs)))}."
            )

        unknown_holiday_blocks = [
            block_name
            for block_name in config.call_holiday_sensitive_blocks
            if block_name not in block_names
        ]
        if unknown_holiday_blocks:
            issues.append(
                "⚠️ Structured 24-hour call holiday-sensitive blocks reference "
                f"unknown blocks: {', '.join(sorted(set(unknown_holiday_blocks)))}."
            )

        if config.call_max_consecutive_weeks_per_fellow < 1:
            issues.append(
                "⚠️ Structured 24-hour call consecutive-week limit must allow at least 1 week."
            )

        if (
            config.call_holiday_anchor_week is not None
            and not 0 <= config.call_holiday_anchor_week < config.num_weeks
        ):
            issues.append("⚠️ Structured 24-hour call holiday anchor week is out of range.")

        invalid_holiday_target_weeks = [
            week
            for week in config.call_holiday_target_weeks
            if not 0 <= week < config.num_weeks
        ]
        if invalid_holiday_target_weeks:
            issues.append(
                "⚠️ Structured 24-hour call holiday target weeks are out of range: "
                f"{', '.join(str(week + 1) for week in invalid_holiday_target_weeks)}."
            )

    if config.srcva_weekend_call_enabled:
        weekend_eligible = config.fellow_indices_for_years(
            config.srcva_weekend_call_eligible_years
        )
        if not weekend_eligible:
            issues.append("⚠️ SRC/VA weekend call rules have no eligible fellows.")

        f1_weekend = sum(
            1
            for fellow_idx in weekend_eligible
            if config.fellows[fellow_idx].training_year == TrainingYear.F1
        )
        s2_weekend = sum(
            1
            for fellow_idx in weekend_eligible
            if config.fellows[fellow_idx].training_year == TrainingYear.S2
        )
        if config.srcva_weekend_call_f1_min > config.srcva_weekend_call_f1_max:
            issues.append(
                "⚠️ SRC/VA weekend call F1 minimum is greater than the maximum."
            )
        if config.srcva_weekend_call_s2_min > config.srcva_weekend_call_s2_max:
            issues.append(
                "⚠️ SRC/VA weekend call S2 minimum is greater than the maximum."
            )
        min_weekend_capacity = (
            f1_weekend * config.srcva_weekend_call_f1_min
            + s2_weekend * config.srcva_weekend_call_s2_min
        )
        max_weekend_capacity = (
            f1_weekend * config.srcva_weekend_call_f1_max
            + s2_weekend * config.srcva_weekend_call_s2_max
        )
        if min_weekend_capacity > config.num_weeks:
            issues.append(
                f"⚠️ SRC/VA weekend-call minimums require at least "
                f"{min_weekend_capacity} weekends, but only {config.num_weeks} exist."
            )
        if max_weekend_capacity < config.num_weeks:
            issues.append(
                f"⚠️ SRC/VA weekend-call maximums cover only {max_weekend_capacity} "
                f"weekends, but {config.num_weeks} need coverage."
            )
        unknown_weekend_blocks = [
            block_name
            for block_name in config.srcva_weekend_call_allowed_block_names
            if block_name not in block_names
        ]
        if unknown_weekend_blocks:
            issues.append(
                "⚠️ SRC/VA weekend-call eligible rotations reference unknown "
                f"blocks: {', '.join(sorted(set(unknown_weekend_blocks)))}."
            )
        if (
            config.srcva_weekend_call_f1_start_week is not None
            and not 0 <= config.srcva_weekend_call_f1_start_week < config.num_weeks
        ):
            issues.append("⚠️ SRC/VA weekend-call F1 start week is out of range.")
        if config.srcva_total_call_f1_min > config.srcva_total_call_f1_max:
            issues.append(
                "⚠️ Total F1 24-hour + SRC/VA weekend call minimum is greater "
                "than the maximum."
            )

    if config.srcva_weekday_call_enabled:
        weekday_eligible = config.fellow_indices_for_years(
            config.srcva_weekday_call_eligible_years
        )
        if not weekday_eligible:
            issues.append("⚠️ SRC/VA weekday call rules have no eligible fellows.")

        f1_weekday = sum(
            1
            for fellow_idx in weekday_eligible
            if config.fellows[fellow_idx].training_year == TrainingYear.F1
        )
        s2_weekday = sum(
            1
            for fellow_idx in weekday_eligible
            if config.fellows[fellow_idx].training_year == TrainingYear.S2
        )
        if config.srcva_weekday_call_f1_min > config.srcva_weekday_call_f1_max:
            issues.append(
                "⚠️ SRC/VA weekday-call F1 minimum is greater than the maximum."
            )
        if config.srcva_weekday_call_s2_min > config.srcva_weekday_call_s2_max:
            issues.append(
                "⚠️ SRC/VA weekday-call S2 minimum is greater than the maximum."
            )
        min_weekday_capacity = (
            f1_weekday * config.srcva_weekday_call_f1_min
            + s2_weekday * config.srcva_weekday_call_s2_min
        )
        max_weekday_capacity = (
            f1_weekday * config.srcva_weekday_call_f1_max
            + s2_weekday * config.srcva_weekday_call_s2_max
        )
        required_weekday_nights = config.num_weeks * 4
        if min_weekday_capacity > required_weekday_nights:
            issues.append(
                f"⚠️ SRC/VA weekday-call minimums require at least "
                f"{min_weekday_capacity} nights, but only "
                f"{required_weekday_nights} need coverage."
            )
        if max_weekday_capacity < required_weekday_nights:
            issues.append(
                f"⚠️ SRC/VA weekday-call maximums cover only {max_weekday_capacity} "
                f"nights, but {required_weekday_nights} need coverage."
            )
        unknown_weekday_blocks = [
            block_name
            for block_name in config.srcva_weekday_call_allowed_block_names
            if block_name not in block_names
        ]
        if unknown_weekday_blocks:
            issues.append(
                "⚠️ SRC/VA weekday-call eligible rotations reference unknown "
                f"blocks: {', '.join(sorted(set(unknown_weekday_blocks)))}."
            )
        if (
            config.srcva_weekday_call_f1_start_week is not None
            and not 0 <= config.srcva_weekday_call_f1_start_week < config.num_weeks
        ):
            issues.append("⚠️ SRC/VA weekday-call F1 start week is out of range.")
        if config.srcva_weekday_call_max_consecutive_nights < 1:
            issues.append(
                "⚠️ SRC/VA weekday-call consecutive-night limit must allow at least 1 night."
            )
        if config.srcva_max_calls_per_week < 0:
            issues.append(
                "⚠️ SRC/VA weekly total-call cap cannot be negative."
            )

    for week_name, week_value in (
        ("holiday anchor week", config.srcva_holiday_anchor_week),
        ("Christmas target week", config.srcva_christmas_target_week),
        ("New Year's target week", config.srcva_new_year_target_week),
    ):
        if week_value is not None and not 0 <= week_value < config.num_weeks:
            issues.append(f"⚠️ SRC/VA {week_name} is out of range.")

    unknown_srcva_holiday_blocks = [
        block_name
        for block_name in config.srcva_holiday_preferred_anchor_blocks
        if block_name != "PTO" and block_name not in block_names
    ]
    if unknown_srcva_holiday_blocks:
        issues.append(
            "⚠️ SRC/VA holiday anchor preferred blocks reference unknown blocks: "
            f"{', '.join(sorted(set(unknown_srcva_holiday_blocks)))}."
        )

    for rule in config.soft_sequence_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in (rule.left_states + rule.right_states)
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Soft rule '{rule.name}' references unknown states: "
                f"{', '.join(sorted(set(unknown_states)))}."
            )

    for rule in config.soft_state_assignment_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in rule.state_names
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Soft state-assignment rule '{rule.name}' references unknown "
                f"states: {', '.join(sorted(set(unknown_states)))}."
            )

    for rule in config.soft_fixed_week_pair_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in (rule.trigger_states + rule.paired_states)
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Soft fixed-week rule '{rule.name}' references unknown "
                f"states: {', '.join(sorted(set(unknown_states)))}."
            )
        if not 0 <= rule.first_week < config.num_weeks:
            issues.append(
                f"⚠️ Soft fixed-week rule '{rule.name}' has a first week out of range."
            )
        if not 0 <= rule.second_week < config.num_weeks:
            issues.append(
                f"⚠️ Soft fixed-week rule '{rule.name}' has a second week out of range."
            )

    for rule in config.soft_cohort_balance_rules:
        if not rule.is_active:
            continue
        unknown_states = [
            state
            for state in rule.state_names
            if state != "PTO" and state not in block_names
        ]
        if unknown_states:
            issues.append(
                f"⚠️ Soft cohort-balance rule '{rule.name}' references unknown "
                f"states: {', '.join(sorted(set(unknown_states)))}."
            )

    for block in active_blocks:
        if block.hours_per_week > 72:
            issues.append(
                f"⚠️ ACGME warning: '{block.name}' has {block.hours_per_week} "
                f"hrs/week, which may violate the 1-day-off-per-7 rule "
                f"(> 72 hrs implies no rest day in a 7-day period)."
            )

    for fellow in config.fellows:
        if len(fellow.pto_rankings) == 0:
            issues.append(
                f"⚠️ '{fellow.name}' has no PTO weeks ranked. The solver "
                f"will assign PTO weeks arbitrarily."
            )

    return issues


def solve_schedule(
    config: ScheduleConfig,
    fixed_assignments: list[list[str]] | None = None,
    fixed_call_assignments: list[list[bool]] | None = None,
) -> ScheduleResult:
    """Build and solve the CP-SAT model for the fellowship schedule."""

    _sync_num_fellows(config)

    model = cp_model.CpModel()
    num_blocks = len(config.blocks)
    pto_idx = num_blocks
    block_name_to_idx = {block.name: index for index, block in enumerate(config.blocks)}
    block_name_to_idx["PTO"] = pto_idx
    nf_idx = block_name_to_idx.get("Night Float")

    assign: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            for block_idx in range(num_blocks + 1):
                assign[fellow_idx, week, block_idx] = model.NewBoolVar(
                    f"assign_f{fellow_idx}_w{week}_b{block_idx}"
                )

    call: dict[tuple[int, int], cp_model.IntVar] = {}
    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            call[fellow_idx, week] = model.NewBoolVar(
                f"call_f{fellow_idx}_w{week}"
            )

    srcva_weekend_call: dict[tuple[int, int], cp_model.IntVar] = {}
    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            srcva_weekend_call[fellow_idx, week] = model.NewBoolVar(
                f"srcva_weekend_call_f{fellow_idx}_w{week}"
            )

    srcva_weekday_call: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            for day_idx in range(4):
                srcva_weekday_call[fellow_idx, week, day_idx] = model.NewBoolVar(
                    f"srcva_weekday_call_f{fellow_idx}_w{week}_d{day_idx}"
                )

    for block_idx, block in enumerate(config.blocks):
        if block.is_active:
            continue
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                model.Add(assign[fellow_idx, week, block_idx] == 0)

    if fixed_assignments is not None:
        _add_fixed_assignments(
            model,
            assign,
            fixed_assignments,
            config,
            block_name_to_idx,
        )
    if fixed_call_assignments is not None:
        _add_fixed_weekly_binary_assignments(
            model,
            call,
            fixed_call_assignments,
            config,
            "24-hour call",
        )

    add_one_assignment_per_week(model, assign, config, num_blocks, pto_idx)
    add_unavailable_weeks(model, assign, config, pto_idx)
    add_pto_count(model, assign, config, pto_idx)
    add_max_concurrent_pto(model, assign, config, pto_idx)

    if nf_idx is not None:
        add_night_float_consecutive_limit(model, assign, config, nf_idx)

    if (
        config.coverage_rules
        or config.eligibility_rules
        or config.week_count_rules
        or config.cohort_limit_rules
        or config.rolling_window_rules
        or config.consecutive_state_limit_rules
        or config.first_assignment_run_limit_rules
        or config.contiguous_block_rules
        or config.first_assignment_pairing_rules
        or config.individual_fellow_requirement_rules
        or config.linked_fellow_state_rules
        or config.prerequisite_rules
        or config.forbidden_transition_rules
    ):
        add_eligibility_rules(model, assign, config, block_name_to_idx)
        add_coverage_rules(model, assign, config, block_name_to_idx)
        add_week_count_rules(model, assign, config, block_name_to_idx)
        add_cohort_limit_rules(model, assign, config, block_name_to_idx)
        add_rolling_window_rules(model, assign, config, block_name_to_idx)
        add_consecutive_state_limit_rules(model, assign, config, block_name_to_idx)
        add_first_assignment_run_limit_rules(model, assign, config, block_name_to_idx)
        add_contiguous_block_rules(model, assign, config, block_name_to_idx)
        add_first_assignment_pairing_rules(model, assign, config, block_name_to_idx)
        add_individual_fellow_requirement_rules(model, assign, config, block_name_to_idx)
        add_linked_fellow_state_rules(model, assign, config, block_name_to_idx)
        add_prerequisite_rules(model, assign, config, block_name_to_idx)
        add_forbidden_transition_rules(model, assign, config, block_name_to_idx)
    else:
        add_block_completion(model, assign, config, num_blocks)

    add_min_max_weeks_per_block(model, assign, config, num_blocks)
    add_staffing_coverage(model, assign, config, num_blocks)
    add_trailing_hours_cap(model, assign, call, config, num_blocks, pto_idx)
    add_call_constraints(model, assign, call, config, num_blocks, pto_idx)
    add_srcva_call_constraints(
        model,
        assign,
        srcva_weekend_call,
        srcva_weekday_call,
        call,
        config,
        num_blocks,
        pto_idx,
    )

    objective_terms = _build_objective_terms(
        model,
        assign,
        call,
        srcva_weekend_call,
        srcva_weekday_call,
        config,
        pto_idx,
        block_name_to_idx,
    )
    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_timeout_seconds
    solver.parameters.num_workers = _recommended_solver_worker_count()

    start_time = time.time()
    status_code = solver.Solve(model)
    solve_time = time.time() - start_time

    status_map = {
        cp_model.OPTIMAL: SolverStatus.OPTIMAL,
        cp_model.FEASIBLE: SolverStatus.FEASIBLE,
        cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
        cp_model.MODEL_INVALID: SolverStatus.ERROR,
        cp_model.UNKNOWN: SolverStatus.TIMEOUT,
    }
    solver_status = status_map.get(status_code, SolverStatus.ERROR)

    if solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
        return _extract_solution(
            solver,
            assign,
            call,
            srcva_weekend_call,
            srcva_weekday_call,
            config,
            num_blocks,
            solver_status,
            solver.ObjectiveValue(),
            solve_time,
        )

    return ScheduleResult(
        assignments=[
            ["" for _ in range(config.num_weeks)] for _ in range(config.num_fellows)
        ],
        call_assignments=[
            [False for _ in range(config.num_weeks)] for _ in range(config.num_fellows)
        ],
        srcva_weekend_call_assignments=[
            [False for _ in range(config.num_weeks)] for _ in range(config.num_fellows)
        ],
        srcva_weekday_call_assignments=[
            [[False for _ in range(4)] for _ in range(config.num_weeks)]
            for _ in range(config.num_fellows)
        ],
        solver_status=solver_status,
        objective_value=0.0,
        solve_time_seconds=solve_time,
    )


def _build_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    srcva_weekend_call: dict[tuple[int, int], cp_model.IntVar],
    srcva_weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Build the optimization objective from PTO preferences and soft rules."""

    objective_terms: list[cp_model.LinearExpr] = []
    objective_terms.extend(_build_pto_objective_terms(assign, config, pto_idx))
    objective_terms.extend(
        _build_soft_sequence_objective_terms(
            model,
            assign,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_soft_single_week_block_objective_terms(
            model,
            assign,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_soft_state_assignment_objective_terms(
            assign,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_soft_fixed_week_pair_objective_terms(
            model,
            assign,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_soft_cohort_balance_objective_terms(
            model,
            assign,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_structured_call_objective_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_srcva_call_objective_terms(
            model,
            assign,
            srcva_weekend_call,
            srcva_weekday_call,
            call,
            config,
            block_name_to_idx,
        )
    )
    return objective_terms


def _build_pto_objective_terms(
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> list[cp_model.LinearExpr]:
    """Return PTO preference objective terms."""

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx, fellow in enumerate(config.fellows):
        cohort_weights = config.pto_preference_weights_for_year(fellow.training_year)
        for rank, week_idx in enumerate(fellow.pto_rankings):
            if rank >= len(cohort_weights):
                continue
            if 0 <= week_idx < config.num_weeks:
                score = cohort_weights[rank]
                if score > 0:
                    objective_terms.append(assign[fellow_idx, week_idx, pto_idx] * score)
    return objective_terms


def _build_soft_sequence_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted bonus / penalty terms for soft sequence rules."""

    objective_terms: list[cp_model.LinearExpr] = []
    for rule_idx, rule in enumerate(config.soft_sequence_rules):
        if not rule.is_active:
            continue
        left_indices = [
            block_name_to_idx[state]
            for state in rule.left_states
            if state in block_name_to_idx
        ]
        right_indices = [
            block_name_to_idx[state]
            for state in rule.right_states
            if state in block_name_to_idx
        ]
        if not left_indices or not right_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for fellow_idx in fellow_indices:
            for week in range(max(0, rule.start_week), end_week):
                objective_terms.extend(
                    _build_sequence_match_terms(
                        model,
                        assign,
                        fellow_idx,
                        week,
                        left_indices,
                        right_indices,
                        rule.weight,
                        f"soft_r{rule_idx}_f{fellow_idx}_w{week}",
                    )
                )
                if (
                    rule.direction == SoftRuleDirection.EITHER
                    and set(left_indices) != set(right_indices)
                ):
                    objective_terms.extend(
                        _build_sequence_match_terms(
                            model,
                            assign,
                            fellow_idx,
                            week,
                            right_indices,
                            left_indices,
                            rule.weight,
                            f"soft_r{rule_idx}_rev_f{fellow_idx}_w{week}",
                        )
                    )
    return objective_terms


def _build_soft_single_week_block_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted bonus terms for consecutive same-rotation weeks."""

    objective_terms: list[cp_model.LinearExpr] = []
    for rule_idx, rule in enumerate(config.soft_single_week_block_rules):
        if not rule.is_active:
            continue
        block_indices = _single_week_rule_block_indices(rule, config, block_name_to_idx)
        if not block_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for fellow_idx in fellow_indices:
            for week in range(max(0, rule.start_week), end_week):
                for block_idx in block_indices:
                    objective_terms.extend(
                        _build_sequence_match_terms(
                            model,
                            assign,
                            fellow_idx,
                            week,
                            [block_idx],
                            [block_idx],
                            rule.weight,
                            f"same_rotation_r{rule_idx}_f{fellow_idx}_w{week}_b{block_idx}",
                        )
                    )
    return objective_terms


def _build_soft_state_assignment_objective_terms(
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted terms for preferred state assignments."""

    objective_terms: list[cp_model.LinearExpr] = []
    for rule in config.soft_state_assignment_rules:
        if not rule.is_active or rule.weight == 0:
            continue
        state_indices = [
            block_name_to_idx[state]
            for state in rule.state_names
            if state in block_name_to_idx
        ]
        if not state_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for fellow_idx in fellow_indices:
            for week in range(max(0, rule.start_week), end_week + 1):
                for state_idx in state_indices:
                    objective_terms.append(
                        assign[fellow_idx, week, state_idx] * rule.weight
                    )
    return objective_terms


def _build_soft_fixed_week_pair_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted terms for two-week holiday pairing preferences."""

    objective_terms: list[cp_model.LinearExpr] = []
    valid_states = set(config.all_states)
    for rule_idx, rule in enumerate(config.soft_fixed_week_pair_rules):
        if not rule.is_active or rule.weight == 0:
            continue
        if not (
            0 <= rule.first_week < config.num_weeks
            and 0 <= rule.second_week < config.num_weeks
        ):
            continue

        trigger_indices = [
            block_name_to_idx[state]
            for state in rule.trigger_states
            if state in valid_states and state in block_name_to_idx
        ]
        paired_indices = [
            block_name_to_idx[state]
            for state in rule.paired_states
            if state in valid_states and state in block_name_to_idx
        ]
        if not trigger_indices or not paired_indices:
            continue

        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        for fellow_idx in fellow_indices:
            first_trigger = sum(
                assign[fellow_idx, rule.first_week, block_idx]
                for block_idx in trigger_indices
            )
            second_paired = sum(
                assign[fellow_idx, rule.second_week, block_idx]
                for block_idx in paired_indices
            )
            forward_match = model.NewBoolVar(
                f"fixed_pair_r{rule_idx}_f{fellow_idx}_forward"
            )
            model.Add(forward_match <= first_trigger)
            model.Add(forward_match <= second_paired)
            model.Add(forward_match >= first_trigger + second_paired - 1)

            first_paired = sum(
                assign[fellow_idx, rule.first_week, block_idx]
                for block_idx in paired_indices
            )
            second_trigger = sum(
                assign[fellow_idx, rule.second_week, block_idx]
                for block_idx in trigger_indices
            )
            reverse_match = model.NewBoolVar(
                f"fixed_pair_r{rule_idx}_f{fellow_idx}_reverse"
            )
            model.Add(reverse_match <= first_paired)
            model.Add(reverse_match <= second_trigger)
            model.Add(reverse_match >= first_paired + second_trigger - 1)

            any_match = model.NewBoolVar(f"fixed_pair_r{rule_idx}_f{fellow_idx}_any")
            model.Add(any_match >= forward_match)
            model.Add(any_match >= reverse_match)
            model.Add(any_match <= forward_match + reverse_match)
            objective_terms.append(any_match * rule.weight)
    return objective_terms


def _build_soft_cohort_balance_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return penalty terms for uneven state distribution inside a cohort."""

    objective_terms: list[cp_model.LinearExpr] = []
    for rule_idx, rule in enumerate(config.soft_cohort_balance_rules):
        if not rule.is_active or rule.weight <= 0:
            continue
        state_indices = [
            block_name_to_idx[state]
            for state in rule.state_names
            if state in block_name_to_idx
        ]
        if not state_indices:
            continue
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        week_indices = range(max(0, rule.start_week), end_week + 1)
        for year in rule.applicable_years:
            fellow_indices = config.fellow_indices_for_years([year])
            if len(fellow_indices) < 2:
                continue
            count_vars: dict[int, cp_model.IntVar] = {}
            max_count = len(state_indices) * len(list(week_indices))
            for fellow_idx in fellow_indices:
                count_var = model.NewIntVar(
                    0,
                    max_count,
                    f"soft_balance_r{rule_idx}_y{year.value}_f{fellow_idx}_count",
                )
                model.Add(
                    count_var
                    == sum(
                        assign[fellow_idx, week, state_idx]
                        for week in week_indices
                        for state_idx in state_indices
                    )
                )
                count_vars[fellow_idx] = count_var

            ordered_fellows = sorted(fellow_indices)
            for left_pos, left_idx in enumerate(ordered_fellows):
                for right_idx in ordered_fellows[left_pos + 1 :]:
                    diff_var = model.NewIntVar(
                        0,
                        max_count,
                        (
                            f"soft_balance_r{rule_idx}_y{year.value}"
                            f"_f{left_idx}_f{right_idx}_diff"
                        ),
                    )
                    model.AddAbsEquality(
                        diff_var,
                        count_vars[left_idx] - count_vars[right_idx],
                    )
                    objective_terms.append(diff_var * (-rule.weight))
    return objective_terms


def _build_structured_call_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted bonus / penalty terms for structured call preferences."""

    if not config.structured_call_rules_enabled:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    objective_terms.extend(
        _build_first_call_block_preference_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_first_call_prerequisite_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_holiday_call_avoidance_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_call_next_week_block_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_call_current_block_terms(
            model,
            assign,
            call,
            config,
            block_name_to_idx,
        )
    )
    return objective_terms


def _build_srcva_call_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Return weighted bonus / penalty terms for SRC/VA overlay calls."""

    if not (config.srcva_weekend_call_enabled or config.srcva_weekday_call_enabled):
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    objective_terms.extend(
        _build_srcva_holiday_preference_terms(
            model,
            assign,
            weekend_call,
            weekday_call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_srcva_holiday_repeat_terms(
            model,
            weekend_call,
            weekday_call,
            config,
        )
    )
    objective_terms.extend(
        _build_srcva_weekday_max_one_per_week_terms(
            model,
            weekday_call,
            config,
        )
    )
    objective_terms.extend(
        _build_srcva_weekday_same_week_as_weekend_terms(
            model,
            weekend_call,
            weekday_call,
            config,
        )
    )
    objective_terms.extend(
        _build_srcva_weekday_same_week_as_24hr_terms(
            model,
            weekday_call,
            call,
            config,
        )
    )
    objective_terms.extend(
        _build_srcva_weekend_next_week_block_terms(
            model,
            assign,
            weekend_call,
            config,
            block_name_to_idx,
        )
    )
    objective_terms.extend(
        _build_srcva_weekend_consecutive_terms(
            model,
            weekend_call,
            config,
        )
    )
    return objective_terms


def _srcva_any_weekday_call_var(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    fellow_idx: int,
    week: int,
    name_prefix: str,
) -> cp_model.IntVar:
    """Return a bool var indicating any weekday SRC/VA call in one week."""

    total = sum(weekday_call[fellow_idx, week, day_idx] for day_idx in range(4))
    any_call = model.NewBoolVar(f"{name_prefix}_f{fellow_idx}_w{week}")
    model.Add(total >= 1).OnlyEnforceIf(any_call)
    model.Add(total == 0).OnlyEnforceIf(any_call.Not())
    return any_call


def _srcva_any_call_in_week_var(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    fellow_idx: int,
    week: int,
    name_prefix: str,
) -> cp_model.IntVar:
    """Return a bool var indicating any SRC/VA call in one week."""

    weekday_any = _srcva_any_weekday_call_var(
        model,
        weekday_call,
        fellow_idx,
        week,
        f"{name_prefix}_weekday",
    )
    any_call = model.NewBoolVar(f"{name_prefix}_f{fellow_idx}_w{week}")
    model.Add(any_call >= weekend_call[fellow_idx, week])
    model.Add(any_call >= weekday_any)
    model.Add(any_call <= weekend_call[fellow_idx, week] + weekday_any)
    return any_call


def _build_srcva_holiday_preference_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Reward Christmas-week SRC/VA call after a preferred Thanksgiving-week block."""

    if (
        config.srcva_holiday_anchor_week is None
        or config.srcva_christmas_target_week is None
        or config.srcva_holiday_preference_weight == 0
    ):
        return []

    anchor_week = config.srcva_holiday_anchor_week
    christmas_week = config.srcva_christmas_target_week
    if not (0 <= anchor_week < config.num_weeks and 0 <= christmas_week < config.num_weeks):
        return []

    preferred_indices = [
        block_name_to_idx[block_name]
        for block_name in config.srcva_holiday_preferred_anchor_blocks
        if block_name in block_name_to_idx
    ]
    if not preferred_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        anchor_match = sum(assign[fellow_idx, anchor_week, idx] for idx in preferred_indices)
        christmas_call = _srcva_any_call_in_week_var(
            model,
            weekend_call,
            weekday_call,
            fellow_idx,
            christmas_week,
            "srcva_christmas_call",
        )
        match_var = model.NewBoolVar(f"srcva_holiday_pref_f{fellow_idx}")
        model.Add(match_var <= anchor_match)
        model.Add(match_var <= christmas_call)
        model.Add(match_var >= anchor_match + christmas_call - 1)
        objective_terms.append(match_var * config.srcva_holiday_preference_weight)
    return objective_terms


def _build_srcva_holiday_repeat_terms(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> list[cp_model.LinearExpr]:
    """Penalize repeated holiday SRC/VA call assignments on the same fellow."""

    if config.srcva_holiday_repeat_weight == 0:
        return []
    if config.srcva_christmas_target_week is None:
        return []

    christmas_week = config.srcva_christmas_target_week
    if not 0 <= christmas_week < config.num_weeks:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        christmas_call = _srcva_any_call_in_week_var(
            model,
            weekend_call,
            weekday_call,
            fellow_idx,
            christmas_week,
            "srcva_holiday_repeat_christmas",
        )
        if config.srcva_holiday_anchor_week is not None and 0 <= config.srcva_holiday_anchor_week < config.num_weeks:
            anchor_call = _srcva_any_call_in_week_var(
                model,
                weekend_call,
                weekday_call,
                fellow_idx,
                config.srcva_holiday_anchor_week,
                "srcva_holiday_repeat_anchor",
            )
            anchor_conflict = model.NewBoolVar(f"srcva_holiday_repeat_anchor_f{fellow_idx}")
            model.Add(anchor_conflict <= anchor_call)
            model.Add(anchor_conflict <= christmas_call)
            model.Add(anchor_conflict >= anchor_call + christmas_call - 1)
            objective_terms.append(anchor_conflict * config.srcva_holiday_repeat_weight)

        if config.srcva_new_year_target_week is not None and 0 <= config.srcva_new_year_target_week < config.num_weeks:
            new_year_call = _srcva_any_call_in_week_var(
                model,
                weekend_call,
                weekday_call,
                fellow_idx,
                config.srcva_new_year_target_week,
                "srcva_holiday_repeat_new_year",
            )
            new_year_conflict = model.NewBoolVar(f"srcva_holiday_repeat_newyear_f{fellow_idx}")
            model.Add(new_year_conflict <= christmas_call)
            model.Add(new_year_conflict <= new_year_call)
            model.Add(new_year_conflict >= christmas_call + new_year_call - 1)
            objective_terms.append(new_year_conflict * config.srcva_holiday_repeat_weight)

    return objective_terms


def _build_srcva_weekday_max_one_per_week_terms(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> list[cp_model.LinearExpr]:
    """Penalize excess weekday calls after the first one in a week."""

    if not config.srcva_weekday_call_enabled or config.srcva_weekday_max_one_per_week_weight == 0:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekday_call_eligible_years):
        for week in range(config.num_weeks):
            total = sum(weekday_call[fellow_idx, week, day_idx] for day_idx in range(4))
            for threshold in range(2, 5):
                threshold_var = model.NewBoolVar(
                    f"srcva_weekday_threshold_{threshold}_f{fellow_idx}_w{week}"
                )
                model.Add(total >= threshold).OnlyEnforceIf(threshold_var)
                model.Add(total < threshold).OnlyEnforceIf(threshold_var.Not())
                objective_terms.append(
                    threshold_var * config.srcva_weekday_max_one_per_week_weight
                )
    return objective_terms


def _build_srcva_weekday_same_week_as_weekend_terms(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> list[cp_model.LinearExpr]:
    """Penalize any week where the same fellow has both weekday and weekend SRC/VA call."""

    if config.srcva_weekday_same_week_as_weekend_weight == 0:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for week in range(config.num_weeks):
            weekday_any = _srcva_any_weekday_call_var(
                model,
                weekday_call,
                fellow_idx,
                week,
                "srcva_same_weekend_weekday",
            )
            match_var = model.NewBoolVar(f"srcva_same_week_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= weekend_call[fellow_idx, week])
            model.Add(match_var <= weekday_any)
            model.Add(
                match_var
                >= weekend_call[fellow_idx, week] + weekday_any - 1
            )
            objective_terms.append(
                match_var * config.srcva_weekday_same_week_as_weekend_weight
            )
    return objective_terms


def _build_srcva_weekday_same_week_as_24hr_terms(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> list[cp_model.LinearExpr]:
    """Penalize any week where the same fellow has SRC/VA weekday call and 24-hour call."""

    if config.srcva_weekday_same_week_as_24hr_weight == 0:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    eligible_years = sorted(
        set(config.srcva_weekday_call_eligible_years + config.call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for week in range(config.num_weeks):
            weekday_any = _srcva_any_weekday_call_var(
                model,
                weekday_call,
                fellow_idx,
                week,
                "srcva_same_weekday_24hr",
            )
            match_var = model.NewBoolVar(f"srcva_same_week_24hr_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= call[fellow_idx, week])
            model.Add(match_var <= weekday_any)
            model.Add(match_var >= call[fellow_idx, week] + weekday_any - 1)
            objective_terms.append(
                match_var * config.srcva_weekday_same_week_as_24hr_weight
            )
    return objective_terms


def _build_first_call_block_preference_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Reward preferred rotations during a fellow's first call week."""

    if (
        not config.call_first_call_preferred_blocks
        or config.call_first_call_preference_weight == 0
    ):
        return []

    preferred_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_first_call_preferred_blocks
        if block_name in block_name_to_idx
    ]
    if not preferred_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        for week in range(config.num_weeks):
            first_call = _first_call_week_var(
                model,
                call,
                config,
                fellow_idx,
                week,
                name_prefix="call_first_preferred",
            )
            on_preferred = sum(assign[fellow_idx, week, block_idx] for block_idx in preferred_indices)
            match_var = model.NewBoolVar(f"call_first_preferred_f{fellow_idx}_w{week}")
            model.Add(match_var <= first_call)
            model.Add(match_var <= on_preferred)
            model.Add(match_var >= first_call + on_preferred - 1)
            objective_terms.append(match_var * config.call_first_call_preference_weight)
    return objective_terms


def _build_first_call_prerequisite_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Reward prior exposure before a fellow's first call week."""

    if (
        not config.call_first_call_prerequisite_blocks
        or config.call_first_call_prerequisite_weight == 0
    ):
        return []

    prerequisite_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_first_call_prerequisite_blocks
        if block_name in block_name_to_idx
    ]
    if not prerequisite_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        for week in range(config.num_weeks):
            first_call = _first_call_week_var(
                model,
                call,
                config,
                fellow_idx,
                week,
                name_prefix="call_first_prereq",
            )
            if week == 0:
                continue
            prior_total = sum(
                assign[fellow_idx, prior_week, block_idx]
                for prior_week in range(week)
                for block_idx in prerequisite_indices
            )
            has_prereq = model.NewBoolVar(f"call_first_prereq_has_f{fellow_idx}_w{week}")
            model.Add(prior_total >= 1).OnlyEnforceIf(has_prereq)
            model.Add(prior_total == 0).OnlyEnforceIf(has_prereq.Not())

            match_var = model.NewBoolVar(f"call_first_prereq_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= first_call)
            model.Add(match_var <= has_prereq)
            model.Add(match_var >= first_call + has_prereq - 1)
            objective_terms.append(match_var * config.call_first_call_prerequisite_weight)
    return objective_terms


def _build_holiday_call_avoidance_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Penalize holiday call after an intense Thanksgiving-week service."""

    if (
        config.call_holiday_anchor_week is None
        or not config.call_holiday_target_weeks
        or not config.call_holiday_sensitive_blocks
        or config.call_holiday_conflict_weight == 0
    ):
        return []

    sensitive_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_holiday_sensitive_blocks
        if block_name in block_name_to_idx
    ]
    if not sensitive_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    anchor_week = config.call_holiday_anchor_week
    if not 0 <= anchor_week < config.num_weeks:
        return []

    holiday_weeks = [
        week for week in config.call_holiday_target_weeks if 0 <= week < config.num_weeks
    ]
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        sensitive_assignment = sum(
            assign[fellow_idx, anchor_week, block_idx] for block_idx in sensitive_indices
        )
        for holiday_week in holiday_weeks:
            conflict_var = model.NewBoolVar(
                f"call_holiday_conflict_f{fellow_idx}_w{holiday_week}"
            )
            model.Add(conflict_var <= sensitive_assignment)
            model.Add(conflict_var <= call[fellow_idx, holiday_week])
            model.Add(
                conflict_var >= sensitive_assignment + call[fellow_idx, holiday_week] - 1
            )
            objective_terms.append(conflict_var * config.call_holiday_conflict_weight)
    return objective_terms


def _build_call_next_week_block_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Penalize 24-hour call immediately before selected next-week blocks."""

    if (
        not config.call_soft_forbidden_next_week_blocks
        or config.call_soft_forbidden_next_week_weight == 0
    ):
        return []

    target_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_soft_forbidden_next_week_blocks
        if block_name in block_name_to_idx
    ]
    if not target_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        for week in range(config.num_weeks - 1):
            next_week_match = sum(
                assign[fellow_idx, week + 1, block_idx] for block_idx in target_indices
            )
            match_var = model.NewBoolVar(f"call_next_week_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= call[fellow_idx, week])
            model.Add(match_var <= next_week_match)
            model.Add(match_var >= call[fellow_idx, week] + next_week_match - 1)
            objective_terms.append(match_var * config.call_soft_forbidden_next_week_weight)
    return objective_terms


def _build_call_current_block_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Penalize 24-hour call on selected current-week rotations."""

    if (
        not config.call_soft_disfavored_current_blocks
        or config.call_soft_disfavored_current_weight == 0
    ):
        return []

    target_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_soft_disfavored_current_blocks
        if block_name in block_name_to_idx
    ]
    if not target_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        for week in range(config.num_weeks):
            current_week_match = sum(
                assign[fellow_idx, week, block_idx] for block_idx in target_indices
            )
            match_var = model.NewBoolVar(f"call_current_block_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= call[fellow_idx, week])
            model.Add(match_var <= current_week_match)
            model.Add(match_var >= call[fellow_idx, week] + current_week_match - 1)
            objective_terms.append(match_var * config.call_soft_disfavored_current_weight)
    return objective_terms


def _build_srcva_weekend_next_week_block_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[cp_model.LinearExpr]:
    """Penalize weekend SRC/VA call immediately before selected next-week blocks."""

    if (
        not config.srcva_weekend_soft_forbidden_next_week_blocks
        or config.srcva_weekend_soft_forbidden_next_week_weight == 0
    ):
        return []

    target_indices = [
        block_name_to_idx[block_name]
        for block_name in config.srcva_weekend_soft_forbidden_next_week_blocks
        if block_name in block_name_to_idx
    ]
    if not target_indices:
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years):
        for week in range(config.num_weeks - 1):
            next_week_match = sum(
                assign[fellow_idx, week + 1, block_idx] for block_idx in target_indices
            )
            match_var = model.NewBoolVar(f"srcva_weekend_next_week_match_f{fellow_idx}_w{week}")
            model.Add(match_var <= weekend_call[fellow_idx, week])
            model.Add(match_var <= next_week_match)
            model.Add(match_var >= weekend_call[fellow_idx, week] + next_week_match - 1)
            objective_terms.append(
                match_var * config.srcva_weekend_soft_forbidden_next_week_weight
            )
    return objective_terms


def _build_srcva_weekend_consecutive_terms(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> list[cp_model.LinearExpr]:
    """Penalize consecutive-week SRC/VA weekend call on the same fellow."""

    if (
        not config.srcva_weekend_call_enabled
        or config.srcva_weekend_consecutive_same_fellow_weight == 0
    ):
        return []

    objective_terms: list[cp_model.LinearExpr] = []
    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years):
        for week in range(config.num_weeks - 1):
            match_var = model.NewBoolVar(
                f"srcva_weekend_consecutive_match_f{fellow_idx}_w{week}"
            )
            model.Add(match_var <= weekend_call[fellow_idx, week])
            model.Add(match_var <= weekend_call[fellow_idx, week + 1])
            model.Add(
                match_var
                >= weekend_call[fellow_idx, week] + weekend_call[fellow_idx, week + 1] - 1
            )
            objective_terms.append(
                match_var * config.srcva_weekend_consecutive_same_fellow_weight
            )
    return objective_terms


def _first_call_week_var(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    fellow_idx: int,
    week: int,
    name_prefix: str,
) -> cp_model.IntVar:
    """Return a bool var for 'this is the fellow's first call week'."""

    current_call = call[fellow_idx, week]
    if week == 0:
        return current_call

    prior_total = sum(call[fellow_idx, prior_week] for prior_week in range(week))
    has_prior = model.NewBoolVar(f"{name_prefix}_has_prior_f{fellow_idx}_w{week}")
    model.Add(prior_total >= 1).OnlyEnforceIf(has_prior)
    model.Add(prior_total == 0).OnlyEnforceIf(has_prior.Not())

    first_call = model.NewBoolVar(f"{name_prefix}_f{fellow_idx}_w{week}")
    model.Add(first_call <= current_call)
    model.Add(first_call <= has_prior.Not())
    model.Add(first_call >= current_call - has_prior)
    return first_call


def _build_sequence_match_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    fellow_idx: int,
    week: int,
    left_indices: list[int],
    right_indices: list[int],
    weight: int,
    name_prefix: str,
) -> list[cp_model.LinearExpr]:
    """Build one conjunction variable for an adjacent block pattern."""

    left_expr = sum(assign[fellow_idx, week, block_idx] for block_idx in left_indices)
    right_expr = sum(
        assign[fellow_idx, week + 1, block_idx] for block_idx in right_indices
    )
    match_var = model.NewBoolVar(name_prefix)
    model.Add(match_var <= left_expr)
    model.Add(match_var <= right_expr)
    model.Add(match_var >= left_expr + right_expr - 1)
    return [match_var * weight]


def _single_week_rule_block_indices(
    rule: SoftSingleWeekBlockRule,
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> list[int]:
    """Return active block indices targeted by a same-rotation bonus rule."""

    included_states = set(rule.included_states)
    excluded_states = set(rule.excluded_states)
    return [
        block_name_to_idx[block.name]
        for block in config.blocks
        if block.is_active
        and block.name in block_name_to_idx
        and (not included_states or block.name in included_states)
        and block.name not in excluded_states
    ]


def _first_state_adjacent_exempt_weeks(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    fellow_idx: int,
    state_idx: int | None,
    name_prefix: str,
) -> dict[int, cp_model.IntVar]:
    """Return bool vars marking weeks immediately before a first state start."""

    if state_idx is None:
        return {}

    first_start_vars: list[cp_model.IntVar] = []
    for week in range(config.num_weeks):
        start_var = model.NewBoolVar(f"{name_prefix}_start_w{week}")
        current = assign[fellow_idx, week, state_idx]
        if week == 0:
            model.Add(start_var == current)
        else:
            prior_total = sum(assign[fellow_idx, prior_week, state_idx] for prior_week in range(week))
            has_prior = model.NewBoolVar(f"{name_prefix}_has_prior_w{week}")
            model.Add(prior_total >= 1).OnlyEnforceIf(has_prior)
            model.Add(prior_total == 0).OnlyEnforceIf(has_prior.Not())
            model.Add(start_var <= current)
            model.Add(start_var + has_prior <= 1)
            model.Add(start_var >= current - has_prior)
        first_start_vars.append(start_var)

    exempt_weeks: dict[int, cp_model.IntVar] = {}
    for week in range(config.num_weeks):
        exempt_var = model.NewBoolVar(f"{name_prefix}_adjacent_w{week}")
        if week + 1 >= config.num_weeks:
            model.Add(exempt_var == 0)
        else:
            model.Add(exempt_var == first_start_vars[week + 1])
        exempt_weeks[week] = exempt_var
    return exempt_weeks


def _build_single_week_match_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    fellow_idx: int,
    week: int,
    block_idx: int,
    weight: int,
    exempt_weeks: dict[int, cp_model.IntVar],
    name_prefix: str,
) -> list[cp_model.LinearExpr]:
    """Build one conjunction variable for a one-week run of one block."""

    current = assign[fellow_idx, week, block_idx]
    previous = assign[fellow_idx, week - 1, block_idx] if week > 0 else None
    next_assignment = (
        assign[fellow_idx, week + 1, block_idx]
        if week + 1 < config.num_weeks
        else None
    )

    single_week = model.NewBoolVar(name_prefix)
    model.Add(single_week <= current)
    if previous is not None:
        model.Add(single_week + previous <= 1)
    if next_assignment is not None:
        model.Add(single_week + next_assignment <= 1)

    lower_bound = current
    if previous is not None:
        lower_bound -= previous
    if next_assignment is not None:
        lower_bound -= next_assignment
    model.Add(single_week >= lower_bound)

    exempt_var = exempt_weeks.get(week)
    if exempt_var is None:
        return [single_week * weight]

    active_single_week = model.NewBoolVar(f"{name_prefix}_active")
    model.Add(active_single_week <= single_week)
    model.Add(active_single_week + exempt_var <= 1)
    model.Add(active_single_week >= single_week - exempt_var)
    return [active_single_week * weight]


def _extract_solution(
    solver: cp_model.CpSolver,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    srcva_weekend_call: dict[tuple[int, int], cp_model.IntVar],
    srcva_weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    status: SolverStatus,
    objective: float,
    solve_time: float,
) -> ScheduleResult:
    """Read the solver's values and build a ``ScheduleResult``."""

    block_names = [block.name for block in config.blocks] + ["PTO"]
    assignments: list[list[str]] = []
    call_assignments: list[list[bool]] = []
    srcva_weekend_call_assignments: list[list[bool]] = []
    srcva_weekday_call_assignments: list[list[list[bool]]] = []

    for fellow_idx in range(config.num_fellows):
        fellow_blocks: list[str] = []
        fellow_calls: list[bool] = []
        fellow_weekend_calls: list[bool] = []
        fellow_weekday_calls: list[list[bool]] = []
        for week in range(config.num_weeks):
            assigned_block = "UNASSIGNED"
            for block_idx in range(num_blocks + 1):
                if solver.Value(assign[fellow_idx, week, block_idx]) == 1:
                    assigned_block = block_names[block_idx]
                    break
            fellow_blocks.append(assigned_block)
            fellow_calls.append(bool(solver.Value(call[fellow_idx, week])))
            fellow_weekend_calls.append(bool(solver.Value(srcva_weekend_call[fellow_idx, week])))
            fellow_weekday_calls.append(
                [
                    bool(solver.Value(srcva_weekday_call[fellow_idx, week, day_idx]))
                    for day_idx in range(4)
                ]
            )
        assignments.append(fellow_blocks)
        call_assignments.append(fellow_calls)
        srcva_weekend_call_assignments.append(fellow_weekend_calls)
        srcva_weekday_call_assignments.append(fellow_weekday_calls)

    objective_breakdown = _build_objective_breakdown(
        config,
        assignments,
        call_assignments,
        srcva_weekend_call_assignments,
        srcva_weekday_call_assignments,
    )
    return ScheduleResult(
        assignments=assignments,
        call_assignments=call_assignments,
        srcva_weekend_call_assignments=srcva_weekend_call_assignments,
        srcva_weekday_call_assignments=srcva_weekday_call_assignments,
        solver_status=status,
        objective_value=objective,
        solve_time_seconds=solve_time,
        objective_breakdown=objective_breakdown,
    )


def _empty_cohort_score_row(category: str) -> dict[str, int | str]:
    """Return one objective-breakdown row initialized to zero."""

    row: dict[str, int | str] = {"Category": category}
    for year in TrainingYear:
        row[year.value] = 0
    row["Total"] = 0
    return row


def _block_list_label(block_names: list[str]) -> str:
    """Return a compact human-readable label for one or more block names."""

    if not block_names:
        return "selected blocks"
    if len(block_names) == 1:
        return block_names[0]
    if len(block_names) == 2:
        return f"{block_names[0]} or {block_names[1]}"
    return ", ".join(block_names[:-1]) + f", or {block_names[-1]}"


def _add_points_to_row(
    row: dict[str, int | str],
    year: TrainingYear,
    points: int,
) -> None:
    """Add points to one cohort/category cell and the category total."""

    row[year.value] = int(row[year.value]) + points
    row["Total"] = int(row["Total"]) + points


def _build_objective_breakdown(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
    srcva_weekend_call_assignments: list[list[bool]],
    srcva_weekday_call_assignments: list[list[list[bool]]],
) -> list[dict[str, int | str]]:
    """Recompute objective points by category and cohort for the solved schedule."""

    rows: list[dict[str, int | str]] = []
    rows.append(_build_pto_objective_breakdown_row(config, assignments))
    rows.extend(_build_soft_sequence_breakdown_rows(config, assignments))
    rows.extend(_build_soft_single_week_block_breakdown_rows(config, assignments))
    rows.extend(_build_soft_state_assignment_breakdown_rows(config, assignments))
    rows.extend(_build_soft_fixed_week_pair_breakdown_rows(config, assignments))
    rows.extend(_build_soft_cohort_balance_breakdown_rows(config, assignments))
    rows.extend(_build_structured_call_breakdown_rows(config, assignments, call_assignments))
    rows.extend(
        _build_srcva_call_breakdown_rows(
            config,
            call_assignments,
            assignments,
            srcva_weekend_call_assignments,
            srcva_weekday_call_assignments,
        )
    )

    total_row = _empty_cohort_score_row("Total")
    for row in rows:
        for year in TrainingYear:
            _add_points_to_row(total_row, year, int(row[year.value]))
    rows.append(total_row)
    return rows


def _build_srcva_call_breakdown_rows(
    config: ScheduleConfig,
    call_assignments: list[list[bool]],
    assignments: list[list[str]],
    weekend_call_assignments: list[list[bool]],
    weekday_call_assignments: list[list[list[bool]]],
) -> list[dict[str, int | str]]:
    """Return objective-breakdown rows for SRC/VA overlay-call soft preferences."""

    if not (config.srcva_weekend_call_enabled or config.srcva_weekday_call_enabled):
        return []

    rows: list[dict[str, int | str]] = []
    rows.append(
        _build_srcva_holiday_preference_breakdown_row(
            config,
            assignments,
            weekend_call_assignments,
            weekday_call_assignments,
        )
    )
    rows.append(
        _build_srcva_holiday_repeat_breakdown_row(
            config,
            weekend_call_assignments,
            weekday_call_assignments,
        )
    )
    rows.append(
        _build_srcva_weekday_max_one_per_week_breakdown_row(
            config,
            weekday_call_assignments,
        )
    )
    rows.append(
        _build_srcva_weekday_same_week_as_weekend_breakdown_row(
            config,
            weekend_call_assignments,
            weekday_call_assignments,
        )
    )
    rows.append(
        _build_srcva_weekday_same_week_as_24hr_breakdown_row(
            config,
            call_assignments,
            weekday_call_assignments,
        )
    )
    rows.append(
        _build_srcva_weekend_next_week_block_breakdown_row(
            config,
            assignments,
            weekend_call_assignments,
        )
    )
    rows.append(
        _build_srcva_weekend_consecutive_breakdown_row(
            config,
            weekend_call_assignments,
        )
    )
    return rows


def _build_structured_call_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> list[dict[str, int | str]]:
    """Return objective-breakdown rows for structured call soft preferences."""

    if not config.structured_call_rules_enabled:
        return []

    rows: list[dict[str, int | str]] = []
    rows.append(_build_first_call_preferred_block_breakdown_row(config, assignments, call_assignments))
    rows.append(_build_first_call_prerequisite_breakdown_row(config, assignments, call_assignments))
    rows.append(_build_holiday_call_avoidance_breakdown_row(config, assignments, call_assignments))
    rows.append(_build_call_next_week_block_breakdown_row(config, assignments, call_assignments))
    rows.append(_build_call_current_block_breakdown_row(config, assignments, call_assignments))
    return rows


def _build_pto_objective_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> dict[str, int | str]:
    """Return PTO objective points grouped by cohort."""

    row = _empty_cohort_score_row("PTO Preferences")
    for fellow_idx, fellow in enumerate(config.fellows):
        cohort_weights = config.pto_preference_weights_for_year(fellow.training_year)
        for rank, week_idx in enumerate(fellow.pto_rankings):
            if rank >= len(cohort_weights):
                continue
            if not 0 <= week_idx < config.num_weeks:
                continue
            score = cohort_weights[rank]
            if score <= 0:
                continue
            if assignments[fellow_idx][week_idx] == "PTO":
                _add_points_to_row(row, fellow.training_year, score)
    return row


def _build_soft_sequence_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> list[dict[str, int | str]]:
    """Return one objective-breakdown row per active soft rule."""

    rows: list[dict[str, int | str]] = []
    valid_states = set(config.all_states)
    for rule in config.soft_sequence_rules:
        if not rule.is_active:
            continue

        row = _empty_cohort_score_row(rule.name)
        forward_left = {state for state in rule.left_states if state in valid_states}
        forward_right = {state for state in rule.right_states if state in valid_states}
        if not forward_left or not forward_right:
            rows.append(row)
            continue

        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        allow_reverse = (
            rule.direction == SoftRuleDirection.EITHER
            and forward_left != forward_right
        )

        for fellow_idx in fellow_indices:
            year = config.fellows[fellow_idx].training_year
            for week in range(max(0, rule.start_week), end_week):
                current_state = assignments[fellow_idx][week]
                next_state = assignments[fellow_idx][week + 1]
                if current_state in forward_left and next_state in forward_right:
                    _add_points_to_row(row, year, rule.weight)
                if allow_reverse and current_state in forward_right and next_state in forward_left:
                    _add_points_to_row(row, year, rule.weight)

        rows.append(row)
    return rows


def _build_soft_single_week_block_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> list[dict[str, int | str]]:
    """Return one objective-breakdown row per active same-rotation bonus rule."""

    rows: list[dict[str, int | str]] = []
    for rule in config.soft_single_week_block_rules:
        if not rule.is_active:
            continue

        row = _empty_cohort_score_row(rule.name)
        included_states = set(rule.included_states)
        excluded_states = set(rule.excluded_states)
        candidate_states = {
            block.name
            for block in config.blocks
            if block.is_active
            and (not included_states or block.name in included_states)
            and block.name not in excluded_states
        }
        if not candidate_states:
            rows.append(row)
            continue

        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for fellow_idx in fellow_indices:
            year = config.fellows[fellow_idx].training_year
            for week in range(max(0, rule.start_week), end_week):
                state = assignments[fellow_idx][week]
                if state not in candidate_states:
                    continue
                if assignments[fellow_idx][week + 1] == state:
                    _add_points_to_row(row, year, rule.weight)

        rows.append(row)
    return rows


def _build_soft_state_assignment_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> list[dict[str, int | str]]:
    """Return one objective-breakdown row per active state-assignment rule."""

    rows: list[dict[str, int | str]] = []
    valid_states = set(config.all_states)
    for rule in config.soft_state_assignment_rules:
        if not rule.is_active:
            continue

        row = _empty_cohort_score_row(rule.name)
        target_states = {state for state in rule.state_names if state in valid_states}
        if not target_states:
            rows.append(row)
            continue

        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for fellow_idx in fellow_indices:
            year = config.fellows[fellow_idx].training_year
            for week in range(max(0, rule.start_week), end_week + 1):
                if assignments[fellow_idx][week] in target_states:
                    _add_points_to_row(row, year, rule.weight)

        rows.append(row)
    return rows


def _build_soft_fixed_week_pair_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> list[dict[str, int | str]]:
    """Return one objective-breakdown row per active fixed-week pairing rule."""

    rows: list[dict[str, int | str]] = []
    valid_states = set(config.all_states)
    for rule in config.soft_fixed_week_pair_rules:
        if not rule.is_active:
            continue

        row = _empty_cohort_score_row(rule.name)
        if not (
            0 <= rule.first_week < config.num_weeks
            and 0 <= rule.second_week < config.num_weeks
        ):
            rows.append(row)
            continue

        trigger_states = {
            state for state in rule.trigger_states if state in valid_states
        }
        paired_states = {
            state for state in rule.paired_states if state in valid_states
        }
        if not trigger_states or not paired_states:
            rows.append(row)
            continue

        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        for fellow_idx in fellow_indices:
            year = config.fellows[fellow_idx].training_year
            first_state = assignments[fellow_idx][rule.first_week]
            second_state = assignments[fellow_idx][rule.second_week]
            if (
                first_state in trigger_states and second_state in paired_states
            ) or (
                first_state in paired_states and second_state in trigger_states
            ):
                _add_points_to_row(row, year, rule.weight)

        rows.append(row)
    return rows


def _build_soft_cohort_balance_breakdown_rows(
    config: ScheduleConfig,
    assignments: list[list[str]],
) -> list[dict[str, int | str]]:
    """Return one objective-breakdown row per active cohort-balance rule."""

    rows: list[dict[str, int | str]] = []
    valid_states = set(config.all_states)
    for rule in config.soft_cohort_balance_rules:
        if not rule.is_active:
            continue

        row = _empty_cohort_score_row(rule.name)
        target_states = {state for state in rule.state_names if state in valid_states}
        if not target_states or rule.weight <= 0:
            rows.append(row)
            continue

        end_week = _resolve_rule_end_week(rule.end_week, config.num_weeks)
        for year in rule.applicable_years:
            fellow_indices = config.fellow_indices_for_years([year])
            if len(fellow_indices) < 2:
                continue

            counts: dict[int, int] = {}
            for fellow_idx in fellow_indices:
                counts[fellow_idx] = sum(
                    1
                    for week in range(max(0, rule.start_week), end_week + 1)
                    if assignments[fellow_idx][week] in target_states
                )

            ordered_fellows = sorted(fellow_indices)
            for left_pos, left_idx in enumerate(ordered_fellows):
                for right_idx in ordered_fellows[left_pos + 1 :]:
                    _add_points_to_row(
                        row,
                        year,
                        -rule.weight * abs(counts[left_idx] - counts[right_idx]),
                    )

        rows.append(row)
    return rows


def _build_first_call_preferred_block_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the first-call preferred-block bonus by cohort."""

    row = _empty_cohort_score_row("Bonus: Preferred rotation during first 24-hr call")
    if (
        not config.call_first_call_preferred_blocks
        or config.call_first_call_preference_weight == 0
    ):
        return row

    preferred_blocks = set(config.call_first_call_preferred_blocks)
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            if not call_assignments[fellow_idx][week]:
                continue
            if assignments[fellow_idx][week] in preferred_blocks:
                _add_points_to_row(row, year, config.call_first_call_preference_weight)
            break
    return row


def _build_first_call_prerequisite_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the first-call prior-experience bonus by cohort."""

    row = _empty_cohort_score_row("Bonus: Prior prerequisite before first 24-hr call")
    if (
        not config.call_first_call_prerequisite_blocks
        or config.call_first_call_prerequisite_weight == 0
    ):
        return row

    prerequisite_blocks = set(config.call_first_call_prerequisite_blocks)
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            if not call_assignments[fellow_idx][week]:
                continue
            if any(assignments[fellow_idx][prior_week] in prerequisite_blocks for prior_week in range(week)):
                _add_points_to_row(row, year, config.call_first_call_prerequisite_weight)
            break
    return row


def _build_holiday_call_avoidance_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the holiday-call avoidance penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: Holiday call after Thanksgiving heavy service")
    anchor_week = config.call_holiday_anchor_week
    if (
        anchor_week is None
        or not 0 <= anchor_week < config.num_weeks
        or not config.call_holiday_target_weeks
        or not config.call_holiday_sensitive_blocks
        or config.call_holiday_conflict_weight == 0
    ):
        return row

    sensitive_blocks = set(config.call_holiday_sensitive_blocks)
    holiday_weeks = [week for week in config.call_holiday_target_weeks if 0 <= week < config.num_weeks]
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        if assignments[fellow_idx][anchor_week] not in sensitive_blocks:
            continue
        for holiday_week in holiday_weeks:
            if call_assignments[fellow_idx][holiday_week]:
                _add_points_to_row(row, year, config.call_holiday_conflict_weight)
    return row


def _build_call_next_week_block_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the next-week 24-hour call penalty by cohort."""

    row = _empty_cohort_score_row(
        f"Penalty: 24-hr call before {_block_list_label(config.call_soft_forbidden_next_week_blocks)}"
    )
    if (
        not config.call_soft_forbidden_next_week_blocks
        or config.call_soft_forbidden_next_week_weight == 0
    ):
        return row

    target_blocks = set(config.call_soft_forbidden_next_week_blocks)
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks - 1):
            if call_assignments[fellow_idx][week] and assignments[fellow_idx][week + 1] in target_blocks:
                _add_points_to_row(row, year, config.call_soft_forbidden_next_week_weight)
    return row


def _build_call_current_block_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the current-rotation 24-hour call penalty by cohort."""

    row = _empty_cohort_score_row(
        f"Penalty: 24-hr call on {_block_list_label(config.call_soft_disfavored_current_blocks)}"
    )
    if (
        not config.call_soft_disfavored_current_blocks
        or config.call_soft_disfavored_current_weight == 0
    ):
        return row

    target_blocks = set(config.call_soft_disfavored_current_blocks)
    for fellow_idx in config.fellow_indices_for_years(config.call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            if call_assignments[fellow_idx][week] and assignments[fellow_idx][week] in target_blocks:
                _add_points_to_row(row, year, config.call_soft_disfavored_current_weight)
    return row


def _build_srcva_holiday_preference_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    weekend_call_assignments: list[list[bool]],
    weekday_call_assignments: list[list[list[bool]]],
) -> dict[str, int | str]:
    """Return the Christmas-week SRC/VA call anchor bonus by cohort."""

    row = _empty_cohort_score_row(
        "Bonus: Thanksgiving-week anchor before Christmas SRC/VA call"
    )
    anchor_week = config.srcva_holiday_anchor_week
    christmas_week = config.srcva_christmas_target_week
    if (
        anchor_week is None
        or christmas_week is None
        or not 0 <= anchor_week < config.num_weeks
        or not 0 <= christmas_week < config.num_weeks
        or config.srcva_holiday_preference_weight == 0
    ):
        return row

    preferred_blocks = set(config.srcva_holiday_preferred_anchor_blocks)
    eligible_years = set(
        config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years
    )
    for fellow_idx in config.fellow_indices_for_years(list(eligible_years)):
        year = config.fellows[fellow_idx].training_year
        has_christmas_call = weekend_call_assignments[fellow_idx][christmas_week] or any(
            weekday_call_assignments[fellow_idx][christmas_week]
        )
        if assignments[fellow_idx][anchor_week] in preferred_blocks and has_christmas_call:
            _add_points_to_row(row, year, config.srcva_holiday_preference_weight)
    return row


def _build_srcva_holiday_repeat_breakdown_row(
    config: ScheduleConfig,
    weekend_call_assignments: list[list[bool]],
    weekday_call_assignments: list[list[list[bool]]],
) -> dict[str, int | str]:
    """Return the repeated-holiday SRC/VA call penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: Repeated holiday SRC/VA call assignments")
    christmas_week = config.srcva_christmas_target_week
    if (
        christmas_week is None
        or not 0 <= christmas_week < config.num_weeks
        or config.srcva_holiday_repeat_weight == 0
    ):
        return row

    eligible_years = set(
        config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years
    )
    for fellow_idx in config.fellow_indices_for_years(list(eligible_years)):
        year = config.fellows[fellow_idx].training_year
        christmas_call = weekend_call_assignments[fellow_idx][christmas_week] or any(
            weekday_call_assignments[fellow_idx][christmas_week]
        )
        if config.srcva_holiday_anchor_week is not None and 0 <= config.srcva_holiday_anchor_week < config.num_weeks:
            anchor_call = weekend_call_assignments[fellow_idx][config.srcva_holiday_anchor_week] or any(
                weekday_call_assignments[fellow_idx][config.srcva_holiday_anchor_week]
            )
            if anchor_call and christmas_call:
                _add_points_to_row(row, year, config.srcva_holiday_repeat_weight)
        if config.srcva_new_year_target_week is not None and 0 <= config.srcva_new_year_target_week < config.num_weeks:
            new_year_call = weekend_call_assignments[fellow_idx][config.srcva_new_year_target_week] or any(
                weekday_call_assignments[fellow_idx][config.srcva_new_year_target_week]
            )
            if christmas_call and new_year_call:
                _add_points_to_row(row, year, config.srcva_holiday_repeat_weight)
    return row


def _build_srcva_weekday_max_one_per_week_breakdown_row(
    config: ScheduleConfig,
    weekday_call_assignments: list[list[list[bool]]],
) -> dict[str, int | str]:
    """Return the per-excess-night weekday-call penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: More than one SRC/VA weekday call in one week")
    if not config.srcva_weekday_call_enabled or config.srcva_weekday_max_one_per_week_weight == 0:
        return row

    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekday_call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            weekday_count = sum(1 for assigned in weekday_call_assignments[fellow_idx][week] if assigned)
            if weekday_count > 1:
                _add_points_to_row(
                    row,
                    year,
                    (weekday_count - 1) * config.srcva_weekday_max_one_per_week_weight,
                )
    return row


def _build_srcva_weekday_same_week_as_weekend_breakdown_row(
    config: ScheduleConfig,
    weekend_call_assignments: list[list[bool]],
    weekday_call_assignments: list[list[list[bool]]],
) -> dict[str, int | str]:
    """Return the same-week weekday/weekend SRC/VA call penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: SRC/VA weekday and weekend call in same week")
    if config.srcva_weekday_same_week_as_weekend_weight == 0:
        return row

    eligible_years = set(
        config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years
    )
    for fellow_idx in config.fellow_indices_for_years(list(eligible_years)):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            if weekend_call_assignments[fellow_idx][week] and any(
                weekday_call_assignments[fellow_idx][week]
            ):
                _add_points_to_row(row, year, config.srcva_weekday_same_week_as_weekend_weight)
    return row


def _build_srcva_weekday_same_week_as_24hr_breakdown_row(
    config: ScheduleConfig,
    call_assignments: list[list[bool]],
    weekday_call_assignments: list[list[list[bool]]],
) -> dict[str, int | str]:
    """Return the same-week SRC/VA weekday and 24-hour call penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: SRC/VA weekday and 24-hr call in same week")
    if config.srcva_weekday_same_week_as_24hr_weight == 0:
        return row

    eligible_years = set(config.srcva_weekday_call_eligible_years + config.call_eligible_years)
    for fellow_idx in config.fellow_indices_for_years(list(eligible_years)):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks):
            if call_assignments[fellow_idx][week] and any(
                weekday_call_assignments[fellow_idx][week]
            ):
                _add_points_to_row(row, year, config.srcva_weekday_same_week_as_24hr_weight)
    return row


def _build_srcva_weekend_next_week_block_breakdown_row(
    config: ScheduleConfig,
    assignments: list[list[str]],
    weekend_call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the next-week weekend SRC/VA call penalty by cohort."""

    row = _empty_cohort_score_row(
        "Penalty: SRC/VA weekend call before "
        f"{_block_list_label(config.srcva_weekend_soft_forbidden_next_week_blocks)}"
    )
    if (
        not config.srcva_weekend_soft_forbidden_next_week_blocks
        or config.srcva_weekend_soft_forbidden_next_week_weight == 0
    ):
        return row

    target_blocks = set(config.srcva_weekend_soft_forbidden_next_week_blocks)
    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks - 1):
            if (
                weekend_call_assignments[fellow_idx][week]
                and assignments[fellow_idx][week + 1] in target_blocks
            ):
                _add_points_to_row(row, year, config.srcva_weekend_soft_forbidden_next_week_weight)
    return row


def _build_srcva_weekend_consecutive_breakdown_row(
    config: ScheduleConfig,
    weekend_call_assignments: list[list[bool]],
) -> dict[str, int | str]:
    """Return the consecutive-weekend SRC/VA penalty by cohort."""

    row = _empty_cohort_score_row("Penalty: Consecutive SRC/VA weekend calls")
    if (
        not config.srcva_weekend_call_enabled
        or config.srcva_weekend_consecutive_same_fellow_weight == 0
    ):
        return row

    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years):
        year = config.fellows[fellow_idx].training_year
        for week in range(config.num_weeks - 1):
            if weekend_call_assignments[fellow_idx][week] and weekend_call_assignments[fellow_idx][week + 1]:
                _add_points_to_row(row, year, config.srcva_weekend_consecutive_same_fellow_weight)
    return row


def _first_state_adjacent_exempt_weeks_from_assignments(
    assignments: list[str],
    exempt_state: str | None,
) -> set[int]:
    """Return week indices immediately before the first exempt-state start."""

    if not exempt_state:
        return set()

    first_index = next(
        (index for index, state in enumerate(assignments) if state == exempt_state),
        None,
    )
    if first_index is None or first_index == 0:
        return set()
    return {first_index - 1}
