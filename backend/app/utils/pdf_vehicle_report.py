"""Vehicle analytics PDF report builder.

Assembles all components and charts into a polished per-vehicle analytics report
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
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.utils.pdf_charts import (
    render_donut_chart,
    render_monthly_spending_chart,
    render_projection_bars,
)
from app.utils.pdf_components import (
    draw_branded_footer,
    draw_branded_header,
    make_data_table,
    make_kpi_row,
    make_season_row,
    make_section_header,
    make_vehicle_banner,
    make_vendor_list,
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
    format_currency,
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


def _trend_badge_html(trend_direction: str) -> str:
    """Build HTML for the trend direction badge."""
    if trend_direction == "decreasing":
        # Down arrow: ↓
        return '<font color="#059669">\u2193 Decreasing</font>'
    elif trend_direction == "increasing":
        # Up arrow: ↑
        return '<font color="#dc2626">\u2191 Increasing</font>'
    return '<font color="#8c91a3">\u2014 Stable</font>'


def generate_vehicle_analytics_pdf(
    analytics_data: dict[str, Any],
    vendor_data: dict[str, Any] | None = None,
    seasonal_data: dict[str, Any] | None = None,
) -> BytesIO:
    """Generate a branded vehicle analytics PDF report.

    Args:
        analytics_data: VehicleAnalytics.model_dump() output.
        vendor_data: VendorAnalyticsSummary.model_dump() output, or None.
        seasonal_data: SeasonalAnalyticsSummary.model_dump() output, or None.

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

    # Page callbacks
    subtitle = "Vehicle Analytics Report"

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
    cost = analytics_data.get("cost_analysis", {})
    projection = analytics_data.get("cost_projection", {})

    # Build the story (list of flowables)
    story: list[Any] = []

    # ── 1. Vehicle Banner ─────────────────────────────────────
    story.append(
        make_vehicle_banner(
            vehicle_name=analytics_data.get("vehicle_name", "Unknown Vehicle"),
            vin=analytics_data.get("vin", ""),
            vehicle_type=analytics_data.get("vehicle_type", "Vehicle"),
            days_owned=_safe_int(analytics_data.get("days_owned")),
        )
    )
    story.append(Spacer(1, SECTION_SPACING))

    # ── 2. KPI Cards ──────────────────────────────────────────
    total_cost = _safe_float(cost.get("total_cost", 0))
    cost_per_mile = _safe_float(cost.get("cost_per_mile"))
    avg_monthly = _safe_float(cost.get("average_monthly_cost", 0))
    projected_12m = _safe_float(projection.get("twelve_month_projection", 0))
    service_count = _safe_int(cost.get("service_count", 0))
    fuel_count = _safe_int(cost.get("fuel_count", 0))
    rolling_3m = _safe_float(cost.get("rolling_avg_3m"))
    trend_dir = str(cost.get("trend_direction", "stable"))

    kpi_cards = [
        {
            "label": "Total Cost",
            "value": format_currency_short(total_cost),
            "sub": f"{service_count} services · {fuel_count} fuel",
            "color": "blue",
        },
        {
            "label": "Cost Per Mile",
            "value": f"${cost_per_mile:.2f}" if cost_per_mile else "N/A",
            "sub_html": _trend_badge_html(trend_dir),
            "color": "green",
        },
        {
            "label": "Avg Monthly",
            "value": format_currency_short(avg_monthly),
            "sub": f"3-mo rolling: {format_currency(rolling_3m)}" if rolling_3m else "",
            "color": "amber",
        },
        {
            "label": "Projected 12-Mo",
            "value": format_currency_short(projected_12m),
            "sub": "Based on recent avg",
            "color": "red",
        },
    ]

    story.append(make_kpi_row(kpi_cards))
    story.append(Spacer(1, SECTION_SPACING))

    # ── 3. Monthly Spending Chart ─────────────────────────────
    monthly_data = cost.get("monthly_breakdown", [])
    if monthly_data:
        story.append(make_section_header("Monthly Spending"))
        story.append(Spacer(1, 6))

        chart_buf = render_monthly_spending_chart(monthly_data[-12:])
        chart_img = Image(chart_buf, width=CONTENT_WIDTH, height=2.4 * inch)
        story.append(wrap_in_card(chart_img, padding=10))
        story.append(Spacer(1, 16))

    # ── 4. Service Breakdown + Cost Distribution ──────────────
    service_breakdown = cost.get("service_type_breakdown", [])
    if service_breakdown:
        story.append(
            make_section_header(
                "Service Breakdown & Cost Distribution",
                annotation=f"{len(service_breakdown)} categories",
                compact_title=True,
            )
        )
        story.append(Spacer(1, 6))

        # Find highest-cost row
        max_cost = 0.0
        max_idx = 0
        for i, svc in enumerate(service_breakdown):
            svc_cost = _safe_float(svc.get("total_cost", 0))
            if svc_cost > max_cost:
                max_cost = svc_cost
                max_idx = i

        # Build service table with compact styles
        amt_style = styles["TableAmountCompact"]
        cell_style = styles["TableCellCompact"]

        table_rows = []
        for svc in service_breakdown:
            table_rows.append(
                [
                    Paragraph(str(svc.get("service_type", "")), cell_style),
                    Paragraph(str(svc.get("count", 0)), cell_style),
                    Paragraph(format_currency_compact(svc.get("total_cost", 0)), amt_style),
                    Paragraph(format_currency_compact(svc.get("average_cost", 0)), amt_style),
                ]
            )

        # Column widths for table side (60% of content)
        table_w = CONTENT_WIDTH * 0.58
        svc_table = make_data_table(
            headers=["Type", "Cnt", "Total", "Avg"],
            rows=table_rows,
            col_widths=[
                table_w * 0.40,
                table_w * 0.12,
                table_w * 0.24,
                table_w * 0.24,
            ],
            highlight_row=max_idx,
            amount_columns=[2, 3],
            compact=True,
        )

        # Donut chart with legend
        donut_categories = [
            (str(s.get("service_type", "")), _safe_float(s.get("total_cost", 0)))
            for s in service_breakdown
            if _safe_float(s.get("total_cost", 0)) > 0
        ]

        if donut_categories:
            donut_buf = render_donut_chart(
                categories=donut_categories,
                total=total_cost,
                width_inches=3.5,
                height_inches=2.0,
                show_legend=True,
            )
            donut_img = Image(
                donut_buf,
                width=CONTENT_WIDTH * 0.42,
                height=2.0 * inch,
            )

            # For large tables, use vertical layout
            if len(service_breakdown) > 10:
                story.append(svc_table)
                story.append(Spacer(1, 8))
                story.append(wrap_in_card(donut_img, padding=10))
            else:
                two_col = Table(
                    [[svc_table, donut_img]],
                    colWidths=[CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.42],
                )
                two_col.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ]
                    )
                )
                story.append(wrap_in_card(two_col, padding=10))
        else:
            if len(service_breakdown) > 10:
                story.append(svc_table)
            else:
                story.append(wrap_in_card(svc_table, padding=10))

        story.append(Spacer(1, 16))

    # ── 5. Vendor Analysis ────────────────────────────────────
    if vendor_data and vendor_data.get("vendors"):
        vendors = vendor_data["vendors"]
        total_vendors = vendor_data.get("total_vendors", len(vendors))
        most_used = vendor_data.get("most_used_vendor")
        highest_spend = vendor_data.get("highest_spending_vendor")

        story.append(
            make_section_header(
                "Vendor Analysis",
                annotation=f"{total_vendors} vendor{'s' if total_vendors != 1 else ''}",
            )
        )
        story.append(Spacer(1, 10))

        vendor_flowables = make_vendor_list(
            vendors=vendors,
            most_used=most_used,
            highest_spend=highest_spend,
        )
        story.extend(vendor_flowables)
        story.append(Spacer(1, SECTION_SPACING))

    # ── 6. Seasonal Spending ──────────────────────────────────
    if seasonal_data and seasonal_data.get("seasons"):
        seasons = seasonal_data["seasons"]
        highest = seasonal_data.get("highest_cost_season")
        lowest = seasonal_data.get("lowest_cost_season")
        annual_avg = _safe_float(seasonal_data.get("annual_average", 0))

        story.append(
            make_section_header(
                "Seasonal Spending",
                annotation=f"Annual avg: {format_currency(annual_avg)}",
            )
        )
        story.append(Spacer(1, 10))

        season_grid = make_season_row(
            seasons=seasons,
            highest_season=highest,
            lowest_season=lowest,
        )
        story.append(KeepTogether([season_grid]))
        story.append(Spacer(1, SECTION_SPACING))

    # ── 7. Cost Projections ───────────────────────────────────
    monthly_avg = _safe_float(projection.get("monthly_average", 0))
    six_month = _safe_float(projection.get("six_month_projection", 0))
    twelve_month = _safe_float(projection.get("twelve_month_projection", 0))
    months_tracked = _safe_int(cost.get("months_tracked", 0))

    if monthly_avg > 0 or six_month > 0 or twelve_month > 0:
        story.append(make_section_header("Cost Projections"))
        story.append(Spacer(1, 10))

        proj_buf = render_projection_bars(
            current_amount=total_cost,
            six_month=six_month,
            twelve_month=twelve_month,
            months_tracked=months_tracked,
        )
        proj_img = Image(proj_buf, width=CONTENT_WIDTH, height=1.8 * inch)
        story.append(wrap_in_card(proj_img, padding=16))

        # Projection details text
        story.append(Spacer(1, 8))
        assumptions = str(projection.get("assumptions", ""))
        if assumptions:
            story.append(Paragraph(assumptions, styles["ProjectionLabel"]))

    # Build PDF
    doc.build(story)
    buf.seek(0)
    return buf
