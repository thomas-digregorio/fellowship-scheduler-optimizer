"""Export schedule to PDF and CSV formats.

Uses ``fpdf2`` for PDF generation and ``pandas`` for CSV. Both exporters
take a ``ScheduleResult`` + ``ScheduleConfig`` and write to disk.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
from fpdf import FPDF

from src.config import BLOCK_COLORS
from src.models import ScheduleConfig, ScheduleResult


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

def export_csv(
    result: ScheduleResult,
    config: ScheduleConfig,
    path: Path,
) -> Path:
    """Export the master schedule grid as a CSV file.

    Rows = weeks, columns = fellows. Each cell contains the block name.
    A second CSV with call assignments is also created alongside.

    Parameters
    ----------
    result : ScheduleResult
        The solved schedule.
    config : ScheduleConfig
        Configuration (for fellow names and dates).
    path : Path
        Output CSV file path.

    Returns
    -------
    Path
        The path to the created CSV file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build week labels (start date of each week)
    week_labels: list[str] = []
    for w in range(config.num_weeks):
        week_start = config.start_date + timedelta(weeks=w)
        week_labels.append(week_start.strftime("%b %d"))

    # Fellow names
    fellow_names: list[str] = [f.name for f in config.fellows]

    # Build DataFrame: weeks as rows, fellows as columns
    data: dict[str, list[str]] = {"Week": week_labels}
    for f_idx, fname in enumerate(fellow_names):
        blocks: list[str] = []
        for w in range(config.num_weeks):
            block_name: str = result.assignments[f_idx][w]
            # Mark call with a ☎ symbol
            if result.call_assignments[f_idx][w]:
                block_name += " ☎"
            blocks.append(block_name)
        data[fname] = blocks

    df = pd.DataFrame(data)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PDF Export
# ---------------------------------------------------------------------------

def export_pdf(
    result: ScheduleResult,
    config: ScheduleConfig,
    path: Path,
) -> Path:
    """Export the master schedule as a formatted PDF.

    Creates a landscape PDF with a color-coded grid showing all 52 weeks
    for all 9 fellows. Uses small fonts to fit the full year on a few pages.

    Parameters
    ----------
    result : ScheduleResult
        The solved schedule.
    config : ScheduleConfig
        Configuration (for fellow names and dates).
    path : Path
        Output PDF file path.

    Returns
    -------
    Path
        The path to the created PDF.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create landscape PDF
    pdf = FPDF(orientation="L", unit="mm", format="A3")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Fellowship Schedule", ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0, 6,
        f"{config.start_date.strftime('%B %d, %Y')} — "
        f"{(config.start_date + timedelta(weeks=config.num_weeks)).strftime('%B %d, %Y')}",
        ln=True, align="C",
    )
    pdf.ln(4)

    # Grid parameters
    fellow_names: list[str] = [f.name for f in config.fellows]
    col_w: float = 6.0   # week column width (mm)
    row_h: float = 5.5   # row height (mm)
    label_w: float = 25.0  # fellow name column width

    # Number of weeks per page (landscape A3 ≈ 420mm wide)
    usable_w: float = 420 - 20 - label_w  # margins
    weeks_per_page: int = int(usable_w / col_w)

    for page_start in range(0, config.num_weeks, weeks_per_page):
        if page_start > 0:
            pdf.add_page()

        page_end: int = min(page_start + weeks_per_page, config.num_weeks)

        # Header row: week numbers
        pdf.set_font("Helvetica", "B", 5)
        pdf.cell(label_w, row_h, "", border=1)
        for w in range(page_start, page_end):
            week_date = config.start_date + timedelta(weeks=w)
            pdf.cell(col_w, row_h, f"W{w + 1}", border=1, align="C")
        pdf.ln()

        # Data rows: one per fellow
        pdf.set_font("Helvetica", "", 5)
        for f_idx, fname in enumerate(fellow_names):
            # Fellow name
            pdf.set_font("Helvetica", "B", 5)
            pdf.cell(label_w, row_h, fname, border=1)
            pdf.set_font("Helvetica", "", 4)

            for w in range(page_start, page_end):
                block_name: str = result.assignments[f_idx][w]
                has_call: bool = result.call_assignments[f_idx][w]

                # Background color from block palette
                hex_color: str = BLOCK_COLORS.get(block_name, "#FFFFFF")
                r, g, b = _hex_to_rgb(hex_color)
                pdf.set_fill_color(r, g, b)

                # Text color: white on dark backgrounds, black on light
                brightness: float = (r * 299 + g * 587 + b * 114) / 1000
                if brightness < 128:
                    pdf.set_text_color(255, 255, 255)
                else:
                    pdf.set_text_color(0, 0, 0)

                # Abbreviate block name to fit cell
                abbrev: str = _abbreviate(block_name)
                if has_call:
                    abbrev += "☎"

                pdf.cell(
                    col_w, row_h, abbrev,
                    border=1, align="C", fill=True,
                )

            pdf.set_text_color(0, 0, 0)
            pdf.ln()

    # Legend
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(0, 5, "Legend:", ln=True)
    pdf.set_font("Helvetica", "", 6)

    x_start: float = pdf.get_x()
    for name, hex_color in BLOCK_COLORS.items():
        r, g, b = _hex_to_rgb(hex_color)
        pdf.set_fill_color(r, g, b)
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        if brightness < 128:
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_text_color(0, 0, 0)
        pdf.cell(25, 4, name, border=1, fill=True, align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.cell(2, 4, "")

        # Wrap legend items
        if pdf.get_x() > 380:
            pdf.ln()
            pdf.set_x(x_start)

    pdf.output(str(path))
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string (e.g., '#C0392B') to an (R, G, B) tuple."""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _abbreviate(block_name: str) -> str:
    """Shorten a block name to fit in a narrow PDF cell.

    Examples:
        'Night Float' → 'NF'
        'Consult SRC' → 'CSR'
        'Research'    → 'Res'
        'PTO'         → 'PTO'
    """
    abbreviations: dict[str, str] = {
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
    return abbreviations.get(block_name, block_name[:3])
