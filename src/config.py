"""Default configuration and rule definitions for the scheduler."""

from __future__ import annotations

from datetime import date

from src.models import (
    BlockConfig,
    BlockType,
    CohortLimitRule,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    FirstAssignmentPairingRule,
    ForbiddenTransitionRule,
    IndividualFellowRequirementRule,
    PrerequisiteRule,
    RollingWindowRule,
    ScheduleConfig,
    SoftRuleDirection,
    SoftSequenceRule,
    TrainingYear,
    WeekCountRule,
)


BLOCK_COLORS: dict[str, str] = {
    "White Consults": "#355C7D",
    "SRC Consults": "#2E86AB",
    "VA Consults": "#0E7490",
    "Goodyer Consults": "#7C3AED",
    "CCU": "#C0392B",
    "Night Float": "#34495E",
    "EP": "#F39C12",
    "CHF": "#A04000",
    "Yale Nuclear": "#F1C40F",
    "VA Nuclear": "#D4AC0D",
    "Yale Echo": "#1F8A70",
    "VA Echo": "#2E8B57",
    "SRC Echo": "#138D75",
    "Yale Cath": "#E67E22",
    "VA Cath": "#D35400",
    "SRC Cath": "#AF601A",
    "Research": "#7F8C8D",
    "CT-MRI": "#6C3483",
    "Elective": "#5D6D7E",
    "Peripheral vascular": "#117A65",
    "PTO": "#BDC3C7",
}


ACADEMIC_YEAR_START = date(2026, 7, 13)
NUM_WEEKS = 52
FIRST_YEAR_CCU_START_WEEK = 5
FIRST_YEAR_NF_START_WEEK = 6
FIRST_YEAR_RESEARCH_PTO_START_WEEK = 4


def get_default_blocks() -> list[BlockConfig]:
    """Return the fellowship rotations with default metadata."""

    consult_call = True
    return [
        BlockConfig(
            name="White Consults",
            fellows_needed=0,
            hours_per_week=65.0,
            requires_call_coverage=consult_call,
        ),
        BlockConfig(
            name="SRC Consults",
            fellows_needed=0,
            hours_per_week=65.0,
            requires_call_coverage=consult_call,
        ),
        BlockConfig(
            name="VA Consults",
            fellows_needed=0,
            hours_per_week=60.0,
            requires_call_coverage=consult_call,
        ),
        BlockConfig(
            name="Goodyer Consults",
            fellows_needed=0,
            hours_per_week=60.0,
            requires_call_coverage=consult_call,
        ),
        BlockConfig(
            name="CCU",
            fellows_needed=0,
            hours_per_week=70.0,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Night Float",
            block_type=BlockType.NIGHT,
            fellows_needed=0,
            hours_per_week=70.0,
            requires_call_coverage=False,
        ),
        BlockConfig(name="EP", fellows_needed=0, hours_per_week=55.0),
        BlockConfig(name="CHF", fellows_needed=0, hours_per_week=55.0),
        BlockConfig(name="Yale Nuclear", fellows_needed=0, hours_per_week=50.0),
        BlockConfig(name="VA Nuclear", fellows_needed=0, hours_per_week=50.0),
        BlockConfig(name="Yale Echo", fellows_needed=0, hours_per_week=50.0),
        BlockConfig(name="VA Echo", fellows_needed=0, hours_per_week=50.0),
        BlockConfig(name="SRC Echo", fellows_needed=0, hours_per_week=50.0),
        BlockConfig(name="Yale Cath", fellows_needed=0, hours_per_week=60.0),
        BlockConfig(name="VA Cath", fellows_needed=0, hours_per_week=60.0),
        BlockConfig(name="SRC Cath", fellows_needed=0, hours_per_week=60.0),
        BlockConfig(name="Research", fellows_needed=0, hours_per_week=40.0),
        BlockConfig(name="CT-MRI", fellows_needed=0, hours_per_week=40.0),
        BlockConfig(name="Elective", fellows_needed=0, hours_per_week=40.0),
        BlockConfig(name="Peripheral vascular", fellows_needed=0, hours_per_week=40.0),
    ]


