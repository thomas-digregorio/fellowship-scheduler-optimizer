"""Data models for the fellowship scheduling system.

Defines the core dataclasses used across the project. These are plain
Python data containers — no business logic lives here. Think of them
as the "schema" that every other module reads from and writes to.

Dataclass Hierarchy:
    BlockConfig     → settings for ONE rotation block
    FellowConfig    → settings for ONE fellow
    ScheduleConfig  → global parameters (contains lists of the above)
    ScheduleResult  → solver output (the generated schedule)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BlockType(Enum):
    """Whether a rotation block runs during the day or night.

    This affects staffing rules and 24-hr call eligibility.
    """
    DAY = "day"
    NIGHT = "night"


class SolverStatus(Enum):
    """Possible outcomes when the CP-SAT solver finishes."""
    OPTIMAL = "optimal"       # best possible solution found
    FEASIBLE = "feasible"     # valid solution, but maybe not the best
    INFEASIBLE = "infeasible" # no valid schedule exists with current constraints
    TIMEOUT = "timeout"       # solver ran out of time
    ERROR = "error"           # something went wrong


# ---------------------------------------------------------------------------
# Block Configuration
# ---------------------------------------------------------------------------

@dataclass
class BlockConfig:
    """Settings for a single rotation block (e.g., "CCU", "Night Float").

    All numeric fields are configurable via the Streamlit sidebar, so the
    program chief can tune them without editing code.

    Attributes
    ----------
    name : str
        Human-readable name shown in the schedule grid.
    block_type : BlockType
        DAY or NIGHT — controls staffing rules.
    fellows_needed : int
        *Minimum* fellows that must be on this block each active week.
        Set to 0 if the block can go unstaffed some weeks.
    hours_per_week : float
        Expected weekly hours. Used for 80-hr trailing-average check.
    min_weeks : int
        Each fellow must spend *at least* this many weeks on the block
        over the year.
    max_weeks : int
        Each fellow can spend *at most* this many weeks on the block.
    is_active : bool
        If False, the block is disabled and won't appear in the schedule.
    has_weekend_off : bool
        If True, fellows on this block don't work weekends (relevant for
        deciding who is eligible for Saturday call).
    requires_call_coverage : bool
        If True, at least one fellow must take 24-hr Saturday call to
        cover this block's weekend needs.
    """
    name: str
    block_type: BlockType = BlockType.DAY
    fellows_needed: int = 0
    hours_per_week: float = 60.0
    min_weeks: int = 1
    max_weeks: int = 8
    is_active: bool = True
    has_weekend_off: bool = False
    requires_call_coverage: bool = False

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "block_type": self.block_type.value,
            "fellows_needed": self.fellows_needed,
            "hours_per_week": self.hours_per_week,
            "min_weeks": self.min_weeks,
            "max_weeks": self.max_weeks,
            "is_active": self.is_active,
            "has_weekend_off": self.has_weekend_off,
            "requires_call_coverage": self.requires_call_coverage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BlockConfig:
        """Deserialize from a JSON dictionary."""
        data = data.copy()
        data["block_type"] = BlockType(data["block_type"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Fellow Configuration
# ---------------------------------------------------------------------------

@dataclass
class FellowConfig:
    """Settings for a single fellow.

    Attributes
    ----------
    name : str
        Display name (e.g., "Fellow 1").
    pto_rankings : list[int]
        Preferred PTO weeks, ranked best-to-worst. Each entry is a
        0-based week index (0 = first week of July). Length should
        equal ``ScheduleConfig.pto_weeks_to_rank``.
    unavailable_weeks : list[int]
        Weeks the fellow cannot work at all (e.g., maternity leave).
        These weeks are locked as unavailable before the solver runs.
    """
    name: str
    pto_rankings: list[int] = field(default_factory=list)
    unavailable_weeks: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "pto_rankings": self.pto_rankings,
            "unavailable_weeks": self.unavailable_weeks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FellowConfig:
        """Deserialize from a JSON dictionary."""
        return cls(**data)


# ---------------------------------------------------------------------------
# Global Schedule Configuration
# ---------------------------------------------------------------------------

@dataclass
class ScheduleConfig:
    """Master configuration that controls the entire scheduling run.

    Holds both scalar parameters (like the 80-hr cap) and the lists of
    block/fellow configs. The Streamlit sidebar populates this object,
    which then gets passed to the solver.

    Attributes
    ----------
    num_fellows : int
        Total fellows to schedule (default 9).
    num_weeks : int
        Weeks in the academic year (default 52).
    start_date : date
        First Monday of the academic year.
    pto_weeks_granted : int
        How many PTO weeks each fellow actually receives.
    pto_weeks_to_rank : int
        How many PTO weeks each fellow ranks in their preference list.
    pto_blackout_weeks : list[int]
        Week indices where PTO is forbidden (e.g., orientation).
    max_concurrent_pto : int
        At most this many fellows can be on PTO the same week.
    max_consecutive_night_float : int
        Max back-to-back weeks a fellow can be on Night Float.
    call_day : str
        Day of week for 24-hr call (e.g., "saturday").
    call_hours : float
        Hours added to a fellow's week when they have call.
    call_excluded_blocks : list[str]
        Fellows on these blocks are exempt from 24-hr call.
    hours_cap : float
        ACGME max weekly hours (the 4-week trailing average limit).
    trailing_avg_weeks : int
        Window size for the trailing hours average.
    solver_timeout_seconds : float
        Max time the solver is allowed to run.
    blocks : list[BlockConfig]
        Configuration for each rotation block.
    fellows : list[FellowConfig]
        Configuration for each fellow.
    """
    num_fellows: int = 9
    num_weeks: int = 52
    start_date: date = field(default_factory=lambda: date(2026, 7, 1))
    pto_weeks_granted: int = 4
    pto_weeks_to_rank: int = 6
    pto_blackout_weeks: list[int] = field(default_factory=lambda: [0, 1])
    max_concurrent_pto: int = 1
    max_consecutive_night_float: int = 2
    call_day: str = "saturday"
    call_hours: float = 24.0
    call_excluded_blocks: list[str] = field(
        default_factory=lambda: ["Night Float", "PTO"]
    )
    hours_cap: float = 80.0
    trailing_avg_weeks: int = 4
    solver_timeout_seconds: float = 120.0
    blocks: list[BlockConfig] = field(default_factory=list)
    fellows: list[FellowConfig] = field(default_factory=list)

    # -- Derived helpers (not stored, computed on access) --

    @property
    def active_blocks(self) -> list[BlockConfig]:
        """Return only blocks that are currently active."""
        return [b for b in self.blocks if b.is_active]

    @property
    def block_names(self) -> list[str]:
        """Return names of all active blocks (no PTO)."""
        return [b.name for b in self.active_blocks]

    @property
    def all_states(self) -> list[str]:
        """All possible states a fellow can be in: block names + 'PTO'."""
        return self.block_names + ["PTO"]

    def to_dict(self) -> dict:
        """Serialize the full config to a JSON-friendly dictionary."""
        return {
            "num_fellows": self.num_fellows,
            "num_weeks": self.num_weeks,
            "start_date": self.start_date.isoformat(),
            "pto_weeks_granted": self.pto_weeks_granted,
            "pto_weeks_to_rank": self.pto_weeks_to_rank,
            "pto_blackout_weeks": self.pto_blackout_weeks,
            "max_concurrent_pto": self.max_concurrent_pto,
            "max_consecutive_night_float": self.max_consecutive_night_float,
            "call_day": self.call_day,
            "call_hours": self.call_hours,
            "call_excluded_blocks": self.call_excluded_blocks,
            "hours_cap": self.hours_cap,
            "trailing_avg_weeks": self.trailing_avg_weeks,
            "solver_timeout_seconds": self.solver_timeout_seconds,
            "blocks": [b.to_dict() for b in self.blocks],
            "fellows": [f.to_dict() for f in self.fellows],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleConfig:
        """Deserialize from a JSON dictionary."""
        data = data.copy()
        data["start_date"] = date.fromisoformat(data["start_date"])
        data["blocks"] = [BlockConfig.from_dict(b) for b in data["blocks"]]
        data["fellows"] = [FellowConfig.from_dict(f) for f in data["fellows"]]
        return cls(**data)


# ---------------------------------------------------------------------------
# Solver Output
# ---------------------------------------------------------------------------

@dataclass
class ScheduleResult:
    """The generated schedule returned by the CP-SAT solver.

    Attributes
    ----------
    assignments : list[list[str]]
        2-D grid: ``assignments[fellow_idx][week]`` is the block name
        (or ``"PTO"``) that fellow is assigned to that week.
    call_assignments : list[list[bool]]
        2-D grid: ``call_assignments[fellow_idx][week]`` is True if
        that fellow has 24-hr Saturday call that week.
    solver_status : SolverStatus
        Whether the solver found an optimal, feasible, or no solution.
    objective_value : float
        PTO satisfaction score (higher = more preferred PTO weeks granted).
    solve_time_seconds : float
        Wall-clock time the solver took.
    """
    assignments: list[list[str]]
    call_assignments: list[list[bool]]
    solver_status: SolverStatus = SolverStatus.ERROR
    objective_value: float = 0.0
    solve_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "assignments": self.assignments,
            "call_assignments": self.call_assignments,
            "solver_status": self.solver_status.value,
            "objective_value": self.objective_value,
            "solve_time_seconds": self.solve_time_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleResult:
        """Deserialize from a JSON dictionary."""
        data = data.copy()
        data["solver_status"] = SolverStatus(data["solver_status"])
        return cls(**data)
