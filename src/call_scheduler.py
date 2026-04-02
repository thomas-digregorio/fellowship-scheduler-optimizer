"""Overlay call scheduling."""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.models import ScheduleConfig, TrainingYear


def add_call_constraints(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Add all 24-hour call constraints to the CP-SAT model."""

    if config.structured_call_rules_enabled:
        _add_structured_call_coverage(model, call, config)
        _add_structured_call_eligibility(model, assign, call, config, num_blocks, pto_idx)
        _add_call_exclusions(model, assign, call, config, num_blocks, pto_idx)
        _add_structured_call_following_block_rules(
            model,
            assign,
            call,
            config,
            num_blocks,
            pto_idx,
        )
        _add_structured_call_fairness(model, call, config)
        _add_structured_call_consecutive_rules(model, call, config)
        _add_structured_call_window_rules(model, call, config)
        return

    _add_legacy_call_coverage(model, call, config)
    _add_call_exclusions(model, assign, call, config, num_blocks, pto_idx)
    _add_legacy_call_fairness(model, call, config)


def add_srcva_call_constraints(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Add all SRC/VA weekend and weekday overlay-call constraints."""

    if config.srcva_weekend_call_enabled:
        _add_srcva_weekend_coverage(model, weekend_call, config)
        _add_srcva_weekend_eligibility(
            model,
            assign,
            weekend_call,
            config,
            num_blocks,
            pto_idx,
        )
        _add_srcva_weekend_following_block_rules(
            model,
            assign,
            weekend_call,
            config,
            pto_idx,
        )
        _add_srcva_weekend_24hr_exclusion(model, weekend_call, call, config)
        _add_srcva_weekend_adjacent_24hr_exclusion(model, weekend_call, call, config)
        _add_srcva_weekend_fairness(model, weekend_call, config)
        _add_srcva_total_f1_call_bounds(model, weekend_call, call, config)
        _add_srcva_combined_call_window_rules(model, weekend_call, call, config)
    else:
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                model.Add(weekend_call[fellow_idx, week] == 0)

    if config.srcva_weekday_call_enabled:
        _add_srcva_weekday_coverage(model, weekday_call, config)
        _add_srcva_weekday_eligibility(
            model,
            assign,
            weekday_call,
            config,
            num_blocks,
            pto_idx,
        )
        _add_srcva_weekday_fairness(model, weekday_call, config)
        _add_srcva_weekday_consecutive_rules(model, weekday_call, config)
        _add_srcva_total_calls_per_week_rules(
            model,
            weekend_call,
            weekday_call,
            config,
        )
        _add_srcva_consecutive_call_slot_rules(
            model,
            weekend_call,
            weekday_call,
            config,
        )
    else:
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                for day_idx in range(4):
                    model.Add(weekday_call[fellow_idx, week, day_idx] == 0)


def _add_structured_call_coverage(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Require exactly one call assignment every week."""

    for week in range(config.num_weeks):
        model.Add(sum(call[fellow_idx, week] for fellow_idx in range(config.num_fellows)) == 1)


def _allowed_overlay_block_indices(
    config: ScheduleConfig,
    allowed_block_names: list[str],
) -> list[int]:
    """Return active block indices allowed for one overlay call model."""

    block_name_to_idx = {block.name: index for index, block in enumerate(config.blocks)}
    return [
        block_name_to_idx[block_name]
        for block_name in allowed_block_names
        if block_name in block_name_to_idx
    ]


def _overlay_state_indices(
    config: ScheduleConfig,
    state_names: list[str],
    pto_idx: int,
) -> list[int]:
    """Return block/state indices for overlay-call rules, including PTO."""

    block_name_to_idx = {block.name: index for index, block in enumerate(config.blocks)}
    block_name_to_idx["PTO"] = pto_idx
    return [
        block_name_to_idx[state_name]
        for state_name in state_names
        if state_name in block_name_to_idx
    ]


def _add_srcva_weekend_coverage(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Require exactly one SRC/VA weekend-call fellow each week."""

    for week in range(config.num_weeks):
        model.Add(
            sum(weekend_call[fellow_idx, week] for fellow_idx in range(config.num_fellows))
            == 1
        )


def _add_srcva_weekend_eligibility(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Restrict SRC/VA weekend call to configured cohorts, dates, and rotations."""

    del num_blocks, pto_idx
    eligible_fellows = set(config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years))
    allowed_indices = _allowed_overlay_block_indices(
        config,
        config.srcva_weekend_call_allowed_block_names,
    )

    for fellow_idx, fellow in enumerate(config.fellows):
        for week in range(config.num_weeks):
            if fellow_idx not in eligible_fellows:
                model.Add(weekend_call[fellow_idx, week] == 0)
                continue
            if (
                fellow.training_year == TrainingYear.F1
                and config.srcva_weekend_call_f1_start_week is not None
                and week < config.srcva_weekend_call_f1_start_week
            ):
                model.Add(weekend_call[fellow_idx, week] == 0)
                continue
            if not allowed_indices:
                model.Add(weekend_call[fellow_idx, week] == 0)
                continue
            model.Add(
                weekend_call[fellow_idx, week]
                <= sum(assign[fellow_idx, week, block_idx] for block_idx in allowed_indices)
            )


def _add_srcva_weekend_24hr_exclusion(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """A fellow cannot take SRC/VA weekend call and 24-hour call in the same week."""

    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            model.Add(weekend_call[fellow_idx, week] + call[fellow_idx, week] <= 1)


def _add_srcva_weekend_following_block_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Forbid weekend SRC/VA call immediately before selected next-week states."""

    target_indices = _overlay_state_indices(
        config,
        config.srcva_weekend_hard_forbidden_next_week_blocks,
        pto_idx,
    )
    if not target_indices:
        return

    for fellow_idx in config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years):
        for week in range(config.num_weeks - 1):
            for block_idx in target_indices:
                model.Add(
                    weekend_call[fellow_idx, week] + assign[fellow_idx, week + 1, block_idx] <= 1
                )


def _add_srcva_weekend_adjacent_24hr_exclusion(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Optionally forbid adjacent-week combinations of weekend and 24-hour call."""

    if not config.srcva_weekend_exclude_adjacent_24hr_weeks:
        return

    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for week in range(config.num_weeks - 1):
            model.Add(weekend_call[fellow_idx, week] + call[fellow_idx, week + 1] <= 1)
            model.Add(call[fellow_idx, week] + weekend_call[fellow_idx, week + 1] <= 1)


def _add_srcva_weekend_fairness(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Apply weekend-call totals by cohort."""

    eligible_fellows = set(config.fellow_indices_for_years(config.srcva_weekend_call_eligible_years))
    for fellow_idx, fellow in enumerate(config.fellows):
        total_calls = sum(
            weekend_call[fellow_idx, week] for week in range(config.num_weeks)
        )
        if fellow_idx not in eligible_fellows:
            model.Add(total_calls == 0)
            continue
        if fellow.training_year == TrainingYear.F1:
            model.Add(total_calls >= config.srcva_weekend_call_f1_min)
            model.Add(total_calls <= config.srcva_weekend_call_f1_max)
        elif fellow.training_year == TrainingYear.S2:
            model.Add(total_calls >= config.srcva_weekend_call_s2_min)
            model.Add(total_calls <= config.srcva_weekend_call_s2_max)
        else:
            model.Add(total_calls == 0)


def _add_srcva_total_f1_call_bounds(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Enforce total 24-hour plus SRC/VA weekend call bounds for F1 fellows."""

    for fellow_idx, fellow in enumerate(config.fellows):
        if fellow.training_year != TrainingYear.F1:
            continue
        total_calls = sum(call[fellow_idx, week] + weekend_call[fellow_idx, week] for week in range(config.num_weeks))
        model.Add(total_calls >= config.srcva_total_call_f1_min)
        model.Add(total_calls <= config.srcva_total_call_f1_max)


def _add_srcva_combined_call_window_rules(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Limit combined 24-hour and weekend SRC/VA calls in rolling windows."""

    window_weeks = config.srcva_combined_call_window_weeks
    max_calls = config.srcva_combined_call_window_max
    if (
        window_weeks <= 0
        or max_calls <= 0
        or config.num_weeks < window_weeks
    ):
        return

    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for start_week in range(config.num_weeks - window_weeks + 1):
            model.Add(
                sum(
                    weekend_call[fellow_idx, week] + call[fellow_idx, week]
                    for week in range(start_week, start_week + window_weeks)
                )
                <= max_calls
            )


def _add_srcva_weekday_coverage(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Require exactly one SRC/VA weekday-call fellow on each Mon-Thu night."""

    for week in range(config.num_weeks):
        for day_idx in range(4):
            model.Add(
                sum(
                    weekday_call[fellow_idx, week, day_idx]
                    for fellow_idx in range(config.num_fellows)
                )
                == 1
            )


def _add_srcva_weekday_eligibility(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Restrict SRC/VA weekday call to configured cohorts, dates, and rotations."""

    del num_blocks, pto_idx
    eligible_fellows = set(config.fellow_indices_for_years(config.srcva_weekday_call_eligible_years))
    allowed_indices = _allowed_overlay_block_indices(
        config,
        config.srcva_weekday_call_allowed_block_names,
    )

    for fellow_idx, fellow in enumerate(config.fellows):
        for week in range(config.num_weeks):
            for day_idx in range(4):
                if fellow_idx not in eligible_fellows:
                    model.Add(weekday_call[fellow_idx, week, day_idx] == 0)
                    continue
                if (
                    fellow.training_year == TrainingYear.F1
                    and config.srcva_weekday_call_f1_start_week is not None
                    and week < config.srcva_weekday_call_f1_start_week
                ):
                    model.Add(weekday_call[fellow_idx, week, day_idx] == 0)
                    continue
                if not allowed_indices:
                    model.Add(weekday_call[fellow_idx, week, day_idx] == 0)
                    continue
                model.Add(
                    weekday_call[fellow_idx, week, day_idx]
                    <= sum(assign[fellow_idx, week, block_idx] for block_idx in allowed_indices)
                )


def _add_srcva_weekday_fairness(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Apply weekday-call totals by cohort."""

    eligible_fellows = set(config.fellow_indices_for_years(config.srcva_weekday_call_eligible_years))
    for fellow_idx, fellow in enumerate(config.fellows):
        total_calls = sum(
            weekday_call[fellow_idx, week, day_idx]
            for week in range(config.num_weeks)
            for day_idx in range(4)
        )
        if fellow_idx not in eligible_fellows:
            model.Add(total_calls == 0)
            continue
        if fellow.training_year == TrainingYear.F1:
            model.Add(total_calls >= config.srcva_weekday_call_f1_min)
            model.Add(total_calls <= config.srcva_weekday_call_f1_max)
        elif fellow.training_year == TrainingYear.S2:
            model.Add(total_calls >= config.srcva_weekday_call_s2_min)
            model.Add(total_calls <= config.srcva_weekday_call_s2_max)
        else:
            model.Add(total_calls == 0)


def _add_srcva_weekday_consecutive_rules(
    model: cp_model.CpModel,
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Limit consecutive weekday-call nights inside each week."""

    max_consecutive = config.srcva_weekday_call_max_consecutive_nights
    if max_consecutive < 1 or 4 <= max_consecutive:
        return

    window = max_consecutive + 1
    eligible_fellows = config.fellow_indices_for_years(config.srcva_weekday_call_eligible_years)
    for fellow_idx in eligible_fellows:
        for week in range(config.num_weeks):
            for start_day in range(4 - window + 1):
                model.Add(
                    sum(
                        weekday_call[fellow_idx, week, day_idx]
                        for day_idx in range(start_day, start_day + window)
                    )
                    <= max_consecutive
                )


def _add_srcva_total_calls_per_week_rules(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Limit total SRC/VA weekend + weekday shifts in a single week."""

    max_calls = config.srcva_max_calls_per_week
    if max_calls <= 0:
        return

    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for week in range(config.num_weeks):
            model.Add(
                weekend_call[fellow_idx, week]
                + sum(weekday_call[fellow_idx, week, day_idx] for day_idx in range(4))
                <= max_calls
            )


def _add_srcva_consecutive_call_slot_rules(
    model: cp_model.CpModel,
    weekend_call: dict[tuple[int, int], cp_model.IntVar],
    weekday_call: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Forbid consecutive chronological SRC/VA call slots for one fellow."""

    if not config.srcva_disallow_consecutive_call_slots:
        return

    eligible_years = sorted(
        set(config.srcva_weekend_call_eligible_years + config.srcva_weekday_call_eligible_years),
        key=lambda year: year.value,
    )
    for fellow_idx in config.fellow_indices_for_years(eligible_years):
        for week in range(config.num_weeks):
            for day_idx in range(3):
                model.Add(
                    weekday_call[fellow_idx, week, day_idx]
                    + weekday_call[fellow_idx, week, day_idx + 1]
                    <= 1
                )
            model.Add(
                weekday_call[fellow_idx, week, 3] + weekend_call[fellow_idx, week] <= 1
            )
            if week + 1 < config.num_weeks:
                model.Add(
                    weekend_call[fellow_idx, week]
                    + weekday_call[fellow_idx, week + 1, 0]
                    <= 1
                )


def _add_structured_call_eligibility(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Restrict structured call to the configured cohorts and rotations."""

    block_name_to_idx = {block.name: index for index, block in enumerate(config.blocks)}
    block_name_to_idx["PTO"] = pto_idx
    eligible_fellows = set(config.fellow_indices_for_years(config.call_eligible_years))
    allowed_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_allowed_block_names
        if block_name in block_name_to_idx
    ]

    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            if fellow_idx not in eligible_fellows:
                model.Add(call[fellow_idx, week] == 0)
                continue
            if not allowed_indices:
                model.Add(call[fellow_idx, week] == 0)
                continue
            model.Add(
                call[fellow_idx, week]
                <= sum(assign[fellow_idx, week, block_idx] for block_idx in allowed_indices)
            )


def _add_call_exclusions(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Fellows on excluded blocks cannot take call."""

    excluded_indices: list[int] = []
    for block_idx, block in enumerate(config.blocks):
        if block.name in config.call_excluded_blocks:
            excluded_indices.append(block_idx)
    if "PTO" in config.call_excluded_blocks:
        excluded_indices.append(pto_idx)

    for fellow_idx in range(config.num_fellows):
        for week in range(config.num_weeks):
            for block_idx in excluded_indices:
                model.Add(call[fellow_idx, week] + assign[fellow_idx, week, block_idx] <= 1)


def _add_structured_call_following_block_rules(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Forbid call in the week before selected next-week assignments."""

    block_name_to_idx = {block.name: index for index, block in enumerate(config.blocks)}
    block_name_to_idx["PTO"] = pto_idx
    forbidden_indices = [
        block_name_to_idx[block_name]
        for block_name in config.call_forbidden_following_blocks
        if block_name in block_name_to_idx
    ]
    if not forbidden_indices:
        return

    eligible_fellows = config.fellow_indices_for_years(config.call_eligible_years)
    for fellow_idx in eligible_fellows:
        for week in range(config.num_weeks - 1):
            for block_idx in forbidden_indices:
                model.Add(call[fellow_idx, week] + assign[fellow_idx, week + 1, block_idx] <= 1)


def _add_structured_call_fairness(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Constrain total call counts for structured-call cohorts."""

    eligible_fellows = set(config.fellow_indices_for_years(config.call_eligible_years))
    for fellow_idx in range(config.num_fellows):
        total_calls = sum(call[fellow_idx, week] for week in range(config.num_weeks))
        if fellow_idx in eligible_fellows:
            model.Add(total_calls >= config.call_min_per_fellow)
            model.Add(total_calls <= config.call_max_per_fellow)
        else:
            model.Add(total_calls == 0)


def _add_structured_call_consecutive_rules(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Limit consecutive call weeks for eligible fellows."""

    max_consecutive = config.call_max_consecutive_weeks_per_fellow
    if max_consecutive < 1 or config.num_weeks <= max_consecutive:
        return

    window = max_consecutive + 1
    eligible_fellows = config.fellow_indices_for_years(config.call_eligible_years)
    for fellow_idx in eligible_fellows:
        for start_week in range(config.num_weeks - window + 1):
            model.Add(
                sum(call[fellow_idx, week] for week in range(start_week, start_week + window))
                <= max_consecutive
            )


def _add_structured_call_window_rules(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Limit 24-hour call frequency in rolling windows."""

    window_weeks = config.call_max_calls_in_window_weeks
    max_calls = config.call_max_calls_in_window_count
    if (
        window_weeks <= 0
        or max_calls <= 0
        or config.num_weeks < window_weeks
    ):
        return

    eligible_fellows = config.fellow_indices_for_years(config.call_eligible_years)
    for fellow_idx in eligible_fellows:
        for start_week in range(config.num_weeks - window_weeks + 1):
            model.Add(
                sum(call[fellow_idx, week] for week in range(start_week, start_week + window_weeks))
                <= max_calls
            )


def _add_legacy_call_coverage(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Legacy behavior: require one call if any active block needs it."""

    any_block_needs_call = any(
        block.requires_call_coverage and block.is_active for block in config.blocks
    )
    for week in range(config.num_weeks):
        total_call = sum(call[fellow_idx, week] for fellow_idx in range(config.num_fellows))
        if any_block_needs_call:
            model.Add(total_call == 1)
        else:
            model.Add(total_call == 0)


def _add_legacy_call_fairness(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Legacy behavior: keep call roughly evenly distributed."""

    any_block_needs_call = any(
        block.requires_call_coverage and block.is_active for block in config.blocks
    )
    if not any_block_needs_call:
        return

    ideal = config.num_weeks / config.num_fellows
    min_calls = max(0, int(ideal) - 1)
    max_calls = int(ideal) + 2

    for fellow_idx in range(config.num_fellows):
        total_calls = sum(call[fellow_idx, week] for week in range(config.num_weeks))
        model.Add(total_calls >= min_calls)
        model.Add(total_calls <= max_calls)
