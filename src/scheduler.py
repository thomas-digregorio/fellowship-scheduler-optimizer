"""Main scheduling engine — orchestrates the CP-SAT solver.

This is the "brain" of the system. It:
1. Builds the CP-SAT model with all decision variables
2. Calls each constraint-builder function (from constraints.py,
   acgme.py, and call_scheduler.py)
3. Sets the objective (maximize PTO preference satisfaction)
4. Runs the solver with a configurable timeout
5. Extracts and returns the solution as a ScheduleResult

Usage:
    from src.scheduler import solve_schedule
    from src.config import get_default_config

    config = get_default_config()
    result = solve_schedule(config)
"""

from __future__ import annotations

import time

from ortools.sat.python import cp_model

from src.acgme import add_trailing_hours_cap
from src.call_scheduler import add_call_constraints
from src.constraints import (
    add_block_completion,
    add_max_concurrent_pto,
    add_min_max_weeks_per_block,
    add_night_float_consecutive_limit,
    add_no_consecutive_same_block,
    add_one_assignment_per_week,
    add_pto_blackout,
    add_pto_count,
    add_staffing_coverage,
    add_unavailable_weeks,
)
from src.models import ScheduleConfig, ScheduleResult, SolverStatus


# ---------------------------------------------------------------------------
# Feasibility pre-check (run before the solver to catch obvious issues)
# ---------------------------------------------------------------------------

