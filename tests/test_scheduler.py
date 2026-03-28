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
    ContiguousBlockRule,
    ConsecutiveStateLimitRule,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    FirstAssignmentRunLimitRule,
    FirstAssignmentPairingRule,
    IndividualFellowRequirementRule,
    LinkedFellowStateRule,
    RollingWindowRule,
    ScheduleConfig,
    ScheduleResult,
    SoftCohortBalanceRule,
    SoftFixedWeekPairRule,
    SoftRuleDirection,
    SoftSequenceRule,
    SoftStateAssignmentRule,
    SoftSingleWeekBlockRule,
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
        FellowConfig("F1 A", training_year=TrainingYear.F1, pto_rankings=[6]),
        FellowConfig("F1 B", training_year=TrainingYear.F1, pto_rankings=[7]),
        FellowConfig("F1 C", training_year=TrainingYear.F1, pto_rankings=[5]),
        FellowConfig("F1 D", training_year=TrainingYear.F1, pto_rankings=[4]),
        FellowConfig("S2 A", training_year=TrainingYear.S2, pto_rankings=[6]),
        FellowConfig("S2 B", training_year=TrainingYear.S2, pto_rankings=[7]),
        FellowConfig("T3 A", training_year=TrainingYear.T3, pto_rankings=[5]),
    ]
    return ScheduleConfig(
        num_fellows=len(fellows),
        num_weeks=8,
        start_date=date(2026, 7, 13),
        pto_weeks_granted=1,
        pto_weeks_to_rank=1,
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
                eligible_years=[TrainingYear.F1],
                min_fellows=1,
                max_fellows=1,
            ),
            CoverageRule(
                name="CCU early",
                block_name="CCU",
                eligible_years=[TrainingYear.S2],
                min_fellows=1,
                max_fellows=1,
                start_week=0,
                end_week=1,
            ),
            CoverageRule(
                name="CCU later",
                block_name="CCU",
                eligible_years=[TrainingYear.F1],
                min_fellows=1,
                max_fellows=1,
                start_week=2,
                end_week=7,
            ),
            CoverageRule(
                name="NF early",
                block_name="Night Float",
                eligible_years=[TrainingYear.S2],
                min_fellows=1,
                max_fellows=1,
                start_week=0,
                end_week=1,
            ),
            CoverageRule(
                name="NF later",
                block_name="Night Float",
                eligible_years=[TrainingYear.F1],
                min_fellows=1,
                max_fellows=1,
                start_week=2,
                end_week=7,
            ),
        ],
        eligibility_rules=[
            EligibilityRule(
                name="White F1 only",
                block_names=["White Consults"],
                allowed_years=[TrainingYear.F1],
            ),
            EligibilityRule(
                name="CCU early S2 only",
                block_names=["CCU"],
                allowed_years=[TrainingYear.S2],
                start_week=0,
                end_week=1,
            ),
            EligibilityRule(
                name="CCU later F1 or S2",
                block_names=["CCU"],
                allowed_years=[TrainingYear.F1, TrainingYear.S2],
                start_week=2,
                end_week=7,
            ),
            EligibilityRule(
                name="NF early S2 only",
                block_names=["Night Float"],
                allowed_years=[TrainingYear.S2],
                start_week=0,
                end_week=1,
            ),
            EligibilityRule(
                name="NF later F1 or S2",
                block_names=["Night Float"],
                allowed_years=[TrainingYear.F1, TrainingYear.S2],
                start_week=2,
                end_week=7,
            ),
            EligibilityRule(
                name="Cath any year",
                block_names=["Yale Cath", "Research"],
                allowed_years=[TrainingYear.F1, TrainingYear.S2, TrainingYear.T3],
            ),
        ],
        week_count_rules=[
            WeekCountRule(
                name="F1 no PTO first two weeks",
                applicable_years=[TrainingYear.F1],
                block_names=["PTO"],
                min_weeks=0,
                max_weeks=0,
                start_week=0,
                end_week=1,
            )
        ],
        cohort_limit_rules=[
            CohortLimitRule(
                name="F1 PTO max 1",
                applicable_years=[TrainingYear.F1],
                state_name="PTO",
                max_fellows=1,
            ),
            CohortLimitRule(
                name="S2 PTO max 1",
                applicable_years=[TrainingYear.S2],
                state_name="PTO",
                max_fellows=1,
            ),
            CohortLimitRule(
                name="T3 PTO max 1",
                applicable_years=[TrainingYear.T3],
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
    """The legacy scheduling path should still satisfy its remaining classic rules."""

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

    def test_legacy_solver_allows_consecutive_same_block_when_required(
        self,
    ) -> None:
        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[BlockConfig(name="Research", min_weeks=2, max_weeks=2)],
            fellows=[FellowConfig(name="Legacy Fellow")],
        )

        result = solve_schedule(config)

        assert result.solver_status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.assignments[0] == ["Research", "Research"]

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
                fellow_years[fellow_idx] == TrainingYear.F1
                for fellow_idx in white_fellows
            )

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
            assert ccu_fellows
            assert nf_fellows
            if week < 2:
                assert all(
                    fellow_years[fellow_idx] == TrainingYear.S2
                    for fellow_idx in ccu_fellows
                )
                assert all(
                    fellow_years[fellow_idx] == TrainingYear.S2
                    for fellow_idx in nf_fellows
                )
            else:
                assert any(
                    fellow_years[fellow_idx] == TrainingYear.F1
                    for fellow_idx in ccu_fellows
                )
                assert any(
                    fellow_years[fellow_idx] == TrainingYear.F1
                    for fellow_idx in nf_fellows
                )
                assert all(
                    fellow_years[fellow_idx] in (TrainingYear.F1, TrainingYear.S2)
                    for fellow_idx in ccu_fellows
                )
                assert all(
                    fellow_years[fellow_idx] in (TrainingYear.F1, TrainingYear.S2)
                    for fellow_idx in nf_fellows
                )

    def test_cohort_pto_cap_and_restricted_windows(
        self,
        structured_config: ScheduleConfig,
        structured_result: ScheduleResult,
    ) -> None:
        f1_indices = [
            idx
            for idx, fellow in enumerate(structured_config.fellows)
            if fellow.training_year == TrainingYear.F1
        ]
        for week in range(structured_config.num_weeks):
            f1_pto = sum(
                1
                for idx in f1_indices
                if structured_result.assignments[idx][week] == "PTO"
            )
            assert f1_pto <= 1
        for idx in f1_indices:
            assert structured_result.assignments[idx][0] != "PTO"
            assert structured_result.assignments[idx][1] != "PTO"

    def test_wrong_years_never_land_on_restricted_blocks(
        self,
        structured_config: ScheduleConfig,
        structured_result: ScheduleResult,
    ) -> None:
        for fellow_idx, fellow in enumerate(structured_config.fellows):
            assignments = structured_result.assignments[fellow_idx]
            if fellow.training_year != TrainingYear.F1:
                assert "White Consults" not in assignments
            if fellow.training_year != TrainingYear.S2:
                assert assignments[0] != "CCU"
                assert assignments[1] != "CCU"
                assert assignments[0] != "Night Float"
                assert assignments[1] != "Night Float"
            if fellow.training_year == TrainingYear.T3:
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
                    training_year=TrainingYear.F1,
                    pto_rankings=[2],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            soft_sequence_rules=[
                SoftSequenceRule(
                    name="Reward Research before PTO",
                    applicable_years=[TrainingYear.F1],
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

    def test_night_float_followup_bonus_shapes_solution(self) -> None:
        """A Night Float follow-up bonus should prefer Research immediately after NF."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=2,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="Night Float", block_type=BlockType.NIGHT, hours_per_week=60.0),
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.F1,
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Night Float", "Research", "Elective"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 NF exact 1",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Night Float"],
                    min_weeks=1,
                    max_weeks=1,
                )
            ],
            soft_sequence_rules=[
                SoftSequenceRule(
                    name="Bonus: F1 Night Float followed by Research or PTO",
                    applicable_years=[TrainingYear.F1],
                    left_states=["Night Float"],
                    right_states=["Research", "PTO"],
                    weight=5,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.assignments[0] == ["Night Float", "Research"]
        assert result.objective_value >= 5

    def test_state_assignment_bonus_shapes_solution(self) -> None:
        """A targeted state bonus should prefer the rewarded assignment."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=1,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=1,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="SRC Echo", hours_per_week=40.0),
                BlockConfig(name="Research", hours_per_week=40.0),
            ],
            fellows=[FellowConfig(name="S2 A", training_year=TrainingYear.S2)],
            eligibility_rules=[
                EligibilityRule(
                    name="S2 can do both",
                    block_names=["SRC Echo", "Research"],
                    allowed_years=[TrainingYear.S2],
                )
            ],
            soft_state_assignment_rules=[
                SoftStateAssignmentRule(
                    name="Bonus: S2 assignment to SRC Echo",
                    applicable_years=[TrainingYear.S2],
                    state_names=["SRC Echo"],
                    weight=3,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert result.assignments[0] == ["SRC Echo"]
        assert result.objective_value >= 3

    def test_cohort_balance_penalty_spreads_assignments(self) -> None:
        """A cohort-balance penalty should spread selected states across fellows."""

        config = ScheduleConfig(
            num_fellows=2,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=2,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="CCU", hours_per_week=55.0),
                BlockConfig(name="Research", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(name="S2 A", training_year=TrainingYear.S2),
                FellowConfig(name="S2 B", training_year=TrainingYear.S2),
            ],
            coverage_rules=[
                CoverageRule(
                    name="CCU staffed",
                    block_name="CCU",
                    eligible_years=[TrainingYear.S2],
                    min_fellows=1,
                    max_fellows=1,
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="S2 can do both",
                    block_names=["CCU", "Research"],
                    allowed_years=[TrainingYear.S2],
                )
            ],
            soft_cohort_balance_rules=[
                SoftCohortBalanceRule(
                    name="Penalty: S2 uneven CCU distribution",
                    applicable_years=[TrainingYear.S2],
                    state_names=["CCU"],
                    weight=4,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        ccu_counts = [assignments.count("CCU") for assignments in result.assignments]
        assert ccu_counts == [1, 1]

    def test_cohort_pto_preference_weights_shape_solution(self) -> None:
        """Cohort PTO weights should override the default linear rank preference."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=1,
            pto_weeks_to_rank=2,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=3,
            solver_timeout_seconds=10.0,
            pto_preference_weight_overrides={
                TrainingYear.F1.value: [1, 100],
            },
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.F1,
                    pto_rankings=[0, 1],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.F1],
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
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=3,
            solver_timeout_seconds=10.0,
            pto_preference_weight_overrides={
                TrainingYear.F1.value: [10],
            },
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Solo Fellow",
                    training_year=TrainingYear.F1,
                    pto_rankings=[2],
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Solo can do all blocks",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            soft_sequence_rules=[
                SoftSequenceRule(
                    name="Reward Research before PTO",
                    applicable_years=[TrainingYear.F1],
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
        assert breakdown["PTO Preferences"]["F1"] == 10
        assert breakdown["PTO Preferences"]["S2"] == 0
        assert breakdown["PTO Preferences"]["T3"] == 0
        assert breakdown["PTO Preferences"]["Total"] == 10
        assert breakdown["Reward Research before PTO"]["F1"] == 7
        assert breakdown["Reward Research before PTO"]["Total"] == 7
        assert breakdown["Total"]["F1"] == 17
        assert breakdown["Total"]["Total"] == 17
        assert result.objective_value >= 17

    def test_individual_fellow_requirement_rule_enforces_exact_block_count(self) -> None:
        """A named-fellow hard rule should pin one fellow to an exact rotation count."""

        config = ScheduleConfig(
            num_fellows=2,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(
                    name="Night Float",
                    block_type=BlockType.NIGHT,
                    hours_per_week=60.0,
                ),
                BlockConfig(name="Research", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(name="Emily", training_year=TrainingYear.S2),
                FellowConfig(name="Alex", training_year=TrainingYear.S2),
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="S2 can do all blocks",
                    block_names=["Night Float", "Research"],
                    allowed_years=[TrainingYear.S2],
                )
            ],
            individual_fellow_requirement_rules=[
                IndividualFellowRequirementRule(
                    training_year=TrainingYear.S2,
                    fellow_name="Emily",
                    block_name="Night Float",
                    min_weeks=2,
                    max_weeks=2,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        emily_idx = next(
            idx for idx, fellow in enumerate(config.fellows) if fellow.name == "Emily"
        )
        assert result.assignments[emily_idx].count("Night Float") == 2

    def test_individual_fellow_requirement_rule_flags_missing_fellow(self) -> None:
        """Named-fellow rules should warn when no matching roster entry exists."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[BlockConfig(name="Research", hours_per_week=40.0)],
            fellows=[FellowConfig(name="Alex", training_year=TrainingYear.S2)],
            individual_fellow_requirement_rules=[
                IndividualFellowRequirementRule(
                    training_year=TrainingYear.S2,
                    fellow_name="Emily",
                    block_name="Research",
                    min_weeks=1,
                    max_weeks=1,
                )
            ],
        )

        issues = check_feasibility(config)

        assert any("Emily" in issue and "matching fellow" in issue for issue in issues)

    def test_linked_fellow_state_rule_keeps_two_s2_fellows_on_same_pto_weeks(self) -> None:
        """A linked-fellow state rule should synchronize PTO weeks."""

        config = ScheduleConfig(
            num_fellows=2,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=1,
            pto_weeks_to_rank=1,
            max_concurrent_pto=2,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(
                    name="Ambrosini",
                    training_year=TrainingYear.S2,
                    pto_rankings=[1],
                ),
                FellowConfig(
                    name="Fishman",
                    training_year=TrainingYear.S2,
                    pto_rankings=[1],
                ),
            ],
            linked_fellow_state_rules=[
                LinkedFellowStateRule(
                    training_year=TrainingYear.S2,
                    first_fellow_name="Ambrosini",
                    second_fellow_name="Fishman",
                    state_name="PTO",
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        for week in range(config.num_weeks):
            assert (result.assignments[0][week] == "PTO") == (
                result.assignments[1][week] == "PTO"
            )

    def test_structured_call_rules_keep_call_on_f1_allowed_rotations(self) -> None:
        """Structured call should stay on eligible F1 fellows and allowed rotations."""

        config = ScheduleConfig(
            num_fellows=2,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            structured_call_rules_enabled=True,
            call_eligible_years=[TrainingYear.F1],
            call_allowed_block_names=["EP"],
            call_min_per_fellow=2,
            call_max_per_fellow=2,
            call_forbidden_following_blocks=["Night Float"],
            call_max_consecutive_weeks_per_fellow=1,
            hours_cap=120.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[
                BlockConfig(name="EP", hours_per_week=55.0),
                BlockConfig(name="Research", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(name="F1 A", training_year=TrainingYear.F1),
                FellowConfig(name="F1 B", training_year=TrainingYear.F1),
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert sum(result.call_assignments[0]) == 2
        assert sum(result.call_assignments[1]) == 2
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                if result.call_assignments[fellow_idx][week]:
                    assert result.assignments[fellow_idx][week] == "EP"
                if week + 1 < config.num_weeks:
                    assert not (
                        result.call_assignments[fellow_idx][week]
                        and result.call_assignments[fellow_idx][week + 1]
                    )

    def test_srcva_overlay_call_rules_respect_rotations_and_counts(self) -> None:
        """SRC/VA weekend and weekday overlay call should honor rotations and totals."""

        config = ScheduleConfig(
            num_fellows=3,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=120.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[BlockConfig(name="CT-MRI", hours_per_week=40.0)],
            fellows=[
                FellowConfig(name="F1 A", training_year=TrainingYear.F1),
                FellowConfig(name="S2 A", training_year=TrainingYear.S2),
                FellowConfig(name="S2 B", training_year=TrainingYear.S2),
            ],
            srcva_weekend_call_enabled=True,
            srcva_weekend_call_eligible_years=[TrainingYear.F1, TrainingYear.S2],
            srcva_weekend_call_allowed_block_names=["CT-MRI"],
            srcva_weekend_call_f1_start_week=2,
            srcva_weekend_call_f1_min=0,
            srcva_weekend_call_f1_max=0,
            srcva_weekend_call_s2_min=1,
            srcva_weekend_call_s2_max=1,
            srcva_total_call_f1_min=0,
            srcva_total_call_f1_max=0,
            srcva_weekday_call_enabled=True,
            srcva_weekday_call_eligible_years=[TrainingYear.F1, TrainingYear.S2],
            srcva_weekday_call_allowed_block_names=["CT-MRI"],
            srcva_weekday_call_f1_start_week=2,
            srcva_weekday_call_f1_min=0,
            srcva_weekday_call_f1_max=0,
            srcva_weekday_call_s2_min=4,
            srcva_weekday_call_s2_max=4,
            srcva_weekday_call_max_consecutive_nights=1,
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert sum(result.srcva_weekend_call_assignments[0]) == 0
        assert sum(result.srcva_weekend_call_assignments[1]) == 1
        assert sum(result.srcva_weekend_call_assignments[2]) == 1
        assert sum(
            assigned
            for week_calls in result.srcva_weekday_call_assignments[0]
            for assigned in week_calls
        ) == 0
        assert sum(
            assigned
            for week_calls in result.srcva_weekday_call_assignments[1]
            for assigned in week_calls
        ) == 4
        assert sum(
            assigned
            for week_calls in result.srcva_weekday_call_assignments[2]
            for assigned in week_calls
        ) == 4

        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                if result.srcva_weekend_call_assignments[fellow_idx][week]:
                    assert result.assignments[fellow_idx][week] == "CT-MRI"
                for day_idx in range(4):
                    if result.srcva_weekday_call_assignments[fellow_idx][week][day_idx]:
                        assert result.assignments[fellow_idx][week] == "CT-MRI"
                for day_idx in range(3):
                    assert not (
                        result.srcva_weekday_call_assignments[fellow_idx][week][day_idx]
                        and result.srcva_weekday_call_assignments[fellow_idx][week][day_idx + 1]
                    )

    def test_srcva_weekday_and_24hr_same_week_penalty_appears_in_objective(self) -> None:
        """The solver should score the SRC/VA weekday + 24-hr same-week penalty."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=1,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            structured_call_rules_enabled=True,
            call_eligible_years=[TrainingYear.F1],
            call_allowed_block_names=["CT-MRI"],
            call_min_per_fellow=1,
            call_max_per_fellow=1,
            call_forbidden_following_blocks=[],
            call_max_consecutive_weeks_per_fellow=1,
            srcva_weekday_call_enabled=True,
            srcva_weekday_call_eligible_years=[TrainingYear.F1],
            srcva_weekday_call_allowed_block_names=["CT-MRI"],
            srcva_weekday_call_f1_start_week=0,
            srcva_weekday_call_f1_min=4,
            srcva_weekday_call_f1_max=4,
            srcva_weekday_call_s2_min=0,
            srcva_weekday_call_s2_max=0,
            srcva_weekday_call_max_consecutive_nights=4,
            srcva_weekday_same_week_as_24hr_weight=-7,
            hours_cap=200.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=10.0,
            blocks=[BlockConfig(name="CT-MRI", hours_per_week=40.0)],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
        )

        result = solve_schedule(config)

        assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        penalty_row = next(
            row
            for row in result.objective_breakdown
            if row["Category"] == "Penalty: SRC/VA weekday and 24-hr call in same week"
        )
        assert penalty_row["F1"] == -7
        assert penalty_row["Total"] == -7

    def test_rolling_window_rule_enforces_multi_state_cap(self) -> None:
        """Rolling-window rules should cap per-fellow state clustering."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=2,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Research", hours_per_week=40.0),
                BlockConfig(name="Elective", hours_per_week=40.0),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="Research/Elective F1",
                    block_names=["Research", "Elective"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="Research exact 2",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Research"],
                    min_weeks=2,
                    max_weeks=2,
                )
            ],
            rolling_window_rules=[
                RollingWindowRule(
                    name="No more than 3 PTO or Research in 4 weeks",
                    applicable_years=[TrainingYear.F1],
                    state_names=["PTO", "Research"],
                    window_size_weeks=4,
                    max_weeks_in_window=3,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE

    def test_consecutive_state_limit_rule_caps_selected_cohort(self) -> None:
        """Cohort-specific consecutive limits should bind even if the global cap is looser."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=3,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Night Float", block_type=BlockType.NIGHT),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 NF/Research",
                    block_names=["Night Float", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 NF exact 3",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Night Float"],
                    min_weeks=3,
                    max_weeks=3,
                )
            ],
            consecutive_state_limit_rules=[
                ConsecutiveStateLimitRule(
                    name="F1 Night Float max 2 consecutive weeks",
                    applicable_years=[TrainingYear.F1],
                    state_names=["Night Float"],
                    max_consecutive_weeks=2,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE

    def test_f1_white_consults_consecutive_limit_caps_run_length(self) -> None:
        """F1 White Consults should not be allowed to run longer than 2 consecutive weeks."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="White Consults"),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 White/Research",
                    block_names=["White Consults", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 White exact 4",
                    applicable_years=[TrainingYear.F1],
                    block_names=["White Consults"],
                    min_weeks=4,
                    max_weeks=4,
                )
            ],
            consecutive_state_limit_rules=[
                ConsecutiveStateLimitRule(
                    name="F1 White Consults max 2 consecutive weeks",
                    applicable_years=[TrainingYear.F1],
                    state_names=["White Consults"],
                    max_consecutive_weeks=2,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE

    def test_f1_ccu_consecutive_limit_caps_run_length(self) -> None:
        """F1 CCU should not be allowed to run longer than 2 consecutive weeks."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=3,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="CCU"),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 CCU/Research",
                    block_names=["CCU", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 CCU exact 3",
                    applicable_years=[TrainingYear.F1],
                    block_names=["CCU"],
                    min_weeks=3,
                    max_weeks=3,
                )
            ],
            consecutive_state_limit_rules=[
                ConsecutiveStateLimitRule(
                    name="F1 CCU max 2 consecutive weeks",
                    applicable_years=[TrainingYear.F1],
                    state_names=["CCU"],
                    max_consecutive_weeks=2,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE

    def test_first_assignment_run_limit_rule_caps_first_night_float_week(self) -> None:
        """The first Night Float run for F1 should obey the dedicated first-run cap."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Night Float", block_type=BlockType.NIGHT),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 NF/Research",
                    block_names=["Night Float", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 NF exact 2",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Night Float"],
                    min_weeks=2,
                    max_weeks=2,
                )
            ],
            first_assignment_run_limit_rules=[
                FirstAssignmentRunLimitRule(
                    name="F1 first Night Float run max 1 week",
                    applicable_years=[TrainingYear.F1],
                    block_name="Night Float",
                    max_run_length_weeks=1,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE

    def test_contiguous_block_rule_allows_s2_ct_mri_two_week_run(self) -> None:
        """S2 CT-MRI can run two consecutive weeks when a contiguous-run rule is present."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="CT-MRI"),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="S2 A", training_year=TrainingYear.S2)],
            eligibility_rules=[
                EligibilityRule(
                    name="S2 CT-MRI/Research",
                    block_names=["CT-MRI", "Research"],
                    allowed_years=[TrainingYear.S2],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="S2 CT-MRI exact 2",
                    applicable_years=[TrainingYear.S2],
                    block_names=["CT-MRI"],
                    min_weeks=2,
                    max_weeks=2,
                )
            ],
            contiguous_block_rules=[
                ContiguousBlockRule(
                    name="S2 CT-MRI must be one contiguous run",
                    applicable_years=[TrainingYear.S2],
                    block_name="CT-MRI",
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.assignments[0] == ["CT-MRI", "CT-MRI"]

    def test_t3_structured_config_allows_consecutive_elective_weeks(self) -> None:
        """T3 should be able to take consecutive Elective weeks."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Elective"),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="T3 A", training_year=TrainingYear.T3)],
            eligibility_rules=[
                EligibilityRule(
                    name="T3 Elective/Research",
                    block_names=["Elective", "Research"],
                    allowed_years=[TrainingYear.T3],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="T3 Elective exact 2",
                    applicable_years=[TrainingYear.T3],
                    block_names=["Elective"],
                    min_weeks=2,
                    max_weeks=2,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.assignments[0] == ["Elective", "Elective"]

    def test_soft_single_week_block_rule_prefers_two_week_runs(self) -> None:
        """One-week penalties should push F1 rotations into longer runs when possible."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=4,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Research"),
                BlockConfig(name="EP"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 Research/EP",
                    block_names=["Research", "EP"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 Research exact 2",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Research"],
                    min_weeks=2,
                    max_weeks=2,
                ),
                WeekCountRule(
                    name="F1 EP exact 2",
                    applicable_years=[TrainingYear.F1],
                    block_names=["EP"],
                    min_weeks=2,
                    max_weeks=2,
                ),
            ],
            soft_single_week_block_rules=[
                SoftSingleWeekBlockRule(
                    name="Bonus: F1 consecutive rotation weeks",
                    applicable_years=[TrainingYear.F1],
                    excluded_states=[],
                    weight=5,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.assignments[0] in (
            ["Research", "Research", "EP", "EP"],
            ["EP", "EP", "Research", "Research"],
        )

    def test_soft_fixed_week_pair_rule_rewards_holiday_pairing(self) -> None:
        """A fixed holiday-week pair bonus should reward a heavy/light split."""

        config = ScheduleConfig(
            num_fellows=1,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["Night Float", "PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="CCU"),
                BlockConfig(name="Research"),
            ],
            fellows=[FellowConfig(name="F1 A", training_year=TrainingYear.F1)],
            eligibility_rules=[
                EligibilityRule(
                    name="F1 CCU/Research",
                    block_names=["CCU", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            week_count_rules=[
                WeekCountRule(
                    name="F1 CCU exact 1",
                    applicable_years=[TrainingYear.F1],
                    block_names=["CCU"],
                    min_weeks=1,
                    max_weeks=1,
                ),
                WeekCountRule(
                    name="F1 Research exact 1",
                    applicable_years=[TrainingYear.F1],
                    block_names=["Research"],
                    min_weeks=1,
                    max_weeks=1,
                ),
            ],
            soft_fixed_week_pair_rules=[
                SoftFixedWeekPairRule(
                    name="Bonus: F1 holiday split",
                    applicable_years=[TrainingYear.F1],
                    trigger_states=["CCU"],
                    paired_states=["Research"],
                    first_week=0,
                    second_week=1,
                    weight=7,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.objective_value == 7.0
        breakdown_row = next(
            row
            for row in result.objective_breakdown
            if row["Category"] == "Bonus: F1 holiday split"
        )
        assert breakdown_row["F1"] == 7

    def test_first_assignment_pairing_rule_requires_supervision(self) -> None:
        """A first-time F1 Yale Nuclear week should need an S2 or experienced F1 partner."""

        config = ScheduleConfig(
            num_fellows=2,
            num_weeks=2,
            start_date=date(2026, 7, 13),
            pto_weeks_granted=0,
            pto_weeks_to_rank=0,
            max_concurrent_pto=1,
            max_consecutive_night_float=2,
            call_day="saturday",
            call_hours=24.0,
            call_excluded_blocks=["PTO"],
            hours_cap=80.0,
            trailing_avg_weeks=4,
            solver_timeout_seconds=5.0,
            blocks=[
                BlockConfig(name="Yale Nuclear", hours_per_week=40.0),
                BlockConfig(name="Research", hours_per_week=40.0),
            ],
            fellows=[
                FellowConfig(name="F1 A", training_year=TrainingYear.F1),
                FellowConfig(name="F1 B", training_year=TrainingYear.F1),
            ],
            coverage_rules=[
                CoverageRule(
                    name="Yale Nuclear exact 1",
                    block_name="Yale Nuclear",
                    eligible_years=[TrainingYear.F1],
                    min_fellows=1,
                    max_fellows=1,
                )
            ],
            eligibility_rules=[
                EligibilityRule(
                    name="Yale Nuclear or Research F1",
                    block_names=["Yale Nuclear", "Research"],
                    allowed_years=[TrainingYear.F1],
                )
            ],
            first_assignment_pairing_rules=[
                FirstAssignmentPairingRule(
                    name="F1 first Yale Nuclear week needs experienced pairing",
                    trainee_years=[TrainingYear.F1],
                    block_name="Yale Nuclear",
                    mentor_years=[TrainingYear.S2],
                    experienced_peer_years=[TrainingYear.F1],
                    required_prior_weeks=1,
                )
            ],
        )

        result = solve_schedule(config)

        assert result.solver_status == SolverStatus.INFEASIBLE


class TestBuiltInDefaults:
    """The shipped defaults should reflect the built-in rule set."""

    def test_default_config_uses_source_cohort_counts_and_rules(self) -> None:
        config = get_default_config()
        expected_pto_weights = [120, 80, 12, 4, 1, 0]

        assert config.start_date == date(2026, 7, 13)
        assert config.cohort_counts[TrainingYear.F1] == 9
        assert config.cohort_counts[TrainingYear.S2] == 9
        assert config.cohort_counts[TrainingYear.T3] == 9
        assert config.max_concurrent_pto == 12
        assert (
            config.pto_preference_weights_for_year(TrainingYear.F1)
            == expected_pto_weights
        )
        assert (
            config.pto_preference_weights_for_year(TrainingYear.S2)
            == expected_pto_weights
        )
        assert (
            config.pto_preference_weights_for_year(TrainingYear.T3)
            == expected_pto_weights
        )
        assert config.srcva_weekend_call_enabled
        assert config.srcva_weekend_call_eligible_years == [TrainingYear.F1, TrainingYear.S2]
        assert "CT-MRI" in config.srcva_weekend_call_allowed_block_names
        assert config.srcva_weekend_call_f1_min == 0
        assert config.srcva_weekend_call_f1_max == 1
        assert config.srcva_weekend_call_s2_min == 5
        assert config.srcva_weekend_call_s2_max == 6
        assert config.srcva_total_call_f1_min == 6
        assert config.srcva_total_call_f1_max == 7
        assert config.srcva_weekday_call_enabled
        assert config.srcva_weekday_call_eligible_years == [TrainingYear.F1, TrainingYear.S2]
        assert "CT-MRI" in config.srcva_weekday_call_allowed_block_names
        assert config.srcva_weekday_call_f1_min == 3
        assert config.srcva_weekday_call_f1_max == 5
        assert config.srcva_weekday_call_s2_min == 18
        assert config.srcva_weekday_call_s2_max == 20
        assert config.srcva_weekday_call_max_consecutive_nights == 1
        assert config.srcva_holiday_preference_weight == 4
        assert config.srcva_holiday_repeat_weight == -5
        assert config.srcva_weekday_max_one_per_week_weight == -3
        assert config.srcva_weekday_same_week_as_weekend_weight == -2
        assert config.srcva_weekday_same_week_as_24hr_weight == -4

        coverage_rule_names = {rule.name for rule in config.coverage_rules}
        assert "White Consults staffed by F1" in coverage_rule_names
        assert "Goodyer staffed by S2" in coverage_rule_names
        assert "Yale Nuclear staffed by F1, S2, or T3" in coverage_rule_names
        assert "VA Nuclear staffed by F1, S2, or T3" in coverage_rule_names
        assert "CT-MRI staffed by S2 or T3" in coverage_rule_names
        assert "Peripheral vascular optional T3" in coverage_rule_names
        assert next(
            rule for rule in config.coverage_rules if rule.name == "CHF staffed by F1 or S2"
        ).min_fellows == 0
        assert next(
            rule for rule in config.coverage_rules if rule.name == "CHF staffed by F1 or S2"
        ).max_fellows == 1
        assert next(
            rule for rule in config.coverage_rules if rule.name == "Yale Cath range"
        ).min_fellows == 0
        assert next(
            rule for rule in config.coverage_rules if rule.name == "Yale Cath range"
        ).max_fellows == 2
        assert next(
            rule for rule in config.coverage_rules if rule.name == "Yale Echo F1 range"
        ).max_fellows == 2
        assert next(
            rule for rule in config.coverage_rules if rule.name == "CT-MRI staffed by S2 or T3"
        ).min_fellows == 0
        assert next(
            rule for rule in config.coverage_rules if rule.name == "CT-MRI staffed by S2 or T3"
        ).max_fellows == 1

        week_rules = {rule.name: rule for rule in config.week_count_rules}
        assert "F1 no PTO before 8/10/26" in week_rules
        assert "F1 no Research before 8/10/26" in week_rules
        assert "F1 White Consults" in week_rules
        assert "F1 Research" in week_rules
        assert week_rules["F1 White Consults"].min_weeks == 5
        assert week_rules["F1 White Consults"].max_weeks == 6
        assert week_rules["F1 White Consults"].is_active
        assert week_rules["F1 SRC Consults"].min_weeks == 2
        assert week_rules["F1 SRC Consults"].max_weeks == 4
        assert week_rules["F1 SRC Consults"].is_active
        assert week_rules["F1 VA Consults"].is_active
        assert week_rules["F1 Consult total"].max_weeks == 12
        assert week_rules["F1 Consult total"].is_active
        assert week_rules["F1 EP"].min_weeks == 4
        assert week_rules["F1 EP"].max_weeks == 5
        assert week_rules["F1 Yale Nuclear"].min_weeks == 2
        assert week_rules["F1 Yale Nuclear"].max_weeks == 4
        assert week_rules["F1 Yale Nuclear"].is_active
        assert week_rules["F1 VA Nuclear"].min_weeks == 1
        assert week_rules["F1 VA Nuclear"].max_weeks == 3
        assert week_rules["F1 VA Nuclear"].is_active
        assert week_rules["F1 Nuclear total"].min_weeks == 4
        assert week_rules["F1 Nuclear total"].max_weeks == 7
        assert week_rules["F1 Nuclear total"].is_active
        assert week_rules["F1 Yale Echo"].is_active
        assert week_rules["F1 Echo total"].min_weeks == 7
        assert week_rules["F1 Echo total"].is_active
        assert week_rules["F1 Yale Cath"].is_active
        assert week_rules["F1 Cath total"].is_active
        assert "F1 Peripheral vascular prohibited" in week_rules
        assert week_rules["S2 White Consults prohibited"].max_weeks == 0
        assert week_rules["S2 Goodyer Consults"].min_weeks == 5
        assert week_rules["S2 Goodyer Consults"].max_weeks == 6
        assert week_rules["S2 CCU"].end_week == 2
        assert week_rules["S2 Night Float"].max_weeks == 1
        assert week_rules["S2 Night Float"].end_week == 5
        assert week_rules["S2 CHF"].min_weeks == 1
        assert week_rules["S2 CHF"].max_weeks == 4
        assert week_rules["S2 Consult total"].block_names == ["SRC Consults", "VA Consults"]
        assert week_rules["S2 Consult total"].min_weeks == 3
        assert week_rules["S2 Consult total"].max_weeks == 4
        assert week_rules["S2 SRC Cath"].min_weeks == 0
        assert week_rules["S2 SRC Cath"].max_weeks == 4
        assert week_rules["S2 Yale Nuclear"].min_weeks == 4
        assert week_rules["S2 Yale Nuclear"].max_weeks == 6
        assert week_rules["S2 VA Cath"].max_weeks == 5
        assert week_rules["S2 Cath total"].min_weeks == 6
        assert week_rules["S2 Cath total"].max_weeks == 8
        assert week_rules["S2 Research"].min_weeks == 6
        assert week_rules["S2 Research"].max_weeks == 6
        assert week_rules["S2 CT-MRI"].min_weeks == 2
        assert week_rules["S2 CT-MRI"].max_weeks == 2
        assert week_rules["S2 Elective prohibited"].max_weeks == 0
        assert week_rules["S2 Peripheral vascular prohibited"].max_weeks == 0
        assert week_rules["T3 White Consults prohibited"].max_weeks == 0
        assert week_rules["T3 Consult total"].block_names == ["SRC Consults", "VA Consults"]
        assert week_rules["T3 Consult total"].min_weeks == 3
        assert week_rules["T3 Consult total"].max_weeks == 4
        assert week_rules["T3 Nuclear total"].min_weeks == 4
        assert week_rules["T3 Nuclear total"].max_weeks == 5
        assert week_rules["T3 Echo total"].block_names == ["Yale Echo", "SRC Echo"]
        assert week_rules["T3 Echo total"].min_weeks == 4
        assert week_rules["T3 Echo total"].max_weeks == 10
        assert week_rules["T3 CT-MRI"].min_weeks == 2
        assert week_rules["T3 CT-MRI"].max_weeks == 2
        assert week_rules["T3 Elective"].min_weeks == 24
        assert week_rules["T3 Elective"].max_weeks == 30
        assert week_rules["T3 Peripheral vascular"].min_weeks == 2
        assert week_rules["T3 Peripheral vascular"].max_weeks == 2
        assert week_rules["T3 Congenital"].min_weeks == 2
        assert week_rules["T3 Congenital"].max_weeks == 2
        assert week_rules["T3 late spring elective/research/PTO only"].block_names == ["PTO", "Research", "Elective"]
        assert week_rules["T3 late spring elective/research/PTO only"].start_week == 46
        assert week_rules["T3 late spring elective/research/PTO only"].end_week == 51
        assert len(config.rolling_window_rules) == 1
        assert (
            config.rolling_window_rules[0].name
            == "Max 3 PTO or Research weeks in any 4-week period"
        )
        assert config.rolling_window_rules[0].window_size_weeks == 4
        assert config.rolling_window_rules[0].max_weeks_in_window == 3
        consecutive_limits = {
            rule.name: rule for rule in config.consecutive_state_limit_rules
        }
        assert len(consecutive_limits) == 15
        assert (
            consecutive_limits["F1 Night Float max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["F1 Goodyer Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["F1 EP max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits[
                "F1 White Consults max 2 consecutive weeks"
            ].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["F1 SRC Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["F1 VA Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["F1 CCU max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 Night Float max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 Goodyer Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 EP max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 White Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 SRC Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 VA Consults max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 CCU max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        assert (
            consecutive_limits["S2 Research max 2 consecutive weeks"].max_consecutive_weeks
            == 2
        )
        contiguous_rules = {rule.name: rule for rule in config.contiguous_block_rules}
        assert len(contiguous_rules) == 2
        assert contiguous_rules["S2 CT-MRI must be one contiguous run"].block_name == "CT-MRI"
        assert contiguous_rules["S2 CT-MRI must be one contiguous run"].applicable_years == [TrainingYear.S2]
        assert contiguous_rules["T3 CT-MRI must be one contiguous run"].block_name == "CT-MRI"
        assert contiguous_rules["T3 CT-MRI must be one contiguous run"].applicable_years == [TrainingYear.T3]
        assert len(config.first_assignment_run_limit_rules) == 1
        assert (
            config.first_assignment_run_limit_rules[0].name
            == "F1 first Night Float run max 1 week"
        )
        assert config.first_assignment_run_limit_rules[0].max_run_length_weeks == 1
        assert len(config.first_assignment_pairing_rules) == 1
        assert (
            config.first_assignment_pairing_rules[0].name
            == "F1 first Yale Nuclear week needs experienced pairing"
        )

        assert any(
            rule.name == "F1 before Night Float needs core exposure"
            and rule.is_active
            and rule.prerequisite_blocks
            == ["Yale Echo", "White Consults", "CCU", "EP", "CHF"]
            and rule.prerequisite_block_groups == [["Yale Cath", "SRC Cath"]]
            for rule in config.prerequisite_rules
        )
        assert any(
            rule.name == "F1/S2 Night Float cannot follow CCU"
            and rule.applicable_years == [TrainingYear.F1, TrainingYear.S2]
            and rule.target_block == "Night Float"
            and rule.forbidden_previous_blocks == ["CCU"]
            and rule.is_active
            for rule in config.forbidden_transition_rules
        )
        assert any(
            rule.name
            == "Penalty: F1 Night Float after White Consults, SRC Consults, VA Consults, or PTO"
            and rule.weight == -40
            and rule.is_active
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: F1 CHF immediately before Night Float"
            and rule.weight == 30
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: S2 Research adjacent to PTO"
            and rule.weight == 10
            and rule.direction == SoftRuleDirection.EITHER
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: S2 two-week PTO block"
            and rule.weight == 8
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: T3 two-week PTO block"
            and rule.weight == 8
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: F1 Night Float followed by Research or PTO"
            and rule.left_states == ["Night Float"]
            and rule.right_states == ["Research", "PTO"]
            and rule.weight == 5
            and rule.is_active
            for rule in config.soft_sequence_rules
        )
        assert any(
            rule.name == "Bonus: S2 Research during final week"
            and rule.state_names == ["Research"]
            and rule.start_week == 51
            and rule.end_week == 51
            and rule.weight == 6
            for rule in config.soft_state_assignment_rules
        )
        assert any(
            rule.name == "Bonus: S2 assignment to SRC Echo"
            and rule.state_names == ["SRC Echo"]
            and rule.weight == 3
            for rule in config.soft_state_assignment_rules
        )
        assert any(
            rule.name == "Penalty: S2 uneven CCU distribution"
            and rule.state_names == ["CCU"]
            and rule.weight == 4
            for rule in config.soft_cohort_balance_rules
        )
        assert any(
            rule.name == "Penalty: S2 uneven Night Float distribution"
            and rule.state_names == ["Night Float"]
            and rule.weight == 4
            for rule in config.soft_cohort_balance_rules
        )
        assert any(
            rule.name
            == "Bonus: F1 consecutive non-Night-Float rotation weeks after first 8 weeks"
            and rule.weight == 1
            and rule.start_week == 8
            and rule.excluded_states == ["Night Float"]
            and rule.included_states == []
            and rule.is_active
            for rule in config.soft_single_week_block_rules
        )
        assert any(
            rule.name
            == "Bonus: S2 two-week Goodyer, consult, EP, CHF, Yale Nuclear, Yale Echo, and Yale Cath runs"
            and rule.weight == 1
            and rule.start_week == 0
            and rule.included_states
            == [
                "Goodyer Consults",
                "VA Consults",
                "SRC Consults",
                "EP",
                "CHF",
                "Yale Nuclear",
                "Yale Echo",
                "Yale Cath",
            ]
            and rule.excluded_states == []
            and rule.is_active
            for rule in config.soft_single_week_block_rules
        )
        assert any(
            rule.name == "Bonus: F1 holiday heavy week paired with lighter holiday week"
            and rule.weight == 5
            and rule.first_week == 19
            and rule.second_week == 23
            and rule.trigger_states
            == [
                "Goodyer Consults",
                "CCU",
                "White Consults",
                "SRC Consults",
                "VA Consults",
                "Night Float",
            ]
            and "PTO" in rule.paired_states
            and "Elective" in rule.paired_states
            and rule.is_active
            for rule in config.soft_fixed_week_pair_rules
        )
        assert any(
            rule.name == "Bonus: S2 holiday heavy week paired with lighter holiday week"
            and rule.weight == 5
            and rule.first_week == 19
            and rule.second_week == 23
            and rule.is_active
            for rule in config.soft_fixed_week_pair_rules
        )

    def test_default_config_feasibility_has_no_staffing_conflict(self) -> None:
        config = get_default_config()

        issues = check_feasibility(config)

        assert not any("Staffing conflict" in issue for issue in issues)

    def test_default_config_with_full_t3_rules_solves_without_pto(
        self,
    ) -> None:
        config = get_default_config()
        config.pto_weeks_granted = 0
        config.pto_weeks_to_rank = 0
        for fellow in config.fellows:
            fellow.pto_rankings = []
        config.solver_timeout_seconds = 30.0

        result = solve_schedule(config)

        assert result.solver_status in {
            SolverStatus.FEASIBLE,
            SolverStatus.OPTIMAL,
        }
