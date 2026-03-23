"""Constraint builder functions for the CP-SAT solver."""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.models import ScheduleConfig


def _week_range(
    start_week: int,
    end_week: int | None,
    num_weeks: int,
) -> range:
    """Return a clamped inclusive week range."""

    start = max(0, start_week)
    end = num_weeks - 1 if end_week is None else min(end_week, num_weeks - 1)
    if end < start:
        return range(0)
    return range(start, end + 1)


def add_one_assignment_per_week(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Each fellow must be on exactly one block or PTO every week."""

    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            model.Add(
                sum(assign[fellow_idx, week, block] for block in range(num_blocks + 1))
                == 1
            )


def add_unavailable_weeks(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Force unavailable weeks to PTO."""

    for fellow_idx, fellow in enumerate(config.fellows):
        for week in fellow.unavailable_weeks:
            if 0 <= week < config.num_weeks:
                model.Add(assign[fellow_idx, week, pto_idx] == 1)


def add_pto_count(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Each fellow gets exactly ``pto_weeks_granted`` PTO weeks."""

    for fellow_idx in range(config.num_fellows):
        model.Add(
            sum(assign[fellow_idx, week, pto_idx] for week in range(config.num_weeks))
            == config.pto_weeks_granted
        )


def add_max_concurrent_pto(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """At most ``max_concurrent_pto`` fellows may be on PTO each week."""

    for week in range(config.num_weeks):
        model.Add(
            sum(assign[fellow_idx, week, pto_idx] for fellow_idx in range(config.num_fellows))
            <= config.max_concurrent_pto
        )


def add_night_float_consecutive_limit(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    nf_idx: int,
) -> None:
    """Cap consecutive Night Float weeks."""

    max_consecutive = config.max_consecutive_night_float
    window = max_consecutive + 1
    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks - window + 1):
            model.Add(
                sum(assign[fellow_idx, week + offset, nf_idx] for offset in range(window))
                <= max_consecutive
            )


def add_block_completion(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Legacy rule: each fellow completes every active block at least once."""

    active_indices = [
        index for index, block in enumerate(config.blocks) if block.is_active
    ]
    for fellow_idx in range(config.num_fellows):
        for block_idx in active_indices:
            model.Add(
                sum(assign[fellow_idx, week, block_idx] for week in range(config.num_weeks))
                >= 1
            )


def add_min_max_weeks_per_block(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Legacy per-block min / max weeks applied to every fellow."""

    for block_idx in range(num_blocks):
        block = config.blocks[block_idx]
        if not block.is_active:
            continue
        for fellow_idx in range(config.num_fellows):
            total = sum(assign[fellow_idx, week, block_idx] for week in range(config.num_weeks))
            model.Add(total >= block.min_weeks)
            model.Add(total <= block.max_weeks)


def add_staffing_coverage(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Legacy block-level staffing coverage."""

    for block_idx in range(num_blocks):
        block = config.blocks[block_idx]
        if not block.is_active or block.fellows_needed <= 0:
            continue
        for week in range(config.num_weeks):
            model.Add(
                sum(assign[fellow_idx, week, block_idx] for fellow_idx in range(config.num_fellows))
                >= block.fellows_needed
            )


def add_eligibility_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Forbid assignments outside the configured cohort eligibility."""

    for rule in config.eligibility_rules:
        if not rule.is_active:
            continue
        block_indices = [
            block_name_to_idx[name]
            for name in rule.block_names
            if name in block_name_to_idx
        ]
        allowed_fellows = set(config.fellow_indices_for_years(rule.allowed_years))
        for week in _week_range(rule.start_week, rule.end_week, config.num_weeks):
            for fellow_idx in range(config.num_fellows):
                if fellow_idx in allowed_fellows:
                    continue
                for block_idx in block_indices:
                    model.Add(assign[fellow_idx, week, block_idx] == 0)


def add_coverage_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Apply cohort-aware staffing coverage rules."""

    for rule in config.coverage_rules:
        if not rule.is_active or rule.block_name not in block_name_to_idx:
            continue
        block_idx = block_name_to_idx[rule.block_name]
        fellow_indices = config.fellow_indices_for_years(rule.eligible_years)
        for week in _week_range(rule.start_week, rule.end_week, config.num_weeks):
            total = sum(assign[fellow_idx, week, block_idx] for fellow_idx in fellow_indices)
            model.Add(total >= rule.min_fellows)
            if rule.max_fellows is not None:
                model.Add(total <= rule.max_fellows)


def add_week_count_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Apply cohort-aware per-fellow week-count rules."""

    for rule in config.week_count_rules:
        if not rule.is_active:
            continue
        block_indices = [
            block_name_to_idx[name]
            for name in rule.block_names
            if name in block_name_to_idx
        ]
        if not block_indices:
            continue
        week_indices = list(_week_range(rule.start_week, rule.end_week, config.num_weeks))
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        if rule.applies_to_each_fellow:
            for fellow_idx in fellow_indices:
                total = sum(
                    assign[fellow_idx, week, block_idx]
                    for week in week_indices
                    for block_idx in block_indices
                )
                model.Add(total >= rule.min_weeks)
                model.Add(total <= rule.max_weeks)
        else:
            total = sum(
                assign[fellow_idx, week, block_idx]
                for fellow_idx in fellow_indices
                for week in week_indices
                for block_idx in block_indices
            )
            model.Add(total >= rule.min_weeks)
            model.Add(total <= rule.max_weeks)


def add_cohort_limit_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Limit concurrent assignments for selected cohorts."""

    for rule in config.cohort_limit_rules:
        if not rule.is_active or rule.state_name not in block_name_to_idx:
            continue
        state_idx = block_name_to_idx[rule.state_name]
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        for week in _week_range(rule.start_week, rule.end_week, config.num_weeks):
            model.Add(
                sum(assign[fellow_idx, week, state_idx] for fellow_idx in fellow_indices)
                <= rule.max_fellows
            )


def add_rolling_window_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Apply per-fellow rolling-window hard limits across selected states."""

    for rule in config.rolling_window_rules:
        if not rule.is_active or rule.window_size_weeks <= 0:
            continue
        state_indices = [
            block_name_to_idx[name]
            for name in rule.state_names
            if name in block_name_to_idx
        ]
        if not state_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        week_indices = list(_week_range(rule.start_week, rule.end_week, config.num_weeks))
        if len(week_indices) < rule.window_size_weeks:
            continue

        start_week = week_indices[0]
        last_window_start = week_indices[-1] - rule.window_size_weeks + 1
        for fellow_idx in fellow_indices:
            for window_start in range(start_week, last_window_start + 1):
                model.Add(
                    sum(
                        assign[fellow_idx, week, state_idx]
                        for week in range(window_start, window_start + rule.window_size_weeks)
                        for state_idx in state_indices
                )
                    <= rule.max_weeks_in_window
                )


def add_consecutive_state_limit_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Apply cohort-aware consecutive-week caps for selected states."""

    for rule in config.consecutive_state_limit_rules:
        if not rule.is_active or rule.max_consecutive_weeks < 1:
            continue
        state_indices = [
            block_name_to_idx[name]
            for name in rule.state_names
            if name in block_name_to_idx
        ]
        if not state_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        week_indices = list(_week_range(rule.start_week, rule.end_week, config.num_weeks))
        if len(week_indices) <= rule.max_consecutive_weeks:
            continue

        start_week = week_indices[0]
        window = rule.max_consecutive_weeks + 1
        last_window_start = week_indices[-1] - window + 1
        for fellow_idx in fellow_indices:
            for window_start in range(start_week, last_window_start + 1):
                model.Add(
                    sum(
                        assign[fellow_idx, week, state_idx]
                        for week in range(window_start, window_start + window)
                        for state_idx in state_indices
                    )
                    <= rule.max_consecutive_weeks
                )


def add_first_assignment_run_limit_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Limit the consecutive length of a fellow's first run on one block."""

    for rule in config.first_assignment_run_limit_rules:
        if (
            not rule.is_active
            or rule.max_run_length_weeks < 1
            or rule.block_name not in block_name_to_idx
        ):
            continue

        block_idx = block_name_to_idx[rule.block_name]
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        max_run = rule.max_run_length_weeks

        for fellow_idx in fellow_indices:
            for week in range(config.num_weeks):
                current_assignment = assign[fellow_idx, week, block_idx]
                if week == 0:
                    first_assignment = current_assignment
                else:
                    prior_total = sum(
                        assign[fellow_idx, prior_week, block_idx]
                        for prior_week in range(week)
                    )
                    has_prior = model.NewBoolVar(
                        f"first_run_limit_has_prior_f{fellow_idx}_w{week}_b{block_idx}"
                    )
                    model.Add(prior_total >= 1).OnlyEnforceIf(has_prior)
                    model.Add(prior_total == 0).OnlyEnforceIf(has_prior.Not())

                    first_assignment = model.NewBoolVar(
                        f"first_run_limit_first_f{fellow_idx}_w{week}_b{block_idx}"
                    )
                    model.Add(first_assignment <= current_assignment)
                    model.Add(first_assignment <= has_prior.Not())
                    model.Add(first_assignment >= current_assignment - has_prior)

                if week + max_run < config.num_weeks:
                    model.Add(
                        sum(
                            assign[fellow_idx, future_week, block_idx]
                            for future_week in range(week, week + max_run + 1)
                        )
                        <= max_run
                    ).OnlyEnforceIf(first_assignment)


def add_contiguous_block_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Require selected blocks to be assigned in one contiguous run."""

    for rule in config.contiguous_block_rules:
        if not rule.is_active or rule.block_name not in block_name_to_idx:
            continue

        block_idx = block_name_to_idx[rule.block_name]
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)

        for fellow_idx in fellow_indices:
            run_starts: list[cp_model.IntVar] = []
            for week in range(config.num_weeks):
                current = assign[fellow_idx, week, block_idx]
                if week == 0:
                    run_starts.append(current)
                    continue

                previous = assign[fellow_idx, week - 1, block_idx]
                run_start = model.NewBoolVar(
                    f"contiguous_run_start_f{fellow_idx}_w{week}_b{block_idx}"
                )
                model.Add(run_start <= current)
                model.Add(run_start + previous <= 1)
                model.Add(run_start >= current - previous)
                run_starts.append(run_start)

            model.Add(sum(run_starts) <= 1)


def add_first_assignment_pairing_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Require supervision for first-time assignments on selected blocks."""

    for rule in config.first_assignment_pairing_rules:
        if not rule.is_active or rule.block_name not in block_name_to_idx:
            continue

        block_idx = block_name_to_idx[rule.block_name]
        trainee_indices = config.fellow_indices_for_years(rule.trainee_years)
        mentor_indices = set(config.fellow_indices_for_years(rule.mentor_years))
        experienced_peer_indices = set(
            config.fellow_indices_for_years(rule.experienced_peer_years)
        )

        for fellow_idx in trainee_indices:
            for week in range(config.num_weeks):
                current_assignment = assign[fellow_idx, week, block_idx]
                if week == 0:
                    first_assignment = current_assignment
                else:
                    prior_total = sum(
                        assign[fellow_idx, prior_week, block_idx]
                        for prior_week in range(week)
                    )
                    has_prior = model.NewBoolVar(
                        f"pair_prior_{rule.block_name}_f{fellow_idx}_w{week}"
                    )
                    model.Add(prior_total >= rule.required_prior_weeks).OnlyEnforceIf(
                        has_prior
                    )
                    model.Add(prior_total < rule.required_prior_weeks).OnlyEnforceIf(
                        has_prior.Not()
                    )

                    first_assignment = model.NewBoolVar(
                        f"pair_first_{rule.block_name}_f{fellow_idx}_w{week}"
                    )
                    model.Add(first_assignment <= current_assignment)
                    model.Add(first_assignment <= has_prior.Not())
                    model.Add(first_assignment >= current_assignment - has_prior)

                supervision_terms: list[cp_model.IntVar] = []
                for mentor_idx in mentor_indices:
                    if mentor_idx == fellow_idx:
                        continue
                    supervision_terms.append(assign[mentor_idx, week, block_idx])

                for peer_idx in experienced_peer_indices:
                    if peer_idx == fellow_idx:
                        continue
                    if week == 0:
                        continue
                    prior_total = sum(
                        assign[peer_idx, prior_week, block_idx]
                        for prior_week in range(week)
                    )
                    has_prior = model.NewBoolVar(
                        f"pair_peer_prior_{rule.block_name}_f{peer_idx}_w{week}"
                    )
                    model.Add(prior_total >= rule.required_prior_weeks).OnlyEnforceIf(
                        has_prior
                    )
                    model.Add(prior_total < rule.required_prior_weeks).OnlyEnforceIf(
                        has_prior.Not()
                    )

                    experienced_peer = model.NewBoolVar(
                        f"pair_peer_{rule.block_name}_f{peer_idx}_w{week}"
                    )
                    model.Add(experienced_peer <= assign[peer_idx, week, block_idx])
                    model.Add(experienced_peer <= has_prior)
                    model.Add(
                        experienced_peer
                        >= assign[peer_idx, week, block_idx] + has_prior - 1
                    )
                    supervision_terms.append(experienced_peer)

                if supervision_terms:
                    model.Add(sum(supervision_terms) >= 1).OnlyEnforceIf(first_assignment)
                else:
                    model.Add(first_assignment == 0)


def add_individual_fellow_requirement_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Apply exact named-fellow block week-count requirements."""

    for rule in config.individual_fellow_requirement_rules:
        if not rule.is_active or rule.block_name not in block_name_to_idx:
            continue
        fellow_idx = config.fellow_index_for_year_and_name(
            rule.training_year,
            rule.fellow_name,
        )
        if fellow_idx is None:
            continue
        block_idx = block_name_to_idx[rule.block_name]
        total = sum(assign[fellow_idx, week, block_idx] for week in range(config.num_weeks))
        model.Add(total >= rule.min_weeks)
        model.Add(total <= rule.max_weeks)


def add_prerequisite_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Require prior block exposure before allowing a target assignment."""

    for rule in config.prerequisite_rules:
        if not rule.is_active or rule.target_block not in block_name_to_idx:
            continue
        target_idx = block_name_to_idx[rule.target_block]
        prerequisite_indices = [
            block_name_to_idx[name]
            for name in rule.prerequisite_blocks
            if name in block_name_to_idx
        ]
        prerequisite_group_indices = [
            [
                block_name_to_idx[name]
                for name in group
                if name in block_name_to_idx
            ]
            for group in rule.prerequisite_block_groups
        ]
        prerequisite_group_indices = [
            group_indices for group_indices in prerequisite_group_indices if group_indices
        ]
        if not prerequisite_indices and not prerequisite_group_indices:
            continue
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        for fellow_idx in fellow_indices:
            for week in range(config.num_weeks):
                target_var = assign[fellow_idx, week, target_idx]
                if week == 0:
                    model.Add(target_var == 0)
                    continue
                for prereq_idx in prerequisite_indices:
                    prior_total = sum(
                        assign[fellow_idx, prior_week, prereq_idx]
                        for prior_week in range(week)
                    )
                    model.Add(prior_total >= rule.prerequisite_min_weeks).OnlyEnforceIf(
                        target_var
                    )
                for prereq_group in prerequisite_group_indices:
                    prior_total = sum(
                        assign[fellow_idx, prior_week, prereq_idx]
                        for prior_week in range(week)
                        for prereq_idx in prereq_group
                    )
                    model.Add(prior_total >= rule.prerequisite_min_weeks).OnlyEnforceIf(
                        target_var
                    )


def add_forbidden_transition_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    block_name_to_idx: dict[str, int],
) -> None:
    """Forbid specific immediately-previous transitions."""

    for rule in config.forbidden_transition_rules:
        if not rule.is_active or rule.target_block not in block_name_to_idx:
            continue
        target_idx = block_name_to_idx[rule.target_block]
        previous_indices = [
            block_name_to_idx[name]
            for name in rule.forbidden_previous_blocks
            if name in block_name_to_idx
        ]
        fellow_indices = config.fellow_indices_for_years(rule.applicable_years)
        for fellow_idx in fellow_indices:
            for week in range(1, config.num_weeks):
                for previous_idx in previous_indices:
                    model.Add(
                        assign[fellow_idx, week, target_idx]
                        + assign[fellow_idx, week - 1, previous_idx]
                        <= 1
                    )
