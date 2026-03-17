"""Tests for legacy and cohort-aware scheduling behavior."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_default_config
from src.models import (
    BlockConfig,
    BlockType,
    CohortLimitRule,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    ScheduleConfig,
    ScheduleResult,
    SoftSequenceRule,
    SolverStatus,
    TrainingYear,
    WeekCountRule,
)
from src.scheduler import check_feasibility, solve_schedule


@pytest.fixture
def legacy_small_config() -> ScheduleConfig:
    """A compact legacy-style config used to preserve old solver behavior."""

    blocks = [
        BlockConfig(
            name="Block A",
            block_type=BlockType.DAY,
            fellows_needed=1,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=True,
        ),
        BlockConfig(
            name="Block B",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Block C",
            block_type=BlockType.DAY,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=10,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
        BlockConfig(
            name="Night Float",
            block_type=BlockType.NIGHT,
            fellows_needed=0,
            hours_per_week=50.0,
            min_weeks=1,
            max_weeks=6,
            is_active=True,
            has_weekend_off=True,
            requires_call_coverage=False,
        ),
    ]
    fellows = [
        FellowConfig(name=f"Fellow {idx + 1}", pto_rankings=[4, 8, 12])
        for idx in range(4)
    ]
    return ScheduleConfig(
        num_fellows=4,
        num_weeks=16,
        start_date=date(2026, 7, 1),
        pto_weeks_granted=1,
        pto_weeks_to_rank=3,
        pto_blackout_weeks=[0],
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=30.0,
        blocks=blocks,
        fellows=fellows,
    )


@pytest.fixture
def legacy_solved_result(legacy_small_config: ScheduleConfig) -> ScheduleResult:
    """Solve the legacy fixture once per test."""

    result = solve_schedule(legacy_small_config)
    assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    return result


@pytest.fixture
def structured_config() -> ScheduleConfig:
    """A compact cohort-aware config exercising structured rule behavior."""

    blocks = [
        BlockConfig(name="White Consults", hours_per_week=55.0),
        BlockConfig(name="CCU", hours_per_week=60.0, requires_call_coverage=True),
        BlockConfig(
            name="Night Float",
            block_type=BlockType.NIGHT,
            hours_per_week=60.0,
        ),
        BlockConfig(name="Yale Cath", hours_per_week=50.0),
        BlockConfig(name="Research", hours_per_week=40.0),
    ]
    fellows = [
        FellowConfig("PGY1 A", training_year=TrainingYear.PGY1, pto_rankings=[6]),
        FellowConfig("PGY1 B", training_year=TrainingYear.PGY1, pto_rankings=[7]),
        FellowConfig("PGY1 C", training_year=TrainingYear.PGY1, pto_rankings=[5]),
        FellowConfig("PGY1 D", training_year=TrainingYear.PGY1, pto_rankings=[4]),
        FellowConfig("PGY2 A", training_year=TrainingYear.PGY2, pto_rankings=[6]),
        FellowConfig("PGY2 B", training_year=TrainingYear.PGY2, pto_rankings=[7]),
        FellowConfig("PGY3 A", training_year=TrainingYear.PGY3, pto_rankings=[5]),
    ]
    return ScheduleConfig(
        num_fellows=len(fellows),
        num_weeks=8,
        start_date=date(2026, 7, 13),
        pto_weeks_granted=1,
        pto_weeks_to_rank=1,
        pto_blackout_weeks=[],
        max_concurrent_pto=1,
        max_consecutive_night_float=2,
        call_day="saturday",
        call_hours=24.0,
        call_excluded_blocks=["Night Float", "PTO"],
        hours_cap=80.0,
        trailing_avg_weeks=4,
        solver_timeout_seconds=15.0,
        blocks=blocks,
        fellows=fellows,
        coverage_rules=[
            CoverageRule(
                name="White each week",
                block_name="White Consults",
                eligible_years=[TrainingYear.PGY1],
                min_fellows=1,
                max_fellows=1,
            ),
            CoverageRule(
                name="CCU early",
                block_name="CCU",
                eligible_years=[TrainingYear.PGY2],
                min_fellows=1,
                max_fellows=1,
                start_week=0,
                end_week=1,
            ),
            CoverageRule(
                name="CCU later",
                block_name="CCU",
                eligible_years=[TrainingYear.PGY1],
                min_fellows=1,
                max_fellows=1,
                start_week=2,
                end_week=7,
            ),
            CoverageRule(
                name="NF early",
                block_name="Night Float",
                eligible_years=[TrainingYear.PGY2],
                min_fellows=1,
                max_fellows=1,
                start_week=0,
                end_week=1,
            ),
            CoverageRule(
                name="NF later",
                block_name="Night Float",
                eligible_years=[TrainingYear.PGY1],
                min_fellows=1,
                max_fellows=1,
                start_week=2,
                end_week=7,
            ),
        ],
        eligibility_rules=[
            EligibilityRule(
                name="White PGY1 only",
                block_names=["White Consults"],
                allowed_years=[TrainingYear.PGY1],
            ),
            EligibilityRule(
                name="CCU early PGY2 only",
                block_names=["CCU"],
                allowed_years=[TrainingYear.PGY2],
                start_week=0,
                end_week=1,
            ),
            EligibilityRule(
                name="CCU later PGY1 only",
                block_names=["CCU"],
                allowed_years=[TrainingYear.PGY1],
                start_week=2,
                end_week=7,
            ),
            EligibilityRule(
                name="NF early PGY2 only",
                block_names=["Night Float"],
                allowed_years=[TrainingYear.PGY2],
                start_week=0,
                end_week=1,
            ),
            EligibilityRule(
                name="NF later PGY1 only",
                block_names=["Night Float"],
                allowed_years=[TrainingYear.PGY1],
                start_week=2,
                end_week=7,
            ),
            EligibilityRule(
                name="Cath any year",
                block_names=["Yale Cath", "Research"],
                allowed_years=[TrainingYear.PGY1, TrainingYear.PGY2, TrainingYear.PGY3],
            ),
        ],
        week_count_rules=[
            WeekCountRule(
                name="PGY1 no PTO first two weeks",
                applicable_years=[TrainingYear.PGY1],
                block_names=["PTO"],
                min_weeks=0,
                max_weeks=0,
                start_week=0,
                end_week=1,
            )
        ],
        cohort_limit_rules=[
            CohortLimitRule(
                name="PGY1 PTO max 1",
                applicable_years=[TrainingYear.PGY1],
                state_name="PTO",
                max_fellows=1,
            ),
            CohortLimitRule(
                name="PGY2 PTO max 1",
                applicable_years=[TrainingYear.PGY2],
                state_name="PTO",
                max_fellows=1,
            ),
            CohortLimitRule(
                name="PGY3 PTO max 1",
                applicable_years=[TrainingYear.PGY3],
                state_name="PTO",
                max_fellows=1,
            ),
        ],
    )


@pytest.fixture
def structured_result(structured_config: ScheduleConfig) -> ScheduleResult:
    """Solve the structured fixture once per test."""

    result = solve_schedule(structured_config)
    assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    return result


class TestLegacyFeasibilityCheck:
    """Legacy feasibility checks should remain intact."""

    def test_valid_config_no_staffing_issues(
        self,
        legacy_small_config: ScheduleConfig,
    ) -> None:
        issues = check_feasibility(legacy_small_config)
        critical = [issue for issue in issues if "Staffing conflict" in issue]
        assert len(critical) == 0

    def test_overstaffed_config_flagged(
        self,
        legacy_small_config: ScheduleConfig,
    ) -> None:
        for block in legacy_small_config.blocks:
            block.fellows_needed = 2
        issues = check_feasibility(legacy_small_config)
        assert any("Staffing conflict" in issue for issue in issues)


class TestLegacyConstraints:
    """The legacy scheduling path should still satisfy its classic rules."""

    def test_one_assignment_per_week(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for fellow_idx in range(legacy_small_config.num_fellows):
            for week in range(legacy_small_config.num_weeks):
                assignment = legacy_solved_result.assignments[fellow_idx][week]
                assert assignment not in {"", "UNASSIGNED"}

    def test_pto_count(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for fellow_idx in range(legacy_small_config.num_fellows):
            assert (
                legacy_solved_result.assignments[fellow_idx].count("PTO")
                == legacy_small_config.pto_weeks_granted
            )

    def test_no_consecutive_same_block_except_night_float(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for fellow_idx in range(legacy_small_config.num_fellows):
            for week in range(legacy_small_config.num_weeks - 1):
                current_block = legacy_solved_result.assignments[fellow_idx][week]
                next_block = legacy_solved_result.assignments[fellow_idx][week + 1]
                if current_block not in {"PTO", "Night Float"}:
                    assert current_block != next_block

    def test_night_float_consecutive_limit(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        max_nf = legacy_small_config.max_consecutive_night_float
        for fellow_idx in range(legacy_small_config.num_fellows):
            streak = 0
            for week in range(legacy_small_config.num_weeks):
                if legacy_solved_result.assignments[fellow_idx][week] == "Night Float":
                    streak += 1
                    assert streak <= max_nf
                else:
                    streak = 0

    def test_all_blocks_completed(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        required = {block.name for block in legacy_small_config.blocks if block.is_active}
        for fellow_idx in range(legacy_small_config.num_fellows):
            completed = {
                assignment
                for assignment in legacy_solved_result.assignments[fellow_idx]
                if assignment != "PTO"
            }
            assert not (required - completed)

    def test_pto_blackout(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for fellow_idx in range(legacy_small_config.num_fellows):
            for week in legacy_small_config.pto_blackout_weeks:
                assert legacy_solved_result.assignments[fellow_idx][week] != "PTO"

    def test_max_concurrent_pto(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for week in range(legacy_small_config.num_weeks):
            pto_count = sum(
                1
                for fellow_idx in range(legacy_small_config.num_fellows)
                if legacy_solved_result.assignments[fellow_idx][week] == "PTO"
            )
            assert pto_count <= legacy_small_config.max_concurrent_pto

    def test_trailing_hours_average(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        block_hours = {block.name: block.hours_per_week for block in legacy_small_config.blocks}
        block_hours["PTO"] = 0.0
        window = legacy_small_config.trailing_avg_weeks
        for fellow_idx in range(legacy_small_config.num_fellows):
            for start_week in range(legacy_small_config.num_weeks - window + 1):
                total = 0.0
                for week in range(start_week, start_week + window):
                    block_name = legacy_solved_result.assignments[fellow_idx][week]
                    total += block_hours.get(block_name, 0.0)
                    if legacy_solved_result.call_assignments[fellow_idx][week]:
                        total += legacy_small_config.call_hours
                assert total / window <= legacy_small_config.hours_cap + 0.1

    def test_call_not_on_pto_or_night_float(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for fellow_idx in range(legacy_small_config.num_fellows):
            for week in range(legacy_small_config.num_weeks):
                if legacy_solved_result.call_assignments[fellow_idx][week]:
                    block_name = legacy_solved_result.assignments[fellow_idx][week]
                    assert block_name not in {"PTO", "Night Float"}

    def test_staffing_coverage(
        self,
        legacy_small_config: ScheduleConfig,
        legacy_solved_result: ScheduleResult,
    ) -> None:
        for block in legacy_small_config.blocks:
            if not block.is_active or block.fellows_needed <= 0:
                continue
            for week in range(legacy_small_config.num_weeks):
                count = sum(
                    1
                    for fellow_idx in range(legacy_small_config.num_fellows)
                    if legacy_solved_result.assignments[fellow_idx][week] == block.name
                )
                assert count >= block.fellows_needed


class TestStructuredRules:
    """Structured cohort-aware rules should influence the solve."""

    def test_structured_schedule_solves(
        self,
        structured_result: ScheduleResult,
    ) -> None:
        assert structured_result.solver_status in (
            SolverStatus.OPTIMAL,
            SolverStatus.FEASIBLE,
        )

    def test_year_specific_coverage(
        self,
        structured_config: ScheduleConfig,
        structured_result: ScheduleResult,
    ) -> None:
        fellow_years = {
            fellow_idx: fellow.training_year
            for fellow_idx, fellow in enumerate(structured_config.fellows)
        }
        for week in range(structured_config.num_weeks):
            white_fellows = [
                fellow_idx
                for fellow_idx in range(structured_config.num_fellows)
                if structured_result.assignments[fellow_idx][week] == "White Consults"
            ]
            assert len(white_fellows) == 1
            assert all(
                fellow_years[fellow_idx] == TrainingYear.PGY1
                for fellow_idx in white_fellows
            )

            ccu_expected_year = TrainingYear.PGY2 if week < 2 else TrainingYear.PGY1
            nf_expected_year = TrainingYear.PGY2 if week < 2 else TrainingYear.PGY1
            ccu_fellows = [
                fellow_idx
                for fellow_idx in range(structured_config.num_fellows)
                if structured_result.assignments[fellow_idx][week] == "CCU"
            ]
            nf_fellows = [
                fellow_idx
                for fellow_idx in range(structured_config.num_fellows)
                if structured_result.assignments[fellow_idx][week] == "Night Float"
            ]
            assert len(ccu_fellows) == 1
            assert len(nf_fellows) == 1
            assert fellow_years[ccu_fellows[0]] == ccu_expected_year
            assert fellow_years[nf_fellows[0]] == nf_expected_year

    def test_cohort_pto_cap_and_blackout(
        self,
        structured_config: ScheduleConfig,
        structured_result: ScheduleResult,
    ) -> None:
        pgy1_indices = [
            idx
            for idx, fellow in enumerate(structured_config.fellows)
            if fellow.training_year == TrainingYear.PGY1
        ]
        for week in range(structured_config.num_weeks):
            pgy1_pto = sum(
                1
                for idx in pgy1_indices
                if structured_result.assignments[idx][week] == "PTO"
            )
            assert pgy1_pto <= 1
        for idx in pgy1_indices:
            assert structured_result.assignments[idx][0] != "PTO"
            assert structured_result.assignments[idx][1] != "PTO"

    def test_wrong_years_never_land_on_restricted_blocks(
        self,
        structured_config: ScheduleConfig,
        structured_result: ScheduleResult,
    ) -> None:
        for fellow_idx, fellow in enumerate(structured_config.fellows):
            assignments = structured_result.assignments[fellow_idx]
            if fellow.training_year != TrainingYear.PGY1:
                assert "White Consults" not in assignments
            if fellow.training_year != TrainingYear.PGY2:
                assert assignments[0] != "CCU"
                assert assignments[1] != "CCU"
                assert assignments[0] != "Night Float"
                assert assignments[1] != "Night Float"
            if fellow.training_year != TrainingYear.PGY1:
                for week in range(2, structured_config.num_weeks):
                    assert assignments[week] != "CCU"
                    assert assignments[week] != "Night Float"

    def test_soft_rule_bonus_shapes_solution(self) -> None:
        """A positive-weight soft rule should create the rewarded adjacency."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=1,
            pto_weeks_to_rank=1,
            pto_blackout_weeks=[],
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=3,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.PGY1,
                    pto_rankings=[2],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.PGY1],
                )
            ],
            soft_sequence_rules=[
                SoftSequenceRule(
                    name="Reward Research before PTO",
                    applicable_years=[TrainingYear.PGY1],
                    left_states=["Research"],
                    right_states=["PTO"],
                    weight=25,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assignments = result.assignments[0]
        has_bonus_pair = any(
            assignments[week] == "Research" and assignments[week + 1] == "PTO"
            for week in range(config.num_weeks - 1)
        )
        assert has_bonus_pair
        assert result.objective_value >= 25

    def test_cohort_pto_preference_weights_shape_solution(self) -> None:
        """Cohort PTO weights should override the default linear rank preference."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=1,
            pto_weeks_to_rank=2,
            pto_blackout_weeks=[],
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=3,
            solver_timeout_seconds=10.0,
            pto_preference_weight_overrides={
                TrainingYear.PGY1.value: [1, 100],
            },
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.PGY1,
                    pto_rankings=[0, 1],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.PGY1],
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assignments = result.assignments[0]
        assert assignments[1] == "PTO"
        assert result.objective_value >= 100

    def test_result_includes_objective_breakdown_by_category_and_cohort(self) -> None:
        """Solved schedules should persist a per-category, per-cohort score table."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=1,
            pto_weeks_to_rank=1,
            pto_blackout_weeks=[],
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=3,
            solver_timeout_seconds=10.0,
            pto_preference_weight_overrides={
                TrainingYear.PGY1.value: [10],
            },
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.PGY1,
                    pto_rankings=[2],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.PGY1],
                )
            ],
            soft_sequence_rules=[
                SoftSequenceRule(
                    name="Reward Research before PTO",
                    applicable_years=[TrainingYear.PGY1],
                    left_states=["Research"],
                    right_states=["PTO"],
                    weight=7,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        breakdown = {
            str(row["Category"]): row for row in result.objective_breakdown
        }
        assert breakdown["PTO Preferences"]["PGY1"] == 10
        assert breakdown["PTO Preferences"]["PGY2"] == 0
        assert breakdown["PTO Preferences"]["PGY3"] == 0
        assert breakdown["PTO Preferences"]["Total"] == 10
        assert breakdown["Reward Research before PTO"]["PGY1"] == 7
        assert breakdown["Reward Research before PTO"]["Total"] == 7
        assert breakdown["Total"]["PGY1"] == 17
        assert breakdown["Total"]["Total"] == 17
        assert result.objective_value >= 17


class TestSourceBackedDefaults:
    """The shipped defaults should reflect scheduling_rules.txt."""

    def test_default_config_uses_source_cohort_counts_and_rules(self) -> None:
        config = get_default_config()
        expected_pto_weights = [120, 80, 12, 4, 1, 0]

        assert config.start_date == date(2026, 7, 13)
        assert config.cohort_counts[TrainingYear.PGY1] == 9
        assert config.cohort_counts[TrainingYear.PGY2] == 9
        assert config.cohort_counts[TrainingYear.PGY3] == 7
        assert config.max_concurrent_pto == 12
        assert (
            config.pto_preference_weights_for_year(TrainingYear.PGY1)
            == expected_pto_weights
        )
        assert (
            config.pto_preference_weights_for_year(TrainingYear.PGY2)
            == expected_pto_weights
        )
        assert (
            config.pto_preference_weights_for_year(TrainingYear.PGY3)
            == expected_pto_weights
        )

        coverage_rule_names = {rule.name for rule in config.coverage_rules}
        assert "White Consults staffed by PGY1" in coverage_rule_names
        assert "Goodyer staffed by PGY2" in coverage_rule_names
        assert "Yale Nuclear optional PGY1 slot" in coverage_rule_names
        assert "Yale Nuclear PGY2 slot" in coverage_rule_names

        week_rules = {rule.name: rule for rule in config.week_count_rules}
        assert "PGY1 no PTO in first two months" in week_rules
        assert "PGY1 White Consults" in week_rules
        assert "PGY1 Research" in week_rules
        assert week_rules["PGY1 White Consults"].min_weeks == 4
        assert week_rules["PGY1 White Consults"].max_weeks == 6
        assert week_rules["PGY1 White Consults"].is_active
        assert week_rules["PGY1 SRC Consults"].is_active
        assert week_rules["PGY1 VA Consults"].is_active
        assert week_rules["PGY1 Consult total"].max_weeks == 12
        assert week_rules["PGY1 Consult total"].is_active
        assert week_rules["PGY1 Yale Nuclear"].min_weeks == 2
        assert week_rules["PGY1 Yale Nuclear"].max_weeks == 6
        assert week_rules["PGY1 Yale Nuclear"].is_active
        assert week_rules["PGY1 VA Nuclear"].min_weeks == 1
        assert week_rules["PGY1 VA Nuclear"].max_weeks == 2
        assert week_rules["PGY1 VA Nuclear"].is_active
        assert week_rules["PGY1 Nuclear total"].min_weeks == 4
        assert week_rules["PGY1 Nuclear total"].max_weeks == 7
        assert week_rules["PGY1 Nuclear total"].is_active
        assert week_rules["PGY1 Yale Echo"].is_active
        assert week_rules["PGY1 Echo total"].is_active
        assert week_rules["PGY1 Yale Cath"].is_active
        assert week_rules["PGY1 Cath total"].is_active

        assert any(
            rule.name == "PGY1 before Night Float needs core exposure"
            and rule.is_active
            for rule in config.prerequisite_rules
        )
        assert any(
            rule.name == "PGY1 no consult or PTO directly before Night Float"
            for rule in config.forbidden_transition_rules
        )
        assert any(
            rule.name == "Bonus: PGY1 CHF immediately before Night Float"
            and rule.weight == 30
            for rule in config.soft_sequence_rules
        )

    def test_default_config_feasibility_has_no_staffing_conflict(self) -> None:
        config = get_default_config()

        issues = check_feasibility(config)

        assert not any("Staffing conflict" in issue for issue in issues)

    def test_default_config_with_all_pgy1_rules_solves_without_pto(self) -> None:
        config = get_default_config()
        config.pto_weeks_granted = 0
        config.pto_weeks_to_rank = 0
        for fellow in config.fellows:
            fellow.pto_rankings = []
        config.solver_timeout_seconds = 10.0

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
