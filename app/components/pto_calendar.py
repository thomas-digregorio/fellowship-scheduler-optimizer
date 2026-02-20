"""Left panel: PTO Calendar.

Shows each fellow's PTO weeks at a glance. Granted PTO is highlighted,
ranked-but-not-granted weeks are shown dimmed, and blackout weeks are
marked with a strikethrough.
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult


def render_pto_calendar(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render the PTO calendar panel.

    Parameters
    ----------
    config : ScheduleConfig
        Current configuration (for fellow names, PTO rankings, blackouts).
    result : ScheduleResult or None
        Solver output (to show which PTO weeks were actually granted).
    """
    st.subheader("📅 PTO Calendar")

    if not config.fellows:
        st.info("No fellows configured yet.")
        return

    # Color constants
    pto_color: str = BLOCK_COLORS.get("PTO", "#BDC3C7")
    granted_bg: str = "#27AE60"   # green for granted
    ranked_bg: str = "#F39C12"    # amber for ranked but not granted
    blackout_bg: str = "#E74C3C"  # red for blackout

    for f_idx, fellow in enumerate(config.fellows):
        with st.expander(f"👤 {fellow.name}", expanded=True):
            # Determine which PTO weeks were actually granted
            granted_weeks: set[int] = set()
            if result and result.assignments:
                for w in range(config.num_weeks):
                    if result.assignments[f_idx][w] == "PTO":
                        granted_weeks.add(w)

            ranked_weeks: set[int] = set(fellow.pto_rankings)

            # Build a compact visual representation
            # Show each ranked week with its status
            if fellow.pto_rankings:
                for rank, week_idx in enumerate(fellow.pto_rankings):
                    week_date = config.start_date + timedelta(weeks=week_idx)
                    label = f"W{week_idx + 1}: {week_date.strftime('%b %d')}"

                    if week_idx in config.pto_blackout_weeks:
                        st.markdown(
                            f"~~{rank + 1}. {label}~~ 🚫 *blackout*"
                        )
                    elif week_idx in granted_weeks:
                        st.markdown(
                            f"**{rank + 1}. {label}** ✅ *granted*"
                        )
                    else:
                        st.markdown(
                            f"{rank + 1}. {label} ⏳ *requested*"
                        )
            else:
                st.caption("No PTO weeks ranked yet. Configure in sidebar →")

            # Summary stats
            if result:
                total_granted: int = len(granted_weeks)
                total_ranked: int = len(ranked_weeks)
                matches: int = len(granted_weeks & ranked_weeks)
                st.caption(
                    f"Granted: {total_granted}/{config.pto_weeks_granted} | "
                    f"Matched preferences: {matches}/{total_ranked}"
                )

    # Overall PTO summary
    if result:
        st.markdown("---")
        st.markdown("**📊 PTO Summary**")

        # Count PTO per week to check concurrency
        pto_per_week: list[int] = [0] * config.num_weeks
        for f_idx in range(config.num_fellows):
            for w in range(config.num_weeks):
                if result.assignments[f_idx][w] == "PTO":
                    pto_per_week[w] += 1

        max_concurrent: int = max(pto_per_week) if pto_per_week else 0
        total_satisfaction: float = result.objective_value

        st.metric("Max concurrent PTO", max_concurrent)
        st.metric("PTO satisfaction score", f"{total_satisfaction:.0f}")
