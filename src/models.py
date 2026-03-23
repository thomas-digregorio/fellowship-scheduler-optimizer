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


LEGACY_YEAR_ALIASES = {
    "PGY1": "F1",
    "PGY2": "S2",
    "PGY3": "T3",
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrainingYear(Enum):
    """Training year / cohort for a fellow."""

    F1 = "F1"
    S2 = "S2"
    T3 = "T3"


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


def _normalize_legacy_year_aliases(value):
    """Recursively replace legacy cohort labels with the new terminology."""

    if isinstance(value, str):
        normalized = value
        for legacy, replacement in LEGACY_YEAR_ALIASES.items():
            normalized = normalized.replace(legacy, replacement)
        return normalized
    if isinstance(value, list):
        return [_normalize_legacy_year_aliases(item) for item in value]
    if isinstance(value, dict):
        return {
            _normalize_legacy_year_aliases(key): _normalize_legacy_year_aliases(item)
            for key, item in value.items()
        }
    return value


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
    training_year: TrainingYear = TrainingYear.F1
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
        default to F1 so older saved files still load successfully.
        """

        payload = _normalize_legacy_year_aliases(data.copy())
        payload["training_year"] = TrainingYear(
            payload.get("training_year", TrainingYear.F1.value)
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
    return [TrainingYear(_normalize_legacy_year_aliases(value)) for value in values or []]


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
        year_value = _normalize_legacy_year_aliases(year_value)
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
class RollingWindowRule:
    """Limit how often a fellow can be in certain states within a rolling window."""

    name: str
    applicable_years: list[TrainingYear]
    state_names: list[str]
    window_size_weeks: int
    max_weeks_in_window: int
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "state_names": self.state_names,
            "window_size_weeks": self.window_size_weeks,
            "max_weeks_in_window": self.max_weeks_in_window,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RollingWindowRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class ConsecutiveStateLimitRule:
    """Limit consecutive weeks in selected states for one cohort."""

    name: str
    applicable_years: list[TrainingYear]
    state_names: list[str]
    max_consecutive_weeks: int
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "state_names": self.state_names,
            "max_consecutive_weeks": self.max_consecutive_weeks,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConsecutiveStateLimitRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class FirstAssignmentRunLimitRule:
    """Limit the consecutive length of a fellow's first run on one block."""

    name: str
    applicable_years: list[TrainingYear]
    block_name: str
    max_run_length_weeks: int
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "block_name": self.block_name,
            "max_run_length_weeks": self.max_run_length_weeks,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FirstAssignmentRunLimitRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class ContiguousBlockRule:
    """Require a cohort to complete one block in a single contiguous run."""

    name: str
    applicable_years: list[TrainingYear]
    block_name: str
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "block_name": self.block_name,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContiguousBlockRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class FirstAssignmentPairingRule:
    """Require supervision when a fellow starts a block for the first time."""

    name: str
    trainee_years: list[TrainingYear]
    block_name: str
    mentor_years: list[TrainingYear]
    experienced_peer_years: list[TrainingYear]
    required_prior_weeks: int = 1
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "trainee_years": _serialize_years(self.trainee_years),
            "block_name": self.block_name,
            "mentor_years": _serialize_years(self.mentor_years),
            "experienced_peer_years": _serialize_years(self.experienced_peer_years),
            "required_prior_weeks": self.required_prior_weeks,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FirstAssignmentPairingRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["trainee_years"] = _deserialize_years(payload.get("trainee_years"))
        payload["mentor_years"] = _deserialize_years(payload.get("mentor_years"))
        payload["experienced_peer_years"] = _deserialize_years(
            payload.get("experienced_peer_years")
        )
        return cls(**payload)


@dataclass
class IndividualFellowRequirementRule:
    """Require an exact fellow to spend a min/max number of weeks on one block."""

    training_year: TrainingYear
    fellow_name: str
    block_name: str
    min_weeks: int = 0
    max_weeks: int = 52
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "training_year": self.training_year.value,
            "fellow_name": self.fellow_name,
            "block_name": self.block_name,
            "min_weeks": self.min_weeks,
            "max_weeks": self.max_weeks,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IndividualFellowRequirementRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["training_year"] = TrainingYear(
            _normalize_legacy_year_aliases(
                payload.get("training_year", TrainingYear.F1.value)
            )
        )
        return cls(**payload)


@dataclass
class LinkedFellowStateRule:
    """Require two named fellows in one cohort to share the same state each week."""

    training_year: TrainingYear
    first_fellow_name: str
    second_fellow_name: str
    state_name: str
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "training_year": self.training_year.value,
            "first_fellow_name": self.first_fellow_name,
            "second_fellow_name": self.second_fellow_name,
            "state_name": self.state_name,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LinkedFellowStateRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["training_year"] = TrainingYear(
            _normalize_legacy_year_aliases(
                payload.get("training_year", TrainingYear.F1.value)
            )
        )
        return cls(**payload)


@dataclass
class PrerequisiteRule:
    """Require certain prior experience before a target rotation."""

    name: str
    applicable_years: list[TrainingYear]
    target_block: str
    prerequisite_blocks: list[str]
    prerequisite_block_groups: list[list[str]] = field(default_factory=list)
    prerequisite_min_weeks: int = 1
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "target_block": self.target_block,
            "prerequisite_blocks": self.prerequisite_blocks,
            "prerequisite_block_groups": self.prerequisite_block_groups,
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


@dataclass
class SoftSingleWeekBlockRule:
    """Weighted bonus / penalty for one-week runs of selected rotations."""

    name: str
    applicable_years: list[TrainingYear]
    excluded_states: list[str]
    weight: int
    included_states: list[str] = field(default_factory=list)
    start_week: int = 0
    end_week: int | None = None
    adjacent_to_first_state_exemption: str | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "included_states": self.included_states,
            "excluded_states": self.excluded_states,
            "weight": self.weight,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "adjacent_to_first_state_exemption": self.adjacent_to_first_state_exemption,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SoftSingleWeekBlockRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class SoftStateAssignmentRule:
    """Weighted bonus / penalty for being assigned to selected states."""

    name: str
    applicable_years: list[TrainingYear]
    state_names: list[str]
    weight: int
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "state_names": self.state_names,
            "weight": self.weight,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SoftStateAssignmentRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
        )
        return cls(**payload)


