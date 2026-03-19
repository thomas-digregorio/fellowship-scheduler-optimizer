"""UI smoke tests for the Streamlit dashboard."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.state as app_state
from app.components.master_schedule import _build_rotation_counts_dataframe
from app.components.rules_tab import (
    _display_optional_week_index,
    _display_week_index,
    _to_optional_zero_based_week_index,
    _to_zero_based_week_index,
)
from src.config import get_default_config
from src.io_utils import save_config
from src.models import (
    BlockConfig,
    BlockType,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    ForbiddenTransitionRule,
    ScheduleConfig,
    SoftSequenceRule,
    TrainingYear,
    WeekCountRule,
)


APP_PATH = Path(__file__).resolve().parent.parent / "app" / "app.py"


def _click_workspace(at: AppTest, label: str) -> AppTest:
    """Navigate to a workspace using the sidebar button menu."""

    return next(button for button in at.button if button.label == label).click().run(
        timeout=20
    )


def make_small_ui_config() -> ScheduleConfig:
    """Build a compact cohort-aware config for fast UI tests."""

    fellows = [
        FellowConfig("F1 A", training_year=TrainingYear.F1, pto_rankings=[3]),
        FellowConfig("F1 B", training_year=TrainingYear.F1, pto_rankings=[4]),
        FellowConfig("S2 A", training_year=TrainingYear.S2, pto_rankings=[3]),
        FellowConfig("S2 B", training_year=TrainingYear.S2, pto_rankings=[2]),
        FellowConfig("T3 A", training_year=TrainingYear.T3, pto_rankings=[4]),
    ]
    return ScheduleConfig(
        num_fellows=len(fellows),
        num_weeks=4,
        start_date=date(2026, 7, 13),
        pto_weeks_granted=0,
        pto_weeks_to_rank=1,
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=10.0,
        blocks=[
            BlockConfig(name="White Consults", hours_per_week=50.0),
            BlockConfig(name="CCU", hours_per_week=55.0),
            BlockConfig(name="Research", hours_per_week=40.0),
            BlockConfig(name="Elective", hours_per_week=40.0),
        ],
        fellows=fellows,
        coverage_rules=[
            CoverageRule(
                name="White F1",
                block_name="White Consults",
                eligible_years=[TrainingYear.F1],
                min_fellows=1,
                max_fellows=1,
            ),
            CoverageRule(
                name="CCU S2",
                block_name="CCU",
                eligible_years=[TrainingYear.S2],
                min_fellows=1,
                max_fellows=1,
            ),
        ],
        eligibility_rules=[
            EligibilityRule(
                name="White F1 only",
                block_names=["White Consults"],
                allowed_years=[TrainingYear.F1],
            ),
            EligibilityRule(
                name="CCU S2 only",
                block_names=["CCU"],
                allowed_years=[TrainingYear.S2],
            ),
            EligibilityRule(
                name="Research any year",
                block_names=["Research", "Elective"],
                allowed_years=[TrainingYear.F1, TrainingYear.S2, TrainingYear.T3],
            ),
        ],
    )


def make_impossible_ui_config() -> ScheduleConfig:
    """Build a config with an obvious blocking feasibility issue."""

    config = make_small_ui_config()
    config.blocks[0].fellows_needed = 3
    config.blocks[1].fellows_needed = 3
    config.coverage_rules = []
    config.eligibility_rules = []
    return config


def make_legacy_saved_config() -> ScheduleConfig:
    """Build an old single-cohort config that should migrate to defaults."""

    fellows = [FellowConfig(f"Legacy Fellow {idx + 1}") for idx in range(9)]
    return ScheduleConfig(
        num_fellows=len(fellows),
        num_weeks=52,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=4,
        pto_weeks_to_rank=6,
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=30.0,
        blocks=[
            BlockConfig(name="Night Float", block_type=BlockType.NIGHT),
            BlockConfig(name="CCU"),
            BlockConfig(name="Consult Y"),
            BlockConfig(name="Consult SRC"),
            BlockConfig(name="Consult VA"),
            BlockConfig(name="Cath Y"),
            BlockConfig(name="Cath SRC"),
            BlockConfig(name="Echo Y"),
            BlockConfig(name="Nuc Y"),
            BlockConfig(name="VA Clinic"),
            BlockConfig(name="Research"),
        ],
        fellows=fellows,
    )


def test_app_renders_and_generates_schedule(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The dashboard should render, navigate, and generate a schedule."""

    config_path = tmp_path / "saved_config.json"
    schedule_path = tmp_path / "schedule_output.json"
    save_config(make_small_ui_config(), config_path)
    monkeypatch.setattr(app_state, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_state, "SCHEDULE_PATH", schedule_path)

    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run(timeout=20)

    assert not at.exception
    nav_labels = [button.label for button in at.button[:4]]
    assert nav_labels == [
        "Overview",
        "Set Rules",
        "Generate Schedule",
        "Fellow Breakdown",
    ]
    assert any(subheader.value == "🏁 Overview" for subheader in at.subheader)
    assert not any(markdown.value == "#### Next Best Action" for markdown in at.markdown)
    assert not any(button.label == "🔄 Generate Schedule" for button in at.button)
    assert not any(subheader.value == "🧭 Validation Center" for subheader in at.subheader)

    at = _click_workspace(at, "Set Rules")

    assert not at.exception
    assert any(subheader.value == "📏 Rules" for subheader in at.subheader)
    assert not any(button.label == "🔄 Generate Schedule" for button in at.button)
    assert any(subheader.value == "🧭 Validation Center" for subheader in at.subheader)
    tab_labels = [tab.label for tab in at.tabs]
    assert "Program-wide Rules" in tab_labels
    assert "F1 Fellow Rules" in tab_labels
    assert "S2 Fellow Rules" in tab_labels
    assert "T3 Fellow Rules" in tab_labels
    assert "Soft Rules" not in tab_labels
    assert "Hard Rules" not in tab_labels
    assert "Shared Hard Rules" not in tab_labels
    assert "Schedule Config" not in tab_labels
    assert "Block Metadata" not in tab_labels
    assert any(markdown.value == "**Weighted Soft Rules**" for markdown in at.markdown)

    at = _click_workspace(at, "Generate Schedule")

    assert not at.exception
    generate = next(button for button in at.button if button.label == "🔄 Generate Schedule")
    at = generate.click().run(timeout=20)

    assert not at.exception
    assert schedule_path.exists()
    assert any(subheader.value == "📋 Master Schedule Workspace" for subheader in at.subheader)
    assert any(subheader.value == "📋 Master Schedule" for subheader in at.subheader)
    assert len(at.dataframe) >= 1
    assert any(markdown.value == "#### Counts" for markdown in at.markdown)
    objective_breakdown_frames = [
        dataframe.value
        for dataframe in at.dataframe
        if {"Category", "F1", "S2", "T3", "Total"}.issubset(
            set(dataframe.value.columns)
        )
    ]
    assert objective_breakdown_frames
    assert "Total" in objective_breakdown_frames[0]["Category"].tolist()
    counts_frames = [
        dataframe.value
        for dataframe in at.dataframe
        if "Rotation" in dataframe.value.columns
    ]
    assert counts_frames
    assert "White Consults" in counts_frames[0]["Rotation"].tolist()
    assert any(subheader.value == "✅ Checks" for subheader in at.subheader)

    at = _click_workspace(at, "Fellow Breakdown")

    assert not at.exception
    assert any(subheader.value == "👥 Fellow Breakdown" for subheader in at.subheader)


