"""24-hour weekend call scheduling.

Adds call-specific constraints and variables to the CP-SAT model.
Call is an *overlay* — a fellow keeps their regular block assignment
for the week but also takes a 24-hr Saturday shift.

Key rules (all configurable):
- 1 fellow on call each Saturday
- Fellows on Night Float or PTO are excluded
- Call hours (default 24) count toward the 80-hr trailing average
- Call is distributed roughly evenly (~1 per fellow per month)
"""

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
    """Add all 24-hr call constraints to the model.

    Parameters
    ----------
    model : CpModel
        The CP-SAT model being built.
    assign : dict
        Block assignment variables ``assign[f, w, b]``.
    call : dict
        Call assignment variables ``call[f, w]``.
    config : ScheduleConfig
        Global configuration.
    num_blocks : int
        Number of rotation blocks (excludes PTO).
    pto_idx : int
        Index of the PTO "block" in the assignment variables.
    """
    _add_call_coverage(model, call, config)
    _add_call_exclusions(model, assign, call, config, num_blocks, pto_idx)
    _add_call_fairness(model, call, config)


# ---------------------------------------------------------------------------
# Coverage: exactly 1 fellow on call each week
# ---------------------------------------------------------------------------

def _add_call_coverage(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Exactly one fellow must cover Saturday call each week.

    If no blocks require weekend call coverage in a given week, the
    constraint is relaxed to allow 0 or 1.
    """
    # Check if ANY block needs call coverage (at least one active block
    # with requires_call_coverage == True)
    any_block_needs_call: bool = any(
        b.requires_call_coverage and b.is_active for b in config.blocks
    )

    for w in range(config.num_weeks):
        total_call = sum(
            call[f, w] for f in range(config.num_fellows)
        )
        if any_block_needs_call:
            # Exactly 1 fellow on call
            model.Add(total_call == 1)
        else:
            # No coverage needed — nobody on call
            model.Add(total_call == 0)


# ---------------------------------------------------------------------------
# Exclusions: can't take call while on certain blocks
# ---------------------------------------------------------------------------

def _add_call_exclusions(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Fellows on excluded blocks (e.g., Night Float, PTO) cannot take call.

    Logic: if ``assign[f, w, b] == 1`` for an excluded block ``b``,
    then ``call[f, w]`` must be 0.  Equivalently:
        ``call[f, w] + assign[f, w, b] <= 1``
    """
    # Build set of excluded block indices
    excluded_indices: list[int] = []
    for i, blk in enumerate(config.blocks):
        if blk.name in config.call_excluded_blocks:
            excluded_indices.append(i)

    # PTO is always excluded (unless user overrides via config)
    if "PTO" in config.call_excluded_blocks:
        excluded_indices.append(pto_idx)

    for f in range(config.num_fellows):
        for w in range(config.num_weeks):
            for b in excluded_indices:
                # If on excluded block, no call
                model.Add(call[f, w] + assign[f, w, b] <= 1)


# ---------------------------------------------------------------------------
# Fairness: roughly equal call distribution
# ---------------------------------------------------------------------------

def _add_call_fairness(
    model: cp_model.CpModel,
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
) -> None:
    """Distribute call shifts roughly equally among fellows.

    With 52 weeks and 9 fellows, each fellow should take about 5-6 calls.
    We constrain every fellow's total to be within 1 of the average.

    Calculation:
        ideal = num_weeks / num_fellows
        min_calls = floor(ideal) - 1   (allow some slack)
        max_calls = ceil(ideal) + 1
    """
    any_block_needs_call: bool = any(
        block.requires_call_coverage and block.is_active
        for block in config.blocks
    )
    if not any_block_needs_call:
        return

    ideal: float = config.num_weeks / config.num_fellows
    min_calls: int = max(0, int(ideal) - 1)
    max_calls: int = int(ideal) + 2  # +2 for slack

    for f in range(config.num_fellows):
        total = sum(call[f, w] for w in range(config.num_weeks))
        model.Add(total >= min_calls)
        model.Add(total <= max_calls)
