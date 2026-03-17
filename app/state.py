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
    get_default_config,
    get_default_pto_preference_weight_overrides,
)
from src.io_utils import load_config, load_schedule, save_config, save_schedule
from src.models import ScheduleConfig, ScheduleResult, TrainingYear

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


def _looks_like_legacy_saved_config(config: ScheduleConfig) -> bool:
    """Return True when a saved config predates the cohort-aware schema."""

    block_names = {block.name for block in config.blocks}
    if block_names & LEGACY_BLOCK_NAMES:
        return True

    cohort_counts = config.cohort_counts
    return (
        not config.uses_structured_rules
        and cohort_counts[TrainingYear.PGY2] == 0
        and cohort_counts[TrainingYear.PGY3] == 0
        and cohort_counts[TrainingYear.PGY1] == len(config.fellows)
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
                "Loaded legacy saved data and reset it to the cohort-aware defaults "
                "from scheduling_rules.txt."
            ),
        )

    updated_messages: list[str] = []
    if _upgrade_source_backed_rule_defaults(config):
        updated_messages.append(
            "Updated saved source-backed rules to match the latest scheduling_rules.txt defaults."
        )
    if updated_messages:
        return config, " ".join(updated_messages)
    return config, None


def _upgrade_source_backed_rule_defaults(config: ScheduleConfig) -> bool:
    """Patch stale saved default rules without overwriting arbitrary user edits."""

    changed = False
    if not config.pto_preference_weight_overrides:
        config.pto_preference_weight_overrides = (
            get_default_pto_preference_weight_overrides()
        )
        changed = True

    for rule in config.coverage_rules:
        if (
            rule.name == "Yale Nuclear PGY1 slot"
            and rule.block_name == "Yale Nuclear"
            and rule.eligible_years == [TrainingYear.PGY1]
            and rule.min_fellows == 1
            and rule.max_fellows == 1
        ):
            rule.name = "Yale Nuclear optional PGY1 slot"
            rule.min_fellows = 0
            changed = True

    for rule in config.week_count_rules:
        if (
            rule.name == "PGY1 White Consults"
            and rule.block_names == ["White Consults"]
            and rule.min_weeks == 4
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.max_weeks = 6
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 SRC Consults"
            and rule.block_names == ["SRC Consults"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 VA Consults"
            and rule.block_names == ["VA Consults"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Consult total"
            and rule.block_names == ["White Consults", "SRC Consults", "VA Consults"]
            and rule.min_weeks == 10
            and rule.max_weeks in {11, 12}
        ):
            rule.max_weeks = 12
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Yale Nuclear"
            and rule.block_names == ["Yale Nuclear"]
            and rule.min_weeks == 2
            and rule.max_weeks == 3
            and not rule.is_active
        ):
            rule.max_weeks = 6
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Yale Echo"
            and rule.block_names == ["Yale Echo"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 VA Echo"
            and rule.block_names == ["VA Echo"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 SRC Echo"
            and rule.block_names == ["SRC Echo"]
            and rule.min_weeks == 1
            and rule.max_weeks == 1
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Echo total"
            and rule.block_names == ["Yale Echo", "VA Echo", "SRC Echo"]
            and rule.min_weeks == 8
            and rule.max_weeks == 9
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Yale Cath"
            and rule.block_names == ["Yale Cath"]
            and rule.min_weeks == 3
            and rule.max_weeks == 4
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 VA Cath"
            and rule.block_names == ["VA Cath"]
            and rule.min_weeks == 1
            and rule.max_weeks == 2
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 SRC Cath"
            and rule.block_names == ["SRC Cath"]
            and rule.min_weeks == 1
            and rule.max_weeks == 2
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Cath total"
            and rule.block_names == ["Yale Cath", "VA Cath", "SRC Cath"]
            and rule.min_weeks == 6
            and rule.max_weeks == 7
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 VA Nuclear"
            and rule.block_names == ["VA Nuclear"]
            and rule.min_weeks == 1
            and rule.max_weeks == 2
            and not rule.is_active
        ):
            rule.is_active = True
            changed = True
        elif (
            rule.name == "PGY1 Nuclear total"
            and rule.block_names == ["Yale Nuclear", "VA Nuclear"]
            and rule.min_weeks == 4
            and rule.max_weeks == 7
            and not rule.is_active
        ):
            rule.is_active = True
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


def get_notice() -> str | None:
    """Return the current migration / validation notice, if any."""

    return st.session_state.get("notice")


def clear_notice() -> None:
    """Clear the current migration / validation notice."""

    st.session_state["notice"] = None
