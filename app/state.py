"""Streamlit session state manager.

Centralizes all reads/writes to ``st.session_state`` so that no other
module touches it directly. This prevents hard-to-debug state bugs
that arise when multiple components read/write the same keys.

Session state keys:
    "config"   → ScheduleConfig   (the current configuration)
    "result"   → ScheduleResult   (the last solver output, or None)
    "issues"   → list[str]        (feasibility warnings)
    "dirty"    → bool             (True if config changed since last solve)
    "notice"   → str | None       (one-time migration / validation notice)
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.config import (
    FIRST_YEAR_CCU_START_WEEK,
    FIRST_YEAR_NF_START_WEEK,
    get_default_config,
    get_default_pto_preference_weight_overrides,
)
from src.io_utils import load_config, load_schedule, save_config, save_schedule
from src.models import (
    BlockConfig,
    CoverageRule,
    EligibilityRule,
    FirstAssignmentPairingRule,
    RollingWindowRule,
    ScheduleConfig,
    ScheduleResult,
    SoftSequenceRule,
    TrainingYear,
    WeekCountRule,
)

# Default paths for persisting state between app restarts
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "saved_config.json"
SCHEDULE_PATH = DATA_DIR / "schedule_output.json"
LEGACY_BLOCK_NAMES = {
    "Consult Y",
    "Consult SRC",
    "Consult VA",
    "Cath Y",
    "Cath SRC",
    "Echo Y",
    "Nuc Y",
    "VA Clinic",
}

SOURCE_BACKED_DEFAULT_BLOCK_NAMES = {
    "White Consults",
    "SRC Consults",
    "VA Consults",
    "Goodyer Consults",
    "CCU",
    "Night Float",
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
    "Research",
    "CT-MRI",
    "Elective",
}


def _looks_like_legacy_saved_config(config: ScheduleConfig) -> bool:
    """Return True when a saved config predates the cohort-aware schema."""

    block_names = {block.name for block in config.blocks}
    if block_names & LEGACY_BLOCK_NAMES:
        return True

    cohort_counts = config.cohort_counts
    return (
        not config.uses_structured_rules
        and cohort_counts[TrainingYear.S2] == 0
        and cohort_counts[TrainingYear.T3] == 0
        and cohort_counts[TrainingYear.F1] == len(config.fellows)
        and len(config.fellows) == 9
    )


def _normalize_loaded_config(
    config: ScheduleConfig,
) -> tuple[ScheduleConfig, str | None]:
    """Upgrade obviously legacy saved configs to the new default schema."""

    if _looks_like_legacy_saved_config(config):
        return (
            get_default_config(),
            (
                "Loaded legacy saved data and reset it to the cohort-aware built-in defaults."
            ),
        )

    updated_messages: list[str] = []
    if _upgrade_source_backed_rule_defaults(config):
        updated_messages.append(
            "Updated saved default rules to match the latest built-in defaults."
        )
    if updated_messages:
        return config, " ".join(updated_messages)
    return config, None


def _looks_like_source_backed_default_family(config: ScheduleConfig) -> bool:
    """Return True when a config appears to be derived from the built-in ruleset."""

    block_names = {block.name for block in config.blocks}
    return len(block_names & SOURCE_BACKED_DEFAULT_BLOCK_NAMES) >= 10


def _upgrade_source_backed_rule_defaults(config: ScheduleConfig) -> bool:
    """Patch stale saved default rules without overwriting arbitrary user edits."""

    changed = False
    if not config.pto_preference_weight_overrides:
        config.pto_preference_weight_overrides = (
            get_default_pto_preference_weight_overrides()
        )
        changed = True

    if not _looks_like_source_backed_default_family(config):
        return changed

    existing_block_names = {block.name for block in config.blocks}
    if "Peripheral vascular" not in existing_block_names:
        config.blocks.append(
            BlockConfig(name="Peripheral vascular", hours_per_week=40.0)
        )
        changed = True

    for rule in config.coverage_rules:
        if (
            rule.name == "Yale Nuclear F1 slot"
            and rule.block_name == "Yale Nuclear"
            and rule.eligible_years == [TrainingYear.F1]
            and rule.min_fellows == 1
            and rule.max_fellows == 1
        ):
            rule.name = "Yale Nuclear optional F1 slot"
            rule.min_fellows = 0
            changed = True
        elif (
            rule.name == "Yale Echo F1 range"
            and rule.block_name == "Yale Echo"
            and rule.eligible_years == [TrainingYear.F1]
            and rule.max_fellows != 2
        ):
            rule.max_fellows = 2
            changed = True
        elif (
            rule.name == "EP staffed by F1 or S2"
            and rule.block_name == "EP"
            and rule.max_fellows != 2
        ):
            rule.max_fellows = 2
            changed = True
        elif (
            rule.name == "CCU early by S2"
            and rule.block_name == "CCU"
            and (
                rule.start_week != 0
                or rule.end_week != FIRST_YEAR_CCU_START_WEEK - 1
            )
        ):
            rule.start_week = 0
            rule.end_week = FIRST_YEAR_CCU_START_WEEK - 1
            changed = True
        elif (
            rule.name == "CCU later by F1"
            and rule.block_name == "CCU"
            and rule.start_week != FIRST_YEAR_CCU_START_WEEK
        ):
            rule.start_week = FIRST_YEAR_CCU_START_WEEK
            changed = True
        elif (
            rule.name == "Night Float early by S2"
            and rule.block_name == "Night Float"
            and (
                rule.start_week != 0
                or rule.end_week != FIRST_YEAR_NF_START_WEEK - 1
            )
        ):
            rule.start_week = 0
            rule.end_week = FIRST_YEAR_NF_START_WEEK - 1
            changed = True
        elif (
            rule.name == "Night Float later by F1"
            and rule.block_name == "Night Float"
            and rule.start_week != FIRST_YEAR_NF_START_WEEK
        ):
            rule.start_week = FIRST_YEAR_NF_START_WEEK
            changed = True

    original_coverage_count = len(config.coverage_rules)
    config.coverage_rules = [
        rule
        for rule in config.coverage_rules
        if rule.name
        not in {
            "Yale Nuclear optional F1 slot",
            "Yale Nuclear S2 slot",
            "SRC Cath staffed",
        }
    ]
    if len(config.coverage_rules) != original_coverage_count:
        changed = True
    if not any(rule.name == "Yale Nuclear staffed by F1 or S2" for rule in config.coverage_rules):
        config.coverage_rules.append(
            CoverageRule(
                name="Yale Nuclear staffed by F1 or S2",
                block_name="Yale Nuclear",
                eligible_years=[TrainingYear.F1, TrainingYear.S2],
                min_fellows=1,
                max_fellows=2,
            )
        )
        changed = True
    if not any(rule.name == "SRC Cath optional F1 or S2" for rule in config.coverage_rules):
        config.coverage_rules.append(
            CoverageRule(
                name="SRC Cath optional F1 or S2",
                block_name="SRC Cath",
                eligible_years=[TrainingYear.F1, TrainingYear.S2],
                min_fellows=0,
                max_fellows=1,
            )
        )
        changed = True
    if not any(rule.name == "CT-MRI staffed by S2 or T3" for rule in config.coverage_rules):
        config.coverage_rules.append(
            CoverageRule(
                name="CT-MRI staffed by S2 or T3",
                block_name="CT-MRI",
                eligible_years=[TrainingYear.S2, TrainingYear.T3],
                min_fellows=1,
                max_fellows=1,
            )
        )
        changed = True
    if not any(rule.name == "Peripheral vascular optional T3" for rule in config.coverage_rules):
        config.coverage_rules.append(
            CoverageRule(
                name="Peripheral vascular optional T3",
                block_name="Peripheral vascular",
                eligible_years=[TrainingYear.T3],
                min_fellows=0,
                max_fellows=1,
            )
        )
        changed = True

    for rule in config.eligibility_rules:
        if (
            rule.name == "CCU later F1 only"
            and rule.block_names == ["CCU"]
            and rule.allowed_years == [TrainingYear.F1]
            and rule.start_week == 4
        ):
            rule.name = "CCU later F1 or S2"
            rule.allowed_years = [TrainingYear.F1, TrainingYear.S2]
            rule.start_week = FIRST_YEAR_CCU_START_WEEK
            changed = True
        elif (
            rule.name == "Night Float later F1 only"
            and rule.block_names == ["Night Float"]
            and rule.allowed_years == [TrainingYear.F1]
            and rule.start_week == 5
        ):
            rule.name = "Night Float later F1 or S2"
            rule.allowed_years = [TrainingYear.F1, TrainingYear.S2]
            rule.start_week = FIRST_YEAR_NF_START_WEEK
            changed = True
        elif (
            rule.name == "SRC Cath any year"
            and rule.block_names == ["SRC Cath"]
            and rule.allowed_years != [TrainingYear.F1, TrainingYear.S2]
        ):
            rule.name = "SRC Cath limited to F1 and S2"
            rule.allowed_years = [TrainingYear.F1, TrainingYear.S2]
            changed = True
        elif (
            rule.name == "CCU early S2 only"
            and rule.block_names == ["CCU"]
            and (
                rule.start_week != 0
                or rule.end_week != FIRST_YEAR_CCU_START_WEEK - 1
            )
        ):
            rule.start_week = 0
            rule.end_week = FIRST_YEAR_CCU_START_WEEK - 1
            changed = True
        elif (
            rule.name == "CCU later F1 or S2"
            and rule.block_names == ["CCU"]
            and rule.start_week != FIRST_YEAR_CCU_START_WEEK
        ):
            rule.start_week = FIRST_YEAR_CCU_START_WEEK
            changed = True
        elif (
            rule.name == "Night Float early S2 only"
            and rule.block_names == ["Night Float"]
            and (
                rule.start_week != 0
                or rule.end_week != FIRST_YEAR_NF_START_WEEK - 1
            )
        ):
            rule.start_week = 0
            rule.end_week = FIRST_YEAR_NF_START_WEEK - 1
            changed = True
        elif (
            rule.name == "Night Float later F1 or S2"
            and rule.block_names == ["Night Float"]
            and rule.start_week != FIRST_YEAR_NF_START_WEEK
        ):
            rule.start_week = FIRST_YEAR_NF_START_WEEK
            changed = True
        elif (
            rule.name == "Research any year"
            and set(rule.block_names) != {"Research"}
        ):
            rule.block_names = ["Research"]
            changed = True

    if not any(rule.name == "CT-MRI limited to S2 and T3" for rule in config.eligibility_rules):
        config.eligibility_rules.append(
            EligibilityRule(
                name="CT-MRI limited to S2 and T3",
                block_names=["CT-MRI"],
                allowed_years=[TrainingYear.S2, TrainingYear.T3],
            )
        )
        changed = True
    if not any(rule.name == "Elective only T3" for rule in config.eligibility_rules):
        config.eligibility_rules.append(
            EligibilityRule(
                name="Elective only T3",
                block_names=["Elective"],
                allowed_years=[TrainingYear.T3],
            )
        )
        changed = True
    if not any(rule.name == "Peripheral vascular only T3" for rule in config.eligibility_rules):
        config.eligibility_rules.append(
            EligibilityRule(
                name="Peripheral vascular only T3",
                block_names=["Peripheral vascular"],
                allowed_years=[TrainingYear.T3],
            )
        )
        changed = True

    for rule in config.week_count_rules:
        if (
            rule.name == "F1 White Consults"
            and rule.block_names == ["White Consults"]
            and (
                rule.min_weeks != 5
                or rule.max_weeks != 6
                or not rule.is_active
            )
        ):
            rule.min_weeks = 5
            rule.max_weeks = 6
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 SRC Consults"
            and rule.block_names == ["SRC Consults"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 VA Consults"
            and rule.block_names == ["VA Consults"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Consult total"
            and rule.block_names == ["White Consults", "SRC Consults", "VA Consults"]
            and rule.min_weeks == 10
            and rule.max_weeks in {11, 12}
        ):
            if rule.max_weeks != 12:
                rule.max_weeks = 12
                changed = True
            if not rule.is_active:
                rule.is_active = True
                changed = True
        elif (
            rule.name in {"F1 no PTO in first two months", "F1 no PTO before 8/10/26"}
            and rule.block_names == ["PTO"]
        ):
            if rule.name != "F1 no PTO before 8/10/26":
                rule.name = "F1 no PTO before 8/10/26"
                changed = True
            if rule.end_week != 3:
                rule.end_week = 3
                changed = True
            if not rule.is_active:
                rule.is_active = True
                changed = True
        elif (
            rule.name == "F1 CCU after orientation"
            and rule.block_names == ["CCU"]
            and (
                rule.start_week != FIRST_YEAR_CCU_START_WEEK
                or not rule.is_active
            )
        ):
            rule.start_week = FIRST_YEAR_CCU_START_WEEK
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Night Float after onboarding"
            and rule.block_names == ["Night Float"]
            and (
                rule.start_week != FIRST_YEAR_NF_START_WEEK
                or not rule.is_active
            )
        ):
            rule.start_week = FIRST_YEAR_NF_START_WEEK
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 EP"
            and rule.block_names == ["EP"]
            and (rule.min_weeks != 4 or rule.max_weeks != 5)
        ):
            rule.min_weeks = 4
            rule.max_weeks = 5
            changed = True
        elif (
            rule.name == "F1 Yale Nuclear"
            and rule.block_names == ["Yale Nuclear"]
            and (
                rule.min_weeks != 2
                or rule.max_weeks != 4
                or not rule.is_active
            )
        ):
            rule.min_weeks = 2
            rule.max_weeks = 4
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Yale Echo"
            and rule.block_names == ["Yale Echo"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 VA Echo"
            and rule.block_names == ["VA Echo"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 SRC Echo"
            and rule.block_names == ["SRC Echo"]
            and rule.min_weeks == 1
            and rule.max_weeks == 1
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Echo total"
            and rule.block_names == ["Yale Echo", "VA Echo", "SRC Echo"]
            and (
                rule.min_weeks != 7
                or rule.max_weeks != 9
                or not rule.is_active
            )
        ):
            rule.min_weeks = 7
            rule.max_weeks = 9
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Yale Cath"
            and rule.block_names == ["Yale Cath"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 VA Cath"
            and rule.block_names == ["VA Cath"]
            and rule.min_weeks == 1
            and rule.max_weeks == 2
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 SRC Cath"
            and rule.block_names == ["SRC Cath"]
            and rule.min_weeks == 1
            and rule.max_weeks == 2
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Cath total"
            and rule.block_names == ["Yale Cath", "VA Cath", "SRC Cath"]
            and rule.min_weeks == 6
            and rule.max_weeks == 7
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 VA Nuclear"
            and rule.block_names == ["VA Nuclear"]
            and (
                rule.min_weeks != 1
                or rule.max_weeks != 3
                or not rule.is_active
            )
        ):
            rule.min_weeks = 1
            rule.max_weeks = 3
            rule.is_active = True
            changed = True
        elif (
            rule.name == "F1 Nuclear total"
            and rule.block_names == ["Yale Nuclear", "VA Nuclear"]
            and (
                rule.min_weeks != 4
                or rule.max_weeks != 7
                or not rule.is_active
            )
        ):
            rule.min_weeks = 4
            rule.max_weeks = 7
            rule.is_active = True
            changed = True

    if not any(rule.name == "F1 no Research before 8/10/26" for rule in config.week_count_rules):
        config.week_count_rules.append(
            WeekCountRule(
                name="F1 no Research before 8/10/26",
                applicable_years=[TrainingYear.F1],
                block_names=["Research"],
                min_weeks=0,
                max_weeks=0,
                start_week=0,
                end_week=3,
            )
        )
        changed = True
    if not any(rule.name == "F1 Peripheral vascular prohibited" for rule in config.week_count_rules):
        config.week_count_rules.append(
            WeekCountRule(
                name="F1 Peripheral vascular prohibited",
                applicable_years=[TrainingYear.F1],
                block_names=["Peripheral vascular"],
                min_weeks=0,
                max_weeks=0,
            )
        )
        changed = True

    prerequisite_rule = next(
        (
            rule
            for rule in config.prerequisite_rules
            if rule.name == "F1 before Night Float needs core exposure"
        ),
        None,
    )
    if prerequisite_rule is not None:
        required_blocks = [
            "Yale Echo",
            "Yale Cath",
            "White Consults",
            "CCU",
            "EP",
            "CHF",
        ]
        if prerequisite_rule.prerequisite_blocks != required_blocks:
            prerequisite_rule.prerequisite_blocks = required_blocks
            changed = True

    pairing_rule = next(
        (
            rule
            for rule in config.first_assignment_pairing_rules
            if rule.name == "F1 first Yale Nuclear week needs experienced pairing"
        ),
        None,
    )
    if pairing_rule is None:
        config.first_assignment_pairing_rules.append(
            FirstAssignmentPairingRule(
                name="F1 first Yale Nuclear week needs experienced pairing",
                trainee_years=[TrainingYear.F1],
                block_name="Yale Nuclear",
                mentor_years=[TrainingYear.S2],
                experienced_peer_years=[TrainingYear.F1],
                required_prior_weeks=1,
            )
        )
        changed = True
    else:
        if pairing_rule.trainee_years != [TrainingYear.F1]:
            pairing_rule.trainee_years = [TrainingYear.F1]
            changed = True
        if pairing_rule.block_name != "Yale Nuclear":
            pairing_rule.block_name = "Yale Nuclear"
            changed = True
        if pairing_rule.mentor_years != [TrainingYear.S2]:
            pairing_rule.mentor_years = [TrainingYear.S2]
            changed = True
        if pairing_rule.experienced_peer_years != [TrainingYear.F1]:
            pairing_rule.experienced_peer_years = [TrainingYear.F1]
            changed = True
        if pairing_rule.required_prior_weeks != 1:
            pairing_rule.required_prior_weeks = 1
            changed = True
        if not pairing_rule.is_active:
            pairing_rule.is_active = True
            changed = True

    matching_rolling_rule = next(
        (
            rule
            for rule in config.rolling_window_rules
            if rule.name == "Max 3 PTO or Research weeks in any 4-week period"
        ),
        None,
    )
    if matching_rolling_rule is None:
        config.rolling_window_rules.append(
            RollingWindowRule(
                name="Max 3 PTO or Research weeks in any 4-week period",
                applicable_years=[
                    TrainingYear.F1,
                    TrainingYear.S2,
                    TrainingYear.T3,
                ],
                state_names=["PTO", "Research"],
                window_size_weeks=4,
                max_weeks_in_window=3,
            )
        )
        changed = True
    else:
        if matching_rolling_rule.applicable_years != [
            TrainingYear.F1,
            TrainingYear.S2,
            TrainingYear.T3,
        ]:
            matching_rolling_rule.applicable_years = [
                TrainingYear.F1,
                TrainingYear.S2,
                TrainingYear.T3,
            ]
            changed = True
        if matching_rolling_rule.state_names != ["PTO", "Research"]:
            matching_rolling_rule.state_names = ["PTO", "Research"]
            changed = True
        if matching_rolling_rule.window_size_weeks != 4:
            matching_rolling_rule.window_size_weeks = 4
            changed = True
        if matching_rolling_rule.max_weeks_in_window != 3:
            matching_rolling_rule.max_weeks_in_window = 3
            changed = True
        if not matching_rolling_rule.is_active:
            matching_rolling_rule.is_active = True
            changed = True

    legacy_nf_forbidden_previous_blocks = [
        "White Consults",
        "SRC Consults",
        "VA Consults",
        "CCU",
        "PTO",
    ]
    filtered_transition_rules = [
        rule
        for rule in config.forbidden_transition_rules
        if not (
            rule.target_block == "Night Float"
            and rule.applicable_years == [TrainingYear.F1]
            and rule.forbidden_previous_blocks == legacy_nf_forbidden_previous_blocks
        )
    ]
    if len(filtered_transition_rules) != len(config.forbidden_transition_rules):
        config.forbidden_transition_rules = filtered_transition_rules
        changed = True

    soft_penalty_name = (
        "Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, "
        "CCU, or PTO"
    )
    matching_soft_penalty = next(
        (
            rule
            for rule in config.soft_sequence_rules
            if rule.applicable_years == [TrainingYear.F1]
            and rule.left_states == legacy_nf_forbidden_previous_blocks
            and rule.right_states == ["Night Float"]
        ),
        None,
    )
    if matching_soft_penalty is None:
        config.soft_sequence_rules.insert(
            0,
            SoftSequenceRule(
                name=soft_penalty_name,
                applicable_years=[TrainingYear.F1],
                left_states=legacy_nf_forbidden_previous_blocks,
                right_states=["Night Float"],
                weight=-40,
            ),
        )
        changed = True
    else:
        if matching_soft_penalty.name != soft_penalty_name:
            matching_soft_penalty.name = soft_penalty_name
            changed = True
        if matching_soft_penalty.weight != -40:
            matching_soft_penalty.weight = -40
            changed = True
        if not matching_soft_penalty.is_active:
            matching_soft_penalty.is_active = True
            changed = True

    return changed


def _result_matches_config(
    result: ScheduleResult | None,
    config: ScheduleConfig,
) -> bool:
    """Return True when a saved schedule still fits the current config."""

    if result is None:
        return True

    if len(result.assignments) != len(config.fellows):
        return False
    if len(result.call_assignments) != len(config.fellows):
        return False

    return all(
        len(week_assignments) == config.num_weeks
        for week_assignments in result.assignments
    ) and all(
        len(week_calls) == config.num_weeks
        for week_calls in result.call_assignments
    )


def init_state() -> None:
    """Initialize session state on first app load.

    Tries to load a previously saved config/schedule from disk.
    Falls back to factory defaults if nothing is saved.
    """
    loaded_notice: str | None = None

    if "config" not in st.session_state:
        if CONFIG_PATH.exists():
            try:
                loaded_config = load_config(CONFIG_PATH)
                loaded_config, loaded_notice = _normalize_loaded_config(loaded_config)
                st.session_state["config"] = loaded_config
                if loaded_notice is not None:
                    save_config(loaded_config, CONFIG_PATH)
            except Exception:
                st.session_state["config"] = get_default_config()
        else:
            st.session_state["config"] = get_default_config()

    current_config, current_notice = _normalize_loaded_config(st.session_state["config"])
    st.session_state["config"] = current_config
    if current_notice is not None:
        loaded_notice = current_notice
        if CONFIG_PATH.exists():
            save_config(current_config, CONFIG_PATH)

    if "result" not in st.session_state:
        if SCHEDULE_PATH.exists():
            try:
                loaded_result = load_schedule(SCHEDULE_PATH)
                if _result_matches_config(loaded_result, st.session_state["config"]):
                    st.session_state["result"] = loaded_result
                else:
                    st.session_state["result"] = None
                    if loaded_notice is None:
                        loaded_notice = (
                            "Ignored a saved schedule because it no longer matches "
                            "the current configuration."
                        )
            except Exception:
                st.session_state["result"] = None
        else:
            st.session_state["result"] = None

    if "issues" not in st.session_state:
        st.session_state["issues"] = []

    if "dirty" not in st.session_state:
        st.session_state["dirty"] = False

    if "notice" not in st.session_state:
        st.session_state["notice"] = loaded_notice


def get_config() -> ScheduleConfig:
    """Return the current schedule configuration."""
    return st.session_state["config"]


def set_config(config: ScheduleConfig) -> None:
    """Update the schedule configuration and mark state as dirty."""
    st.session_state["config"] = config
    st.session_state["dirty"] = True


def get_result() -> ScheduleResult | None:
    """Return the last solver result, or None if not yet solved."""
    return st.session_state.get("result")


def set_result(result: ScheduleResult) -> None:
    """Store a new solver result and persist to disk."""
    st.session_state["result"] = result
    st.session_state["dirty"] = False
    save_schedule(result, SCHEDULE_PATH)


def get_issues() -> list[str]:
    """Return the current list of feasibility issues."""
    return st.session_state.get("issues", [])


def set_issues(issues: list[str]) -> None:
    """Update the feasibility issues list."""
    st.session_state["issues"] = issues


def persist_config() -> None:
    """Save the current config to disk."""
    save_config(get_config(), CONFIG_PATH)
    st.session_state["dirty"] = False


def is_dirty() -> bool:
    """Return True when the config has changed since the last save/solve."""

    return bool(st.session_state.get("dirty", False))


def get_notice() -> str | None:
    """Return the current migration / validation notice, if any."""

    return st.session_state.get("notice")


def clear_notice() -> None:
    """Clear the current migration / validation notice."""

    st.session_state["notice"] = None
