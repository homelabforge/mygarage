"""matplotlib chart generation for PDF analytics reports.

Each function renders a chart to a PNG BytesIO buffer for embedding in ReportLab PDFs.
All charts use the Agg backend and explicitly close figures to prevent memory leaks.
"""

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties, fontManager  # noqa: E402

from app.utils.pdf_styles import CHART_COLORS, MPL, apply_chart_rcparams  # noqa: E402

logger = logging.getLogger(__name__)

# ── Font Registration ──────────────────────────────────────
_FONT_DIR = Path(__file__).parent.parent / "fonts"
_fonts_loaded = False


def _ensure_fonts() -> None:
    """Register custom fonts with matplotlib's font manager."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    if _FONT_DIR.exists():
        for ttf in _FONT_DIR.glob("*.ttf"):
            try:
                fontManager.addfont(str(ttf))
            except Exception:
                logger.debug("Could not add font %s to matplotlib", ttf.name)
    _fonts_loaded = True


def _body_font() -> FontProperties:
    """Get DM Sans font properties, falling back to sans-serif."""
    _ensure_fonts()
    try:
        return FontProperties(family="DM Sans", weight="medium")
    except Exception:
        return FontProperties(family="sans-serif")


def _mono_font() -> FontProperties:
    """Get JetBrains Mono font properties, falling back to monospace."""
    _ensure_fonts()
    try:
        return FontProperties(family="JetBrains Mono", weight="medium")
    except Exception:
        return FontProperties(family="monospace")


def _to_float(val: Any) -> float:
    """Convert Decimal/str/int/None to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0


def _format_dollar(val: float) -> str:
    """Format a float as a dollar string for chart labels."""
    if val >= 10000:
        return f"${val:,.0f}"
    if val >= 1000:
        return f"${val:,.0f}"
    return f"${val:,.2f}"


# ── Chart Functions ────────────────────────────────────────


