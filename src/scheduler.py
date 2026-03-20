"""Main scheduling engine — orchestrates the CP-SAT solver."""

from __future__ import annotations

import time

from ortools.sat.python import cp_model

from src.acgme import add_trailing_hours_cap
from src.call_scheduler import add_call_constraints
from src.constraints import (
    add_block_completion,
    add_cohort_limit_rules,
    add_consecutive_state_limit_rules,
    add_coverage_rules,
    add_eligibility_rules,
    add_first_assignment_run_limit_rules,
    add_first_assignment_pairing_rules,
    add_forbidden_transition_rules,
    add_individual_fellow_requirement_rules,
    add_max_concurrent_pto,
    add_min_max_weeks_per_block,
    add_night_float_consecutive_limit,
    add_no_consecutive_same_block,
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
    SoftRuleDirection,
    SoftSingleWeekBlockRule,
    SolverStatus,
    TrainingYear,
)


def _sync_num_fellows(config: ScheduleConfig) -> None:
    """Keep the legacy ``num_fellows`` field aligned with the roster."""

    config.num_fellows = len(config.fellows)


def _resolve_rule_end_week(end_week: int | None, num_weeks: int) -> int:
    """Clamp a rule window to the schedule length."""

    return num_weeks - 1 if end_week is None else min(end_week, num_weeks - 1)


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


def solve_schedule(config: ScheduleConfig) -> ScheduleResult:
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

    for block_idx, block in enumerate(config.blocks):
        if block.is_active:
            continue
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                model.Add(assign[fellow_idx, week, block_idx] == 0)

    add_one_assignment_per_week(model, assign, config, num_blocks, pto_idx)
    add_unavailable_weeks(model, assign, config, pto_idx)
    add_pto_count(model, assign, config, pto_idx)
    add_max_concurrent_pto(model, assign, config, pto_idx)
    add_no_consecutive_same_block(model, assign, config, num_blocks)

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
        or config.first_assignment_pairing_rules
        or config.individual_fellow_requirement_rules
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
        add_first_assignment_pairing_rules(model, assign, config, block_name_to_idx)
        add_individual_fellow_requirement_rules(model, assign, config, block_name_to_idx)
        add_prerequisite_rules(model, assign, config, block_name_to_idx)
        add_forbidden_transition_rules(model, assign, config, block_name_to_idx)
    else:
        add_block_completion(model, assign, config, num_blocks)

    add_min_max_weeks_per_block(model, assign, config, num_blocks)
    add_staffing_coverage(model, assign, config, num_blocks)
    add_trailing_hours_cap(model, assign, call, config, num_blocks, pto_idx)
    add_call_constraints(model, assign, call, config, num_blocks, pto_idx)

    objective_terms = _build_objective_terms(
        model,
        assign,
        config,
        pto_idx,
        block_name_to_idx,
    )
    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_timeout_seconds
    solver.parameters.num_workers = 8

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
        solver_status=solver_status,
        objective_value=0.0,
        solve_time_seconds=solve_time,
    )


def _build_objective_terms(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
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

    excluded_states = set(rule.excluded_states)
    return [
        block_name_to_idx[block.name]
        for block in config.blocks
        if block.is_active
        and block.name in block_name_to_idx
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

    for fellow_idx in range(config.num_fellows):
        fellow_blocks: list[str] = []
        fellow_calls: list[bool] = []
        for week in range(config.num_weeks):
            assigned_block = "UNASSIGNED"
            for block_idx in range(num_blocks + 1):
                if solver.Value(assign[fellow_idx, week, block_idx]) == 1:
                    assigned_block = block_names[block_idx]
                    break
            fellow_blocks.append(assigned_block)
            fellow_calls.append(bool(solver.Value(call[fellow_idx, week])))
        assignments.append(fellow_blocks)
        call_assignments.append(fellow_calls)

    objective_breakdown = _build_objective_breakdown(config, assignments)
    return ScheduleResult(
        assignments=assignments,
        call_assignments=call_assignments,
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
) -> list[dict[str, int | str]]:
    """Recompute objective points by category and cohort for the solved schedule."""

    rows: list[dict[str, int | str]] = []
    rows.append(_build_pto_objective_breakdown_row(config, assignments))
    rows.extend(_build_soft_sequence_breakdown_rows(config, assignments))
    rows.extend(_build_soft_single_week_block_breakdown_rows(config, assignments))

    total_row = _empty_cohort_score_row("Total")
    for row in rows:
        for year in TrainingYear:
            _add_points_to_row(total_row, year, int(row[year.value]))
    rows.append(total_row)
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
        candidate_states = {
            block.name
            for block in config.blocks
            if block.is_active and block.name not in set(rule.excluded_states)
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
