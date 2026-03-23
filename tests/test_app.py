"""UI smoke tests for the Streamlit dashboard."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.state as app_state
from app.components.master_schedule import (
    _build_call_counts_dataframe,
    _build_rotation_counts_dataframe,
    _build_rotation_schedule_dataframe,
    _build_srcva_call_counts_dataframe,
    _build_srcva_call_calendar_dataframe,
    _build_fellow_color_map,
    _style_fellow_assignment_cell,
)
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
    ScheduleResult,
    ScheduleConfig,
    SolverStatus,
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
    assert any(markdown.value == "#### SRC/VA Call Rules" for markdown in at.markdown)

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
    assert migrated.cohort_counts[TrainingYear.T3] == 9


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
    s2_goodyer = next(rule for rule in migrated.week_count_rules if rule.name == "S2 Goodyer Consults")
    s2_ccu = next(rule for rule in migrated.week_count_rules if rule.name == "S2 CCU")
    s2_night_float = next(rule for rule in migrated.week_count_rules if rule.name == "S2 Night Float")
    s2_chf = next(rule for rule in migrated.week_count_rules if rule.name == "S2 CHF")
    s2_consult_total = next(rule for rule in migrated.week_count_rules if rule.name == "S2 Consult total")
    s2_src_cath = next(rule for rule in migrated.week_count_rules if rule.name == "S2 SRC Cath")
    s2_va_cath = next(rule for rule in migrated.week_count_rules if rule.name == "S2 VA Cath")
    s2_cath_total = next(rule for rule in migrated.week_count_rules if rule.name == "S2 Cath total")
    s2_research = next(rule for rule in migrated.week_count_rules if rule.name == "S2 Research")
    s2_ct_mri = next(rule for rule in migrated.week_count_rules if rule.name == "S2 CT-MRI")
    t3_consult_total = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Consult total")
    t3_nuclear_total = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Nuclear total")
    t3_echo_total = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Echo total")
    t3_ct_mri = next(rule for rule in migrated.week_count_rules if rule.name == "T3 CT-MRI")
    t3_elective = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Elective")
    t3_peripheral = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Peripheral vascular")
    t3_congenital = next(rule for rule in migrated.week_count_rules if rule.name == "T3 Congenital")
    t3_late_spring = next(rule for rule in migrated.week_count_rules if rule.name == "T3 late spring elective/research/PTO only")
    chf_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "CHF staffed by F1 or S2")
    yn_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "Yale Nuclear staffed by F1, S2, or T3")
    va_nuclear_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "VA Nuclear staffed by F1, S2, or T3")
    yale_cath_coverage = next(rule for rule in migrated.coverage_rules if rule.name == "Yale Cath range")
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
    white_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 White Consults max 2 consecutive weeks"
    )
    f1_src_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 SRC Consults max 2 consecutive weeks"
    )
    f1_va_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 VA Consults max 2 consecutive weeks"
    )
    ccu_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 CCU max 2 consecutive weeks"
    )
    f1_ep_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 EP max 2 consecutive weeks"
    )
    f1_goodyer_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "F1 Goodyer Consults max 2 consecutive weeks"
    )
    s2_nf_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 Night Float max 2 consecutive weeks"
    )
    s2_goodyer_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 Goodyer Consults max 2 consecutive weeks"
    )
    s2_ep_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 EP max 2 consecutive weeks"
    )
    s2_white_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 White Consults max 2 consecutive weeks"
    )
    s2_src_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 SRC Consults max 2 consecutive weeks"
    )
    s2_va_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 VA Consults max 2 consecutive weeks"
    )
    s2_ccu_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 CCU max 2 consecutive weeks"
    )
    s2_research_consecutive_limit = next(
        rule
        for rule in migrated.consecutive_state_limit_rules
        if rule.name == "S2 Research max 2 consecutive weeks"
    )
    first_nf_run_limit = next(
        rule
        for rule in migrated.first_assignment_run_limit_rules
        if rule.name == "F1 first Night Float run max 1 week"
    )
    s2_ct_mri_contiguous = next(
        rule
        for rule in migrated.contiguous_block_rules
        if rule.name == "S2 CT-MRI must be one contiguous run"
    )
    t3_ct_mri_contiguous = next(
        rule
        for rule in migrated.contiguous_block_rules
        if rule.name == "T3 CT-MRI must be one contiguous run"
    )
    pairing_rule = next(
        rule
        for rule in migrated.first_assignment_pairing_rules
        if rule.name == "F1 first Yale Nuclear week needs experienced pairing"
    )
    prerequisite_rule = next(
        rule
        for rule in migrated.prerequisite_rules
        if rule.name == "F1 before Night Float needs core exposure"
    )
    ccu_transition = next(
        rule
        for rule in migrated.forbidden_transition_rules
        if rule.name == "F1/S2 Night Float cannot follow CCU"
    )
    nf_penalty = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name
        == "Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, or PTO"
    )
    nf_followup_bonus = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name == "Bonus: F1 Night Float followed by Research or PTO"
    )
    s2_research_pto_bonus = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name == "Bonus: S2 Research adjacent to PTO"
    )
    s2_pto_block_bonus = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name == "Bonus: S2 two-week PTO block"
    )
    t3_pto_block_bonus = next(
        rule
        for rule in migrated.soft_sequence_rules
        if rule.name == "Bonus: T3 two-week PTO block"
    )
    s2_final_week_bonus = next(
        rule
        for rule in migrated.soft_state_assignment_rules
        if rule.name == "Bonus: S2 Research during final week"
    )
    s2_src_echo_bonus = next(
        rule
        for rule in migrated.soft_state_assignment_rules
        if rule.name == "Bonus: S2 assignment to SRC Echo"
    )
    s2_ccu_balance = next(
        rule
        for rule in migrated.soft_cohort_balance_rules
        if rule.name == "Penalty: S2 uneven CCU distribution"
    )
    single_week_bonus = next(
        rule
        for rule in migrated.soft_single_week_block_rules
        if rule.name
        == "Bonus: F1 consecutive non-Night-Float rotation weeks after first 8 weeks"
    )
    s2_single_week_bonus = next(
        rule
        for rule in migrated.soft_single_week_block_rules
        if rule.name
        == "Bonus: S2 two-week Goodyer, consult, EP, CHF, Yale Nuclear, Yale Echo, and Yale Cath runs"
    )

    assert f1_no_pto.end_week == 3
    assert f1_no_research.end_week == 3
    assert f1_white.min_weeks == 5
    assert f1_white.max_weeks == 6
    assert f1_white.is_active
    assert f1_src.min_weeks == 2
    assert f1_src.max_weeks == 4
    assert f1_src.is_active
    assert f1_va.is_active
    assert f1_consult_total.is_active
    assert f1_consult_total.max_weeks == 12
    assert f1_ep.min_weeks == 4
    assert f1_ep.max_weeks == 5
    assert s2_goodyer.min_weeks == 5
    assert s2_goodyer.max_weeks == 6
    assert s2_ccu.end_week == 2
    assert s2_night_float.max_weeks == 1
    assert s2_night_float.end_week == 5
    assert s2_chf.min_weeks == 1
    assert s2_chf.max_weeks == 4
    assert s2_consult_total.block_names == ["SRC Consults", "VA Consults"]
    assert s2_consult_total.min_weeks == 3
    assert s2_consult_total.max_weeks == 4
    assert s2_src_cath.min_weeks == 0
    assert s2_src_cath.max_weeks == 4
    assert s2_va_cath.max_weeks == 5
    assert s2_cath_total.min_weeks == 6
    assert s2_cath_total.max_weeks == 8
    assert s2_research.min_weeks == 6
    assert s2_research.max_weeks == 6
    assert s2_ct_mri.min_weeks == 2
    assert s2_ct_mri.max_weeks == 2
    assert t3_consult_total.block_names == ["SRC Consults", "VA Consults"]
    assert t3_consult_total.min_weeks == 3
    assert t3_consult_total.max_weeks == 4
    assert t3_nuclear_total.min_weeks == 4
    assert t3_nuclear_total.max_weeks == 5
    assert t3_echo_total.block_names == ["Yale Echo", "SRC Echo"]
    assert t3_echo_total.min_weeks == 4
    assert t3_echo_total.max_weeks == 10
    assert t3_ct_mri.min_weeks == 2
    assert t3_ct_mri.max_weeks == 2
    assert t3_elective.min_weeks == 24
    assert t3_elective.max_weeks == 30
    assert t3_peripheral.min_weeks == 2
    assert t3_peripheral.max_weeks == 2
    assert t3_congenital.min_weeks == 2
    assert t3_congenital.max_weeks == 2
    assert t3_late_spring.block_names == ["PTO", "Research", "Elective"]
    assert t3_late_spring.start_week == 46
    assert t3_late_spring.end_week == 51
    assert f1_yn.max_weeks == 4
    assert f1_yn.is_active
    assert f1_va_nuclear.max_weeks == 3
    assert f1_va_nuclear.is_active
    assert f1_total.min_weeks == 4
    assert f1_total.is_active
    assert f1_echo_total.min_weeks == 7
    assert f1_echo_total.is_active
    assert f1_cath_total.is_active
    assert chf_coverage.min_fellows == 0
    assert chf_coverage.max_fellows == 1
    assert yn_coverage.min_fellows == 1
    assert yn_coverage.max_fellows == 2
    assert va_nuclear_coverage.min_fellows == 1
    assert va_nuclear_coverage.max_fellows == 1
    assert yale_cath_coverage.min_fellows == 0
    assert yale_cath_coverage.max_fellows == 2
    assert ye_coverage.max_fellows == 2
    assert ct_mri_coverage.min_fellows == 0
    assert ct_mri_coverage.max_fellows == 1
    assert peripheral_coverage.max_fellows == 1
    assert rolling_window.state_names == ["PTO", "Research"]
    assert rolling_window.window_size_weeks == 4
    assert rolling_window.max_weeks_in_window == 3
    assert rolling_window.is_active
    assert nf_consecutive_limit.state_names == ["Night Float"]
    assert nf_consecutive_limit.max_consecutive_weeks == 2
    assert nf_consecutive_limit.is_active
    assert white_consecutive_limit.state_names == ["White Consults"]
    assert white_consecutive_limit.max_consecutive_weeks == 2
    assert white_consecutive_limit.is_active
    assert f1_src_consecutive_limit.state_names == ["SRC Consults"]
    assert f1_src_consecutive_limit.max_consecutive_weeks == 2
    assert f1_src_consecutive_limit.is_active
    assert f1_va_consecutive_limit.state_names == ["VA Consults"]
    assert f1_va_consecutive_limit.max_consecutive_weeks == 2
    assert f1_va_consecutive_limit.is_active
    assert ccu_consecutive_limit.state_names == ["CCU"]
    assert ccu_consecutive_limit.max_consecutive_weeks == 2
    assert ccu_consecutive_limit.is_active
    assert f1_ep_consecutive_limit.state_names == ["EP"]
    assert f1_ep_consecutive_limit.max_consecutive_weeks == 2
    assert f1_ep_consecutive_limit.is_active
    assert f1_goodyer_consecutive_limit.state_names == ["Goodyer Consults"]
    assert f1_goodyer_consecutive_limit.max_consecutive_weeks == 2
    assert f1_goodyer_consecutive_limit.is_active
    assert s2_nf_consecutive_limit.state_names == ["Night Float"]
    assert s2_nf_consecutive_limit.max_consecutive_weeks == 2
    assert s2_nf_consecutive_limit.is_active
    assert s2_goodyer_consecutive_limit.state_names == ["Goodyer Consults"]
    assert s2_goodyer_consecutive_limit.max_consecutive_weeks == 2
    assert s2_goodyer_consecutive_limit.is_active
    assert s2_ep_consecutive_limit.state_names == ["EP"]
    assert s2_ep_consecutive_limit.max_consecutive_weeks == 2
    assert s2_ep_consecutive_limit.is_active
    assert s2_white_consecutive_limit.state_names == ["White Consults"]
    assert s2_white_consecutive_limit.max_consecutive_weeks == 2
    assert s2_white_consecutive_limit.is_active
    assert s2_src_consecutive_limit.state_names == ["SRC Consults"]
    assert s2_src_consecutive_limit.max_consecutive_weeks == 2
    assert s2_src_consecutive_limit.is_active
    assert s2_va_consecutive_limit.state_names == ["VA Consults"]
    assert s2_va_consecutive_limit.max_consecutive_weeks == 2
    assert s2_va_consecutive_limit.is_active
    assert s2_ccu_consecutive_limit.state_names == ["CCU"]
    assert s2_ccu_consecutive_limit.max_consecutive_weeks == 2
    assert s2_ccu_consecutive_limit.is_active
    assert s2_research_consecutive_limit.state_names == ["Research"]
    assert s2_research_consecutive_limit.max_consecutive_weeks == 2
    assert s2_research_consecutive_limit.is_active
    assert first_nf_run_limit.block_name == "Night Float"
    assert first_nf_run_limit.max_run_length_weeks == 1
    assert first_nf_run_limit.is_active
    assert s2_ct_mri_contiguous.block_name == "CT-MRI"
    assert s2_ct_mri_contiguous.applicable_years == [TrainingYear.S2]
    assert s2_ct_mri_contiguous.is_active
    assert t3_ct_mri_contiguous.block_name == "CT-MRI"
    assert t3_ct_mri_contiguous.applicable_years == [TrainingYear.T3]
    assert t3_ct_mri_contiguous.is_active
    assert prerequisite_rule.prerequisite_blocks == [
        "Yale Echo",
        "White Consults",
        "CCU",
        "EP",
        "CHF",
    ]
    assert prerequisite_rule.prerequisite_block_groups == [["Yale Cath", "SRC Cath"]]
    assert pairing_rule.mentor_years == [TrainingYear.S2]
    assert pairing_rule.experienced_peer_years == [TrainingYear.F1]
    assert ccu_transition.applicable_years == [TrainingYear.F1, TrainingYear.S2]
    assert ccu_transition.target_block == "Night Float"
    assert ccu_transition.forbidden_previous_blocks == ["CCU"]
    assert ccu_transition.is_active
    assert nf_penalty.left_states == [
        "White Consults",
        "SRC Consults",
        "VA Consults",
        "PTO",
    ]
    assert nf_penalty.right_states == ["Night Float"]
    assert nf_penalty.weight == -40
    assert nf_penalty.is_active
    assert nf_followup_bonus.left_states == ["Night Float"]
    assert nf_followup_bonus.right_states == ["Research", "PTO"]
    assert nf_followup_bonus.weight == 5
    assert nf_followup_bonus.is_active
    assert s2_research_pto_bonus.left_states == ["Research"]
    assert s2_research_pto_bonus.right_states == ["PTO"]
    assert s2_research_pto_bonus.weight == 10
    assert s2_research_pto_bonus.is_active
    assert s2_pto_block_bonus.left_states == ["PTO"]
    assert s2_pto_block_bonus.right_states == ["PTO"]
    assert s2_pto_block_bonus.weight == 8
    assert t3_pto_block_bonus.left_states == ["PTO"]
    assert t3_pto_block_bonus.right_states == ["PTO"]
    assert t3_pto_block_bonus.weight == 8
    assert s2_final_week_bonus.state_names == ["Research"]
    assert s2_final_week_bonus.start_week == 51
    assert s2_final_week_bonus.end_week == 51
    assert s2_final_week_bonus.weight == 6
    assert s2_src_echo_bonus.state_names == ["SRC Echo"]
    assert s2_src_echo_bonus.weight == 3
    assert s2_ccu_balance.state_names == ["CCU"]
    assert s2_ccu_balance.weight == 4
    assert single_week_bonus.excluded_states == ["Night Float"]
    assert single_week_bonus.included_states == []
    assert single_week_bonus.weight == 1
    assert single_week_bonus.start_week == 8
    assert single_week_bonus.adjacent_to_first_state_exemption is None
    assert single_week_bonus.is_active
    assert s2_single_week_bonus.included_states == [
        "Goodyer Consults",
        "VA Consults",
        "SRC Consults",
        "EP",
        "CHF",
        "Yale Nuclear",
        "Yale Echo",
        "Yale Cath",
    ]
    assert s2_single_week_bonus.excluded_states == []
    assert s2_single_week_bonus.weight == 1
    assert s2_single_week_bonus.start_week == 0
    assert s2_single_week_bonus.adjacent_to_first_state_exemption is None
    assert s2_single_week_bonus.is_active


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


def test_call_counts_dataframe_summarizes_visible_fellows() -> None:
    """The 24-hour call counts table should total call assignments per visible fellow."""

    config = make_small_ui_config()
    visible_fellows = [0, 1, 2]
    result = ScheduleResult(
        assignments=[["Research"] * 4 for _ in range(5)],
        call_assignments=[
            [True, False, True, False],
            [False, True, False, False],
            [False, False, True, True],
            [False, False, False, False],
            [False, False, False, False],
        ],
        solver_status=SolverStatus.FEASIBLE,
    )

    counts_df = _build_call_counts_dataframe(config, result, visible_fellows)

    assert counts_df.loc[0, "Call Type"] == "24-Hr Call"
    assert counts_df.loc[0, "F1 A"] == 2
    assert counts_df.loc[0, "F1 B"] == 1
    assert counts_df.loc[0, "S2 A"] == 2


def test_rotation_schedule_dataframe_groups_names_by_rotation() -> None:
    """The alternate schedule grid should pivot fellows into rotation columns."""

    config = make_small_ui_config()
    visible_fellows = [0, 1, 2]
    result = ScheduleResult(
        assignments=[
            ["White Consults", "Research", "PTO", "CCU"],
            ["White Consults", "Elective", "Research", "CCU"],
            ["CCU", "CCU", "White Consults", "Research"],
            ["Research", "Research", "Research", "Research"],
            ["Elective", "Elective", "Elective", "Elective"],
        ],
        call_assignments=[[False] * 4 for _ in range(5)],
        solver_status=SolverStatus.FEASIBLE,
    )

    rotation_df = _build_rotation_schedule_dataframe(config, result, visible_fellows)

    assert rotation_df.loc[0, "White Consults"] == "F1 A, F1 B"
    assert rotation_df.loc[0, "CCU"] == "S2 A"
    assert rotation_df.loc[2, "PTO"] == "F1 A"
    assert rotation_df.loc[3, "CCU"] == "F1 A, F1 B"


def test_rotation_schedule_styling_uses_fellow_colors() -> None:
    """Rotation-view cells should style fellow assignments with fellow colors."""

    config = make_small_ui_config()
    fellow_colors = _build_fellow_color_map(config, [0, 1, 2])

    single_style = _style_fellow_assignment_cell("F1 A", fellow_colors)
    multi_style = _style_fellow_assignment_cell("F1 A, F1 B", fellow_colors)

    assert fellow_colors["F1 A"] in single_style
    assert "linear-gradient" in multi_style
    assert fellow_colors["F1 A"] in multi_style
    assert fellow_colors["F1 B"] in multi_style


def test_srcva_call_calendar_dataframe_shows_weekend_and_weekday_overlays() -> None:
    """The SRC/VA call tile should map overlay call assignments by week and day."""

    config = make_small_ui_config()
    config.srcva_weekend_call_enabled = True
    config.srcva_weekday_call_enabled = True
    config.srcva_weekend_call_eligible_years = [TrainingYear.F1, TrainingYear.S2]
    config.srcva_weekday_call_eligible_years = [TrainingYear.F1, TrainingYear.S2]
    visible_fellows = [0, 1, 2, 3]
    result = ScheduleResult(
        assignments=[
            ["Research", "White Consults", "Research", "Research"],
            ["Research", "Research", "Research", "Research"],
            ["CCU", "CCU", "CCU", "CCU"],
            ["Research", "Research", "Research", "Research"],
            ["Elective", "Elective", "Elective", "Elective"],
        ],
        call_assignments=[[False] * 4 for _ in range(5)],
        srcva_weekend_call_assignments=[
            [False, True, False, False],
            [False, False, False, False],
            [True, False, False, False],
            [False, False, True, False],
            [False, False, False, False],
        ],
        srcva_weekday_call_assignments=[
            [[True, False, False, False], [False, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, True, False, False], [False, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, False, True, False], [True, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, False, False, True], [False, True, False, False], [True, False, False, False], [False, False, False, False]],
            [[False, False, False, False] for _ in range(4)],
        ],
        solver_status=SolverStatus.FEASIBLE,
    )

    srcva_df = _build_srcva_call_calendar_dataframe(config, result, visible_fellows)

    assert srcva_df.loc[0, "Weekend"] == "S2 A"
    assert srcva_df.loc[0, "Mon"] == "F1 A"
    assert srcva_df.loc[0, "Tue"] == "F1 B"
    assert srcva_df.loc[0, "Wed"] == "S2 A"
    assert srcva_df.loc[0, "Thu"] == "S2 B"
    assert srcva_df.loc[1, "Weekend"] == "F1 A"
    assert srcva_df.loc[1, "Mon"] == "S2 A"
    assert srcva_df.loc[1, "Tue"] == "S2 B"


def test_srcva_call_counts_dataframe_summarizes_visible_fellows() -> None:
    """The SRC/VA call counts table should total weekend, weekday, and total calls."""

    config = make_small_ui_config()
    visible_fellows = [0, 1, 2, 3]
    result = ScheduleResult(
        assignments=[["Research"] * 4 for _ in range(5)],
        call_assignments=[[False] * 4 for _ in range(5)],
        srcva_weekend_call_assignments=[
            [False, True, False, False],
            [False, False, False, False],
            [True, False, False, False],
            [False, False, True, False],
            [False, False, False, False],
        ],
        srcva_weekday_call_assignments=[
            [[True, False, False, False], [False, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, True, False, False], [False, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, False, True, False], [True, False, False, False], [False, False, False, False], [False, False, False, False]],
            [[False, False, False, True], [False, True, False, False], [True, False, False, False], [False, False, False, False]],
            [[False, False, False, False] for _ in range(4)],
        ],
        solver_status=SolverStatus.FEASIBLE,
    )

    counts_df = _build_srcva_call_counts_dataframe(config, result, visible_fellows)

    weekend_row = counts_df[counts_df["Call Type"] == "SRC/VA Weekend Call"].iloc[0]
    weekday_row = counts_df[counts_df["Call Type"] == "SRC/VA Weekday Call"].iloc[0]
    total_row = counts_df[counts_df["Call Type"] == "SRC/VA Total Call"].iloc[0]

    assert weekend_row["F1 A"] == 1
    assert weekend_row["F1 B"] == 0
    assert weekend_row["S2 A"] == 1
    assert weekend_row["S2 B"] == 1
    assert weekday_row["F1 A"] == 1
    assert weekday_row["F1 B"] == 1
    assert weekday_row["S2 A"] == 2
    assert weekday_row["S2 B"] == 3
    assert total_row["F1 A"] == 2
    assert total_row["F1 B"] == 1
    assert total_row["S2 A"] == 3
    assert total_row["S2 B"] == 4


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
