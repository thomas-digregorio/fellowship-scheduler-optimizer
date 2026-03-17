"""Data models for the fellowship scheduling system.

The scheduler now distinguishes fellows by training year and stores
hard/soft scheduling rules as explicit configuration objects. The solver
and UI both read the same rule definitions so cohort-specific behavior is
described in data rather than scattered across ad hoc conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrainingYear(Enum):
    """Training year / cohort for a fellow."""

    PGY1 = "PGY1"
    PGY2 = "PGY2"
    PGY3 = "PGY3"


class BlockType(Enum):
    """Whether a rotation block runs during the day or night."""

    DAY = "day"
    NIGHT = "night"


class SolverStatus(Enum):
    """Possible outcomes when the CP-SAT solver finishes."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    TIMEOUT = "timeout"
    ERROR = "error"


class SoftRuleDirection(Enum):
    """How a soft sequence rule should evaluate adjacency."""

    FORWARD = "forward"
    EITHER = "either"


# ---------------------------------------------------------------------------
# Block Configuration
# ---------------------------------------------------------------------------


@dataclass
class BlockConfig:
    """Settings for a single rotation block."""

    name: str
    block_type: BlockType = BlockType.DAY
    fellows_needed: int = 0
    hours_per_week: float = 60.0
    min_weeks: int = 0
    max_weeks: int = 52
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
        payload = data.copy()
        payload["block_type"] = BlockType(payload["block_type"])
        return cls(**payload)


# ---------------------------------------------------------------------------
# Fellow Configuration
# ---------------------------------------------------------------------------


@dataclass
class FellowConfig:
    """Settings for a single fellow."""

    name: str
    training_year: TrainingYear = TrainingYear.PGY1
    pto_rankings: list[int] = field(default_factory=list)
    unavailable_weeks: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "training_year": self.training_year.value,
            "pto_rankings": self.pto_rankings,
            "unavailable_weeks": self.unavailable_weeks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FellowConfig:
        """Deserialize from a JSON dictionary.

        Legacy configs may not include ``training_year``. Those fellows
        default to PGY1 so older saved files still load successfully.
        """

        payload = data.copy()
        payload["training_year"] = TrainingYear(
            payload.get("training_year", TrainingYear.PGY1.value)
        )
        return cls(**payload)


# ---------------------------------------------------------------------------
# Rule Configuration
# ---------------------------------------------------------------------------


def _serialize_years(years: list[TrainingYear]) -> list[str]:
    """Return enum values as strings for JSON."""
    return [year.value for year in years]


def _deserialize_years(values: list[str] | None) -> list[TrainingYear]:
    """Parse training-year strings from JSON."""
    return [TrainingYear(value) for value in values or []]


def _default_pto_preference_weights(num_ranked_weeks: int) -> list[int]:
    """Return the legacy linear PTO preference weights for the rank count."""

    return [max(num_ranked_weeks - rank, 0) for rank in range(num_ranked_weeks)]


def _normalize_pto_preference_weight_overrides(
    values: dict[str, list[int]] | None,
) -> dict[str, list[int]]:
    """Parse saved PTO weight overrides into a clean JSON-compatible mapping."""

    if not isinstance(values, dict):
        return {}

    valid_years = {year.value for year in TrainingYear}
    normalized: dict[str, list[int]] = {}
    for year_value, weights in values.items():
        if year_value not in valid_years or not isinstance(weights, list):
            continue
        parsed_weights: list[int] = []
        for weight in weights:
            if weight in (None, ""):
                parsed_weights.append(0)
                continue
            parsed_weights.append(max(0, int(weight)))
        normalized[year_value] = parsed_weights
    return normalized


@dataclass
class CoverageRule:
    """Minimum / maximum staffing for a block by cohort and week window."""

    name: str
    block_name: str
    eligible_years: list[TrainingYear]
    min_fellows: int = 0
    max_fellows: int | None = None
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "block_name": self.block_name,
            "eligible_years": _serialize_years(self.eligible_years),
            "min_fellows": self.min_fellows,
            "max_fellows": self.max_fellows,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CoverageRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["eligible_years"] = _deserialize_years(
            payload.get("eligible_years")
        )
        return cls(**payload)


@dataclass
class EligibilityRule:
    """Restrict which cohorts may be assigned to certain blocks."""

    name: str
    block_names: list[str]
    allowed_years: list[TrainingYear]
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "block_names": self.block_names,
            "allowed_years": _serialize_years(self.allowed_years),
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EligibilityRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["allowed_years"] = _deserialize_years(
            payload.get("allowed_years")
        )
        return cls(**payload)


