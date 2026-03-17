"""Tests for the schedule-derived checks panel."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.components.checks_panel import build_schedule_checks
from src.models import (
    BlockConfig,
    BlockType,
    FellowConfig,
    ScheduleConfig,
    ScheduleResult,
    SolverStatus,
)


def test_build_schedule_checks_counts_schedule_patterns() -> None:
    """Checks should summarize the generated schedule directly."""
    config = ScheduleConfig(
        num_fellows=3,
        num_weeks=4,
        start_date=date(2026, 7, 1),
        blocks=[
            BlockConfig(name="Night Float", block_type=BlockType.NIGHT),
            BlockConfig(name="CCU", block_type=BlockType.DAY),
            BlockConfig(name="Research", block_type=BlockType.DAY),
        ],
        fellows=[
            FellowConfig(name="Fellow 1"),
            FellowConfig(name="Fellow 2"),
            FellowConfig(name="Fellow 3"),
        ],
    )
    result = ScheduleResult(
        assignments=[
            ["Night Float", "CCU", "CCU", "Research"],
            ["CCU", "Night Float", "CCU", "PTO"],
            ["Research", "CCU", "CCU", "CCU"],
        ],
        call_assignments=[
            [False, True, False, False],
            [False, False, True, False],
            [True, False, False, True],
        ],
        solver_status=SolverStatus.OPTIMAL,
    )

    checks = build_schedule_checks(config, result)

    assert checks["night_float_followed_by_call"].value == 2
    assert checks["weeks_with_gt_two_ccu"].value == 1
    assert checks["max_ccu_per_week"].value == 3
    assert checks["weeks_without_exactly_one_call"].value == 0
    assert checks["call_spread"].value == 1
    assert checks["max_concurrent_pto"].value == 1
    assert checks["max_night_float_streak"].value == 1