def render_monthly_spending_chart(
    monthly_data: list[dict[str, Any]],
    width_inches: float = 7.0,
    height_inches: float = 2.8,
) -> BytesIO:
    """Render a grouped bar chart of monthly service vs fuel spending.

    Args:
        monthly_data: List of MonthlyCostSummary dicts with keys:
            month_name, year, total_service_cost, total_fuel_cost
        width_inches: Chart width in inches
        height_inches: Chart height in inches

    Returns:
        BytesIO containing PNG image data.
    """
    apply_chart_rcparams()
    fig, ax = plt.subplots(figsize=(width_inches, height_inches), dpi=150)
    try:
        if not monthly_data:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                fontproperties=_body_font(),
                color=MPL["text_muted"],
                fontsize=12,
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
        else:
            # Build labels and values
            labels = []
            service_vals = []
            fuel_vals = []

            for m in monthly_data:
                month_name = str(m.get("month_name", ""))[:3]
                year = str(m.get("year", ""))
                # Show year suffix for first month and when year changes
                if not labels or year != str(
                    monthly_data[labels.__len__() - 1 if labels else 0].get("year", "")
                ):
                    labels.append(f"{month_name} {year[2:]}")
                else:
                    labels.append(month_name)

                service_vals.append(_to_float(m.get("total_service_cost", 0)))
                fuel_vals.append(_to_float(m.get("total_fuel_cost", 0)))

            import numpy as np

            x = np.arange(len(labels))
            bar_width = 0.35

            ax.bar(
                x - bar_width / 2,
                service_vals,
                bar_width,
                label="Service",
                color=MPL["blue"],
                zorder=3,
            )
            ax.bar(
                x + bar_width / 2,
                fuel_vals,
                bar_width,
                label="Fuel",
                color=MPL["cyan"],
                zorder=3,
            )

            # Style axes
            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontproperties=_mono_font(), fontsize=9)
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))  # pyright: ignore[reportPrivateImportUsage]

            for label in ax.get_yticklabels():
                label.set_fontproperties(_mono_font())
                label.set_fontsize(9)

            ax.grid(axis="y", linestyle="-", alpha=0.4, zorder=0)
            ax.set_axisbelow(True)

            # Remove top and right spines
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color(MPL["border"])
            ax.spines["bottom"].set_color(MPL["border"])

            # Legend
            ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.12),
                ncol=2,
                frameon=False,
                prop=_body_font(),
            )

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def render_donut_chart(
    categories: list[tuple[str, float]],
    total: float,
    width_inches: float = 4.5,
    height_inches: float = 2.8,
    show_legend: bool = True,
) -> BytesIO:
    """Render a donut/ring chart with center total and optional legend.

    Args:
        categories: List of (name, amount) tuples sorted by amount descending.
        total: Total dollar amount for center text.
        width_inches: Chart width in inches.
        height_inches: Chart height in inches.

    Returns:
        BytesIO containing PNG image data.
    """
    apply_chart_rcparams()

    if show_legend:
        fig, (ax_donut, ax_legend) = plt.subplots(
            1,
            2,
            figsize=(width_inches, height_inches),
            dpi=150,
            gridspec_kw={"width_ratios": [1, 1]},
        )
    else:
        fig, ax_donut = plt.subplots(
            figsize=(width_inches, height_inches),
            dpi=150,
        )
        ax_legend = None

    try:
        if not categories or total <= 0:
            ax_donut.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                fontproperties=_body_font(),
                color=MPL["text_muted"],
                fontsize=12,
            )
            ax_donut.axis("off")
            if ax_legend is not None:
                ax_legend.axis("off")
        else:
            values = [c[1] for c in categories]
            chart_colors = CHART_COLORS[: len(categories)]

            # Draw donut
            ax_donut.pie(
                values,
                colors=chart_colors,
                startangle=90,
                counterclock=False,
                wedgeprops={"width": 0.3, "edgecolor": MPL["bg_card"], "linewidth": 1.5},
            )

            # Center text
            ax_donut.text(
                0,
                0.05,
                _format_dollar(total),
                ha="center",
                va="center",
                fontproperties=_mono_font(),
                fontsize=14,
                fontweight="bold",
                color=MPL["text_primary"],
            )
            ax_donut.text(
                0,
                -0.15,
                "total",
                ha="center",
                va="center",
                fontproperties=_body_font(),
                fontsize=10,
                color=MPL["text_muted"],
            )

            # Legend (custom, not matplotlib default)
            if ax_legend is not None:
                ax_legend.axis("off")
                y_start = 0.95
                y_step = 1.0 / max(len(categories), 1)

                for i, (name, _amount) in enumerate(categories):
                    y = y_start - i * y_step
                    color = chart_colors[i] if i < len(chart_colors) else "#6b7280"

                    ax_legend.plot(
                        0.0,
                        y,
                        "o",
                        color=color,
                        markersize=6,
                        transform=ax_legend.transAxes,
                        clip_on=False,
                    )
                    ax_legend.text(
                        0.08,
                        y,
                        name,
                        transform=ax_legend.transAxes,
                        va="center",
                        fontproperties=_body_font(),
                        fontsize=10,
                        color=MPL["text_secondary"],
                    )

        fig.tight_layout(pad=0.5)
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def render_projection_bars(
    current_amount: float,
    six_month: float,
    twelve_month: float,
    months_tracked: int,
    width_inches: float = 7.0,
    height_inches: float = 1.8,
) -> BytesIO:
    """Render horizontal projection bars (current, 6mo, 12mo).

    Args:
        current_amount: Current total spending.
        six_month: Projected additional spend over next 6 months.
        twelve_month: Projected additional spend over next 12 months.
        months_tracked: Number of months of data.
        width_inches: Chart width in inches.
        height_inches: Chart height in inches.

    Returns:
        BytesIO containing PNG image data.
    """
    apply_chart_rcparams()
    fig, ax = plt.subplots(figsize=(width_inches, height_inches), dpi=150)
    try:
        max_val = max(current_amount + twelve_month, 1)
        bar_lw = 18  # line width in points — round capstyle makes rounded ends

        labels = [
            f"Current ({months_tracked} mo)",
            "Next 6 Months",
            "Next 12 Months",
        ]
        y_positions = [2, 1, 0]

        # Background tracks
        for y in y_positions:
            ax.plot(
                [0, max_val],
                [y, y],
                linewidth=bar_lw,
                color=MPL["bg_card_alt"],
                solid_capstyle="round",
                zorder=1,
            )

        # Current bar (solid blue)
        if current_amount > 0:
            ax.plot(
                [0, current_amount],
                [2, 2],
                linewidth=bar_lw,
                color=MPL["blue"],
                solid_capstyle="round",
                zorder=2,
            )
            ax.text(
                current_amount + max_val * 0.02,
                2,
                _format_dollar(current_amount),
                ha="left",
                va="center",
                fontproperties=_mono_font(),
                fontsize=10,
                fontweight="bold",
                color=MPL["blue"],
                zorder=3,
            )

        # Projected bars (lighter blue, single solid line — no dashed overlay)
        for y, val, label_prefix in [(1, six_month, "+"), (0, twelve_month, "+")]:
            if val > 0:
                ax.plot(
                    [0, val],
                    [y, y],
                    linewidth=bar_lw,
                    color=MPL["blue"],
                    alpha=0.25,
                    solid_capstyle="round",
                    zorder=2,
                )
                ax.text(
                    val + max_val * 0.02,
                    y,
                    f"{label_prefix}{_format_dollar(val)}",
                    ha="left",
                    va="center",
                    fontproperties=_mono_font(),
                    fontsize=10,
                    fontweight="bold",
                    color=MPL["blue"],
                    zorder=3,
                )

        ax.set_yticks(y_positions)
        ax.set_yticklabels(labels, fontproperties=_body_font(), fontsize=11)
        ax.set_xlim(-max_val * 0.01, max_val * 1.18)
        ax.set_ylim(-0.5, 2.7)
        ax.xaxis.set_visible(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.tick_params(left=False)

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


def render_garage_monthly_trends(
    monthly_data: list[dict[str, Any]],
    width_inches: float = 7.0,
    height_inches: float = 2.8,
) -> BytesIO:
    """Render a grouped bar chart for garage monthly trends.

    Uses exact GarageMonthlyTrend schema field names: month, service, fuel, def_cost.

    Args:
        monthly_data: List of GarageMonthlyTrend dicts.
        width_inches: Chart width in inches.
        height_inches: Chart height in inches.

    Returns:
        BytesIO containing PNG image data.
    """
    apply_chart_rcparams()
    fig, ax = plt.subplots(figsize=(width_inches, height_inches), dpi=150)
    try:
        if not monthly_data:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                fontproperties=_body_font(),
                color=MPL["text_muted"],
                fontsize=12,
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
        else:
            import numpy as np

            labels = [str(m.get("month", "")) for m in monthly_data]
            service_vals = [_to_float(m.get("service", 0)) for m in monthly_data]
            fuel_vals = [_to_float(m.get("fuel", 0)) for m in monthly_data]
            def_vals = [_to_float(m.get("def_cost", 0)) for m in monthly_data]

            x = np.arange(len(labels))
            bar_width = 0.25

            ax.bar(
                x - bar_width,
                service_vals,
                bar_width,
                label="Service",
                color=MPL["blue"],
                zorder=3,
            )
            ax.bar(
                x,
                fuel_vals,
                bar_width,
                label="Fuel",
                color=MPL["cyan"],
                zorder=3,
            )
            ax.bar(
                x + bar_width,
                def_vals,
                bar_width,
                label="DEF",
                color=MPL["teal"],
                zorder=3,
            )

            ax.set_xticks(x)
            ax.set_xticklabels(
                labels, fontproperties=_mono_font(), fontsize=8, rotation=45, ha="right"
            )
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))  # pyright: ignore[reportPrivateImportUsage]

            for label in ax.get_yticklabels():
                label.set_fontproperties(_mono_font())
                label.set_fontsize(9)

            ax.grid(axis="y", linestyle="-", alpha=0.4, zorder=0)
            ax.set_axisbelow(True)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color(MPL["border"])
            ax.spines["bottom"].set_color(MPL["border"])

            ax.legend(
                loc="upper center",
                bbox_to_anchor=(0.5, -0.35),
                ncol=3,
                frameon=False,
                prop=_body_font(),
            )

        fig.subplots_adjust(bottom=0.25)
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)
