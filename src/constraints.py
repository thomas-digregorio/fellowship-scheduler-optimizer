"""Constraint builder functions for the CP-SAT solver.

Each function adds one *type* of constraint to the ``CpModel``. The
main ``scheduler.py`` calls them in sequence to assemble the full
model. Keeping constraints in separate functions makes it easy to
toggle individual rules on/off for debugging.

Terminology used in variable names:
    f  = fellow index   (0 … num_fellows-1)
    w  = week index     (0 … num_weeks-1)
    b  = block index    (0 … num_blocks-1);  the PTO "block" is at index ``pto_idx``
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.models import ScheduleConfig


# ---------------------------------------------------------------------------
# 1. EXACTLY ONE STATE PER WEEK
# ---------------------------------------------------------------------------

def add_one_assignment_per_week(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Each fellow must be on exactly one block (or PTO) every week.

    This is the fundamental "partitioning" constraint — without it a
    fellow could be double-booked or unassigned.
    """
    for f in range(config.num_fellows):
        for w in range(config.num_weeks):
            # Sum across all blocks (including PTO) must be exactly 1
            model.Add(
                sum(assign[f, w, b] for b in range(num_blocks + 1)) == 1
            )


# ---------------------------------------------------------------------------
# 2. PTO CONSTRAINTS
# ---------------------------------------------------------------------------

def add_pto_count(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Each fellow gets exactly ``pto_weeks_granted`` PTO weeks."""
    for f in range(config.num_fellows):
        model.Add(
            sum(assign[f, w, pto_idx] for w in range(config.num_weeks))
            == config.pto_weeks_granted
        )


def add_pto_blackout(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Forbid PTO during blackout weeks (e.g., July orientation)."""
    for f in range(config.num_fellows):
        for w in config.pto_blackout_weeks:
            if 0 <= w < config.num_weeks:
                model.Add(assign[f, w, pto_idx] == 0)


def add_max_concurrent_pto(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """At most ``max_concurrent_pto`` fellows on PTO the same week."""
    for w in range(config.num_weeks):
        model.Add(
            sum(assign[f, w, pto_idx] for f in range(config.num_fellows))
            <= config.max_concurrent_pto
        )


# ---------------------------------------------------------------------------
# 3. NO CONSECUTIVE SAME BLOCK
# ---------------------------------------------------------------------------

def add_no_consecutive_same_block(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """A fellow cannot be on the same rotation block two weeks in a row.

    Note: this does NOT apply to PTO — a fellow *can* take consecutive
    PTO weeks (though the 4-week total still limits it).
    """
    for f in range(config.num_fellows):
        for w in range(config.num_weeks - 1):
            for b in range(num_blocks):  # exclude PTO index
                model.Add(assign[f, w, b] + assign[f, w + 1, b] <= 1)


# ---------------------------------------------------------------------------
# 4. NIGHT FLOAT CONSECUTIVE LIMIT
# ---------------------------------------------------------------------------

def add_night_float_consecutive_limit(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    nf_idx: int,
) -> None:
    """Cap consecutive Night Float weeks at ``max_consecutive_night_float``.

    Default is 2 — so a fellow can do NF for 2 weeks in a row but then
    must switch to something else for at least 1 week.

    Works by saying: in any window of (max+1) consecutive weeks, the
    fellow can be on NF for at most ``max`` of them.
    """
    max_consec: int = config.max_consecutive_night_float
    window: int = max_consec + 1

    for f in range(config.num_fellows):
        for w in range(config.num_weeks - window + 1):
            model.Add(
                sum(assign[f, w + d, nf_idx] for d in range(window))
                <= max_consec
            )


# ---------------------------------------------------------------------------
# 5. BLOCK COMPLETION (every fellow does every block at least once)
# ---------------------------------------------------------------------------

def add_block_completion(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Each fellow must complete every active block at least once.

    Combined with the min_weeks / max_weeks per-block constraint below,
    this ensures training requirements are met.
    """
    active_indices: list[int] = [
        i for i, blk in enumerate(config.blocks) if blk.is_active
    ]
    for f in range(config.num_fellows):
        for b in active_indices:
            model.Add(
                sum(assign[f, w, b] for w in range(config.num_weeks)) >= 1
            )


# ---------------------------------------------------------------------------
# 6. MIN / MAX WEEKS PER BLOCK PER FELLOW
# ---------------------------------------------------------------------------

def add_min_max_weeks_per_block(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Enforce per-block minimum and maximum week counts for each fellow.

    For example, "Research" might have min=2, max=8, meaning each fellow
    must spend at least 2 weeks and at most 8 weeks on Research.
    """
    for b in range(num_blocks):
        blk = config.blocks[b]
        if not blk.is_active:
            continue

        for f in range(config.num_fellows):
            total = sum(assign[f, w, b] for w in range(config.num_weeks))
            model.Add(total >= blk.min_weeks)
            model.Add(total <= blk.max_weeks)


# ---------------------------------------------------------------------------
# 7. STAFFING COVERAGE
# ---------------------------------------------------------------------------

def add_staffing_coverage(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Each active block must have at least ``fellows_needed`` fellows/week.

    Blocks with ``fellows_needed == 0`` are unconstrained (anyone can be
    placed there, but nobody is *required*).
    """
    for b in range(num_blocks):
        blk = config.blocks[b]
        if not blk.is_active or blk.fellows_needed <= 0:
            continue

        for w in range(config.num_weeks):
            model.Add(
                sum(assign[f, w, b] for f in range(config.num_fellows))
                >= blk.fellows_needed
            )

