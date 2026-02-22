"""Garage-wide analytics PDF report builder.

Assembles all components and charts into a polished garage analytics report
matching the branded design system.
"""

import logging
from io import BytesIO
from typing import Any

from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
)

from app.utils.pdf_charts import render_donut_chart, render_garage_monthly_trends
from app.utils.pdf_components import (
    draw_branded_footer,
    draw_branded_header,
    make_data_table,
    make_garage_banner,
    make_kpi_row,
    make_section_header,
    style_as_card,
    wrap_in_card,
)
from app.utils.pdf_styles import (
    CONTENT_WIDTH,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    MARGIN,
    PAGE_HEIGHT,
    PAGE_SIZE,
    SECTION_SPACING,
    format_currency_compact,
    format_currency_short,
    get_styles,
    register_fonts,
)

logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> float:
    """Convert Decimal/str/int/None to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val: Any) -> int:
    """Convert to int safely."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def generate_garage_analytics_pdf(garage_data: dict[str, Any]) -> BytesIO:
    """Generate a branded garage-wide analytics PDF report.

    Args:
        garage_data: GarageAnalytics.model_dump() output.

    Returns:
        BytesIO containing the PDF document.
    """
    register_fonts()
    styles = get_styles()
    buf = BytesIO()

    # Page setup
    doc = BaseDocTemplate(
        buf,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + HEADER_HEIGHT,
        bottomMargin=MARGIN + FOOTER_HEIGHT,
    )

    frame = Frame(
        MARGIN,
        MARGIN + FOOTER_HEIGHT,
        CONTENT_WIDTH,
        PAGE_HEIGHT - (2 * MARGIN) - HEADER_HEIGHT - FOOTER_HEIGHT,
        id="main",
    )

    subtitle = "Garage Analytics Report"

    def on_first_page(canvas: Any, doc: Any) -> None:  # pyright: ignore[reportUnusedParameter]
        draw_branded_header(canvas, doc, subtitle)
        draw_branded_footer(canvas, doc)

    def on_later_pages(canvas: Any, doc: Any) -> None:  # pyright: ignore[reportUnusedParameter]
        draw_branded_footer(canvas, doc)

    doc.addPageTemplates(
        [
            PageTemplate(id="first", frames=[frame], onPage=on_first_page),
            PageTemplate(id="later", frames=[frame], onPage=on_later_pages),
        ]
    )

    # Extract data sections
    total_costs = garage_data.get("total_costs", {})
    vehicle_count = _safe_int(garage_data.get("vehicle_count", 0))

    # Build story
    story: list[Any] = []

    # ── 1. Garage Banner ──────────────────────────────────────
    story.append(make_garage_banner(vehicle_count))
    story.append(Spacer(1, 16))

    # ── 2. KPI Cards ──────────────────────────────────────────
    garage_value = _safe_float(total_costs.get("total_garage_value", 0))
    total_maintenance = _safe_float(total_costs.get("total_maintenance", 0))
    total_fuel = _safe_float(total_costs.get("total_fuel", 0))

    # Calculate total operating cost (all categories except garage value)
    operating_cost = sum(
        _safe_float(total_costs.get(f, 0))
        for f in [
            "total_maintenance",
            "total_fuel",
            "total_insurance",
            "total_taxes",
            "total_upgrades",
            "total_inspection",
            "total_collision",
            "total_detailing",
            "total_def",
        ]
    )

    kpi_cards = [
        {
            "label": "Garage Value",
            "value": format_currency_short(garage_value),
            "sub": f"{vehicle_count} vehicle{'s' if vehicle_count != 1 else ''}",
            "color": "blue",
        },
        {
            "label": "Operating Cost",
            "value": format_currency_short(operating_cost),
            "sub": "Maintenance + Fuel + Insurance + Taxes",
            "color": "green",
        },
        {
            "label": "Total Maintenance",
            "value": format_currency_short(total_maintenance),
            "sub": "Service records",
            "color": "amber",
        },
        {
            "label": "Total Fuel",
            "value": format_currency_short(total_fuel),
            "sub": "Fuel records",
            "color": "red",
        },
    ]

    story.append(make_kpi_row(kpi_cards))
    story.append(Spacer(1, 16))

    # ── 3. Cost Breakdown Donut ───────────────────────────────
    cost_categories = garage_data.get("cost_breakdown_by_category", [])
    if cost_categories:
        story.append(make_section_header("Cost Breakdown by Category"))
        story.append(Spacer(1, 6))

        donut_cats = [
            (str(c.get("category", "")), _safe_float(c.get("amount", 0)))
            for c in cost_categories
            if _safe_float(c.get("amount", 0)) > 0
        ]
        donut_total = sum(c[1] for c in donut_cats)

        if donut_cats:
            donut_buf = render_donut_chart(
                categories=donut_cats,
                total=donut_total,
                width_inches=6.5,
                height_inches=2.4,
            )
            donut_img = Image(donut_buf, width=CONTENT_WIDTH, height=2.4 * inch)
            story.append(wrap_in_card(donut_img, padding=12))
        story.append(Spacer(1, 16))

    # ── 4. Cost by Vehicle Table ──────────────────────────────
    vehicles = garage_data.get("cost_by_vehicle", [])
    if vehicles:
        story.append(
            make_section_header(
                "Cost by Vehicle",
                annotation=f"{len(vehicles)} vehicle{'s' if len(vehicles) != 1 else ''}",
            )
        )
        story.append(Spacer(1, 6))

        # Build compact table with smaller fonts for 10-column layout
        amt_style = styles["TableAmountCompact"]
        name_style = styles["TableHighlightCompact"]

        table_rows = []
        for v in vehicles:
            name = str(v.get("name", ""))
            nickname = str(v.get("nickname", ""))
            display_name = nickname if nickname else name

            table_rows.append(
                [
                    Paragraph(display_name, name_style),
                    Paragraph(format_currency_compact(v.get("purchase_price", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_maintenance", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_upgrades", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_inspection", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_collision", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_detailing", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_fuel", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_def", 0)), amt_style),
                    Paragraph(format_currency_compact(v.get("total_cost", 0)), amt_style),
                ]
            )

        # Column widths — give name more room, dollar cols share the rest
        name_w = CONTENT_WIDTH * 0.13
        dollar_w = (CONTENT_WIDTH - name_w) / 9

        vehicle_table = make_data_table(
            headers=[
                "Vehicle",
                "Purchase",
                "Maint.",
                "Upgrades",
                "Inspect.",
                "Collision",
                "Detail.",
                "Fuel",
                "DEF",
                "Total",
            ],
            rows=table_rows,
            col_widths=[name_w] + [dollar_w] * 9,
            amount_columns=list(range(1, 10)),
            compact=True,
        )

        story.append(style_as_card(vehicle_table, padding=8))
        story.append(Spacer(1, SECTION_SPACING))

    # ── 5. Monthly Spending Trends Chart ──────────────────────
    monthly_trends = garage_data.get("monthly_trends", [])
    if monthly_trends:
        story.append(make_section_header("Monthly Spending Trends"))
        story.append(Spacer(1, 6))

        chart_buf = render_garage_monthly_trends(monthly_trends[-12:])
        chart_img = Image(chart_buf, width=CONTENT_WIDTH, height=3.0 * inch)
        story.append(wrap_in_card(chart_img, padding=12))

    # Build PDF
    doc.build(story)
    buf.seek(0)
    return buf