@dataclass
class WeekCountRule:
    """Per-fellow minimum / maximum weeks on one or more blocks."""

    name: str
    applicable_years: list[TrainingYear]
    block_names: list[str]
    min_weeks: int = 0
    max_weeks: int = 52
    start_week: int = 0
    end_week: int | None = None
    applies_to_each_fellow: bool = True
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "block_names": self.block_names,
            "min_weeks": self.min_weeks,
            "max_weeks": self.max_weeks,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "applies_to_each_fellow": self.applies_to_each_fellow,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WeekCountRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class CohortLimitRule:
    """Limit how many fellows from a cohort can be in a state per week."""

    name: str
    applicable_years: list[TrainingYear]
    state_name: str
    max_fellows: int
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "state_name": self.state_name,
            "max_fellows": self.max_fellows,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CohortLimitRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class PrerequisiteRule:
    """Require certain prior experience before a target rotation."""

    name: str
    applicable_years: list[TrainingYear]
    target_block: str
    prerequisite_blocks: list[str]
    prerequisite_min_weeks: int = 1
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "target_block": self.target_block,
            "prerequisite_blocks": self.prerequisite_blocks,
            "prerequisite_min_weeks": self.prerequisite_min_weeks,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PrerequisiteRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class ForbiddenTransitionRule:
    """Forbid a target block immediately after certain blocks."""

    name: str
    applicable_years: list[TrainingYear]
    target_block: str
    forbidden_previous_blocks: list[str]
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "target_block": self.target_block,
            "forbidden_previous_blocks": self.forbidden_previous_blocks,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ForbiddenTransitionRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class SoftSequenceRule:
    """Weighted bonus / penalty for adjacent weekly assignments."""

    name: str
    applicable_years: list[TrainingYear]
    left_states: list[str]
    right_states: list[str]
    weight: int
    direction: SoftRuleDirection = SoftRuleDirection.FORWARD
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "left_states": self.left_states,
            "right_states": self.right_states,
            "weight": self.weight,
            "direction": self.direction.value,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SoftSequenceRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        payload["direction"] = SoftRuleDirection(
            payload.get("direction", SoftRuleDirection.FORWARD.value)
        )
        return cls(**payload)


# ---------------------------------------------------------------------------
# Global Schedule Configuration
# ---------------------------------------------------------------------------


