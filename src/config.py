"""Default configuration and rule definitions for the scheduler."""

from __future__ import annotations

from datetime import date

from src.models import (
    BlockConfig,
    BlockType,
    CohortLimitRule,
    ContiguousBlockRule,
    ConsecutiveStateLimitRule,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    FirstAssignmentRunLimitRule,
    FirstAssignmentPairingRule,
    ForbiddenTransitionRule,
    IndividualFellowRequirementRule,
    PrerequisiteRule,
    RollingWindowRule,
    ScheduleConfig,
    SoftCohortBalanceRule,
    SoftRuleDirection,
    SoftStateAssignmentRule,
    SoftSequenceRule,
    SoftSingleWeekBlockRule,
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
    "Congenital": "#8E44AD",
    "PTO": "#BDC3C7",
}


ACADEMIC_YEAR_START = date(2026, 7, 13)
NUM_WEEKS = 52
FIRST_YEAR_CCU_START_WEEK = 3
FIRST_YEAR_NF_START_WEEK = 6
FIRST_YEAR_RESEARCH_PTO_START_WEEK = 4


def _week_index_for_date(target_date: date) -> int | None:
    """Return the zero-based schedule week containing one calendar date."""

    delta_days = (target_date - ACADEMIC_YEAR_START).days
    if delta_days < 0:
        return None
    week_index = delta_days // 7
    if week_index >= NUM_WEEKS:
        return None
    return week_index


DEFAULT_F1_FELLOW_NAMES = [
    "Eisman",
    "Flores",
    "Kayani",
    "Kostantinis",
    "Mekhael",
    "Nazari",
    "Osorio",
    "Safiullah",
    "Zhang",
]

DEFAULT_T3_FELLOW_NAMES = [
    "Alashi",
    "Mahajan",
    "Park",
    "Luna",
    "Schwann",
    "Hansen",
    "Amutuhaire",
    "El_Charif",
    "Nurula",
]


def get_default_fellow_name(training_year: TrainingYear, index: int) -> str:
    """Return the default roster name for a cohort/index slot."""

    if training_year == TrainingYear.F1 and index < len(DEFAULT_F1_FELLOW_NAMES):
        return DEFAULT_F1_FELLOW_NAMES[index]
    if training_year == TrainingYear.T3 and index < len(DEFAULT_T3_FELLOW_NAMES):
        return DEFAULT_T3_FELLOW_NAMES[index]
    return f"{training_year.value} Fellow {index + 1}"


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
        BlockConfig(name="Congenital", fellows_needed=0, hours_per_week=40.0),
    ]