def get_default_fellows(
    f1_count: int = 9,
    s2_count: int = 9,
    t3_count: int = 7,
) -> list[FellowConfig]:
    """Return cohort-aware default fellow configs."""

    fellows: list[FellowConfig] = []
    for idx in range(f1_count):
        fellows.append(
            FellowConfig(
                name=f"F1 Fellow {idx + 1}",
                training_year=TrainingYear.F1,
            )
        )
    for idx in range(s2_count):
        fellows.append(
            FellowConfig(
                name=f"S2 Fellow {idx + 1}",
                training_year=TrainingYear.S2,
            )
        )
    for idx in range(t3_count):
        fellows.append(
            FellowConfig(
                name=f"T3 Fellow {idx + 1}",
                training_year=TrainingYear.T3,
            )
        )
    return fellows


def get_default_coverage_rules() -> list[CoverageRule]:
    """Return default staffing rules for the built-in rule set."""

    any_year = [TrainingYear.F1, TrainingYear.S2, TrainingYear.T3]
    return [
        CoverageRule(
            name="White Consults staffed by F1",
            block_name="White Consults",
            eligible_years=[TrainingYear.F1],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="SRC Consults staffed",
            block_name="SRC Consults",
            eligible_years=any_year,
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="VA Consults staffed",
            block_name="VA Consults",
            eligible_years=any_year,
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="Goodyer staffed by S2",
            block_name="Goodyer Consults",
            eligible_years=[TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="CCU early by S2",
            block_name="CCU",
            eligible_years=[TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
            start_week=0,
            end_week=FIRST_YEAR_CCU_START_WEEK - 1,
        ),
        CoverageRule(
            name="CCU later by F1",
            block_name="CCU",
            eligible_years=[TrainingYear.F1],
            min_fellows=1,
            max_fellows=1,
            start_week=FIRST_YEAR_CCU_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        CoverageRule(
            name="Night Float early by S2",
            block_name="Night Float",
            eligible_years=[TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
            start_week=0,
            end_week=FIRST_YEAR_NF_START_WEEK - 1,
        ),
        CoverageRule(
            name="Night Float later by F1",
            block_name="Night Float",
            eligible_years=[TrainingYear.F1],
            min_fellows=1,
            max_fellows=1,
            start_week=FIRST_YEAR_NF_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        CoverageRule(
            name="EP staffed by F1 or S2",
            block_name="EP",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=2,
        ),
        CoverageRule(
            name="CHF staffed by F1 or S2",
            block_name="CHF",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="Yale Nuclear staffed by F1 or S2",
            block_name="Yale Nuclear",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=2,
        ),
        CoverageRule(
            name="VA Nuclear staffed by F1 or S2",
            block_name="VA Nuclear",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="Yale Echo F1 range",
            block_name="Yale Echo",
            eligible_years=[TrainingYear.F1],
            min_fellows=0,
            max_fellows=2,
        ),
        CoverageRule(
            name="Yale Echo senior range",
            block_name="Yale Echo",
            eligible_years=[TrainingYear.S2, TrainingYear.T3],
            min_fellows=2,
            max_fellows=3,
        ),
        CoverageRule(
            name="VA Echo staffed by F1 or S2",
            block_name="VA Echo",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="SRC Echo staffed",
            block_name="SRC Echo",
            eligible_years=any_year,
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="Yale Cath range",
            block_name="Yale Cath",
            eligible_years=any_year,
            min_fellows=1,
            max_fellows=2,
        ),
        CoverageRule(
            name="VA Cath staffed by F1 or S2",
            block_name="VA Cath",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="SRC Cath optional F1 or S2",
            block_name="SRC Cath",
            eligible_years=[TrainingYear.F1, TrainingYear.S2],
            min_fellows=0,
            max_fellows=1,
        ),
        CoverageRule(
            name="CT-MRI staffed by S2 or T3",
            block_name="CT-MRI",
            eligible_years=[TrainingYear.S2, TrainingYear.T3],
            min_fellows=1,
            max_fellows=1,
        ),
        CoverageRule(
            name="Peripheral vascular optional T3",
            block_name="Peripheral vascular",
            eligible_years=[TrainingYear.T3],
            min_fellows=0,
            max_fellows=1,
        ),
    ]


def get_default_eligibility_rules() -> list[EligibilityRule]:
    """Return cohort eligibility rules for each rotation."""

    any_year = [TrainingYear.F1, TrainingYear.S2, TrainingYear.T3]
    return [
        EligibilityRule(
            name="White Consults only F1",
            block_names=["White Consults"],
            allowed_years=[TrainingYear.F1],
        ),
        EligibilityRule(
            name="SRC Consults any year",
            block_names=["SRC Consults"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="VA Consults any year",
            block_names=["VA Consults"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="Goodyer only S2",
            block_names=["Goodyer Consults"],
            allowed_years=[TrainingYear.S2],
        ),
        EligibilityRule(
            name="CCU early S2 only",
            block_names=["CCU"],
            allowed_years=[TrainingYear.S2],
            start_week=0,
            end_week=FIRST_YEAR_CCU_START_WEEK - 1,
        ),
        EligibilityRule(
            name="CCU later F1 or S2",
            block_names=["CCU"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
            start_week=FIRST_YEAR_CCU_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        EligibilityRule(
            name="Night Float early S2 only",
            block_names=["Night Float"],
            allowed_years=[TrainingYear.S2],
            start_week=0,
            end_week=FIRST_YEAR_NF_START_WEEK - 1,
        ),
        EligibilityRule(
            name="Night Float later F1 or S2",
            block_names=["Night Float"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
            start_week=FIRST_YEAR_NF_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        EligibilityRule(
            name="EP limited to F1 and S2",
            block_names=["EP"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="CHF limited to F1 and S2",
            block_names=["CHF"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="Yale Nuclear limited to F1 and S2",
            block_names=["Yale Nuclear"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="VA Nuclear limited to F1 and S2",
            block_names=["VA Nuclear"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="Yale Echo any year",
            block_names=["Yale Echo"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="VA Echo limited to F1 and S2",
            block_names=["VA Echo"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="SRC Echo any year",
            block_names=["SRC Echo"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="Yale Cath any year",
            block_names=["Yale Cath"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="VA Cath limited to F1 and S2",
            block_names=["VA Cath"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="SRC Cath limited to F1 and S2",
            block_names=["SRC Cath"],
            allowed_years=[TrainingYear.F1, TrainingYear.S2],
        ),
        EligibilityRule(
            name="Research any year",
            block_names=["Research"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="CT-MRI limited to S2 and T3",
            block_names=["CT-MRI"],
            allowed_years=[TrainingYear.S2, TrainingYear.T3],
        ),
        EligibilityRule(
            name="Elective only T3",
            block_names=["Elective"],
            allowed_years=[TrainingYear.T3],
        ),
        EligibilityRule(
            name="Peripheral vascular only T3",
            block_names=["Peripheral vascular"],
            allowed_years=[TrainingYear.T3],
        ),
    ]


def get_default_week_count_rules() -> list[WeekCountRule]:
    """Return cohort-specific per-fellow rotation requirements."""

    f1 = [TrainingYear.F1]
    return [
        WeekCountRule(
            name="F1 no PTO before 8/10/26",
            applicable_years=f1,
            block_names=["PTO"],
            min_weeks=0,
            max_weeks=0,
            start_week=0,
            end_week=FIRST_YEAR_RESEARCH_PTO_START_WEEK - 1,
        ),
        WeekCountRule(
            name="F1 White Consults",
            applicable_years=f1,
            block_names=["White Consults"],
            min_weeks=5,
            max_weeks=6,
        ),
        WeekCountRule(
            name="F1 SRC Consults",
            applicable_years=f1,
            block_names=["SRC Consults"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 VA Consults",
            applicable_years=f1,
            block_names=["VA Consults"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 Consult total",
            applicable_years=f1,
            block_names=["White Consults", "SRC Consults", "VA Consults"],
            min_weeks=10,
            max_weeks=12,
        ),
        WeekCountRule(
            name="F1 Goodyer prohibited",
            applicable_years=f1,
            block_names=["Goodyer Consults"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="F1 CCU after orientation",
            applicable_years=f1,
            block_names=["CCU"],
            min_weeks=5,
            max_weeks=6,
            start_week=FIRST_YEAR_CCU_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        WeekCountRule(
            name="F1 Night Float after onboarding",
            applicable_years=f1,
            block_names=["Night Float"],
            min_weeks=5,
            max_weeks=6,
            start_week=FIRST_YEAR_NF_START_WEEK,
            end_week=NUM_WEEKS - 1,
        ),
        WeekCountRule(
            name="F1 EP",
            applicable_years=f1,
            block_names=["EP"],
            min_weeks=4,
            max_weeks=5,
        ),
        WeekCountRule(
            name="F1 CHF",
            applicable_years=f1,
            block_names=["CHF"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="F1 Yale Nuclear",
            applicable_years=f1,
            block_names=["Yale Nuclear"],
            min_weeks=2,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 VA Nuclear",
            applicable_years=f1,
            block_names=["VA Nuclear"],
            min_weeks=1,
            max_weeks=3,
        ),
        WeekCountRule(
            name="F1 Nuclear total",
            applicable_years=f1,
            block_names=["Yale Nuclear", "VA Nuclear"],
            min_weeks=4,
            max_weeks=7,
        ),
        WeekCountRule(
            name="F1 Yale Echo",
            applicable_years=f1,
            block_names=["Yale Echo"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 VA Echo",
            applicable_years=f1,
            block_names=["VA Echo"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 SRC Echo",
            applicable_years=f1,
            block_names=["SRC Echo"],
            min_weeks=1,
            max_weeks=1,
        ),
        WeekCountRule(
            name="F1 Echo total",
            applicable_years=f1,
            block_names=["Yale Echo", "VA Echo", "SRC Echo"],
            min_weeks=7,
            max_weeks=9,
        ),
        WeekCountRule(
            name="F1 Yale Cath",
            applicable_years=f1,
            block_names=["Yale Cath"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="F1 VA Cath",
            applicable_years=f1,
            block_names=["VA Cath"],
            min_weeks=1,
            max_weeks=2,
        ),
        WeekCountRule(
            name="F1 SRC Cath",
            applicable_years=f1,
            block_names=["SRC Cath"],
            min_weeks=1,
            max_weeks=2,
        ),
        WeekCountRule(
            name="F1 Cath total",
            applicable_years=f1,
            block_names=["Yale Cath", "VA Cath", "SRC Cath"],
            min_weeks=6,
            max_weeks=7,
        ),
        WeekCountRule(
            name="F1 no Research before 8/10/26",
            applicable_years=f1,
            block_names=["Research"],
            min_weeks=0,
            max_weeks=0,
            start_week=0,
            end_week=FIRST_YEAR_RESEARCH_PTO_START_WEEK - 1,
        ),
        WeekCountRule(
            name="F1 Research",
            applicable_years=f1,
            block_names=["Research"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="F1 CT-MRI prohibited",
            applicable_years=f1,
            block_names=["CT-MRI"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="F1 Elective prohibited",
            applicable_years=f1,
            block_names=["Elective"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="F1 Peripheral vascular prohibited",
            applicable_years=f1,
            block_names=["Peripheral vascular"],
            min_weeks=0,
            max_weeks=0,
        ),
    ]


def get_default_cohort_limit_rules() -> list[CohortLimitRule]:
    """Return same-cohort vacation concurrency rules."""

    return [
        CohortLimitRule(
            name="F1 PTO cap",
            applicable_years=[TrainingYear.F1],
            state_name="PTO",
            max_fellows=4,
        ),
        CohortLimitRule(
            name="S2 PTO cap",
            applicable_years=[TrainingYear.S2],
            state_name="PTO",
            max_fellows=4,
        ),
        CohortLimitRule(
            name="T3 PTO cap",
            applicable_years=[TrainingYear.T3],
            state_name="PTO",
            max_fellows=4,
        ),
    ]


def get_default_prerequisite_rules() -> list[PrerequisiteRule]:
    """Return default hard prerequisite rules."""

    return [
        PrerequisiteRule(
            name="F1 before Night Float needs core exposure",
            applicable_years=[TrainingYear.F1],
            target_block="Night Float",
            prerequisite_blocks=[
                "Yale Echo",
                "Yale Cath",
                "White Consults",
                "CCU",
                "EP",
                "CHF",
            ],
            prerequisite_min_weeks=1,
        )
    ]


def get_default_first_assignment_pairing_rules() -> list[FirstAssignmentPairingRule]:
    """Return first-assignment supervision rules."""

    return [
        FirstAssignmentPairingRule(
            name="F1 first Yale Nuclear week needs experienced pairing",
            trainee_years=[TrainingYear.F1],
            block_name="Yale Nuclear",
            mentor_years=[TrainingYear.S2],
            experienced_peer_years=[TrainingYear.F1],
            required_prior_weeks=1,
        )
    ]


def get_default_individual_fellow_requirement_rules() -> list[IndividualFellowRequirementRule]:
    """Return default named-fellow hard rules."""

    return []


def get_default_rolling_window_rules() -> list[RollingWindowRule]:
    """Return default rolling-window hard limits."""

    return [
        RollingWindowRule(
            name="Max 3 PTO or Research weeks in any 4-week period",
            applicable_years=[TrainingYear.F1, TrainingYear.S2, TrainingYear.T3],
            state_names=["PTO", "Research"],
            window_size_weeks=4,
            max_weeks_in_window=3,
        )
    ]


def get_default_forbidden_transition_rules() -> list[ForbiddenTransitionRule]:
    """Return hard transition rules."""

    return []


def get_default_soft_sequence_rules() -> list[SoftSequenceRule]:
    """Return default weighted soft rules."""

    return [
        SoftSequenceRule(
            name="Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, CCU, or PTO",
            applicable_years=[TrainingYear.F1],
            left_states=[
                "White Consults",
                "SRC Consults",
                "VA Consults",
                "CCU",
                "PTO",
            ],
            right_states=["Night Float"],
            weight=-40,
        ),
        SoftSequenceRule(
            name="Bonus: F1 CHF immediately before Night Float",
            applicable_years=[TrainingYear.F1],
            left_states=["CHF"],
            right_states=["Night Float"],
            weight=30,
        ),
        SoftSequenceRule(
            name="Bonus: F1 Research adjacent to PTO",
            applicable_years=[TrainingYear.F1],
            left_states=["Research"],
            right_states=["PTO"],
            weight=12,
            direction=SoftRuleDirection.EITHER,
        ),
        SoftSequenceRule(
            name="Bonus: F1 two-week PTO block",
            applicable_years=[TrainingYear.F1],
            left_states=["PTO"],
            right_states=["PTO"],
            weight=8,
        ),
    ]


def get_default_pto_preference_weight_overrides() -> dict[str, list[int]]:
    """Return the default cohort PTO preference weights."""

    strongest_top_two = [120, 80, 12, 4, 1, 0]
    return {
        TrainingYear.F1.value: strongest_top_two.copy(),
        TrainingYear.S2.value: strongest_top_two.copy(),
        TrainingYear.T3.value: strongest_top_two.copy(),
    }


def get_default_config() -> ScheduleConfig:
    """Return a complete default cohort-aware ScheduleConfig."""

    fellows = get_default_fellows()
    return ScheduleConfig(
        num_fellows=len(fellows),
        num_weeks=NUM_WEEKS,
        start_date=ACADEMIC_YEAR_START,
        pto_weeks_granted=4,
        pto_weeks_to_rank=6,
        max_concurrent_pto=12,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=300.0,
        pto_preference_weight_overrides=get_default_pto_preference_weight_overrides(),
        blocks=get_default_blocks(),
        fellows=fellows,
        coverage_rules=get_default_coverage_rules(),
        eligibility_rules=get_default_eligibility_rules(),
        week_count_rules=get_default_week_count_rules(),
        cohort_limit_rules=get_default_cohort_limit_rules(),
        rolling_window_rules=get_default_rolling_window_rules(),
        first_assignment_pairing_rules=get_default_first_assignment_pairing_rules(),
        individual_fellow_requirement_rules=get_default_individual_fellow_requirement_rules(),
        prerequisite_rules=get_default_prerequisite_rules(),
        forbidden_transition_rules=get_default_forbidden_transition_rules(),
        soft_sequence_rules=get_default_soft_sequence_rules(),
    )
