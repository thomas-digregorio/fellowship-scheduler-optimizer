"""Configuration sidebar for the Streamlit dashboard."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from app.state import get_config, persist_config, set_config
from src.models import FellowConfig, ScheduleConfig, TrainingYear


def render_config_sidebar() -> None:
    """Render the sidebar controls."""

    config = get_config()
    config.num_fellows = len(config.fellows)

    st.sidebar.title("⚙️ Schedule Config")

    with st.sidebar.expander("📋 Global Settings", expanded=False):
        cohort_counts = config.cohort_counts
        f1_count = st.number_input(
            "F1 fellows",
            min_value=0,
            max_value=30,
            value=cohort_counts[TrainingYear.F1],
            key="cfg_f1_count",
        )
        s2_count = st.number_input(
            "S2 fellows",
            min_value=0,
            max_value=30,
            value=cohort_counts[TrainingYear.S2],
            key="cfg_s2_count",
        )
        t3_count = st.number_input(
            "T3 fellows",
            min_value=0,
            max_value=30,
            value=cohort_counts[TrainingYear.T3],
            key="cfg_t3_count",
        )
        _sync_fellows_by_year(config, f1_count, s2_count, t3_count)
        st.caption(f"Total fellows: {len(config.fellows)}")

        config.pto_weeks_granted = st.number_input(
            "PTO weeks granted",
            min_value=0,
            max_value=10,
            value=config.pto_weeks_granted,
            key="cfg_pto_granted",
        )
        config.pto_weeks_to_rank = st.number_input(
            "PTO weeks to rank",
            min_value=config.pto_weeks_granted,
            max_value=15,
            value=config.pto_weeks_to_rank,
            key="cfg_pto_rank",
        )
        config.max_concurrent_pto = st.number_input(
            "Global max fellows on PTO",
            min_value=1,
            max_value=max(1, len(config.fellows)),
            value=config.max_concurrent_pto,
            key="cfg_max_pto",
        )
        config.solver_timeout_seconds = st.number_input(
            "Solver timeout (seconds)",
            min_value=10.0,
            max_value=600.0,
            value=config.solver_timeout_seconds,
            step=10.0,
            key="cfg_timeout",
        )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Block Metadata")
    st.sidebar.caption(
        "Cohort-specific staffing and min/max week rules are managed in the "
        "**Rules** tab."
    )

    for block_idx, block in enumerate(config.blocks):
        with st.sidebar.expander(block.name, expanded=False):
            block.is_active = st.checkbox(
                "Active",
                value=block.is_active,
                key=f"blk_active_{block_idx}",
            )
            block.hours_per_week = st.number_input(
                "Hours/week",
                min_value=0.0,
                max_value=100.0,
                value=block.hours_per_week,
                step=5.0,
                key=f"blk_hours_{block_idx}",
            )
            block.has_weekend_off = st.checkbox(
                "Weekend off",
                value=block.has_weekend_off,
                key=f"blk_wknd_{block_idx}",
            )
            block.requires_call_coverage = st.checkbox(
                "Needs call coverage",
                value=block.requires_call_coverage,
                key=f"blk_call_{block_idx}",
            )

    st.sidebar.markdown("---")
    with st.sidebar.expander("📞 24-Hr Call Settings", expanded=False):
        config.call_day = st.selectbox(
            "Call day",
            options=["saturday", "sunday", "friday"],
            index=["saturday", "sunday", "friday"].index(config.call_day),
            key="cfg_call_day",
        )
        config.call_hours = st.number_input(
            "Call hours",
            min_value=0.0,
            max_value=48.0,
            value=config.call_hours,
            step=1.0,
            key="cfg_call_hours",
        )
        config.max_consecutive_night_float = st.number_input(
            "Max consecutive Night Float weeks",
            min_value=1,
            max_value=6,
            value=config.max_consecutive_night_float,
            key="cfg_max_nf",
        )
        all_block_names = [block.name for block in config.blocks] + ["PTO"]
        config.call_excluded_blocks = st.multiselect(
            "Blocks excluded from call",
            options=all_block_names,
            default=[
                block_name
                for block_name in config.call_excluded_blocks
                if block_name in all_block_names
            ],
            key="cfg_call_excluded",
        )

    st.sidebar.markdown("---")
    st.sidebar.subheader("👤 Fellow PTO Rankings")
    _render_fellow_sections(config)

    config.num_fellows = len(config.fellows)
    set_config(config)

    if st.sidebar.button("💾 Save Config", use_container_width=True):
        persist_config()
        st.sidebar.success("Configuration saved.")
def _render_fellow_sections(config: ScheduleConfig) -> None:
    """Render fellow PTO editors grouped by cohort."""

    for year in TrainingYear:
        fellows = [
            (index, fellow)
            for index, fellow in enumerate(config.fellows)
            if fellow.training_year == year
        ]
        if not fellows:
            continue
        with st.sidebar.expander(f"{year.value} Fellows", expanded=False):
            for fellow_idx, fellow in fellows:
                st.markdown(f"**{fellow.name}**")
                fellow.name = st.text_input(
                    "Name",
                    value=fellow.name.strip(),
                    key=f"fellow_name_{fellow_idx}",
                )
                st.caption(
                    f"Select up to {config.pto_weeks_to_rank} preferred PTO "
                    f"weeks, ranked best → worst"
                )
                week_options: dict[str, int] = {}
                for week in range(config.num_weeks):
                    week_date = config.start_date + timedelta(weeks=week)
                    week_options[
                        f"W{week + 1}: {week_date.strftime('%b %d')}"
                    ] = week
                current_labels: list[str] = []
                for week in fellow.pto_rankings:
                    for label, idx in week_options.items():
                        if idx == week:
                            current_labels.append(label)
                            break
                selected = st.multiselect(
                    "Ranked PTO weeks",
                    options=list(week_options.keys()),
                    default=current_labels,
                    max_selections=config.pto_weeks_to_rank,
                    key=f"fellow_pto_{fellow_idx}",
                )
                fellow.pto_rankings = [week_options[label] for label in selected]

                unavailable = st.multiselect(
                    "Unavailable weeks",
                    options=list(week_options.keys()),
                    default=[
                        label
                        for label, idx in week_options.items()
                        if idx in fellow.unavailable_weeks
                    ],
                    key=f"fellow_unavailable_{fellow_idx}",
                )
                fellow.unavailable_weeks = [week_options[label] for label in unavailable]
                st.markdown("---")


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