def get_default_fellows(
    f1_count: int = 9,
    s2_count: int = 9,
    t3_count: int = 9,
) -> list[FellowConfig]:
    """Return cohort-aware default fellow configs."""
    fellows: list[FellowConfig] = []
    for idx in range(f1_count):
        fellows.append(
            FellowConfig(
                name=get_default_fellow_name(TrainingYear.F1, idx),
                training_year=TrainingYear.F1,
            )
        )
    for idx in range(s2_count):
        fellows.append(
            FellowConfig(
                name=get_default_fellow_name(TrainingYear.S2, idx),
                training_year=TrainingYear.S2,
            )
        )
    for idx in range(t3_count):
        fellows.append(
            FellowConfig(
                name=get_default_fellow_name(TrainingYear.T3, idx),
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
            min_fellows=0,
            max_fellows=1,
        ),
        CoverageRule(
            name="Yale Nuclear staffed by F1, S2, or T3",
            block_name="Yale Nuclear",
            eligible_years=[TrainingYear.F1, TrainingYear.S2, TrainingYear.T3],
            min_fellows=1,
            max_fellows=2,
        ),
        CoverageRule(
            name="VA Nuclear staffed by F1, S2, or T3",
            block_name="VA Nuclear",
            eligible_years=[TrainingYear.F1, TrainingYear.S2, TrainingYear.T3],
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
            min_fellows=0,
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
            min_fellows=0,
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
            name="CCU later F1 only",
            block_names=["CCU"],
            allowed_years=[TrainingYear.F1],
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
            name="Night Float later F1 only",
            block_names=["Night Float"],
            allowed_years=[TrainingYear.F1],
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
            name="Yale Nuclear any year",
            block_names=["Yale Nuclear"],
            allowed_years=any_year,
        ),
        EligibilityRule(
            name="VA Nuclear any year",
            block_names=["VA Nuclear"],
            allowed_years=any_year,
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
        EligibilityRule(
            name="Congenital only T3",
            block_names=["Congenital"],
            allowed_years=[TrainingYear.T3],
        ),
    ]


def get_default_week_count_rules() -> list[WeekCountRule]:
    """Return cohort-specific per-fellow rotation requirements."""

    f1 = [TrainingYear.F1]
    s2 = [TrainingYear.S2]
    t3 = [TrainingYear.T3]
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
            min_weeks=2,
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
        WeekCountRule(
            name="S2 White Consults prohibited",
            applicable_years=s2,
            block_names=["White Consults"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="S2 SRC Consults",
            applicable_years=s2,
            block_names=["SRC Consults"],
            min_weeks=1,
            max_weeks=3,
        ),
        WeekCountRule(
            name="S2 VA Consults",
            applicable_years=s2,
            block_names=["VA Consults"],
            min_weeks=1,
            max_weeks=3,
        ),
        WeekCountRule(
            name="S2 Consult total",
            applicable_years=s2,
            block_names=["SRC Consults", "VA Consults"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="S2 Goodyer Consults",
            applicable_years=s2,
            block_names=["Goodyer Consults"],
            min_weeks=5,
            max_weeks=6,
        ),
        WeekCountRule(
            name="S2 CCU",
            applicable_years=s2,
            block_names=["CCU"],
            min_weeks=0,
            max_weeks=2,
            start_week=0,
            end_week=FIRST_YEAR_CCU_START_WEEK - 1,
        ),
        WeekCountRule(
            name="S2 Night Float",
            applicable_years=s2,
            block_names=["Night Float"],
            min_weeks=0,
            max_weeks=1,
            start_week=0,
            end_week=FIRST_YEAR_NF_START_WEEK - 1,
        ),
        WeekCountRule(
            name="S2 EP",
            applicable_years=s2,
            block_names=["EP"],
            min_weeks=3,
            max_weeks=5,
        ),
        WeekCountRule(
            name="S2 CHF",
            applicable_years=s2,
            block_names=["CHF"],
            min_weeks=1,
            max_weeks=4,
        ),
        WeekCountRule(
            name="S2 Yale Nuclear",
            applicable_years=s2,
            block_names=["Yale Nuclear"],
            min_weeks=4,
            max_weeks=6,
        ),
        WeekCountRule(
            name="S2 VA Nuclear",
            applicable_years=s2,
            block_names=["VA Nuclear"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="S2 Nuclear total",
            applicable_years=s2,
            block_names=["Yale Nuclear", "VA Nuclear"],
            min_weeks=7,
            max_weeks=10,
        ),
        WeekCountRule(
            name="S2 Yale Echo",
            applicable_years=s2,
            block_names=["Yale Echo"],
            min_weeks=4,
            max_weeks=12,
        ),
        WeekCountRule(
            name="S2 VA Echo",
            applicable_years=s2,
            block_names=["VA Echo"],
            min_weeks=0,
            max_weeks=2,
        ),
        WeekCountRule(
            name="S2 SRC Echo",
            applicable_years=s2,
            block_names=["SRC Echo"],
            min_weeks=2,
            max_weeks=12,
        ),
        WeekCountRule(
            name="S2 Echo total",
            applicable_years=s2,
            block_names=["Yale Echo", "VA Echo", "SRC Echo"],
            min_weeks=10,
            max_weeks=12,
        ),
        WeekCountRule(
            name="S2 Yale Cath",
            applicable_years=s2,
            block_names=["Yale Cath"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="S2 VA Cath",
            applicable_years=s2,
            block_names=["VA Cath"],
            min_weeks=2,
            max_weeks=5,
        ),
        WeekCountRule(
            name="S2 SRC Cath",
            applicable_years=s2,
            block_names=["SRC Cath"],
            min_weeks=0,
            max_weeks=4,
        ),
        WeekCountRule(
            name="S2 Cath total",
            applicable_years=s2,
            block_names=["Yale Cath", "VA Cath", "SRC Cath"],
            min_weeks=6,
            max_weeks=8,
        ),
        WeekCountRule(
            name="S2 Research",
            applicable_years=s2,
            block_names=["Research"],
            min_weeks=6,
            max_weeks=6,
        ),
        WeekCountRule(
            name="S2 CT-MRI",
            applicable_years=s2,
            block_names=["CT-MRI"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="S2 Elective prohibited",
            applicable_years=s2,
            block_names=["Elective"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="S2 Peripheral vascular prohibited",
            applicable_years=s2,
            block_names=["Peripheral vascular"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 White Consults prohibited",
            applicable_years=t3,
            block_names=["White Consults"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 SRC Consults",
            applicable_years=t3,
            block_names=["SRC Consults"],
            min_weeks=1,
            max_weeks=3,
        ),
        WeekCountRule(
            name="T3 VA Consults",
            applicable_years=t3,
            block_names=["VA Consults"],
            min_weeks=1,
            max_weeks=3,
        ),
        WeekCountRule(
            name="T3 Consult total",
            applicable_years=t3,
            block_names=["SRC Consults", "VA Consults"],
            min_weeks=3,
            max_weeks=4,
        ),
        WeekCountRule(
            name="T3 Goodyer Consults prohibited",
            applicable_years=t3,
            block_names=["Goodyer Consults"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 CCU prohibited",
            applicable_years=t3,
            block_names=["CCU"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 Night Float prohibited",
            applicable_years=t3,
            block_names=["Night Float"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 EP prohibited",
            applicable_years=t3,
            block_names=["EP"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 CHF prohibited",
            applicable_years=t3,
            block_names=["CHF"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 Yale Nuclear",
            applicable_years=t3,
            block_names=["Yale Nuclear"],
            min_weeks=0,
            max_weeks=4,
        ),
        WeekCountRule(
            name="T3 VA Nuclear",
            applicable_years=t3,
            block_names=["VA Nuclear"],
            min_weeks=0,
            max_weeks=2,
        ),
        WeekCountRule(
            name="T3 Nuclear total",
            applicable_years=t3,
            block_names=["Yale Nuclear", "VA Nuclear"],
            min_weeks=4,
            max_weeks=5,
        ),
        WeekCountRule(
            name="T3 Yale Echo",
            applicable_years=t3,
            block_names=["Yale Echo"],
            min_weeks=4,
            max_weeks=10,
        ),
        WeekCountRule(
            name="T3 VA Echo prohibited",
            applicable_years=t3,
            block_names=["VA Echo"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 SRC Echo",
            applicable_years=t3,
            block_names=["SRC Echo"],
            min_weeks=0,
            max_weeks=1,
        ),
        WeekCountRule(
            name="T3 Echo total",
            applicable_years=t3,
            block_names=["Yale Echo", "SRC Echo"],
            min_weeks=4,
            max_weeks=10,
        ),
        WeekCountRule(
            name="T3 Yale Cath prohibited",
            applicable_years=t3,
            block_names=["Yale Cath"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 VA Cath prohibited",
            applicable_years=t3,
            block_names=["VA Cath"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 SRC Cath prohibited",
            applicable_years=t3,
            block_names=["SRC Cath"],
            min_weeks=0,
            max_weeks=0,
        ),
        WeekCountRule(
            name="T3 Research",
            applicable_years=t3,
            block_names=["Research"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="T3 CT-MRI",
            applicable_years=t3,
            block_names=["CT-MRI"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="T3 Elective",
            applicable_years=t3,
            block_names=["Elective"],
            min_weeks=24,
            max_weeks=30,
        ),
        WeekCountRule(
            name="T3 Peripheral vascular",
            applicable_years=t3,
            block_names=["Peripheral vascular"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="T3 Congenital",
            applicable_years=t3,
            block_names=["Congenital"],
            min_weeks=2,
            max_weeks=2,
        ),
        WeekCountRule(
            name="T3 late spring elective/research/PTO only",
            applicable_years=t3,
            block_names=["PTO", "Research", "Elective"],
            min_weeks=6,
            max_weeks=6,
            start_week=46,
            end_week=51,
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
                "White Consults",
                "CCU",
                "EP",
                "CHF",
            ],
            prerequisite_block_groups=[["Yale Cath", "SRC Cath"]],
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


def get_default_consecutive_state_limit_rules() -> list[ConsecutiveStateLimitRule]:
    """Return cohort-specific consecutive-week hard limits."""

    return [
        ConsecutiveStateLimitRule(
            name="F1 Night Float max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["Night Float"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 Goodyer Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["Goodyer Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 EP max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["EP"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 White Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["White Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 SRC Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["SRC Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 VA Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["VA Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="F1 CCU max 2 consecutive weeks",
            applicable_years=[TrainingYear.F1],
            state_names=["CCU"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 Night Float max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["Night Float"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 Goodyer Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["Goodyer Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 EP max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["EP"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 White Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["White Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 SRC Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["SRC Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 VA Consults max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["VA Consults"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 CCU max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["CCU"],
            max_consecutive_weeks=2,
        ),
        ConsecutiveStateLimitRule(
            name="S2 Research max 2 consecutive weeks",
            applicable_years=[TrainingYear.S2],
            state_names=["Research"],
            max_consecutive_weeks=2,
        )
    ]


def get_default_first_assignment_run_limit_rules() -> list[FirstAssignmentRunLimitRule]:
    """Return first-assignment run-length hard rules."""

    return [
        FirstAssignmentRunLimitRule(
            name="F1 first Night Float run max 1 week",
            applicable_years=[TrainingYear.F1],
            block_name="Night Float",
            max_run_length_weeks=1,
        )
    ]


def get_default_contiguous_block_rules() -> list[ContiguousBlockRule]:
    """Return hard rules requiring selected rotations to be contiguous."""

    return [
        ContiguousBlockRule(
            name="S2 CT-MRI must be one contiguous run",
            applicable_years=[TrainingYear.S2],
            block_name="CT-MRI",
        ),
        ContiguousBlockRule(
            name="T3 CT-MRI must be one contiguous run",
            applicable_years=[TrainingYear.T3],
            block_name="CT-MRI",
        )
    ]


def get_default_forbidden_transition_rules() -> list[ForbiddenTransitionRule]:
    """Return hard transition rules."""

    return [
        ForbiddenTransitionRule(
            name="F1/S2 Night Float cannot follow CCU",
            applicable_years=[TrainingYear.F1, TrainingYear.S2],
            target_block="Night Float",
            forbidden_previous_blocks=["CCU"],
        )
    ]


def get_default_soft_sequence_rules() -> list[SoftSequenceRule]:
    """Return default weighted soft rules."""

    return [
        SoftSequenceRule(
            name="Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, or PTO",
            applicable_years=[TrainingYear.F1],
            left_states=[
                "White Consults",
                "SRC Consults",
                "VA Consults",
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
            name="Bonus: F1 Night Float followed by Research or PTO",
            applicable_years=[TrainingYear.F1],
            left_states=["Night Float"],
            right_states=["Research", "PTO"],
            weight=5,
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
        SoftSequenceRule(
            name="Bonus: S2 Research adjacent to PTO",
            applicable_years=[TrainingYear.S2],
            left_states=["Research"],
            right_states=["PTO"],
            weight=10,
            direction=SoftRuleDirection.EITHER,
        ),
        SoftSequenceRule(
            name="Bonus: S2 two-week PTO block",
            applicable_years=[TrainingYear.S2],
            left_states=["PTO"],
            right_states=["PTO"],
            weight=8,
        ),
        SoftSequenceRule(
            name="Bonus: T3 two-week PTO block",
            applicable_years=[TrainingYear.T3],
            left_states=["PTO"],
            right_states=["PTO"],
            weight=8,
        ),
    ]


def get_default_soft_single_week_block_rules() -> list[SoftSingleWeekBlockRule]:
    """Return default bonuses for longer same-rotation runs."""

    return [
        SoftSingleWeekBlockRule(
            name="Bonus: F1 consecutive non-Night-Float rotation weeks after first 8 weeks",
            applicable_years=[TrainingYear.F1],
            excluded_states=["Night Float"],
            weight=1,
            start_week=8,
            adjacent_to_first_state_exemption=None,
        ),
        SoftSingleWeekBlockRule(
            name=(
                "Bonus: S2 two-week Goodyer, consult, EP, CHF, Yale Nuclear, "
                "Yale Echo, and Yale Cath runs"
            ),
            applicable_years=[TrainingYear.S2],
            excluded_states=[],
            included_states=[
                "Goodyer Consults",
                "VA Consults",
                "SRC Consults",
                "EP",
                "CHF",
                "Yale Nuclear",
                "Yale Echo",
                "Yale Cath",
            ],
            weight=1,
            adjacent_to_first_state_exemption=None,
        ),
    ]


def get_default_soft_state_assignment_rules() -> list[SoftStateAssignmentRule]:
    """Return default weighted placement bonuses for targeted states."""

    return [
        SoftStateAssignmentRule(
            name="Bonus: S2 Research during final week",
            applicable_years=[TrainingYear.S2],
            state_names=["Research"],
            weight=6,
            start_week=NUM_WEEKS - 1,
            end_week=NUM_WEEKS - 1,
        ),
        SoftStateAssignmentRule(
            name="Bonus: S2 assignment to SRC Echo",
            applicable_years=[TrainingYear.S2],
            state_names=["SRC Echo"],
            weight=3,
        ),
    ]


def get_default_soft_cohort_balance_rules() -> list[SoftCohortBalanceRule]:
    """Return default weighted penalties for uneven within-cohort distribution."""

    return [
        SoftCohortBalanceRule(
            name="Penalty: S2 uneven CCU distribution",
            applicable_years=[TrainingYear.S2],
            state_names=["CCU"],
            weight=4,
            start_week=0,
            end_week=FIRST_YEAR_CCU_START_WEEK - 1,
        ),
        SoftCohortBalanceRule(
            name="Penalty: S2 uneven Night Float distribution",
            applicable_years=[TrainingYear.S2],
            state_names=["Night Float"],
            weight=4,
            start_week=0,
            end_week=FIRST_YEAR_NF_START_WEEK - 1,
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
        structured_call_rules_enabled=True,
        call_eligible_years=[TrainingYear.F1],
        call_allowed_block_names=[
            "EP",
            "CHF",
            "Yale Nuclear",
            "VA Nuclear",
            "Yale Echo",
            "VA Echo",
            "SRC Echo",
            "Yale Cath",
            "VA Cath",
            "SRC Cath",
        ],
        call_min_per_fellow=5,
        call_max_per_fellow=6,
        call_forbidden_following_blocks=["Night Float"],
        call_max_consecutive_weeks_per_fellow=1,
        call_first_call_preferred_blocks=["Yale Echo"],
        call_first_call_preference_weight=8,
        call_first_call_prerequisite_blocks=["White Consults"],
        call_first_call_prerequisite_weight=6,
        call_holiday_anchor_week=_week_index_for_date(date(2026, 11, 26)),
        call_holiday_sensitive_blocks=[
            "White Consults",
            "CCU",
            "SRC Consults",
            "VA Consults",
            "Night Float",
        ],
        call_holiday_target_weeks=[
            week
            for week in (
                _week_index_for_date(date(2026, 12, 24)),
                _week_index_for_date(date(2026, 12, 31)),
            )
            if week is not None
        ],
        call_holiday_conflict_weight=-5,
        srcva_weekend_call_enabled=True,
        srcva_weekend_call_eligible_years=[TrainingYear.F1, TrainingYear.S2],
        srcva_weekend_call_allowed_block_names=[
            "EP",
            "CHF",
            "Yale Nuclear",
            "VA Nuclear",
            "Yale Echo",
            "VA Echo",
            "SRC Echo",
            "Yale Cath",
            "VA Cath",
            "SRC Cath",
            "CT-MRI",
        ],
        srcva_weekend_call_f1_start_week=_week_index_for_date(date(2027, 3, 1)),
        srcva_weekend_call_f1_min=0,
        srcva_weekend_call_f1_max=1,
        srcva_weekend_call_s2_min=5,
        srcva_weekend_call_s2_max=6,
        srcva_total_call_f1_min=6,
        srcva_total_call_f1_max=7,
        srcva_weekday_call_enabled=True,
        srcva_weekday_call_eligible_years=[TrainingYear.F1, TrainingYear.S2],
        srcva_weekday_call_allowed_block_names=[
            "Yale Nuclear",
            "VA Nuclear",
            "VA Echo",
            "SRC Echo",
            "Yale Cath",
            "VA Cath",
            "SRC Cath",
            "CT-MRI",
        ],
        srcva_weekday_call_f1_start_week=_week_index_for_date(date(2027, 1, 4)),
        srcva_weekday_call_f1_min=3,
        srcva_weekday_call_f1_max=5,
        srcva_weekday_call_s2_min=18,
        srcva_weekday_call_s2_max=20,
        srcva_weekday_call_max_consecutive_nights=1,
        srcva_holiday_anchor_week=_week_index_for_date(date(2026, 11, 23)),
        srcva_christmas_target_week=_week_index_for_date(date(2026, 12, 24)),
        srcva_new_year_target_week=_week_index_for_date(date(2026, 12, 31)),
        srcva_holiday_preferred_anchor_blocks=[
            "EP",
            "CHF",
            "Yale Nuclear",
            "Yale Echo",
            "VA Echo",
            "SRC Echo",
            "Yale Cath",
            "VA Cath",
            "SRC Cath",
            "CT-MRI",
            "Research",
            "PTO",
        ],
        srcva_holiday_preference_weight=4,
        srcva_holiday_repeat_weight=-5,
        srcva_weekday_max_one_per_week_weight=-3,
        srcva_weekday_same_week_as_weekend_weight=-2,
        srcva_weekday_same_week_as_24hr_weight=-4,
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=60.0,
        pto_preference_weight_overrides=get_default_pto_preference_weight_overrides(),
        blocks=get_default_blocks(),
        fellows=fellows,
        coverage_rules=get_default_coverage_rules(),
        eligibility_rules=get_default_eligibility_rules(),
        week_count_rules=get_default_week_count_rules(),
        cohort_limit_rules=get_default_cohort_limit_rules(),
        rolling_window_rules=get_default_rolling_window_rules(),
        consecutive_state_limit_rules=get_default_consecutive_state_limit_rules(),
        first_assignment_run_limit_rules=get_default_first_assignment_run_limit_rules(),
        contiguous_block_rules=get_default_contiguous_block_rules(),
        first_assignment_pairing_rules=get_default_first_assignment_pairing_rules(),
        individual_fellow_requirement_rules=get_default_individual_fellow_requirement_rules(),
        prerequisite_rules=get_default_prerequisite_rules(),
        forbidden_transition_rules=get_default_forbidden_transition_rules(),
        soft_sequence_rules=get_default_soft_sequence_rules(),
        soft_single_week_block_rules=get_default_soft_single_week_block_rules(),
        soft_state_assignment_rules=get_default_soft_state_assignment_rules(),
        soft_cohort_balance_rules=get_default_soft_cohort_balance_rules(),
    )
