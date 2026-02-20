"""Right panel: Fellow Cards.

Displays a scrollable card for each fellow showing their week-by-week
schedule, total hours, blocks completed, and call assignments.
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult


def render_fellow_cards(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render the per-fellow breakdown cards.

    Parameters
    ----------
    config : ScheduleConfig
        Current configuration.
    result : ScheduleResult or None
        Solver output.
    """
    st.subheader("👥 Fellow Breakdown")

    if result is None:
        st.info("Generate a schedule to see fellow details.")
        return

    for f_idx, fellow in enumerate(config.fellows):
        _render_single_card(config, result, f_idx)


def _render_single_card(
    config: ScheduleConfig,
    result: ScheduleResult,
    f_idx: int,
) -> None:
    """Render a single fellow's card showing their yearly schedule."""
    fellow = config.fellows[f_idx]
    assignments: list[str] = result.assignments[f_idx]
    calls: list[bool] = result.call_assignments[f_idx]

    # Compute summary stats
    blocks_done: set[str] = {
        a for a in assignments if a != "PTO" and a != ""
    }
    pto_weeks: int = assignments.count("PTO")
    call_count: int = sum(calls)
    working_weeks: int = config.num_weeks - pto_weeks

    # Calculate total hours (approximate)
    total_hours: float = 0.0
    block_hours_map: dict[str, float] = {
        b.name: b.hours_per_week for b in config.blocks
    }
    for w in range(config.num_weeks):
        block_name = assignments[w]
        total_hours += block_hours_map.get(block_name, 0.0)
        if calls[w]:
            total_hours += config.call_hours

    avg_hours: float = total_hours / working_weeks if working_weeks > 0 else 0

    # Check if all required blocks are completed
    required_blocks: set[str] = {
        b.name for b in config.blocks if b.is_active
    }
    missing_blocks: set[str] = required_blocks - blocks_done

    with st.expander(
        f"👤 {fellow.name} — {len(blocks_done)}/{len(required_blocks)} "
        f"blocks | {pto_weeks} PTO | {call_count} calls",
        expanded=False,
    ):
        # Summary metrics row
        col1, col2, col3 = st.columns(3)
        col1.metric("Working weeks", working_weeks)
        col2.metric("Avg hrs/week", f"{avg_hours:.0f}")
        col3.metric("24-hr calls", call_count)

        # Missing blocks warning
        if missing_blocks:
            st.warning(
                f"⚠️ Missing blocks: {', '.join(sorted(missing_blocks))}"
            )
        else:
            st.success("✅ All required blocks completed")

        # Week-by-week schedule as colored badges
        st.markdown("**Weekly Schedule:**")

        # Display in rows of 13 weeks (4 rows = 52 weeks)
        weeks_per_row: int = 13
        for row_start in range(0, config.num_weeks, weeks_per_row):
            row_end: int = min(row_start + weeks_per_row, config.num_weeks)
            cols = st.columns(weeks_per_row)

            for w in range(row_start, row_end):
                col = cols[w - row_start]
                block_name: str = assignments[w]
                color: str = BLOCK_COLORS.get(block_name, "#FFFFFF")
                week_date = config.start_date + timedelta(weeks=w)

                # Abbreviate for compact display
                abbrev: str = _short_name(block_name)
                if calls[w]:
                    abbrev += "📞"

                col.markdown(
                    f'<div style="background-color:{color}; color:white; '
                    f'text-align:center; padding:2px; border-radius:3px; '
                    f'font-size:0.65em; margin:1px 0;" '
                    f'title="W{w+1}: {block_name} ({week_date.strftime("%b %d")})">'
                    f'W{w+1}<br>{abbrev}</div>',
                    unsafe_allow_html=True,
                )

        # Block distribution table
        st.markdown("**Block Distribution:**")
        block_counts: dict[str, int] = {}
        for a in assignments:
            block_counts[a] = block_counts.get(a, 0) + 1

        dist_text: list[str] = []
        for block_name, count in sorted(
            block_counts.items(), key=lambda x: -x[1]
        ):
            dist_text.append(f"**{block_name}**: {count}w")
        st.markdown(" · ".join(dist_text))


def _short_name(block_name: str) -> str:
    """Abbreviate block names for compact card display."""
    abbrevs: dict[str, str] = {
        "Night Float": "NF",
        "CCU": "CCU",
        "Consult SRC": "CSR",
        "Consult Y": "CY",
        "Consult VA": "CVA",
        "Cath Y": "CaY",
        "Cath SRC": "CaS",
        "EP": "EP",
        "Echo Y": "EcY",
        "VA Echo": "VAE",
        "CHF": "CHF",
        "Nuc Y": "NuY",
        "VA Clinic": "VAC",
        "Research": "Res",
        "PTO": "PTO",
    }
    return abbrevs.get(block_name, block_name[:3])
