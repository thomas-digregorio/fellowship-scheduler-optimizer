"""ACGME duty-hour rule enforcement.

ACGME (Accreditation Council for Graduate Medical Education) mandates
several work-hour limits for trainees. At the *weekly* scheduling
granularity we use, only the 80-hour trailing average is directly
enforceable. The other rules (1 day off per 7, rest between shifts)
are documented here and approximated via hour thresholds.

Reference: ACGME Common Program Requirements, Section VI.F.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from src.models import ScheduleConfig


def add_trailing_hours_cap(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
) -> None:
    """Enforce the 80-hour trailing 4-week average for every fellow.

    How it works:
    1. For each fellow and each week, compute that week's hours as:
       ``hours = Σ_b (assign[f,w,b] × block_hours[b]) + call[f,w] × call_hours``
    2. For every window of ``trailing_avg_weeks`` consecutive weeks,
       the sum of hours must be ≤ ``hours_cap × trailing_avg_weeks``.

    Since PTO weeks have 0 hours, they naturally bring the average down.

    Notes
    -----
    The constraint is *linear* because ``assign`` and ``call`` are binary
    variables multiplied by constant hour values.
    """
    window: int = config.trailing_avg_weeks
    max_total: int = int(config.hours_cap * window)  # e.g., 80 × 4 = 320

    # Precompute hours-per-block as integers (CP-SAT uses integers)
    # We scale by 10 to keep one decimal of precision (e.g., 60.0 → 600)
    SCALE: int = 10
    block_hours_scaled: list[int] = [
        int(blk.hours_per_week * SCALE) for blk in config.blocks
    ]
    # PTO hours = 0
    pto_hours_scaled: int = 0
    call_hours_scaled: int = int(config.call_hours * SCALE)
    max_total_scaled: int = max_total * SCALE

    for f in range(config.num_fellows):
        for w_start in range(config.num_weeks - window + 1):
            # Sum of hours across the trailing window
            window_hours = []
            for w in range(w_start, w_start + window):
                # Hours from block assignment
                for b in range(num_blocks):
                    window_hours.append(
                        assign[f, w, b] * block_hours_scaled[b]
                    )
                # PTO contributes 0 hours (skip for clarity)
                # Hours from 24-hr call
                window_hours.append(call[f, w] * call_hours_scaled)

            model.Add(sum(window_hours) <= max_total_scaled)


def add_day_off_approximation(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
) -> None:
    """Approximate ACGME '1 day off per 7' at weekly granularity.

    Since we schedule at the week level (not individual shifts), we
    approximate this rule by capping per-block hours so that at least
    1 day of rest is possible within a 7-day period.

    Specifically: if a block's hours_per_week > 72 (which would mean
    12+ hrs × 7 days with no rest), we flag it during the feasibility
    check rather than in the solver.

    For now this function is a no-op placeholder — the actual validation
    happens in the ``check_feasibility`` function in ``scheduler.py``.
    """
    # Intentionally a no-op at the solver level.
    # The feasibility checker flags blocks with hours > 72 pre-solve.
    pass
