"""PTO calendar panel."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.models import ScheduleConfig, ScheduleResult, TrainingYear


def render_pto_calendar(
    config: ScheduleConfig,
    result: ScheduleResult | None,
) -> None:
    """Render PTO rankings and granted PTO for each fellow."""

    st.subheader("📅 PTO Calendar")

    if not config.fellows:
        st.info("No fellows configured yet.")
        return

    total_ranked = sum(len(fellow.pto_rankings) for fellow in config.fellows)
    matched_ranked = 0
    granted_pto = 0
    if result:
        for fellow_idx, fellow in enumerate(config.fellows):
            granted_weeks = {
                week
                for week in range(config.num_weeks)
                if result.assignments[fellow_idx][week] == "PTO"
            }
            granted_pto += len(granted_weeks)
            matched_ranked += len(granted_weeks & set(fellow.pto_rankings))

    summary_left, summary_middle, summary_right = st.columns(3)
    summary_left.metric("Ranked requests", total_ranked)
    summary_middle.metric("Matched ranked PTO", matched_ranked if result else 0)
    summary_right.metric("Granted PTO weeks", granted_pto if result else 0)

    for year in TrainingYear:
        fellows_in_year = [
            (index, fellow)
            for index, fellow in enumerate(config.fellows)
            if fellow.training_year == year
        ]
        if not fellows_in_year:
            continue

        with st.container(border=True):
            st.markdown(f"#### {year.value} PTO")
            for fellow_idx, fellow in fellows_in_year:
                with st.expander(f"👤 {fellow.name}", expanded=False):
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
                            if week_idx in granted_weeks:
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
