"""24-hour weekend call scheduling."""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.models import ScheduleConfig


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
        return

    _add_legacy_call_coverage(model, call, config)
    _add_call_exclusions(model, assign, call, config, num_blocks, pto_idx)
    _add_legacy_call_fairness(model, call, config)


def _add_structured_call_coverage(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Require exactly one call assignment every week."""

    for week in range(config.num_weeks):
        model.Add(sum(call[fellow_idx, week] for fellow_idx in range(config.num_fellows)) == 1)


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
