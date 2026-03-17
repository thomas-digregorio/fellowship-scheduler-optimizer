"""PTO calendar panel."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.models import ScheduleConfig, ScheduleResult


def render_pto_calendar(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render PTO rankings and granted PTO for each fellow."""

    st.subheader("📅 PTO Calendar")

    if not config.fellows:
        st.info("No fellows configured yet.")
        return

    for fellow_idx, fellow in enumerate(config.fellows):
        with st.expander(
            f"👤 {fellow.name} ({fellow.training_year.value})",
            expanded=False,
        ):
            granted_weeks: set[int] = set()
            if result and result.assignments:
                for week in range(config.num_weeks):
                    if result.assignments[fellow_idx][week] == "PTO":
                        granted_weeks.add(week)

            ranked_weeks = set(fellow.pto_rankings)
            if fellow.pto_rankings:
                for rank, week_idx in enumerate(fellow.pto_rankings):
                    week_date = config.start_date + timedelta(weeks=week_idx)
                    label = f"W{week_idx + 1}: {week_date.strftime('%b %d')}"
                    if week_idx in config.pto_blackout_weeks:
                        st.markdown(f"~~{rank + 1}. {label}~~ 🚫 *global blackout*")
                    elif week_idx in granted_weeks:
                        st.markdown(f"**{rank + 1}. {label}** ✅ *granted*")
                    else:
                        st.markdown(f"{rank + 1}. {label} ⏳ *requested*")
            else:
                st.caption("No PTO weeks ranked yet.")

            if result:
                matches = len(granted_weeks & ranked_weeks)
                st.caption(
                    f"Granted: {len(granted_weeks)}/{config.pto_weeks_granted} | "
                    f"Matched preferences: {matches}/{len(ranked_weeks)}"
                )

    if result:
        st.markdown("---")
        st.markdown("**📊 PTO Summary**")
        pto_per_week = [0] * config.num_weeks
        for fellow_idx in range(config.num_fellows):
            for week in range(config.num_weeks):
                if result.assignments[fellow_idx][week] == "PTO":
                    pto_per_week[week] += 1
        max_concurrent = max(pto_per_week) if pto_per_week else 0
        st.metric("Max concurrent PTO", max_concurrent)
        st.metric("Objective score", f"{result.objective_value:.0f}")