@dataclass
class SoftCohortBalanceRule:
    """Weighted penalty on imbalance across fellows for selected states."""

    name: str
    applicable_years: list[TrainingYear]
    state_names: list[str]
    weight: int
    start_week: int = 0
    end_week: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "applicable_years": _serialize_years(self.applicable_years),
            "state_names": self.state_names,
            "weight": self.weight,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SoftCohortBalanceRule:
        """Deserialize from a JSON dictionary."""
        payload = data.copy()
        payload["applicable_years"] = _deserialize_years(
            payload.get("applicable_years")
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
    max_concurrent_pto: int = 1
    max_consecutive_night_float: int = 2
    call_day: str = "saturday"
    call_hours: float = 24.0
    call_excluded_blocks: list[str] = field(
        default_factory=lambda: ["Night Float", "PTO"]
    )
    structured_call_rules_enabled: bool = False
    call_eligible_years: list[TrainingYear] = field(default_factory=list)
    call_allowed_block_names: list[str] = field(default_factory=list)
    call_min_per_fellow: int = 0
    call_max_per_fellow: int = 52
    call_forbidden_following_blocks: list[str] = field(default_factory=list)
    call_max_consecutive_weeks_per_fellow: int = 52
    call_first_call_preferred_blocks: list[str] = field(default_factory=list)
    call_first_call_preference_weight: int = 0
    call_first_call_prerequisite_blocks: list[str] = field(default_factory=list)
    call_first_call_prerequisite_weight: int = 0
    call_holiday_anchor_week: int | None = None
    call_holiday_sensitive_blocks: list[str] = field(default_factory=list)
    call_holiday_target_weeks: list[int] = field(default_factory=list)
    call_holiday_conflict_weight: int = 0
    srcva_weekend_call_enabled: bool = False
    srcva_weekend_call_eligible_years: list[TrainingYear] = field(default_factory=list)
    srcva_weekend_call_allowed_block_names: list[str] = field(default_factory=list)
    srcva_weekend_call_f1_start_week: int | None = None
    srcva_weekend_call_f1_min: int = 0
    srcva_weekend_call_f1_max: int = 0
    srcva_weekend_call_s2_min: int = 0
    srcva_weekend_call_s2_max: int = 0
    srcva_total_call_f1_min: int = 0
    srcva_total_call_f1_max: int = 52
    srcva_weekday_call_enabled: bool = False
    srcva_weekday_call_eligible_years: list[TrainingYear] = field(default_factory=list)
    srcva_weekday_call_allowed_block_names: list[str] = field(default_factory=list)
    srcva_weekday_call_f1_start_week: int | None = None
    srcva_weekday_call_f1_min: int = 0
    srcva_weekday_call_f1_max: int = 0
    srcva_weekday_call_s2_min: int = 0
    srcva_weekday_call_s2_max: int = 0
    srcva_weekday_call_max_consecutive_nights: int = 1
    srcva_holiday_anchor_week: int | None = None
    srcva_christmas_target_week: int | None = None
    srcva_new_year_target_week: int | None = None
    srcva_holiday_preferred_anchor_blocks: list[str] = field(default_factory=list)
    srcva_holiday_preference_weight: int = 0
    srcva_holiday_repeat_weight: int = 0
    srcva_weekday_max_one_per_week_weight: int = 0
    srcva_weekday_same_week_as_weekend_weight: int = 0
    srcva_weekday_same_week_as_24hr_weight: int = 0
    hours_cap: float = 80.0
    trailing_avg_weeks: int = 4
    solver_timeout_seconds: float = 60.0
    pto_preference_weight_overrides: dict[str, list[int]] = field(default_factory=dict)
    blocks: list[BlockConfig] = field(default_factory=list)
    fellows: list[FellowConfig] = field(default_factory=list)
    coverage_rules: list[CoverageRule] = field(default_factory=list)
    eligibility_rules: list[EligibilityRule] = field(default_factory=list)
    week_count_rules: list[WeekCountRule] = field(default_factory=list)
    cohort_limit_rules: list[CohortLimitRule] = field(default_factory=list)
    rolling_window_rules: list[RollingWindowRule] = field(default_factory=list)
    consecutive_state_limit_rules: list[ConsecutiveStateLimitRule] = field(
        default_factory=list
    )
    first_assignment_run_limit_rules: list[FirstAssignmentRunLimitRule] = field(
        default_factory=list
    )
    contiguous_block_rules: list[ContiguousBlockRule] = field(default_factory=list)
    first_assignment_pairing_rules: list[FirstAssignmentPairingRule] = field(
        default_factory=list
    )
    individual_fellow_requirement_rules: list[IndividualFellowRequirementRule] = field(
        default_factory=list
    )
    linked_fellow_state_rules: list[LinkedFellowStateRule] = field(default_factory=list)
    prerequisite_rules: list[PrerequisiteRule] = field(default_factory=list)
    forbidden_transition_rules: list[ForbiddenTransitionRule] = field(
        default_factory=list
    )
    soft_sequence_rules: list[SoftSequenceRule] = field(default_factory=list)
    soft_single_week_block_rules: list[SoftSingleWeekBlockRule] = field(
        default_factory=list
    )
    soft_state_assignment_rules: list[SoftStateAssignmentRule] = field(
        default_factory=list
    )
    soft_cohort_balance_rules: list[SoftCohortBalanceRule] = field(
        default_factory=list
    )

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
                self.rolling_window_rules,
                self.consecutive_state_limit_rules,
                self.first_assignment_run_limit_rules,
                self.contiguous_block_rules,
                self.first_assignment_pairing_rules,
                self.individual_fellow_requirement_rules,
                self.linked_fellow_state_rules,
                self.prerequisite_rules,
                self.forbidden_transition_rules,
                self.soft_sequence_rules,
                self.soft_single_week_block_rules,
                self.soft_state_assignment_rules,
                self.soft_cohort_balance_rules,
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

    def fellow_index_for_year_and_name(
        self,
        year: TrainingYear,
        fellow_name: str,
    ) -> int | None:
        """Return the unique fellow index for one cohort/name pair, if any."""

        matches = [
            index
            for index, fellow in enumerate(self.fellows)
            if fellow.training_year == year and fellow.name == fellow_name
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def to_dict(self) -> dict:
        """Serialize the full config to a JSON-friendly dictionary."""
        return {
            "num_fellows": len(self.fellows),
            "num_weeks": self.num_weeks,
            "start_date": self.start_date.isoformat(),
            "pto_weeks_granted": self.pto_weeks_granted,
            "pto_weeks_to_rank": self.pto_weeks_to_rank,
            "max_concurrent_pto": self.max_concurrent_pto,
            "max_consecutive_night_float": self.max_consecutive_night_float,
            "call_day": self.call_day,
            "call_hours": self.call_hours,
            "call_excluded_blocks": self.call_excluded_blocks,
            "structured_call_rules_enabled": self.structured_call_rules_enabled,
            "call_eligible_years": _serialize_years(self.call_eligible_years),
            "call_allowed_block_names": self.call_allowed_block_names,
            "call_min_per_fellow": self.call_min_per_fellow,
            "call_max_per_fellow": self.call_max_per_fellow,
            "call_forbidden_following_blocks": self.call_forbidden_following_blocks,
            "call_max_consecutive_weeks_per_fellow": self.call_max_consecutive_weeks_per_fellow,
            "call_first_call_preferred_blocks": self.call_first_call_preferred_blocks,
            "call_first_call_preference_weight": self.call_first_call_preference_weight,
            "call_first_call_prerequisite_blocks": self.call_first_call_prerequisite_blocks,
            "call_first_call_prerequisite_weight": self.call_first_call_prerequisite_weight,
            "call_holiday_anchor_week": self.call_holiday_anchor_week,
            "call_holiday_sensitive_blocks": self.call_holiday_sensitive_blocks,
            "call_holiday_target_weeks": self.call_holiday_target_weeks,
            "call_holiday_conflict_weight": self.call_holiday_conflict_weight,
            "srcva_weekend_call_enabled": self.srcva_weekend_call_enabled,
            "srcva_weekend_call_eligible_years": _serialize_years(self.srcva_weekend_call_eligible_years),
            "srcva_weekend_call_allowed_block_names": self.srcva_weekend_call_allowed_block_names,
            "srcva_weekend_call_f1_start_week": self.srcva_weekend_call_f1_start_week,
            "srcva_weekend_call_f1_min": self.srcva_weekend_call_f1_min,
            "srcva_weekend_call_f1_max": self.srcva_weekend_call_f1_max,
            "srcva_weekend_call_s2_min": self.srcva_weekend_call_s2_min,
            "srcva_weekend_call_s2_max": self.srcva_weekend_call_s2_max,
            "srcva_total_call_f1_min": self.srcva_total_call_f1_min,
            "srcva_total_call_f1_max": self.srcva_total_call_f1_max,
            "srcva_weekday_call_enabled": self.srcva_weekday_call_enabled,
            "srcva_weekday_call_eligible_years": _serialize_years(self.srcva_weekday_call_eligible_years),
            "srcva_weekday_call_allowed_block_names": self.srcva_weekday_call_allowed_block_names,
            "srcva_weekday_call_f1_start_week": self.srcva_weekday_call_f1_start_week,
            "srcva_weekday_call_f1_min": self.srcva_weekday_call_f1_min,
            "srcva_weekday_call_f1_max": self.srcva_weekday_call_f1_max,
            "srcva_weekday_call_s2_min": self.srcva_weekday_call_s2_min,
            "srcva_weekday_call_s2_max": self.srcva_weekday_call_s2_max,
            "srcva_weekday_call_max_consecutive_nights": self.srcva_weekday_call_max_consecutive_nights,
            "srcva_holiday_anchor_week": self.srcva_holiday_anchor_week,
            "srcva_christmas_target_week": self.srcva_christmas_target_week,
            "srcva_new_year_target_week": self.srcva_new_year_target_week,
            "srcva_holiday_preferred_anchor_blocks": self.srcva_holiday_preferred_anchor_blocks,
            "srcva_holiday_preference_weight": self.srcva_holiday_preference_weight,
            "srcva_holiday_repeat_weight": self.srcva_holiday_repeat_weight,
            "srcva_weekday_max_one_per_week_weight": self.srcva_weekday_max_one_per_week_weight,
            "srcva_weekday_same_week_as_weekend_weight": self.srcva_weekday_same_week_as_weekend_weight,
            "srcva_weekday_same_week_as_24hr_weight": self.srcva_weekday_same_week_as_24hr_weight,
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
            "rolling_window_rules": [
                rule.to_dict() for rule in self.rolling_window_rules
            ],
            "consecutive_state_limit_rules": [
                rule.to_dict() for rule in self.consecutive_state_limit_rules
            ],
            "first_assignment_run_limit_rules": [
                rule.to_dict() for rule in self.first_assignment_run_limit_rules
            ],
            "contiguous_block_rules": [
                rule.to_dict() for rule in self.contiguous_block_rules
            ],
            "first_assignment_pairing_rules": [
                rule.to_dict() for rule in self.first_assignment_pairing_rules
            ],
            "individual_fellow_requirement_rules": [
                rule.to_dict() for rule in self.individual_fellow_requirement_rules
            ],
            "linked_fellow_state_rules": [
                rule.to_dict() for rule in self.linked_fellow_state_rules
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
            "soft_single_week_block_rules": [
                rule.to_dict() for rule in self.soft_single_week_block_rules
            ],
            "soft_state_assignment_rules": [
                rule.to_dict() for rule in self.soft_state_assignment_rules
            ],
            "soft_cohort_balance_rules": [
                rule.to_dict() for rule in self.soft_cohort_balance_rules
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleConfig:
        """Deserialize from a JSON dictionary."""

        payload = _normalize_legacy_year_aliases(data.copy())
        # Older saved configs may still carry the retired global PTO restriction key.
        payload.pop("pto_blackout_weeks", None)
        payload["start_date"] = date.fromisoformat(payload["start_date"])
        payload["pto_preference_weight_overrides"] = _normalize_pto_preference_weight_overrides(
            payload.get("pto_preference_weight_overrides")
        )
        payload["call_eligible_years"] = _deserialize_years(
            payload.get("call_eligible_years")
        )
        payload["srcva_weekend_call_eligible_years"] = _deserialize_years(
            payload.get("srcva_weekend_call_eligible_years")
        )
        payload["srcva_weekday_call_eligible_years"] = _deserialize_years(
            payload.get("srcva_weekday_call_eligible_years")
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
        payload["rolling_window_rules"] = [
            RollingWindowRule.from_dict(rule)
            for rule in payload.get("rolling_window_rules", [])
        ]
        payload["consecutive_state_limit_rules"] = [
            ConsecutiveStateLimitRule.from_dict(rule)
            for rule in payload.get("consecutive_state_limit_rules", [])
        ]
        payload["first_assignment_run_limit_rules"] = [
            FirstAssignmentRunLimitRule.from_dict(rule)
            for rule in payload.get("first_assignment_run_limit_rules", [])
        ]
        payload["contiguous_block_rules"] = [
            ContiguousBlockRule.from_dict(rule)
            for rule in payload.get("contiguous_block_rules", [])
        ]
        payload["first_assignment_pairing_rules"] = [
            FirstAssignmentPairingRule.from_dict(rule)
            for rule in payload.get("first_assignment_pairing_rules", [])
        ]
        payload["individual_fellow_requirement_rules"] = [
            IndividualFellowRequirementRule.from_dict(rule)
            for rule in payload.get("individual_fellow_requirement_rules", [])
        ]
        payload["linked_fellow_state_rules"] = [
            LinkedFellowStateRule.from_dict(rule)
            for rule in payload.get("linked_fellow_state_rules", [])
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
        payload["soft_single_week_block_rules"] = [
            SoftSingleWeekBlockRule.from_dict(rule)
            for rule in payload.get("soft_single_week_block_rules", [])
        ]
        payload["soft_state_assignment_rules"] = [
            SoftStateAssignmentRule.from_dict(rule)
            for rule in payload.get("soft_state_assignment_rules", [])
        ]
        payload["soft_cohort_balance_rules"] = [
            SoftCohortBalanceRule.from_dict(rule)
            for rule in payload.get("soft_cohort_balance_rules", [])
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
    srcva_weekend_call_assignments: list[list[bool]] = field(default_factory=list)
    srcva_weekday_call_assignments: list[list[list[bool]]] = field(default_factory=list)
    solver_status: SolverStatus = SolverStatus.ERROR
    objective_value: float = 0.0
    solve_time_seconds: float = 0.0
    objective_breakdown: list[dict[str, int | str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dictionary."""
        return {
            "assignments": self.assignments,
            "call_assignments": self.call_assignments,
            "srcva_weekend_call_assignments": self.srcva_weekend_call_assignments,
            "srcva_weekday_call_assignments": self.srcva_weekday_call_assignments,
            "solver_status": self.solver_status.value,
            "objective_value": self.objective_value,
            "solve_time_seconds": self.solve_time_seconds,
            "objective_breakdown": self.objective_breakdown,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduleResult:
        """Deserialize from a JSON dictionary."""
        payload = _normalize_legacy_year_aliases(data.copy())
        payload["solver_status"] = SolverStatus(payload["solver_status"])
        payload.setdefault("srcva_weekend_call_assignments", [])
        payload.setdefault("srcva_weekday_call_assignments", [])
        return cls(**payload)
