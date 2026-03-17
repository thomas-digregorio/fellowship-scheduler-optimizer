"""UI smoke tests for the Streamlit dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.state as app_state
from src.config import get_default_config
from src.io_utils import save_config


APP_PATH = Path(__file__).resolve().parent.parent / "app" / "app.py"


def test_app_renders_and_generates_schedule(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The main dashboard should render and generate a schedule."""
    config_path = tmp_path / "saved_config.json"
    schedule_path = tmp_path / "schedule_output.json"
    monkeypatch.setattr(app_state, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_state, "SCHEDULE_PATH", schedule_path)

    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run(timeout=20)

    assert not at.exception
    assert any(title.value == "🏥 Fellowship Schedule Dashboard" for title in at.title)

    generate = next(
        button for button in at.button
        if button.label == "🔄 Generate Schedule"
    )
    at = generate.click().run(timeout=20)

    assert not at.exception
    assert schedule_path.exists()
    assert len(at.dataframe) >= 1
    assert any(subheader.value == "✅ Checks" for subheader in at.subheader)


def test_app_surfaces_blocking_feasibility_issues(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The dashboard should warn before attempting an impossible solve."""
    config = get_default_config()
    for block in config.blocks:
        if block.name == "CCU":
            block.fellows_needed = 2

    config_path = tmp_path / "saved_config.json"
    schedule_path = tmp_path / "schedule_output.json"
    save_config(config, config_path)
    monkeypatch.setattr(app_state, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_state, "SCHEDULE_PATH", schedule_path)

    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run(timeout=20)

    generate = next(
        button for button in at.button
        if button.label == "🔄 Generate Schedule"
    )
    at = generate.click().run(timeout=20)

    warning_values = [warning.value for warning in at.warning]
    assert not at.exception
    assert any("Block capacity conflict" in value for value in warning_values)
    assert any("Coverage/minimum conflict" in value for value in warning_values)
    assert not schedule_path.exists()