def test_app_surfaces_blocking_feasibility_issues(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The dashboard should warn before attempting an impossible solve."""

    config_path = tmp_path / "saved_config.json"
    schedule_path = tmp_path / "schedule_output.json"
    save_config(make_impossible_ui_config(), config_path)
    monkeypatch.setattr(app_state, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_state, "SCHEDULE_PATH", schedule_path)

    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run(timeout=20)

    at = _click_workspace(at, "Generate Schedule")

    generate = next(button for button in at.button if button.label == "🔄 Generate Schedule")
    at = generate.click().run(timeout=20)

    assert not at.exception
    assert not any(subheader.value == "🧭 Validation Center" for subheader in at.subheader)

    at = _click_workspace(at, "Set Rules")

    assert not at.exception
    assert any(subheader.value == "🧭 Validation Center" for subheader in at.subheader)
    surfaced_values = (
        [warning.value for warning in at.warning]
        + [error.value for error in at.error]
        + [markdown.value for markdown in at.markdown]
    )
    assert any("Staffing conflict" in value for value in surfaced_values)
    assert not schedule_path.exists()


def test_legacy_saved_config_migrates_to_cohort_defaults() -> None:
    """Old single-cohort saves should be replaced with the new cohort-aware defaults."""

    migrated, notice = app_state._normalize_loaded_config(make_legacy_saved_config())

    assert notice is not None
    assert migrated.cohort_counts[TrainingYear.F1] == 9
    assert migrated.cohort_counts[TrainingYear.S2] == 9
    assert migrated.cohort_counts[TrainingYear.T3] == 7


def test_saved_defaults_upgrade_to_latest_defaults() -> None:
    """Persisted older defaults should be upgraded in place."""

    config = make_small_ui_config()
    config.blocks = get_default_config().blocks
    config.coverage_rules.append(
        CoverageRule(
            name="Yale Nuclear F1 slot",
            block_name="Yale Nuclear",
            eligible_years=[TrainingYear.F1],
            min_fellows=1,
            max_fellows=1,
        )
    )
    config.coverage_rules.append(
        CoverageRule(
            name="Yale Echo F1 range",
            block_name="Yale Echo",
            eligible_years=[TrainingYear.F1],
            min_fellows=0,
            max_fellows=3,
        )
    )
    config.week_count_rules = [
        WeekCountRule(
            name="F1 no PTO before 8/10/26",
            applicable_years=[TrainingYear.F1],
            block_names=["PTO"],
            min_weeks=0,
            max_weeks=0,
            start_week=0,
            end_week=3,
            is_active=True,
        ),
    ]
    config.week_count_rules.extend(
        [
            WeekCountRule(
                name="F1 White Consults",
                applicable_years=[TrainingYear.F1],
                block_names=["White Consults"],
                min_weeks=4,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 SRC Consults",
                applicable_years=[TrainingYear.F1],
                block_names=["SRC Consults"],
                min_weeks=3,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 VA Consults",
                applicable_years=[TrainingYear.F1],
                block_names=["VA Consults"],
                min_weeks=3,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Consult total",
                applicable_years=[TrainingYear.F1],
                block_names=["White Consults", "SRC Consults", "VA Consults"],
                min_weeks=10,
                max_weeks=12,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 EP",
                applicable_years=[TrainingYear.F1],
                block_names=["EP"],
                min_weeks=3,
                max_weeks=5,
                is_active=True,
            ),
            WeekCountRule(
                name="F1 Yale Nuclear",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Nuclear"],
                min_weeks=2,
                max_weeks=3,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 VA Nuclear",
                applicable_years=[TrainingYear.F1],
                block_names=["VA Nuclear"],
                min_weeks=1,
                max_weeks=2,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Nuclear total",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Nuclear", "VA Nuclear"],
                min_weeks=4,
                max_weeks=7,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Yale Echo",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Echo"],
                min_weeks=3,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 VA Echo",
                applicable_years=[TrainingYear.F1],
                block_names=["VA Echo"],
                min_weeks=3,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 SRC Echo",
                applicable_years=[TrainingYear.F1],
                block_names=["SRC Echo"],
                min_weeks=1,
                max_weeks=1,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Echo total",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Echo", "VA Echo", "SRC Echo"],
                min_weeks=8,
                max_weeks=9,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Yale Cath",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Cath"],
                min_weeks=3,
                max_weeks=4,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 VA Cath",
                applicable_years=[TrainingYear.F1],
                block_names=["VA Cath"],
                min_weeks=1,
                max_weeks=2,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 SRC Cath",
                applicable_years=[TrainingYear.F1],
                block_names=["SRC Cath"],
                min_weeks=1,
                max_weeks=2,
                is_active=False,
            ),
            WeekCountRule(
                name="F1 Cath total",
                applicable_years=[TrainingYear.F1],
                block_names=["Yale Cath", "VA Cath", "SRC Cath"],
                min_weeks=6,
                max_weeks=7,
                is_active=False,
            ),
        ]
    )
    config.forbidden_transition_rules = [
        ForbiddenTransitionRule(
            name="F1 no consult or PTO directly before Night Float",
            applicable_years=[TrainingYear.F1],
            target_block="Night Float",
            forbidden_previous_blocks=[
                "White Consults",
                "SRC Consults",
                "VA Consults",
                "CCU",
                "PTO",
            ],
            is_active=False,
        )
    ]

    migrated, notice = app_state._normalize_loaded_config(config)

    assert notice is not None
    f1_no_pto = next(rule for rule in migrated.week_count_rules if rule.name == "F1 no PTO before 8/10/26")
    f1_no_research = next(rule for rule in migrated.week_count_rules if rule.name == "F1 no Research before 8/10/26")
    f1_white = next(rule for rule in migrated.week_count_rules if rule.name == "F1 White Consults")
    f1_src = next(rule for rule in migrated.week_count_rules if rule.name == "F1 SRC Consults")
    f1_va = next(rule for rule in migrated.week_count_rules if rule.name == "F1 VA Consults")
    f1_consult_total = next(rule for rule in migrated.week_count_rules if rule.name == "F1 Consult total")
    f1_yn = next(rule for rule in migrated.week_count_rules if rule.name == "F1 Yale Nuclear")
    f1_va_nuclear = next(rule for rule in migrated.week_count_rules if rule.name == "F1 VA Nuclear")
    f1_total = next(rule for rule in migrated.week_count_rules if rule.name == "F1 Nuclear total")
    f1_echo_total = next(rule for rule in migrated.week_count_rules if rule.name == "F1 Echo total")
    f1_cath_total = next(rule for rule in migrated.week_count_rules if rule.name == "F1 Cath total")
    f1_ep = next(rule for rule in migrated.week_count_rules if rule.name == "F1 EP")
    yn_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "Yale Nuclear staffed by F1 or S2")
    ye_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "Yale Echo F1 range")
    ct_mri_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "CT-MRI staffed by S2 or T3")
    peripheral_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "Peripheral vascular optional T3")
    rolling_window = next(
        rule
        for rule in migrated.rolling_window_rules
        if rule.name == "Max 3 PTO or Research weeks in any 4-week period"
    )
    nf_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 Night Float max 2 consecutive weeks"
    )
    pairing_rule = next(
        rule
        for rule in migrated.first_assignment_pairing_rules
        if rule.name == "F1 first Yale Nuclear week needs experienced pairing"
    )
    nf_penalty = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name
        == "Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, CCU, or PTO"
    )
    single_week_bonus = next(
        rule
        for rule in migrated.soft_single_week_block_rules
        if rule.name
        == "Bonus: F1 consecutive non-Night-Float rotation weeks after first 8 weeks"
    )

    assert f1_no_pto.end_week == 3
    assert f1_no_research.end_week == 3
    assert f1_white.min_weeks == 5
    assert f1_white.max_weeks == 6
    assert f1_white.is_active
    assert f1_src.is_active
    assert f1_va.is_active
    assert f1_consult_total.is_active
    assert f1_consult_total.max_weeks == 12
    assert f1_ep.min_weeks == 4
    assert f1_ep.max_weeks == 5
    assert f1_yn.max_weeks == 4
    assert f1_yn.is_active
    assert f1_va_nuclear.max_weeks == 3
    assert f1_va_nuclear.is_active
    assert f1_total.min_weeks == 4
    assert f1_total.is_active
    assert f1_echo_total.min_weeks == 7
    assert f1_echo_total.is_active
    assert f1_cath_total.is_active
    assert yn_coverage.min_fellows == 1
    assert yn_coverage.max_fellows == 2
    assert ye_coverage.max_fellows == 2
    assert ct_mri_coverage.min_fellows == 1
    assert peripheral_coverage.max_fellows == 1
    assert rolling_window.state_names == ["PTO", "Research"]
    assert rolling_window.window_size_weeks == 4
    assert rolling_window.max_weeks_in_window == 3
    assert rolling_window.is_active
    assert nf_consecutive_limit.state_names == ["Night Float"]
    assert nf_consecutive_limit.max_consecutive_weeks == 2
    assert nf_consecutive_limit.is_active
    assert pairing_rule.mentor_years == [TrainingYear.S2]
    assert pairing_rule.experienced_peer_years == [TrainingYear.F1]
    assert not migrated.forbidden_transition_rules
    assert nf_penalty.left_states == [
        "White Consults",
        "SRC Consults",
        "VA Consults",
        "CCU",
        "PTO",
    ]
    assert nf_penalty.right_states == ["Night Float"]
    assert nf_penalty.weight == -40
    assert nf_penalty.is_active
    assert single_week_bonus.excluded_states == ["Night Float"]
    assert single_week_bonus.weight == 1
    assert single_week_bonus.start_week == 8
    assert single_week_bonus.adjacent_to_first_state_exemption is None
    assert single_week_bonus.is_active


def test_current_built_in_defaults_do_not_trigger_upgrade_notice() -> None:
    """Already-current defaults should not report a migration notice."""

    migrated, notice = app_state._normalize_loaded_config(get_default_config())

    assert notice is None
    assert migrated.pto_preference_weight_overrides == get_default_config().pto_preference_weight_overrides


def test_rotation_counts_dataframe_summarizes_visible_fellows() -> None:
    """The master schedule counts table should total rotations per visible fellow."""

    config = make_small_ui_config()
    visible_fellows = [0, 1]
    schedule_df = pd.DataFrame(
        {
            "Week": ["W1", "W2", "W3", "W4"],
            "F1 A": [
                "White Consults",
                "Elective",
                "White Consults",
                "Research",
            ],
            "F1 B": [
                "Elective",
                "White Consults",
                "Research",
                "White Consults",
            ],
        }
    )

    counts_df = _build_rotation_counts_dataframe(config, schedule_df, visible_fellows)
    counts_by_rotation = {
        row["Rotation"]: row for row in counts_df.to_dict("records")
    }

    assert counts_by_rotation["White Consults"]["F1 A"] == 2
    assert counts_by_rotation["White Consults"]["F1 B"] == 2
    assert counts_by_rotation["Research"]["F1 A"] == 1
    assert counts_by_rotation["Research"]["F1 B"] == 1
    assert counts_by_rotation["CCU"]["F1 A"] == 0


def test_rules_tab_week_windows_are_1_based_in_the_ui() -> None:
    """Rules-tab week windows should display 1-based values while storing zero-based."""

    assert _display_week_index(0) == 1
    assert _display_week_index(51) == 52
    assert _display_optional_week_index(None) is None
    assert _display_optional_week_index(7) == 8

    assert _to_zero_based_week_index(1, default=0) == 0
    assert _to_zero_based_week_index(52, default=0) == 51
    assert _to_zero_based_week_index("", default=0) == 0

    assert _to_optional_zero_based_week_index(None) is None
    assert _to_optional_zero_based_week_index(1) == 0
    assert _to_optional_zero_based_week_index(52) == 51
