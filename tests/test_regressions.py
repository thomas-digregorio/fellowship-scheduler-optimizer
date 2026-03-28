"""Regression coverage for solver and feasibility edge cases."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export import export_csv_bytes, export_pdf, export_pdf_bytes
from src.models import BlockConfig, BlockType, FellowConfig, ScheduleConfig
from src.scheduler import check_feasibility, solve_schedule


def make_small_config() -> ScheduleConfig:
    """Build a compact but feasible config for regression tests."""
    blocks = [
        BlockConfig(
            name="Block A",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Block B",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Block C",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Night Float",
            block_type=BlockType.NIGHT,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
    ]
    fellows = [
        FellowConfig(name=f"Fellow {i + 1}", pto_rankings=[4, 8, 12])
        for i in range(4)
    ]
    return ScheduleConfig(
        num_fellows=4,
        num_weeks=16,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=1,
        pto_weeks_to_rank=3,
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


def test_feasibility_flags_block_capacity_conflict() -> None:
    """The feasibility checker should catch impossible per-block staffing."""
    config = make_small_config()
    config.blocks[0].max_weeks = 1

    issues = check_feasibility(config)

    assert any("Block capacity conflict" in issue for issue in issues)


def test_feasibility_flags_aggregate_assignment_conflict() -> None:
    """The feasibility checker should catch impossible total assignment load."""
    config = ScheduleConfig(
        num_fellows=3,
        num_weeks=4,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=1,
        pto_weeks_to_rank=1,
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=5.0,
        blocks=[
            BlockConfig(
                name=name,
                block_type=BlockType.DAY,
                fellows_needed=0,
                hours_per_week=40.0,
                min_weeks=0,
                max_weeks=4,
                is_active=True,
            )
            for name in ("A", "B", "C", "D")
        ],
        fellows=[
            FellowConfig(name=f"Fellow {idx + 1}", pto_rankings=[1])
            for idx in range(3)
        ],
    )

    issues = check_feasibility(config)

    assert any("Coverage/minimum conflict" in issue for issue in issues)


def test_export_pdf_writes_ascii_safe_output(tmp_path: Path) -> None:
    """PDF export should succeed with the built-in Helvetica font."""
    config = make_small_config()
    result = solve_schedule(config)

    pdf_path = export_pdf(result, config, tmp_path / "schedule.pdf")

    assert pdf_path.exists()


def test_export_download_helpers_return_bytes() -> None:
    """Browser-download helpers should produce non-empty payloads."""
    config = make_small_config()
    result = solve_schedule(config)

    csv_bytes = export_csv_bytes(result, config)
    pdf_bytes = export_pdf_bytes(result, config)

    assert csv_bytes.startswith(b"Week,")
    assert pdf_bytes.startswith(b"%PDF")
