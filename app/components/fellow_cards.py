"""Per-fellow schedule cards."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult


def render_fellow_cards(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render one schedule summary card per fellow."""

    st.subheader("👥 Fellow Breakdown")

    if result is None:
        st.info("Generate a schedule to see fellow details.")
        return

    for fellow_idx, _fellow in enumerate(config.fellows):
        _render_single_card(config, result, fellow_idx)


def _render_single_card(
    config: ScheduleConfig,
    result: ScheduleResult,
    fellow_idx: int,
) -> None:
    """Render a single fellow's schedule card."""

    fellow = config.fellows[fellow_idx]
    assignments = result.assignments[fellow_idx]
    calls = result.call_assignments[fellow_idx]

    blocks_done = {assignment for assignment in assignments if assignment not in {"PTO", ""}}
    pto_weeks = assignments.count("PTO")
    call_count = sum(calls)
    working_weeks = config.num_weeks - pto_weeks

    total_hours = 0.0
    block_hours_map = {block.name: block.hours_per_week for block in config.blocks}
    for week in range(config.num_weeks):
        total_hours += block_hours_map.get(assignments[week], 0.0)
        if calls[week]:
            total_hours += config.call_hours
    avg_hours = total_hours / working_weeks if working_weeks > 0 else 0

    required_blocks = _required_blocks_for_fellow(config, fellow_idx)
    missing_blocks = required_blocks - blocks_done

    with st.expander(
        f"👤 {fellow.name} ({fellow.training_year.value})"
        f" — {len(blocks_done)}/{len(required_blocks) if required_blocks else 0} required"
        f" | {pto_weeks} PTO | {call_count} calls",
        expanded=False,
    ):
        metric_left, metric_middle, metric_right = st.columns(3)
        metric_left.metric("Working weeks", working_weeks)
        metric_middle.metric("Avg hrs/week", f"{avg_hours:.0f}")
        metric_right.metric("24-hr calls", call_count)

        if required_blocks:
            if missing_blocks:
                st.warning(
                    f"⚠️ Missing required blocks: {', '.join(sorted(missing_blocks))}"
                )
            else:
                st.success("✅ All cohort-specific required blocks completed")
        else:
            st.caption("No explicit cohort-specific required blocks are configured.")

        st.markdown("**Weekly Schedule:**")
        weeks_per_row = 13
        for row_start in range(0, config.num_weeks, weeks_per_row):
            row_end = min(row_start + weeks_per_row, config.num_weeks)
            columns = st.columns(weeks_per_row)
            for week in range(row_start, row_end):
                column = columns[week - row_start]
                block_name = assignments[week]
                color = BLOCK_COLORS.get(block_name, "#FFFFFF")
                week_date = config.start_date + timedelta(weeks=week)
                abbreviation = _short_name(block_name)
                if calls[week]:
                    abbreviation += "📞"
                column.markdown(
                    f'<div style="background-color:{color}; color:white; '
                    f'text-align:center; padding:2px; border-radius:3px; '
                    f'font-size:0.65em; margin:1px 0;" '
                    f'title="W{week + 1}: {block_name} '
                    f'({week_date.strftime("%b %d")})">'
                    f"W{week + 1}<br>{abbreviation}</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("**Block Distribution:**")
        block_counts: dict[str, int] = {}
        for assignment in assignments:
            block_counts[assignment] = block_counts.get(assignment, 0) + 1
        parts = [
            f"**{block_name}**: {count}w"
            for block_name, count in sorted(block_counts.items(), key=lambda item: -item[1])
        ]
        st.markdown(" · ".join(parts))


def _required_blocks_for_fellow(
    config: ScheduleConfig,
    fellow_idx: int,
) -> set[str]:
    """Return blocks with a positive per-fellow minimum for this cohort."""

    fellow = config.fellows[fellow_idx]
    required_blocks = {
        block_name
        for rule in config.week_count_rules
        if (
            rule.is_active
            and rule.applies_to_each_fellow
            and rule.min_weeks > 0
            and fellow.training_year in set(rule.applicable_years)
        )
        for block_name in rule.block_names
        if block_name != "PTO"
    }
    return required_blocks


def _short_name(block_name: str) -> str:
    """Abbreviate block names for compact card display."""

    abbreviations = {
        "White Consults": "Wht",
        "SRC Consults": "SRC",
        "VA Consults": "VAC",
        "Goodyer Consults": "Goo",
        "Night Float": "NF",
        "CCU": "CCU",
        "EP": "EP",
        "CHF": "CHF",
        "Yale Nuclear": "YNu",
        "VA Nuclear": "VNu",
        "Yale Echo": "YEc",
        "VA Echo": "VEc",
        "SRC Echo": "SEc",
        "Yale Cath": "YCa",
        "VA Cath": "VCa",
        "SRC Cath": "SCa",
        "Research": "Res",
        "CT-MRI": "MRI",
        "Elective": "Ele",
        "PTO": "PTO",
    }
    return abbreviations.get(block_name, block_name[:3])