@dataclass
class ScheduleConfig:
    """Master configuration that controls the entire scheduling run."""

    num_fellows: int = 9
    num_weeks: int = 52
    start_date: date = field(default_factory=lambda: date(2026, 7, 13))
    pto_weeks_granted: int = 4
    pto_weeks_to_rank: int = 6
    pto_blackout_weeks: list[int] = field(default_factory=list)
    max_concurrent_pto: int = 1
    max_consecutive_night_float: int = 2
    call_day: str = "saturday"
    call_hours: float = 24.0
    call_excluded_blocks: list[str] = field(
        default_factory=lambda: ["Night Float", "PTO"]
    )
    hours_cap: float = 80.0
    trailing_avg_weeks: int = 4
    solver_timeout_seconds: float = 300.0
    pto_preference_weight_overrides: dict[str, list[int]] = field(default_factory=dict)
    blocks: list[BlockConfig] = field(default_factory=list)
    fellows: list[FellowConfig] = field(default_factory=list)
    coverage_rules: list[CoverageRule] = field(default_factory=list)
    eligibility_rules: list[EligibilityRule] = field(default_factory=list)
    week_count_rules: list[WeekCountRule] = field(default_factory=list)
    cohort_limit_rules: list[CohortLimitRule] = field(default_factory=list)
    prerequisite_rules: list[PrerequisiteRule] = field(default_factory=list)
    forbidden_transition_rules: list[ForbiddenTransitionRule] = field(
        default_factory=list
    )
    soft_sequence_rules: list[SoftSequenceRule] = field(default_factory=list)

    @property
    def active_blocks(self) -> list[BlockConfig]:
        """Return only blocks that are currently active."""
        return [block for block in self.blocks if block.is_active]

    @property
    def block_names(self) -> list[str]:
        """Return names of all active blocks."""
        return [block.name for block in self.active_blocks]

    @property
    def all_states(self) -> list[str]:
        """All possible states a fellow can be in."""
        return self.block_names + ["PTO"]

    @property
    def cohort_counts(self) -> dict[TrainingYear, int]:
        """Return fellow counts for each cohort."""
        return {
            year: sum(
                1 for fellow in self.fellows if fellow.training_year == year
            )
            for year in TrainingYear
        }

    @property
    def uses_structured_rules(self) -> bool:
        """Return True when cohort-aware rules are configured."""
        return any(
            (
                self.coverage_rules,
                self.eligibility_rules,
                self.week_count_rules,
                self.cohort_limit_rules,
                self.prerequisite_rules,
                self.forbidden_transition_rules,
                self.soft_sequence_rules,
            )
        )

    def fellow_indices_for_years(
        self,
        years: list[TrainingYear],
    ) -> list[int]:
        """Return fellow indices for the requested cohorts.

        An empty ``years`` list means "all fellows", which keeps rule
        definitions concise when a constraint is not cohort-specific.
        """

        if not years:
            return list(range(len(self.fellows)))
        year_set = set(years)
        return [
            index
            for index, fellow in enumerate(self.fellows)
            if fellow.training_year in year_set
        ]

    def pto_preference_weights_for_year(self, year: TrainingYear) -> list[int]:
        """Return objective weights for ranked PTO weeks for one cohort."""

        default_weights = _default_pto_preference_weights(self.pto_weeks_to_rank)
        override_weights = self.pto_preference_weight_overrides.get(year.value, [])
        if not override_weights:
            return default_weights

        weights = default_weights.copy()
        for rank, weight in enumerate(override_weights[: self.pto_weeks_to_rank]):
            weights[rank] = max(0, int(weight))
        return weights

    def set_pto_preference_weights_for_year(
        self,
        year: TrainingYear,
        weights: list[int],
    ) -> None:
        """Persist cohort PTO preference weights, omitting default-only overrides."""

        normalized = [max(0, int(weight)) for weight in weights[: self.pto_weeks_to_rank]]
        default_weights = _default_pto_preference_weights(self.pto_weeks_to_rank)
        full_weights = default_weights.copy()
        for rank, weight in enumerate(normalized):
            full_weights[rank] = weight

        if full_weights == default_weights:
            self.pto_preference_weight_overrides.pop(year.value, None)
        else:
            self.pto_preference_weight_overrides[year.value] = full_weights

    def to_dict(self) -> dict:
        """Serialize the full config to a JSON-friendly dictionary."""
        return {
            "num_fellows": len(self.fellows),
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
            "pto_preference_weight_overrides": self.pto_preference_weight_overrides,
            "blocks": [block.to_dict() for block in self.blocks],
            "fellows": [fellow.to_dict() for fellow in self.fellows],
            "coverage_rules": [rule.to_dict() for rule in self.coverage_rules],
            "eligibility_rules": [
                rule.to_dict() for rule in self.eligibility_rules
            ],
            "week_count_rules": [
                rule.to_dict() for rule in self.week_count_rules
            ],
            "cohort_limit_rules": [
                rule.to_dict() for rule in self.cohort_limit_rules
            ],
            "prerequisite_rules": [
                rule.to_dict() for rule in self.prerequisite_rules
            ],
            "forbidden_transition_rules": [
                rule.to_dict() for rule in self.forbidden_transition_rules
            ],
            "soft_sequence_rules": [
                rule.to_dict() for rule in self.soft_sequence_rules
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleConfig:
        """Deserialize from a JSON dictionary."""

        payload = data.copy()
        payload["start_date"] = date.fromisoformat(payload["start_date"])
        payload["pto_preference_weight_overrides"] = _normalize_pto_preference_weight_overrides(
            payload.get("pto_preference_weight_overrides")
        )
        payload["blocks"] = [
            BlockConfig.from_dict(block) for block in payload.get("blocks", [])
        ]
        payload["fellows"] = [
            FellowConfig.from_dict(fellow)
            for fellow in payload.get("fellows", [])
        ]
        payload["coverage_rules"] = [
            CoverageRule.from_dict(rule)
            for rule in payload.get("coverage_rules", [])
        ]
        payload["eligibility_rules"] = [
            EligibilityRule.from_dict(rule)
            for rule in payload.get("eligibility_rules", [])
        ]
        payload["week_count_rules"] = [
            WeekCountRule.from_dict(rule)
            for rule in payload.get("week_count_rules", [])
        ]
        payload["cohort_limit_rules"] = [
            CohortLimitRule.from_dict(rule)
            for rule in payload.get("cohort_limit_rules", [])
        ]
        payload["prerequisite_rules"] = [
            PrerequisiteRule.from_dict(rule)
            for rule in payload.get("prerequisite_rules", [])
        ]
        payload["forbidden_transition_rules"] = [
            ForbiddenTransitionRule.from_dict(rule)
            for rule in payload.get("forbidden_transition_rules", [])
        ]
        payload["soft_sequence_rules"] = [
            SoftSequenceRule.from_dict(rule)
            for rule in payload.get("soft_sequence_rules", [])
        ]
        payload["num_fellows"] = len(payload["fellows"]) or payload.get(
            "num_fellows", 0
        )
        return cls(**payload)


# ---------------------------------------------------------------------------
# Solver Output
# ---------------------------------------------------------------------------


@dataclass
class ScheduleResult:
    """The generated schedule returned by the CP-SAT solver."""

    assignments: list[list[str]]
    call_assignments: list[list[bool]]
    solver_status: SolverStatus = SolverStatus.ERROR
    objective_value: float = 0.0
    solve_time_seconds: float = 0.0
    objective_breakdown: list[dict[str, int | str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "assignments": self.assignments,
            "call_assignments": self.call_assignments,
            "solver_status": self.solver_status.value,
            "objective_value": self.objective_value,
            "solve_time_seconds": self.solve_time_seconds,
            "objective_breakdown": self.objective_breakdown,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleResult:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["solver_status"] = SolverStatus(payload["solver_status"])
        return cls(**payload)