def check_feasibility(config: ScheduleConfig) -> list[str]:
    """Run quick sanity checks on the config before invoking the solver.

    Returns a list of human-readable warning/error strings. An empty
    list means no issues were detected (but the solver may still fail
    if constraints are conflicting).

    Parameters
    ----------
    config : ScheduleConfig
        The schedule configuration to validate.

    Returns
    -------
    list[str]
        Warning/error messages. Empty if everything looks OK.
    """
    issues: list[str] = []

    # --- Check 1: total staffing vs available fellows ---
    active_blocks = config.active_blocks
    total_needed: int = sum(b.fellows_needed for b in active_blocks)
    available: int = config.num_fellows - config.max_concurrent_pto

    if total_needed > available:
        issues.append(
            f"⚠️ Staffing conflict: blocks need {total_needed} fellows/week "
            f"but only {available} are available ({config.num_fellows} total "
            f"minus {config.max_concurrent_pto} on PTO). "
            f"Reduce fellows_needed on some blocks."
        )

    # --- Check 2: enough weeks for all block completions ---
    working_weeks: int = config.num_weeks - config.pto_weeks_granted
    total_min_weeks: int = sum(
        b.min_weeks for b in active_blocks
    )
    if total_min_weeks > working_weeks:
        issues.append(
            f"⚠️ Block minimums conflict: total min_weeks across blocks = "
            f"{total_min_weeks}, but each fellow only works {working_weeks} "
            f"weeks. Reduce some min_weeks values."
        )

    # --- Check 3: blocks with hours > 72 (day-off approximation) ---
    for blk in active_blocks:
        if blk.hours_per_week > 72:
            issues.append(
                f"⚠️ ACGME warning: '{blk.name}' has {blk.hours_per_week} "
                f"hrs/week, which may violate the 1-day-off-per-7 rule "
                f"(> 72 hrs implies no rest day in a 7-day period)."
            )

    # --- Check 4: PTO rankings provided ---
    for fellow in config.fellows:
        if len(fellow.pto_rankings) == 0:
            issues.append(
                f"⚠️ '{fellow.name}' has no PTO weeks ranked. The solver "
                f"will assign PTO weeks arbitrarily."
            )

    return issues


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve_schedule(
    config: ScheduleConfig,
    locked_weeks: dict[int, dict[int, str]] | None = None,
) -> ScheduleResult:
    """Build and solve the CP-SAT model for the fellowship schedule.

    Parameters
    ----------
    config : ScheduleConfig
        Fully populated schedule configuration.
    locked_weeks : dict, optional
        Pre-locked assignments for mid-year re-solve. Format:
        ``{fellow_idx: {week: block_name}}``. These assignments are
        fixed (not changeable by the solver).

    Returns
    -------
    ScheduleResult
        The generated schedule, including solver status and metrics.
    """
    if locked_weeks is None:
        locked_weeks = {}

    # --- Setup ---
    model = cp_model.CpModel()
    num_blocks: int = len(config.blocks)
    pto_idx: int = num_blocks  # PTO is the last "block" index

    # Build a lookup: block_name → block_index
    block_name_to_idx: dict[str, int] = {
        blk.name: i for i, blk in enumerate(config.blocks)
    }
    block_name_to_idx["PTO"] = pto_idx

    # Find Night Float index for the consecutive-NF constraint
    nf_idx: int | None = block_name_to_idx.get("Night Float")

    # --- Decision variables ---
    # assign[f, w, b] = 1 if fellow f is on block b in week w
    assign: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for f in range(config.num_fellows):
        for w in range(config.num_weeks):
            for b in range(num_blocks + 1):  # +1 for PTO
                assign[f, w, b] = model.new_bool_var(
                    f"assign_f{f}_w{w}_b{b}"
                )

    # call[f, w] = 1 if fellow f has Saturday call in week w
    call: dict[tuple[int, int], cp_model.IntVar] = {}
    for f in range(config.num_fellows):
        for w in range(config.num_weeks):
            call[f, w] = model.new_bool_var(f"call_f{f}_w{w}")

    # --- Lock pre-assigned weeks (for mid-year re-solve) ---
    for f_idx, week_map in locked_weeks.items():
        for w, block_name in week_map.items():
            if block_name in block_name_to_idx:
                b_idx = block_name_to_idx[block_name]
                model.Add(assign[f_idx, w, b_idx] == 1)

    # --- Add all constraints ---

    # 1. Exactly one assignment per fellow per week
    add_one_assignment_per_week(model, assign, config, num_blocks, pto_idx)

    # 2. PTO count, blackout, and concurrency
    add_pto_count(model, assign, config, pto_idx)
    add_pto_blackout(model, assign, config, pto_idx)
    add_max_concurrent_pto(model, assign, config, pto_idx)

    # 3. No consecutive same rotation block
    add_no_consecutive_same_block(model, assign, config, num_blocks)

    # 4. Night Float consecutive limit
    if nf_idx is not None:
        add_night_float_consecutive_limit(model, assign, config, nf_idx)

    # 5. Every fellow completes every active block at least once
    add_block_completion(model, assign, config, num_blocks)

    # 6. Min/max weeks per block per fellow
    add_min_max_weeks_per_block(model, assign, config, num_blocks)

    # 7. Staffing coverage minimums
    add_staffing_coverage(model, assign, config, num_blocks)

    # 8. Unavailable weeks (maternity leave, etc.)
    add_unavailable_weeks(model, assign, config, pto_idx)

    # 9. ACGME 80-hour trailing average
    add_trailing_hours_cap(model, assign, call, config, num_blocks, pto_idx)

    # 10. 24-hr Saturday call constraints
    add_call_constraints(model, assign, call, config, num_blocks, pto_idx)

    # --- Objective: maximize PTO preference satisfaction ---
    _add_pto_objective(model, assign, config, pto_idx)

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_timeout_seconds
    # Use multiple workers for faster search
    solver.parameters.num_workers = 8

    start_time: float = time.time()
    status_code: int = solver.solve(model)
    solve_time: float = time.time() - start_time

    # --- Map solver status ---
    status_map: dict[int, SolverStatus] = {
        cp_model.OPTIMAL: SolverStatus.OPTIMAL,
        cp_model.FEASIBLE: SolverStatus.FEASIBLE,
        cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
        cp_model.MODEL_INVALID: SolverStatus.ERROR,
        cp_model.UNKNOWN: SolverStatus.TIMEOUT,
    }
    solver_status: SolverStatus = status_map.get(
        status_code, SolverStatus.ERROR
    )

    # --- Extract solution ---
    if solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
        return _extract_solution(
            solver, assign, call, config, num_blocks, pto_idx,
            solver_status, solver.objective_value, solve_time,
        )

    # No valid solution found
    return ScheduleResult(
        assignments=[
            ["" for _ in range(config.num_weeks)]
            for _ in range(config.num_fellows)
        ],
        call_assignments=[
            [False for _ in range(config.num_weeks)]
            for _ in range(config.num_fellows)
        ],
        solver_status=solver_status,
        objective_value=0.0,
        solve_time_seconds=solve_time,
    )


