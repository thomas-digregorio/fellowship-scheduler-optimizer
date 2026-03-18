"""Rules tab for editing schedule configuration and solver rules."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from app.state import set_config
from src.models import (
    BlockConfig,
    BlockType,
    CohortLimitRule,
    CoverageRule,
    EligibilityRule,
    FellowConfig,
    ForbiddenTransitionRule,
    IndividualFellowRequirementRule,
    PrerequisiteRule,
    ScheduleConfig,
    SoftRuleDirection,
    SoftSequenceRule,
    TrainingYear,
    WeekCountRule,
)


def render_rules_tab(config: ScheduleConfig) -> None:
    """Render schedule config, cohort setup, and rule summaries/editors."""

    st.subheader("📏 Rules")

    program_tab, f1_tab, s2_tab, t3_tab = st.tabs(
        [
            "Program-wide Rules",
            "F1 Fellow Rules",
            "S2 Fellow Rules",
            "T3 Fellow Rules",
        ]
    )

    with program_tab:
        _render_program_setup(config)

    with f1_tab:
        _render_cohort_setup(config, TrainingYear.F1)

    with s2_tab:
        _render_cohort_setup(config, TrainingYear.S2)

    with t3_tab:
        _render_cohort_setup(config, TrainingYear.T3)

    config.num_fellows = len(config.fellows)
    set_config(config)


def _render_program_setup(config: ScheduleConfig) -> None:
    """Render global schedule config, shared rules, and block metadata."""

    with st.container(border=True):
        st.markdown("#### Schedule Basics")
        left_col, middle_col, right_col = st.columns(3)
        config.start_date = left_col.date_input(
            "Academic year start",
            value=config.start_date,
            key="program_start_date",
        )
        config.num_weeks = middle_col.number_input(
            "Schedule length (weeks)",
            min_value=1,
            max_value=104,
            value=config.num_weeks,
            key="program_num_weeks",
        )
        config.solver_timeout_seconds = right_col.number_input(
            "Solver timeout (seconds)",
            min_value=5.0,
            max_value=600.0,
            value=config.solver_timeout_seconds,
            step=5.0,
            key="program_timeout",
        )

    with st.container(border=True):
        st.markdown("#### PTO & Coverage Limits")
        left_col, middle_col, right_col = st.columns(3)
        config.pto_weeks_granted = left_col.number_input(
            "PTO weeks granted",
            min_value=0,
            max_value=12,
            value=config.pto_weeks_granted,
            key="program_pto_granted",
        )
        config.pto_weeks_to_rank = middle_col.number_input(
            "PTO weeks to rank",
            min_value=config.pto_weeks_granted,
            max_value=20,
            value=config.pto_weeks_to_rank,
            key="program_pto_rank",
        )
        config.max_concurrent_pto = right_col.number_input(
            "Global max fellows on PTO",
            min_value=1,
            max_value=max(1, len(config.fellows)),
            value=config.max_concurrent_pto,
            key="program_max_pto",
        )

    with st.container(border=True):
        st.markdown("#### Call & Hours")
        left_col, middle_col, right_col = st.columns(3)
        config.max_consecutive_night_float = left_col.number_input(
            "Max consecutive Night Float weeks",
            min_value=1,
            max_value=6,
            value=config.max_consecutive_night_float,
            key="program_max_nf",
        )
        config.hours_cap = middle_col.number_input(
            "Hours cap",
            min_value=40.0,
            max_value=120.0,
            value=config.hours_cap,
            step=1.0,
            key="program_hours_cap",
        )
        config.trailing_avg_weeks = right_col.number_input(
            "Trailing average window",
            min_value=1,
            max_value=12,
            value=config.trailing_avg_weeks,
            key="program_trailing_avg_weeks",
        )

        left_col, middle_col, right_col = st.columns(3)
        config.call_day = left_col.selectbox(
            "24-hr call day",
            options=["saturday", "sunday", "friday"],
            index=["saturday", "sunday", "friday"].index(config.call_day),
            key="program_call_day",
        )
        config.call_hours = middle_col.number_input(
            "Call hours",
            min_value=0.0,
            max_value=48.0,
            value=config.call_hours,
            step=1.0,
            key="program_call_hours",
        )
        all_state_names = [block.name for block in config.blocks] + ["PTO"]
        config.call_excluded_blocks = right_col.multiselect(
            "Blocks excluded from call",
            options=all_state_names,
            default=[
                block_name
                for block_name in config.call_excluded_blocks
                if block_name in all_state_names
            ],
            key="program_call_excluded",
        )

    with st.container(border=True):
        st.markdown("#### Block Catalog")
        st.caption(
            "These fields apply to the shared block catalog. Cohort-specific staffing, "
            "eligibility, and per-fellow block requirements are managed in the cohort "
            "Configuration tabs. Shared multi-cohort hard rules are edited below."
        )
        config.blocks = _render_block_metadata_editor(config.blocks, key_prefix="program_blocks")

    st.caption(
        "Edit rules that span multiple cohorts here. Exact single-cohort rules are edited "
        "inside the F1 / S2 / T3 tabs."
    )
    with st.container(border=True):
        shared_coverage = _select_shared_coverage_rules(config.coverage_rules)
        config.coverage_rules = _merge_coverage_rules(
            config.coverage_rules,
            _render_coverage_rules_editor(
                shared_coverage,
                key_prefix="shared_coverage",
                title="Shared Coverage Rules",
                caption="Cross-cohort coverage such as any-year staffing or combined senior slots.",
            ),
            predicate=_is_shared_coverage_rule,
        )

    with st.container(border=True):
        shared_eligibility = _select_shared_eligibility_rules(config.eligibility_rules)
        config.eligibility_rules = _merge_eligibility_rules(
            config.eligibility_rules,
            _render_eligibility_rules_editor(
                shared_eligibility,
                key_prefix="shared_eligibility",
                title="Shared Eligibility Rules",
                caption="Cross-cohort eligibility windows such as any-year or senior-only blocks.",
            ),
            predicate=_is_shared_eligibility_rule,
        )

    with st.container(border=True):
        shared_week_counts = _select_shared_year_rules(config.week_count_rules)
        config.week_count_rules = _merge_year_rules(
            config.week_count_rules,
            _render_week_count_rules_editor(
                shared_week_counts,
                key_prefix="shared_week_counts",
                title="Shared Week Count Rules",
                caption="Week-count rules that span more than one cohort.",
            ),
            predicate=_is_shared_year_rule,
        )

    with st.container(border=True):
        shared_soft_rules = _select_shared_soft_rules(config.soft_sequence_rules)
        config.soft_sequence_rules = _merge_year_rules(
            config.soft_sequence_rules,
            _render_soft_sequence_rules_editor(
                shared_soft_rules,
                key_prefix="shared_soft",
                title="Weighted Soft Rules",
                caption=(
                    "Cross-cohort weighted bonuses or penalties that apply to more than "
                    "one cohort."
                ),
            ),
            predicate=_is_shared_soft_rule,
        )

def _render_cohort_setup(config: ScheduleConfig, year: TrainingYear) -> None:
    """Render cohort-specific schedule config and block metadata."""

    st.caption(
        f"Combined cohort roster, PTO, and exact {year.value} block-rule configuration."
    )

    cohort_counts = config.cohort_counts
    target_count = int(st.session_state.get(f"{year.value}_count", cohort_counts[year]))
    updated_counts = cohort_counts.copy()
    updated_counts[year] = target_count
    _sync_fellows_by_year(
        config,
        updated_counts[TrainingYear.F1],
        updated_counts[TrainingYear.S2],
        updated_counts[TrainingYear.T3],
    )

    fellows_in_year = [
        (index, fellow)
        for index, fellow in enumerate(config.fellows)
        if fellow.training_year == year
    ]

    with st.container(border=True):
        st.markdown("#### Roster, PTO Preferences, and Availability")
        if not fellows_in_year:
            st.info(f"No fellows are currently configured for {year.value}.")
        else:
            _render_fellow_editors(config, year)

    with st.container(border=True):
        st.markdown(f"#### {year.value} Configuration")
        target_count = st.number_input(
            f"{year.value} fellows",
            min_value=0,
            max_value=30,
            value=target_count,
            key=f"{year.value}_count",
        )
        updated_counts = cohort_counts.copy()
        updated_counts[year] = target_count
        _sync_fellows_by_year(
            config,
            updated_counts[TrainingYear.F1],
            updated_counts[TrainingYear.S2],
            updated_counts[TrainingYear.T3],
        )

        fellows_in_year = [
            (index, fellow)
            for index, fellow in enumerate(config.fellows)
            if fellow.training_year == year
        ]
        st.caption(f"{len(fellows_in_year)} fellows currently assigned to {year.value}.")

    with st.container(border=True):
        cohort_limits = [
            rule
            for rule in config.cohort_limit_rules
            if _is_exact_year_rule(rule.applicable_years, year)
        ]
        config.cohort_limit_rules = _merge_year_rules(
            config.cohort_limit_rules,
            _render_cohort_limit_rules_editor(
                cohort_limits,
                key_prefix=f"{year.value}_cohort_limits",
                title="Cohort Schedule Limits",
                caption="Includes same-year PTO caps and any other concurrent cohort state limits.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year),
        )

    with st.container(border=True):
        pto_window_rules = [
            rule
            for rule in config.week_count_rules
            if _is_exact_year_rule(rule.applicable_years, year)
            and _is_pto_rule(rule.block_names)
        ]
        config.week_count_rules = _merge_year_rules(
            config.week_count_rules,
            _render_week_count_rules_editor(
                pto_window_rules,
                key_prefix=f"{year.value}_pto_windows",
                title="Cohort PTO Windows",
                caption="Use PTO week-count rules to encode cohort-specific PTO restricted windows.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year)
            and _is_pto_rule(rule.block_names),
        )

    with st.container(border=True):
        st.markdown(f"#### {year.value} Block Rules")
        st.caption(
            "These are the exact single-cohort hard rules wired into the solver for "
            f"{year.value}. Shared multi-cohort rules stay in Program Setup."
        )

        exact_coverage = [
            rule
            for rule in config.coverage_rules
            if _is_exact_year_rule(rule.eligible_years, year)
        ]
        config.coverage_rules = _merge_coverage_rules(
            config.coverage_rules,
            _render_coverage_rules_editor(
                exact_coverage,
                key_prefix=f"{year.value}_coverage",
                title="Cohort Coverage Rules",
                caption="Weekly coverage windows owned by this cohort alone.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.eligible_years, year),
        )

        exact_eligibility = [
            rule
            for rule in config.eligibility_rules
            if _is_exact_year_rule(rule.allowed_years, year)
        ]
        config.eligibility_rules = _merge_eligibility_rules(
            config.eligibility_rules,
            _render_eligibility_rules_editor(
                exact_eligibility,
                key_prefix=f"{year.value}_eligibility",
                title="Cohort Eligibility Rules",
                caption="Exact single-cohort eligibility windows for this class year.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.allowed_years, year),
        )

        block_week_rules = [
            rule
            for rule in config.week_count_rules
            if _is_exact_year_rule(rule.applicable_years, year)
            and not _is_pto_rule(rule.block_names)
        ]
        config.week_count_rules = _merge_year_rules(
            config.week_count_rules,
            _render_week_count_rules_editor(
                block_week_rules,
                key_prefix=f"{year.value}_block_weeks",
                title="Per-Fellow Block Requirements",
                caption="Per-fellow min/max week targets for this cohort.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year)
            and not _is_pto_rule(rule.block_names),
        )

        prerequisite_rules = [
            rule
            for rule in config.prerequisite_rules
            if _is_exact_year_rule(rule.applicable_years, year)
        ]
        config.prerequisite_rules = _merge_year_rules(
            config.prerequisite_rules,
            _render_prerequisite_rules_editor(
                prerequisite_rules,
                key_prefix=f"{year.value}_prereq",
                title="Prerequisite Rules",
                caption="Require prior exposure before a target rotation is allowed.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year),
        )

        transition_rules = [
            rule
            for rule in config.forbidden_transition_rules
            if _is_exact_year_rule(rule.applicable_years, year)
        ]
        config.forbidden_transition_rules = _merge_year_rules(
            config.forbidden_transition_rules,
            _render_transition_rules_editor(
                transition_rules,
                key_prefix=f"{year.value}_transition",
                title="Forbidden Transition Rules",
                caption="Forbid a target rotation immediately after specific prior blocks.",
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year),
        )

    with st.container(border=True):
        individual_rules = [
            rule
            for rule in config.individual_fellow_requirement_rules
            if rule.training_year == year
        ]
        config.individual_fellow_requirement_rules = _merge_year_rules(
            config.individual_fellow_requirement_rules,
            _render_individual_fellow_requirement_rules_editor(
                config,
                year,
                individual_rules,
                key_prefix=f"{year.value}_individual_fellow_requirements",
            ),
            predicate=lambda rule: rule.training_year == year,
        )

    with st.container(border=True):
        cohort_soft_rules = [
            rule
            for rule in config.soft_sequence_rules
            if _is_exact_year_rule(rule.applicable_years, year)
        ]
        config.soft_sequence_rules = _merge_year_rules(
            config.soft_sequence_rules,
            _render_soft_sequence_rules_editor(
                cohort_soft_rules,
                key_prefix=f"{year.value}_soft",
                title=f"{year.value} Weighted Soft Rules",
                caption=(
                    f"Weighted bonuses or penalties applied only to {year.value} schedules."
                ),
                fixed_years=[year],
            ),
            predicate=lambda rule: _is_exact_year_rule(rule.applicable_years, year),
        )

    with st.container(border=True):
        _render_pto_preference_weights_editor(config, year)


def _render_summary_table(title: str, rows: list[dict[str, object]]) -> None:
    """Render a read-only dataframe summary."""

    st.markdown(f"**{title}**")
    if not rows:
        st.caption("No rules configured.")
        return
    numeric_columns = [
        column
        for column in (
            "Min Fellows",
            "Max Fellows",
            "Start Week",
            "End Week",
            "Min Weeks",
            "Max Weeks",
            "Max Fellows",
            "Min Each",
        )
        if column in rows[0]
    ]
    st.dataframe(
        _build_dataframe(rows, list(rows[0].keys()), nullable_int_columns=numeric_columns),
        use_container_width=True,
        hide_index=True,
    )


def _render_fellow_editors(config: ScheduleConfig, year: TrainingYear) -> None:
    """Render roster and PTO editors for one cohort."""

    fellows = [
        (index, fellow)
        for index, fellow in enumerate(config.fellows)
        if fellow.training_year == year
    ]
    week_options = _build_week_options(config)

    st.markdown("**Roster Names**")
    st.caption(f"Edit the fellow names for {year.value}.")
    roster_rows = [
        {
            "Slot": idx + 1,
            "Name": fellow.name.strip(),
        }
        for idx, (_, fellow) in enumerate(fellows)
    ]
    edited_roster = st.data_editor(
        _build_dataframe(roster_rows, ["Slot", "Name"]),
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key=f"{year.value}_roster_names_editor",
        column_config={
            "Slot": st.column_config.NumberColumn("Slot", disabled=True, format="%d"),
            "Name": st.column_config.TextColumn("Name"),
        },
    )
    for idx, (fellow_idx, fellow) in enumerate(fellows):
        fallback_name = f"{year.value} Fellow {idx + 1}"
        fellow.name = str(edited_roster.at[idx, "Name"]).strip() or fallback_name
        config.fellows[fellow_idx] = fellow

    st.markdown("**PTO Preferences and Availability**")
    st.caption(
        "Edit ranked PTO weeks and unavailable weeks for each fellow below."
    )
    for fellow_idx, fellow in fellows:
        with st.expander(f"👤 {fellow.name}", expanded=False):
            st.caption(
                f"Select up to {config.pto_weeks_to_rank} preferred PTO weeks, ranked best → worst."
            )

            current_labels: list[str] = []
            for week in fellow.pto_rankings:
                for label, week_idx in week_options.items():
                    if week == week_idx:
                        current_labels.append(label)
                        break
            selected_ranked = st.multiselect(
                "Ranked PTO weeks",
                options=list(week_options.keys()),
                default=current_labels,
                max_selections=config.pto_weeks_to_rank,
                key=f"{year.value}_fellow_pto_{fellow_idx}",
            )
            fellow.pto_rankings = [week_options[label] for label in selected_ranked]

            unavailable = st.multiselect(
                "Unavailable weeks",
                options=list(week_options.keys()),
                default=[
                    label
                    for label, week_idx in week_options.items()
                    if week_idx in fellow.unavailable_weeks
                ],
                key=f"{year.value}_fellow_unavailable_{fellow_idx}",
            )
            fellow.unavailable_weeks = [week_options[label] for label in unavailable]


def _render_pto_preference_weights_editor(
    config: ScheduleConfig,
    year: TrainingYear,
) -> None:
    """Render the cohort-level PTO objective weights."""

    st.markdown("**PTO Preference Weights**")
    st.caption(
        "These weights drive the PTO portion of the objective for this cohort. "
        "Higher values make a rank more valuable. Larger gaps between early ranks "
        "make top choices matter more."
    )

    weights = config.pto_preference_weights_for_year(year)
    rows = [
        {
            "Rank": f"#{rank + 1}",
            "Weight": weight,
        }
        for rank, weight in enumerate(weights)
    ]
    edited = st.data_editor(
        _build_dataframe(rows, ["Rank", "Weight"], nullable_int_columns=["Weight"]),
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key=f"{year.value}_pto_preference_weights_editor",
        column_config={
            "Rank": st.column_config.TextColumn("Rank", disabled=True),
        },
    )

    config.set_pto_preference_weights_for_year(
        year,
        [
            max(0, _to_int(row.get("Weight"), default=0))
            for row in edited.to_dict("records")
            if row.get("Rank")
        ],
    )

    max_ranked_score = sum(sorted(config.pto_preference_weights_for_year(year), reverse=True)[: config.pto_weeks_granted])
    st.caption(
        f"If all {config.pto_weeks_granted} PTO weeks for {year.value} landed on the "
        f"highest-weight ranked choices, that cohort member could contribute up to "
        f"{max_ranked_score} PTO objective points before any soft-rule bonuses."
    )


def _render_individual_fellow_requirement_rules_editor(
    config: ScheduleConfig,
    year: TrainingYear,
    rules: list[IndividualFellowRequirementRule],
    *,
    key_prefix: str,
) -> list[IndividualFellowRequirementRule]:
    """Render exact named-fellow hard requirements for one cohort."""

    st.markdown("**Individual Fellow Requirements**")
    st.caption(
        "Use this for named-fellow hard rules such as one fellow needing an exact "
        "number of weeks on a specific rotation."
    )

    fellow_names = [
        fellow.name
        for fellow in config.fellows
        if fellow.training_year == year
    ]
    block_names = [block.name for block in config.blocks]
    if not fellow_names:
        st.info(f"No fellows are available in {year.value} to attach individual rules.")
        return []
    if not block_names:
        st.info("No rotations are available yet. Add block metadata first.")
        return []

    columns = ["Fellow", "Rotation", "Min Weeks", "Max Weeks", "Active"]
    rows = [
        {
            "Fellow": rule.fellow_name,
            "Rotation": rule.block_name,
            "Min Weeks": rule.min_weeks,
            "Max Weeks": rule.max_weeks,
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Min Weeks", "Max Weeks"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
        column_config={
            "Fellow": st.column_config.SelectboxColumn(
                "Fellow",
                options=fellow_names,
                required=True,
            ),
            "Rotation": st.column_config.SelectboxColumn(
                "Rotation",
                options=block_names,
                required=True,
            ),
        },
    )

    invalid_rows: list[str] = []
    updated_rules: list[IndividualFellowRequirementRule] = []
    for row in edited.to_dict("records"):
        fellow_name = str(row.get("Fellow") or "").strip()
        block_name = str(row.get("Rotation") or "").strip()
        if not fellow_name or not block_name:
            continue
        if fellow_name not in fellow_names or block_name not in block_names:
            invalid_rows.append(f"{fellow_name or '<blank>'} / {block_name or '<blank>'}")
            continue
        updated_rules.append(
            IndividualFellowRequirementRule(
                training_year=year,
                fellow_name=fellow_name,
                block_name=block_name,
                min_weeks=_to_int(row.get("Min Weeks"), default=0),
                max_weeks=_to_int(row.get("Max Weeks"), default=52),
                is_active=bool(row.get("Active", True)),
            )
        )

    if invalid_rows:
        st.error(
            "Skipped invalid individual-fellow rows because the fellow or rotation "
            f"no longer exists in the live roster/catalog: {', '.join(invalid_rows)}"
        )

    return updated_rules


def _render_block_metadata_editor(
    blocks: list[BlockConfig],
    *,
    key_prefix: str,
) -> list[BlockConfig]:
    """Render the global block metadata editor."""

    rows = [
        {
            "Name": block.name,
            "Type": block.block_type.value,
            "Active": block.is_active,
            "Hours/Week": block.hours_per_week,
            "Weekend Off": block.has_weekend_off,
            "Requires Call Coverage": block.requires_call_coverage,
            "Legacy Fellows Needed": block.fellows_needed,
            "Legacy Min Weeks": block.min_weeks,
            "Legacy Max Weeks": block.max_weeks,
        }
        for block in blocks
    ]
    columns = [
        "Name",
        "Type",
        "Active",
        "Hours/Week",
        "Weekend Off",
        "Requires Call Coverage",
        "Legacy Fellows Needed",
        "Legacy Min Weeks",
        "Legacy Max Weeks",
    ]
    edited = st.data_editor(
        pd.DataFrame(rows, columns=columns),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
        column_config={
            "Type": st.column_config.SelectboxColumn(
                "Type",
                options=[block_type.value for block_type in BlockType],
                required=True,
            ),
        },
    )
    updated_blocks: list[BlockConfig] = []
    for row in edited.to_dict("records"):
        if not row.get("Name"):
            continue
        updated_blocks.append(
            BlockConfig(
                name=str(row["Name"]).strip(),
                block_type=BlockType(
                    str(row.get("Type") or BlockType.DAY.value).strip()
                ),
                fellows_needed=_to_int(row.get("Legacy Fellows Needed"), default=0),
                hours_per_week=_to_float(row.get("Hours/Week"), default=60.0),
                min_weeks=_to_int(row.get("Legacy Min Weeks"), default=0),
                max_weeks=_to_int(row.get("Legacy Max Weeks"), default=52),
                is_active=bool(row.get("Active", True)),
                has_weekend_off=bool(row.get("Weekend Off", False)),
                requires_call_coverage=bool(row.get("Requires Call Coverage", False)),
            )
        )
    return updated_blocks


def _render_coverage_rules_editor(
    rules: list[CoverageRule],
    *,
    key_prefix: str,
    title: str = "Coverage Rules",
    caption: str = "Per-week staffing targets by block, cohort, and date window.",
) -> list[CoverageRule]:
    """Render a coverage-rule editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    st.caption("Week windows in this table use human-readable week numbers starting at 1.")
    columns = [
        "Name",
        "Block",
        "Eligible Years",
        "Min Fellows",
        "Max Fellows",
        "Start Week",
        "End Week",
        "Active",
    ]
    rows = [
        {
            "Name": rule.name,
            "Block": rule.block_name,
            "Eligible Years": _years_to_text(rule.eligible_years),
            "Min Fellows": rule.min_fellows,
            "Max Fellows": rule.max_fellows,
            "Start Week": _display_week_index(rule.start_week),
            "End Week": _display_optional_week_index(rule.end_week),
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Min Fellows", "Max Fellows", "Start Week", "End Week"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[CoverageRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Block"):
            continue
        updated_rules.append(
            CoverageRule(
                name=str(row["Name"]).strip(),
                block_name=str(row["Block"]).strip(),
                eligible_years=_parse_years(row.get("Eligible Years")),
                min_fellows=_to_int(row.get("Min Fellows"), default=0),
                max_fellows=_to_optional_int(row.get("Max Fellows")),
                start_week=_to_zero_based_week_index(row.get("Start Week"), default=0),
                end_week=_to_optional_zero_based_week_index(row.get("End Week")),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_eligibility_rules_editor(
    rules: list[EligibilityRule],
    *,
    key_prefix: str,
    title: str = "Eligibility Rules",
    caption: str = "Restrict which cohorts may ever be assigned to specific blocks.",
) -> list[EligibilityRule]:
    """Render an eligibility-rule editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    st.caption("Week windows in this table use human-readable week numbers starting at 1.")
    columns = ["Name", "Blocks", "Allowed Years", "Start Week", "End Week", "Active"]
    rows = [
        {
            "Name": rule.name,
            "Blocks": _list_to_text(rule.block_names),
            "Allowed Years": _years_to_text(rule.allowed_years),
            "Start Week": _display_week_index(rule.start_week),
            "End Week": _display_optional_week_index(rule.end_week),
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Start Week", "End Week"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[EligibilityRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Blocks"):
            continue
        updated_rules.append(
            EligibilityRule(
                name=str(row["Name"]).strip(),
                block_names=_parse_list(row.get("Blocks")),
                allowed_years=_parse_years(row.get("Allowed Years")),
                start_week=_to_zero_based_week_index(row.get("Start Week"), default=0),
                end_week=_to_optional_zero_based_week_index(row.get("End Week")),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_week_count_rules_editor(
    rules: list[WeekCountRule],
    *,
    key_prefix: str,
    title: str = "Week Count Rules",
    caption: str = "Minimum / maximum block counts per fellow or per cohort.",
) -> list[WeekCountRule]:
    """Render a week-count editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    st.caption("Week windows in this table use human-readable week numbers starting at 1.")
    columns = [
        "Name",
        "Years",
        "Blocks",
        "Min Weeks",
        "Max Weeks",
        "Start Week",
        "End Week",
        "Each Fellow",
        "Active",
    ]
    rows = [
        {
            "Name": rule.name,
            "Years": _years_to_text(rule.applicable_years),
            "Blocks": _list_to_text(rule.block_names),
            "Min Weeks": rule.min_weeks,
            "Max Weeks": rule.max_weeks,
            "Start Week": _display_week_index(rule.start_week),
            "End Week": _display_optional_week_index(rule.end_week),
            "Each Fellow": rule.applies_to_each_fellow,
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Min Weeks", "Max Weeks", "Start Week", "End Week"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[WeekCountRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Blocks"):
            continue
        updated_rules.append(
            WeekCountRule(
                name=str(row["Name"]).strip(),
                applicable_years=_parse_years(row.get("Years")),
                block_names=_parse_list(row.get("Blocks")),
                min_weeks=_to_int(row.get("Min Weeks"), default=0),
                max_weeks=_to_int(row.get("Max Weeks"), default=52),
                start_week=_to_zero_based_week_index(row.get("Start Week"), default=0),
                end_week=_to_optional_zero_based_week_index(row.get("End Week")),
                applies_to_each_fellow=bool(row.get("Each Fellow", True)),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_cohort_limit_rules_editor(
    rules: list[CohortLimitRule],
    *,
    key_prefix: str,
    title: str = "Cohort Limit Rules",
    caption: str = "Limit concurrent PTO or other states within a single cohort.",
) -> list[CohortLimitRule]:
    """Render a cohort-limit editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    st.caption("Week windows in this table use human-readable week numbers starting at 1.")
    columns = ["Name", "Years", "State", "Max Fellows", "Start Week", "End Week", "Active"]
    rows = [
        {
            "Name": rule.name,
            "Years": _years_to_text(rule.applicable_years),
            "State": rule.state_name,
            "Max Fellows": rule.max_fellows,
            "Start Week": _display_week_index(rule.start_week),
            "End Week": _display_optional_week_index(rule.end_week),
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Max Fellows", "Start Week", "End Week"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[CohortLimitRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("State"):
            continue
        updated_rules.append(
            CohortLimitRule(
                name=str(row["Name"]).strip(),
                applicable_years=_parse_years(row.get("Years")),
                state_name=str(row["State"]).strip(),
                max_fellows=_to_int(row.get("Max Fellows"), default=0),
                start_week=_to_zero_based_week_index(row.get("Start Week"), default=0),
                end_week=_to_optional_zero_based_week_index(row.get("End Week")),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_prerequisite_rules_editor(
    rules: list[PrerequisiteRule],
    *,
    key_prefix: str,
    title: str = "Prerequisite Rules",
    caption: str = "Require prior block exposure before a target rotation starts.",
) -> list[PrerequisiteRule]:
    """Render a prerequisite-rule editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    columns = ["Name", "Years", "Target Block", "Prerequisites", "Min Each", "Active"]
    rows = [
        {
            "Name": rule.name,
            "Years": _years_to_text(rule.applicable_years),
            "Target Block": rule.target_block,
            "Prerequisites": _list_to_text(rule.prerequisite_blocks),
            "Min Each": rule.prerequisite_min_weeks,
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        pd.DataFrame(rows, columns=columns),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[PrerequisiteRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Target Block"):
            continue
        updated_rules.append(
            PrerequisiteRule(
                name=str(row["Name"]).strip(),
                applicable_years=_parse_years(row.get("Years")),
                target_block=str(row["Target Block"]).strip(),
                prerequisite_blocks=_parse_list(row.get("Prerequisites")),
                prerequisite_min_weeks=_to_int(row.get("Min Each"), default=1),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_transition_rules_editor(
    rules: list[ForbiddenTransitionRule],
    *,
    key_prefix: str,
    title: str = "Forbidden Transition Rules",
    caption: str = "Forbid a target block immediately after specific prior blocks.",
) -> list[ForbiddenTransitionRule]:
    """Render a forbidden-transition editor."""

    st.markdown(f"**{title}**")
    st.caption(caption)
    columns = ["Name", "Years", "Target Block", "Forbidden Previous", "Active"]
    rows = [
        {
            "Name": rule.name,
            "Years": _years_to_text(rule.applicable_years),
            "Target Block": rule.target_block,
            "Forbidden Previous": _list_to_text(rule.forbidden_previous_blocks),
            "Active": rule.is_active,
        }
        for rule in rules
    ]
    edited = st.data_editor(
        pd.DataFrame(rows, columns=columns),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
    )
    updated_rules: list[ForbiddenTransitionRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Target Block"):
            continue
        updated_rules.append(
            ForbiddenTransitionRule(
                name=str(row["Name"]).strip(),
                applicable_years=_parse_years(row.get("Years")),
                target_block=str(row["Target Block"]).strip(),
                forbidden_previous_blocks=_parse_list(row.get("Forbidden Previous")),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _render_soft_sequence_rules_editor(
    rules: list[SoftSequenceRule],
    *,
    key_prefix: str,
    title: str = "Weighted Soft Rules",
    caption: str = (
        "Each time the adjacent sequence matches, the solver adds the configured "
        "weight to the objective. Positive = bonus. Negative = penalty."
    ),
    fixed_years: list[TrainingYear] | None = None,
) -> list[SoftSequenceRule]:
    """Render the weighted soft-rule table."""

    show_years = fixed_years is None

    st.markdown(f"**{title}**")
    st.caption(caption)
    st.caption("Week windows in this table use human-readable week numbers starting at 1.")
    columns = [
        "Name",
        "Left States",
        "Right States",
        "Direction",
        "Weight",
        "Effect",
        "Start Week",
        "End Week",
        "Active",
    ]
    if show_years:
        columns.insert(1, "Years")
    rows = [
        {
            "Name": rule.name,
            "Left States": _list_to_text(rule.left_states),
            "Right States": _list_to_text(rule.right_states),
            "Direction": rule.direction.value,
            "Weight": rule.weight,
            "Effect": "Bonus" if rule.weight >= 0 else "Penalty",
            "Start Week": _display_week_index(rule.start_week),
            "End Week": _display_optional_week_index(rule.end_week),
            "Active": rule.is_active,
            **(
                {"Years": _years_to_text(rule.applicable_years)}
                if show_years
                else {}
            ),
        }
        for rule in rules
    ]
    edited = st.data_editor(
        _build_dataframe(
            rows,
            columns,
            nullable_int_columns=["Weight", "Start Week", "End Week"],
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_prefix}_editor",
        column_config={
            "Direction": st.column_config.SelectboxColumn(
                "Direction",
                options=[
                    SoftRuleDirection.FORWARD.value,
                    SoftRuleDirection.EITHER.value,
                ],
                required=True,
            ),
            "Effect": st.column_config.TextColumn("Effect", disabled=True),
        },
    )
    updated_rules: list[SoftSequenceRule] = []
    for row in edited.to_dict("records"):
        if not row.get("Name") or not row.get("Left States") or not row.get("Right States"):
            continue
        direction = str(row.get("Direction") or SoftRuleDirection.FORWARD.value).strip()
        if direction not in {
            SoftRuleDirection.FORWARD.value,
            SoftRuleDirection.EITHER.value,
        }:
            direction = SoftRuleDirection.FORWARD.value
        updated_rules.append(
            SoftSequenceRule(
                name=str(row["Name"]).strip(),
                applicable_years=(
                    fixed_years.copy()
                    if fixed_years is not None
                    else _parse_years(row.get("Years"))
                ),
                left_states=_parse_list(row.get("Left States")),
                right_states=_parse_list(row.get("Right States")),
                weight=_to_int(row.get("Weight"), default=0),
                direction=SoftRuleDirection(direction),
                start_week=_to_zero_based_week_index(row.get("Start Week"), default=0),
                end_week=_to_optional_zero_based_week_index(row.get("End Week")),
                is_active=bool(row.get("Active", True)),
            )
        )
    return updated_rules


def _build_week_options(config: ScheduleConfig) -> dict[str, int]:
    """Return labeled week options for multiselect inputs."""

    week_options: dict[str, int] = {}
    for week in range(config.num_weeks):
        week_date = config.start_date + timedelta(weeks=week)
        week_options[f"W{week + 1}: {week_date.strftime('%b %d')}"] = week
    return week_options


def _sync_fellows_by_year(
    config: ScheduleConfig,
    f1_count: int,
    s2_count: int,
    t3_count: int,
) -> None:
    """Resize the roster by cohort while preserving existing fellow data."""

    existing_by_year = {
        year: [
            fellow
            for fellow in config.fellows
            if fellow.training_year == year
        ]
        for year in TrainingYear
    }
    target_counts = {
        TrainingYear.F1: f1_count,
        TrainingYear.S2: s2_count,
        TrainingYear.T3: t3_count,
    }

    new_fellows: list[FellowConfig] = []
    for year in TrainingYear:
        existing = existing_by_year[year]
        for idx in range(target_counts[year]):
            if idx < len(existing):
                fellow = existing[idx]
                fellow.training_year = year
                if not fellow.name.strip():
                    fellow.name = f"{year.value} Fellow {idx + 1}"
                new_fellows.append(fellow)
            else:
                new_fellows.append(
                    FellowConfig(
                        name=f"{year.value} Fellow {idx + 1}",
                        training_year=year,
                    )
                )
    config.fellows = new_fellows


def _select_shared_coverage_rules(rules: list[CoverageRule]) -> list[CoverageRule]:
    """Return coverage rules that are not exact single-cohort rules."""

    return [rule for rule in rules if _is_shared_coverage_rule(rule)]


def _select_shared_eligibility_rules(
    rules: list[EligibilityRule],
) -> list[EligibilityRule]:
    """Return eligibility rules that are not exact single-cohort rules."""

    return [rule for rule in rules if _is_shared_eligibility_rule(rule)]


def _select_shared_year_rules(rules: list[WeekCountRule]) -> list[WeekCountRule]:
    """Return year-scoped rules that span multiple cohorts."""

    return [rule for rule in rules if _is_shared_year_rule(rule)]


def _select_shared_soft_rules(rules: list[SoftSequenceRule]) -> list[SoftSequenceRule]:
    """Return weighted soft rules that span multiple cohorts."""

    return [rule for rule in rules if _is_shared_soft_rule(rule)]


def _merge_coverage_rules(
    original: list[CoverageRule],
    replacement: list[CoverageRule],
    *,
    predicate,
) -> list[CoverageRule]:
    """Replace a selected subset of coverage rules."""

    return [rule for rule in original if not predicate(rule)] + replacement


def _merge_eligibility_rules(
    original: list[EligibilityRule],
    replacement: list[EligibilityRule],
    *,
    predicate,
) -> list[EligibilityRule]:
    """Replace a selected subset of eligibility rules."""

    return [rule for rule in original if not predicate(rule)] + replacement


def _merge_year_rules(original: list, replacement: list, *, predicate) -> list:
    """Replace a selected subset of year-scoped rules."""

    return [rule for rule in original if not predicate(rule)] + replacement


def _is_exact_year_rule(years: list[TrainingYear], year: TrainingYear) -> bool:
    """Return True when the rule applies to exactly one cohort."""

    return len(years) == 1 and years[0] == year


def _is_shared_year_rule(rule) -> bool:
    """Return True when a rule spans multiple cohorts or all cohorts."""

    return len(rule.applicable_years) != 1


def _is_shared_soft_rule(rule: SoftSequenceRule) -> bool:
    """Return True when a weighted soft rule spans multiple cohorts."""

    return _is_shared_year_rule(rule)


def _is_shared_coverage_rule(rule: CoverageRule) -> bool:
    """Return True when a coverage rule is shared across cohorts."""

    return len(rule.eligible_years) != 1


def _is_shared_eligibility_rule(rule: EligibilityRule) -> bool:
    """Return True when an eligibility rule is shared across cohorts."""

    return len(rule.allowed_years) != 1


def _is_pto_rule(block_names: list[str]) -> bool:
    """Return True when a week-count rule only targets PTO."""

    return len(block_names) == 1 and block_names[0] == "PTO"


def _parse_list(value: object) -> list[str]:
    """Parse comma-separated values into a clean string list."""

    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_years(value: object) -> list[TrainingYear]:
    """Parse comma-separated training-year values."""

    mapping = {year.value.upper(): year for year in TrainingYear}
    years: list[TrainingYear] = []
    for item in _parse_list(value):
        year = mapping.get(item.upper())
        if year is not None:
            years.append(year)
    return years


def _years_to_text(years: list[TrainingYear]) -> str:
    """Render cohort enums as comma-separated text."""

    return ", ".join(year.value for year in years)


def _list_to_text(values: list[str]) -> str:
    """Render string lists as comma-separated text."""

    return ", ".join(values)


def _build_dataframe(
    rows: list[dict[str, object]],
    columns: list[str],
    *,
    nullable_int_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Build a dataframe with Arrow-friendly nullable integer columns."""

    df = pd.DataFrame(rows, columns=columns)
    for column in nullable_int_columns or []:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
    return df


def _display_week_index(week: int) -> int:
    """Convert an internal zero-based week index into a 1-based UI value."""

    return week + 1


def _display_optional_week_index(week: int | None) -> int | None:
    """Convert an optional internal zero-based week index for display."""

    if week is None:
        return None
    return _display_week_index(week)


def _to_zero_based_week_index(value: object, default: int) -> int:
    """Convert a displayed 1-based UI week back into the internal zero-based index."""

    if value in (None, "") or pd.isna(value):
        return default
    return max(0, int(value) - 1)


def _to_optional_zero_based_week_index(value: object) -> int | None:
    """Convert an optional displayed 1-based UI week back into zero-based form."""

    if value in (None, "") or pd.isna(value):
        return None
    return max(0, int(value) - 1)


def _to_int(value: object, default: int) -> int:
    """Best-effort integer conversion."""

    if value in (None, "") or pd.isna(value):
        return default
    return int(value)


def _to_optional_int(value: object) -> int | None:
    """Convert blank table cells into ``None``."""

    if value in (None, "") or pd.isna(value):
        return None
    return int(value)


def _to_float(value: object, default: float) -> float:
    """Best-effort float conversion."""

    if value in (None, "") or pd.isna(value):
        return default
    return float(value)
