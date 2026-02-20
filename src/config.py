"""Default configuration and block definitions.

This module creates the "factory defaults" for all 14 rotation blocks
and 9 fellows. When the Streamlit app boots for the first time (no
saved config on disk), it calls ``get_default_config()`` to populate
the sidebar.

The defaults are intentionally *loose* — all block minimums are set to 0
so the solver has maximum freedom. Tighten them in the dashboard before
running the solver.
"""

from __future__ import annotations

from datetime import date

from src.models import BlockConfig, BlockType, FellowConfig, ScheduleConfig


# ---------------------------------------------------------------------------
# Color palette for each block (used by the dashboard for consistent
# color-coding across all three panels).  Maps block name → hex color.
# ---------------------------------------------------------------------------

BLOCK_COLORS: dict[str, str] = {
    "Night Float":  "#6C3483",   # deep purple
    "CCU":          "#C0392B",   # red
    "Consult SRC":  "#2980B9",   # blue
    "Consult Y":    "#1ABC9C",   # teal
    "Consult VA":   "#16A085",   # dark teal
    "Cath Y":       "#E67E22",   # orange
    "Cath SRC":     "#D35400",   # dark orange
    "EP":           "#F1C40F",   # yellow
    "Echo Y":       "#27AE60",   # green
    "VA Echo":      "#2ECC71",   # light green
    "CHF":          "#8E44AD",   # purple
    "Nuc Y":        "#3498DB",   # light blue
    "VA Clinic":    "#E74C3C",   # coral
    "Research":     "#95A5A6",   # gray
    "PTO":          "#BDC3C7",   # light gray
}


def get_default_blocks() -> list[BlockConfig]:
    """Return the 14 rotation blocks with sensible defaults.

    Notes
    -----
    ``fellows_needed`` is set to 0 for all blocks by default. The user
    must configure staffing requirements in the Streamlit sidebar before
    solving.  The feasibility checker will flag if the total exceeds the
    number of available fellows.

    Returns
    -------
    list[BlockConfig]
        One ``BlockConfig`` per rotation block, ordered as they appear
        in clinical convention.
    """
    return [
        BlockConfig(
            name="Night Float",
            block_type=BlockType.NIGHT,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="CCU",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=8,
            is_active=True,
            has_weekend_off=False,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Consult SRC",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=8,
            is_active=True,
            has_weekend_off=False,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Consult Y",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=8,
            is_active=True,
            has_weekend_off=False,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Consult VA",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=8,
            is_active=True,
            has_weekend_off=False,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Cath Y",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Cath SRC",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="EP",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Echo Y",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="VA Echo",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="CHF",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Nuc Y",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="VA Clinic",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Research",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=60.0,
            min_weeks=1,
            max_weeks=8,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
    ]


def get_default_fellows(num_fellows: int = 9) -> list[FellowConfig]:
    """Return default fellow configs with empty PTO rankings.

    Parameters
    ----------
    num_fellows : int
        Number of fellows (default 9).

    Returns
    -------
    list[FellowConfig]
        One config per fellow, named "Fellow 1" through "Fellow N".
    """
    return [
        FellowConfig(name=f"Fellow {i + 1}")
        for i in range(num_fellows)
    ]


def get_default_config() -> ScheduleConfig:
    """Return a complete default ScheduleConfig.

    This is the starting point when no saved config exists on disk.
    The user is expected to customize block staffing, PTO rankings,
    and other parameters through the Streamlit sidebar.

    Returns
    -------
    ScheduleConfig
        Fully populated config with default blocks and fellows.
    """
    return ScheduleConfig(
        num_fellows=9,
        num_weeks=52,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=4,
        pto_weeks_to_rank=6,
        pto_blackout_weeks=[0, 1],  # first two weeks of July
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=120.0,
        blocks=get_default_blocks(),
        fellows=get_default_fellows(9),
    )