# ---------------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------------

def _add_pto_objective(
    model: cp_model.CpModel,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    config: ScheduleConfig,
    pto_idx: int,
) -> None:
    """Maximize PTO preference satisfaction.

    Each fellow ranks ``pto_weeks_to_rank`` weeks. We assign a score
    based on rank position:
        rank 1 (most preferred) → score = pto_weeks_to_rank
        rank 2                  → score = pto_weeks_to_rank - 1
        ...
        rank N (least preferred) → score = 1
        unranked weeks           → score = 0

    The solver maximizes the total score across all fellows, meaning
    higher-ranked weeks are prioritized.
    """
    objective_terms = []

    for f, fellow in enumerate(config.fellows):
        for rank, week_idx in enumerate(fellow.pto_rankings):
            if 0 <= week_idx < config.num_weeks:
                # Higher score for higher-ranked (lower index) weeks
                score: int = config.pto_weeks_to_rank - rank
                objective_terms.append(
                    assign[f, week_idx, pto_idx] * score
                )

    if objective_terms:
        model.maximize(sum(objective_terms))
    else:
        # No PTO preferences provided — solver just finds any feasible
        # solution (no optimization direction)
        pass


# ---------------------------------------------------------------------------
# Solution extraction
# ---------------------------------------------------------------------------

def _extract_solution(
    solver: cp_model.CpSolver,
    assign: dict[tuple[int, int, int], cp_model.IntVar],
    call: dict[tuple[int, int], cp_model.IntVar],
    config: ScheduleConfig,
    num_blocks: int,
    pto_idx: int,
    status: SolverStatus,
    objective: float,
    solve_time: float,
) -> ScheduleResult:
    """Read the solver's variable values and build a ScheduleResult.

    Parameters
    ----------
    solver : CpSolver
        The solved CP-SAT solver instance.
    assign, call : dict
        Decision variable dictionaries.
    config : ScheduleConfig
        Configuration used for the solve.
    num_blocks, pto_idx : int
        Index bounds.
    status : SolverStatus
        Mapped solver status.
    objective : float
        Objective function value.
    solve_time : float
        Wall-clock solve time.

    Returns
    -------
    ScheduleResult
        The complete extracted schedule.
    """
    # Build block index → name lookup
    block_names: list[str] = [blk.name for blk in config.blocks] + ["PTO"]

    assignments: list[list[str]] = []
    call_assignments: list[list[bool]] = []

    for f in range(config.num_fellows):
        fellow_blocks: list[str] = []
        fellow_calls: list[bool] = []

        for w in range(config.num_weeks):
            # Find which block this fellow is assigned to this week
            assigned_block: str = "UNASSIGNED"
            for b in range(num_blocks + 1):
                if solver.value(assign[f, w, b]) == 1:
                    assigned_block = block_names[b]
                    break
            fellow_blocks.append(assigned_block)

            # Check if fellow has call this week
            fellow_calls.append(bool(solver.value(call[f, w])))

        assignments.append(fellow_blocks)
        call_assignments.append(fellow_calls)

    return ScheduleResult(
        assignments=assignments,
        call_assignments=call_assignments,
        solver_status=status,
        objective_value=objective,
        solve_time_seconds=solve_time,
    )
