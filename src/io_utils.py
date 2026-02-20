"""JSON I/O utilities for loading and saving schedule data.

All file operations use ``pathlib.Path`` for cross-platform safety.
Functions here are thin wrappers around JSON serialization — the real
work is done by the ``to_dict`` / ``from_dict`` methods on each dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.models import ScheduleConfig, ScheduleResult


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def save_config(config: ScheduleConfig, path: Path) -> None:
    """Write a ScheduleConfig to a JSON file.

    Parameters
    ----------
    config : ScheduleConfig
        The configuration to persist.
    path : Path
        Destination file path (created if it doesn't exist).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2),
        encoding="utf-8",
    )


def load_config(path: Path) -> ScheduleConfig:
    """Read a ScheduleConfig from a JSON file.

    Parameters
    ----------
    path : Path
        Source file path. Must exist and contain valid JSON.

    Returns
    -------
    ScheduleConfig
        The deserialized configuration.

    Raises
    ------
    FileNotFoundError
        If the file doesn't exist.
    json.JSONDecodeError
        If the file isn't valid JSON.
    """
    raw: str = path.read_text(encoding="utf-8")
    data: dict = json.loads(raw)
    return ScheduleConfig.from_dict(data)


# ---------------------------------------------------------------------------
# Schedule result persistence
# ---------------------------------------------------------------------------

def save_schedule(result: ScheduleResult, path: Path) -> None:
    """Write a ScheduleResult to a JSON file.

    Parameters
    ----------
    result : ScheduleResult
        The solver output to persist.
    path : Path
        Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2),
        encoding="utf-8",
    )


def load_schedule(path: Path) -> ScheduleResult:
    """Read a ScheduleResult from a JSON file.

    Parameters
    ----------
    path : Path
        Source file path.

    Returns
    -------
    ScheduleResult
        The deserialized schedule.
    """
    raw: str = path.read_text(encoding="utf-8")
    data: dict = json.loads(raw)
    return ScheduleResult.from_dict(data)
