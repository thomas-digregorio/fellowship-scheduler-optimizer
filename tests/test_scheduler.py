"""Tests for the scheduling constraint solver.

Runs a small-scale solve (3 fellows, 12 weeks, 5 blocks) and validates
that every hard constraint is satisfied in the output.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_default_blocks
from src.models import (
    BlockConfig,
    BlockType,
    FellowConfig,
    ScheduleConfig,
    ScheduleResult,
    SolverStatus,
)
from src.scheduler import check_feasibility, solve_schedule


# ---------------------------------------------------------------------------
# Fixtures: small config for fast tests
# ---------------------------------------------------------------------------

@pytest.fixture
def small_config() -> ScheduleConfig:
    """A minimal config: 4 fellows, 16 weeks, 4 blocks.

    Designed to be comfortably feasible while still exercising the
    solver. Key math:
      - 4 fellows, 1 PTO/week max → 3 available/week
      - Block A needs 1 fellow → 1 slot used, 2 flexible
      - 4 blocks + NF → each fellow needs 4 blocks in 15 working weeks
      - Call: 1 per week, 2+ fellows always eligible
    """
    blocks = [
        BlockConfig(
            name="Block A", block_type=BlockType.DAY,
            fellows_needed=1, hours_per_week=50.0,
            min_weeks=1, max_weeks=10, is_active=True,
            has_weekend_off=True, requires_call_coverage=True,
        ),
        BlockConfig(
            name="Block B", block_type=BlockType.DAY,
            fellows_needed=0, hours_per_week=50.0,
            min_weeks=1, max_weeks=10, is_active=True,
            has_weekend_off=True, requires_call_coverage=False,
        ),
        BlockConfig(
            name="Block C", block_type=BlockType.DAY,
            fellows_needed=0, hours_per_week=50.0,
            min_weeks=1, max_weeks=10, is_active=True,
            has_weekend_off=True, requires_call_coverage=False,
        ),
        BlockConfig(
            name="Night Float", block_type=BlockType.NIGHT,
            fellows_needed=0, hours_per_week=50.0,
            min_weeks=1, max_weeks=6, is_active=True,
            has_weekend_off=True, requires_call_coverage=False,
        ),
    ]
    fellows = [
        FellowConfig(
            name=f"Fellow {i + 1}",
            pto_rankings=[4, 8, 12],  # rank 3 weeks each
        )
        for i in range(4)
    ]
    return ScheduleConfig(
        num_fellows=4,
        num_weeks=16,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=1,
        pto_weeks_to_rank=3,
        pto_blackout_weeks=[0],  # first week blackout
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=30.0,
        blocks=blocks,
        fellows=fellows,
    )


@pytest.fixture
def solved_result(small_config: ScheduleConfig) -> ScheduleResult:
    """Run the solver on the small config and return the result."""
    result = solve_schedule(small_config)
    assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE), (
        f"Solver failed with status: {result.solver_status.value}"
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFeasibilityCheck:
    """Tests for the pre-solve feasibility checker."""

    def test_valid_config_no_issues(self, small_config: ScheduleConfig) -> None:
        """A well-formed config should produce zero issues."""
        issues = check_feasibility(small_config)
        # May have PTO ranking warnings, but no staffing conflicts
        critical = [i for i in issues if "Staffing conflict" in i]
        assert len(critical) == 0

    def test_overstaffed_config_flagged(self, small_config: ScheduleConfig) -> None:
        """If total needed > available, feasibility check should flag it."""
        for block in small_config.blocks:
            block.fellows_needed = 2  # 5 blocks × 2 = 10 > 2 available
        issues = check_feasibility(small_config)
        assert any("Staffing conflict" in i for i in issues)


class TestConstraints:
    """Tests validating that each constraint holds in the solution."""

    def test_one_assignment_per_week(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Each fellow should be on exactly one block or PTO each week."""
        for f in range(small_config.num_fellows):
            for w in range(small_config.num_weeks):
                assignment = solved_result.assignments[f][w]
                assert assignment != "", f"Fellow {f}, week {w} is unassigned"
                assert assignment != "UNASSIGNED"

    def test_pto_count(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Each fellow should have exactly pto_weeks_granted PTO weeks."""
        for f in range(small_config.num_fellows):
            pto_count = solved_result.assignments[f].count("PTO")
            assert pto_count == small_config.pto_weeks_granted, (
                f"Fellow {f} has {pto_count} PTO weeks, "
                f"expected {small_config.pto_weeks_granted}"
            )

    def test_no_consecutive_same_block(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """No fellow should be on the same rotation block two weeks in a row."""
        for f in range(small_config.num_fellows):
            for w in range(small_config.num_weeks - 1):
                block_this = solved_result.assignments[f][w]
                block_next = solved_result.assignments[f][w + 1]
                if block_this != "PTO":
                    assert block_this != block_next, (
                        f"Fellow {f} has consecutive '{block_this}' "
                        f"in weeks {w} and {w + 1}"
                    )

    def test_night_float_max_consecutive(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Night Float should not exceed max_consecutive_night_float in a row."""
        max_nf = small_config.max_consecutive_night_float
        for f in range(small_config.num_fellows):
            consec = 0
            for w in range(small_config.num_weeks):
                if solved_result.assignments[f][w] == "Night Float":
                    consec += 1
                    assert consec <= max_nf, (
                        f"Fellow {f} has {consec} consecutive NF weeks "
                        f"at week {w}, max allowed is {max_nf}"
                    )
                else:
                    consec = 0

    def test_all_blocks_completed(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Each fellow should complete every active block at least once."""
        required = {b.name for b in small_config.blocks if b.is_active}
        for f in range(small_config.num_fellows):
            completed = {
                a for a in solved_result.assignments[f]
                if a != "PTO"
            }
            missing = required - completed
            assert len(missing) == 0, (
                f"Fellow {f} missing blocks: {missing}"
            )

    def test_pto_blackout(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """No fellow should be on PTO during blackout weeks."""
        for f in range(small_config.num_fellows):
            for w in small_config.pto_blackout_weeks:
                assert solved_result.assignments[f][w] != "PTO", (
                    f"Fellow {f} is on PTO during blackout week {w}"
                )

    def test_max_concurrent_pto(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """At most max_concurrent_pto fellows on PTO the same week."""
        for w in range(small_config.num_weeks):
            pto_count = sum(
                1 for f in range(small_config.num_fellows)
                if solved_result.assignments[f][w] == "PTO"
            )
            assert pto_count <= small_config.max_concurrent_pto, (
                f"Week {w} has {pto_count} fellows on PTO, "
                f"max is {small_config.max_concurrent_pto}"
            )

    def test_trailing_hours_average(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """The 4-week trailing average should never exceed 80 hours."""
        block_hours = {b.name: b.hours_per_week for b in small_config.blocks}
        block_hours["PTO"] = 0.0
        window = small_config.trailing_avg_weeks

        for f in range(small_config.num_fellows):
            for w_start in range(small_config.num_weeks - window + 1):
                total = 0.0
                for w in range(w_start, w_start + window):
                    block = solved_result.assignments[f][w]
                    total += block_hours.get(block, 0.0)
                    if solved_result.call_assignments[f][w]:
                        total += small_config.call_hours

                avg = total / window
                assert avg <= small_config.hours_cap + 0.1, (
                    f"Fellow {f}, weeks {w_start}-{w_start + window - 1}: "
                    f"trailing avg = {avg:.1f}, cap = {small_config.hours_cap}"
                )

    def test_call_not_on_pto_or_nf(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Fellows on PTO or Night Float should not have call."""
        for f in range(small_config.num_fellows):
            for w in range(small_config.num_weeks):
                if solved_result.call_assignments[f][w]:
                    block = solved_result.assignments[f][w]
                    assert block not in ("PTO", "Night Float"), (
                        f"Fellow {f} has call in week {w} while on {block}"
                    )

    def test_staffing_coverage(
        self, small_config: ScheduleConfig, solved_result: ScheduleResult,
    ) -> None:
        """Active blocks with fellows_needed > 0 should be staffed."""
        for b_idx, block in enumerate(small_config.blocks):
            if not block.is_active or block.fellows_needed <= 0:
                continue
            for w in range(small_config.num_weeks):
                count = sum(
                    1 for f in range(small_config.num_fellows)
                    if solved_result.assignments[f][w] == block.name
                )
                assert count >= block.fellows_needed, (
                    f"Block '{block.name}' week {w}: {count} fellows, "
                    f"need {block.fellows_needed}"
                )
