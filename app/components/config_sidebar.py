"""Configuration sidebar for the Streamlit dashboard.

Renders all configurable parameters in ``st.sidebar``:
- Block settings (fellows needed, hours, min/max weeks, etc.)
- PTO settings (blackout weeks, max concurrent, ranking count)
- Call settings (excluded blocks, call day)
- Action buttons (Generate Schedule, Export, Re-solve)
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src.models import BlockConfig, BlockType, FellowConfig, ScheduleConfig
from state import get_config, set_config, persist_config


def render_config_sidebar() -> None:
    """Render the full configuration sidebar."""
    config: ScheduleConfig = get_config()

    st.sidebar.title("⚙️ Schedule Config")

    # ── Global Settings ──────────────────────────────────────────────
    with st.sidebar.expander("📋 Global Settings", expanded=False):
        config.num_fellows = st.number_input(
            "Number of fellows", min_value=1, max_value=20,
            value=config.num_fellows, key="cfg_num_fellows",
        )
        config.pto_weeks_granted = st.number_input(
            "PTO weeks granted", min_value=0, max_value=10,
            value=config.pto_weeks_granted, key="cfg_pto_granted",
        )
        config.pto_weeks_to_rank = st.number_input(
            "PTO weeks to rank", min_value=config.pto_weeks_granted,
            max_value=15, value=config.pto_weeks_to_rank,
            key="cfg_pto_rank",
        )
        config.max_concurrent_pto = st.number_input(
            "Max fellows on PTO same week", min_value=1, max_value=5,
            value=config.max_concurrent_pto, key="cfg_max_pto",
        )
        config.solver_timeout_seconds = st.number_input(
            "Solver timeout (seconds)", min_value=10.0, max_value=600.0,
            value=config.solver_timeout_seconds, step=10.0,
            key="cfg_timeout",
        )

    # ── PTO Blackout Weeks ───────────────────────────────────────────
    with st.sidebar.expander("🚫 PTO Blackout Weeks", expanded=False):
        # Show weeks as date labels for clarity
        week_options: dict[str, int] = {}
        for w in range(config.num_weeks):
            week_date = config.start_date + timedelta(weeks=w)
            label = f"W{w + 1}: {week_date.strftime('%b %d')}"
            week_options[label] = w

        selected_labels = st.multiselect(
            "Select blackout weeks (no PTO allowed)",
            options=list(week_options.keys()),
            default=[
                label for label, idx in week_options.items()
                if idx in config.pto_blackout_weeks
            ],
            key="cfg_blackout",
        )
        config.pto_blackout_weeks = [
            week_options[label] for label in selected_labels
        ]

    # ── Block Configuration ──────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Block Configuration")

    # Track total staffing for feasibility indicator
    total_staffing: int = 0

    for i, block in enumerate(config.blocks):
        with st.sidebar.expander(
            f"{'🌙' if block.block_type == BlockType.NIGHT else '☀️'} "
            f"{block.name}",
            expanded=False,
        ):
            block.is_active = st.checkbox(
                "Active", value=block.is_active,
                key=f"blk_active_{i}",
            )

            if block.is_active:
                block.fellows_needed = st.number_input(
                    "Min fellows/week", min_value=0, max_value=9,
                    value=block.fellows_needed,
                    key=f"blk_needed_{i}",
                )
                total_staffing += block.fellows_needed

                block.hours_per_week = st.number_input(
                    "Hours/week", min_value=0.0, max_value=100.0,
                    value=block.hours_per_week, step=5.0,
                    key=f"blk_hours_{i}",
                )

                col1, col2 = st.columns(2)
                with col1:
                    block.min_weeks = st.number_input(
                        "Min weeks", min_value=0, max_value=52,
                        value=block.min_weeks,
                        key=f"blk_min_{i}",
                    )
                with col2:
                    block.max_weeks = st.number_input(
                        "Max weeks", min_value=block.min_weeks,
                        max_value=52, value=block.max_weeks,
                        key=f"blk_max_{i}",
                    )

                block.has_weekend_off = st.checkbox(
                    "Weekend off", value=block.has_weekend_off,
                    key=f"blk_wknd_{i}",
                )
                block.requires_call_coverage = st.checkbox(
                    "Needs call coverage", value=block.requires_call_coverage,
                    key=f"blk_call_{i}",
                )

    # Feasibility indicator
    available = config.num_fellows - config.max_concurrent_pto
    if total_staffing > available:
        st.sidebar.error(
            f"⚠️ Staffing: {total_staffing} needed > {available} available"
        )
    else:
        st.sidebar.success(
            f"✅ Staffing: {total_staffing} needed / {available} available"
        )

    # ── Call Settings ────────────────────────────────────────────────
    st.sidebar.markdown("---")
    with st.sidebar.expander("📞 24-Hr Call Settings", expanded=False):
        config.call_day = st.selectbox(
            "Call day", options=["saturday", "sunday", "friday"],
            index=["saturday", "sunday", "friday"].index(config.call_day),
            key="cfg_call_day",
        )
        config.call_hours = st.number_input(
            "Call hours", min_value=0.0, max_value=48.0,
            value=config.call_hours, step=1.0,
            key="cfg_call_hours",
        )
        config.max_consecutive_night_float = st.number_input(
            "Max consecutive Night Float weeks",
            min_value=1, max_value=6,
            value=config.max_consecutive_night_float,
            key="cfg_max_nf",
        )

        all_block_names: list[str] = [b.name for b in config.blocks] + ["PTO"]
        config.call_excluded_blocks = st.multiselect(
            "Blocks excluded from call",
            options=all_block_names,
            default=config.call_excluded_blocks,
            key="cfg_call_excluded",
        )

    # ── Fellow PTO Rankings ──────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("👤 Fellow PTO Rankings")

    # Ensure we have the right number of fellows
    while len(config.fellows) < config.num_fellows:
        config.fellows.append(
            FellowConfig(name=f"Fellow {len(config.fellows) + 1}")
        )
    config.fellows = config.fellows[: config.num_fellows]

    for f_idx, fellow in enumerate(config.fellows):
        with st.sidebar.expander(f"👤 {fellow.name}", expanded=False):
            fellow.name = st.text_input(
                "Name", value=fellow.name.strip(),
                key=f"fellow_name_{f_idx}",
            )

            # PTO week picker
            st.caption(
                f"Select up to {config.pto_weeks_to_rank} preferred PTO "
                f"weeks, ranked best → worst"
            )

            # Build week options for the multi-select
            week_opts: dict[str, int] = {}
            for w in range(config.num_weeks):
                if w not in config.pto_blackout_weeks:
                    wd = config.start_date + timedelta(weeks=w)
                    week_opts[f"W{w + 1}: {wd.strftime('%b %d')}"] = w

            # Current selections as labels
            current_labels: list[str] = []
            for w in fellow.pto_rankings:
                for label, idx in week_opts.items():
                    if idx == w:
                        current_labels.append(label)
                        break

            selected = st.multiselect(
                "Ranked PTO weeks (order = priority)",
                options=list(week_opts.keys()),
                default=current_labels,
                max_selections=config.pto_weeks_to_rank,
                key=f"fellow_pto_{f_idx}",
            )
            fellow.pto_rankings = [week_opts[label] for label in selected]

    # ── Save config ──────────────────────────────────────────────────
    set_config(config)

    if st.sidebar.button("💾 Save Config", use_container_width=True):
        persist_config()
        st.sidebar.success("Configuration saved!")
