"""Streamlit session state manager.

Centralizes all reads/writes to ``st.session_state`` so that no other
module touches it directly. This prevents hard-to-debug state bugs
that arise when multiple components read/write the same keys.

Session state keys:
    "config"   → ScheduleConfig   (the current configuration)
    "result"   → ScheduleResult   (the last solver output, or None)
    "issues"   → list[str]        (feasibility warnings)
    "dirty"    → bool             (True if config changed since last solve)
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.config import get_default_config
from src.io_utils import load_config, load_schedule, save_config, save_schedule
from src.models import ScheduleConfig, ScheduleResult

# Default paths for persisting state between app restarts
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "saved_config.json"
SCHEDULE_PATH = DATA_DIR / "schedule_output.json"


def init_state() -> None:
    """Initialize session state on first app load.

    Tries to load a previously saved config/schedule from disk.
    Falls back to factory defaults if nothing is saved.
    """
    if "config" not in st.session_state:
        if CONFIG_PATH.exists():
            try:
                st.session_state["config"] = load_config(CONFIG_PATH)
            except Exception:
                st.session_state["config"] = get_default_config()
        else:
            st.session_state["config"] = get_default_config()

    if "result" not in st.session_state:
        if SCHEDULE_PATH.exists():
            try:
                st.session_state["result"] = load_schedule(SCHEDULE_PATH)
            except Exception:
                st.session_state["result"] = None
        else:
            st.session_state["result"] = None

    if "issues" not in st.session_state:
        st.session_state["issues"] = []

    if "dirty" not in st.session_state:
        st.session_state["dirty"] = False


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
