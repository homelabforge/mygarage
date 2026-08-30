"""Vehicle analytics PDF report builder.

Assembles all components and charts into a polished per-vehicle analytics report
matching the branded design system.
"""

import logging
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal, InvalidOperation
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

from app.utils.hours_formatting import format_hours
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
    format_currency,
    format_currency_compact,
    format_currency_short,
    get_styles,
    register_fonts,
)
from app.utils.render_context import RenderContext
from app.utils.unit_derived import format_cost_per_distance, format_fuel_rate
from app.utils.unit_formatting import format_quantity, format_rate

logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> float:
    """Convert Decimal/str/int/None to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val))
    except ValueError, TypeError:
        return 0.0


def _safe_int(val: Any) -> int:
    """Convert to int safely."""
    if val is None:
        return 0
    try:
        return int(val)
    except ValueError, TypeError:
        return 0


def _safe_decimal(val: Any) -> Decimal | None:
    """Convert Decimal/str/int/float/None to Decimal safely (never float —
    hours/economy figures keep full precision through to display)."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except InvalidOperation, ValueError, TypeError:
        return None


def _parse_date(val: Any) -> date_type | None:
    """Normalize a date/datetime/ISO-string/None into a ``date``."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date_type):
        return val
    if isinstance(val, str):
        try:
            return date_type.fromisoformat(val)
        except ValueError:
            return None
    return None


def _format_date(val: date_type | None) -> str:
    """Format a date for report display, or 'N/A' if absent."""
    if val is None:
        return "N/A"
    return val.strftime("%b %d, %Y")


def _latest_hours_point(
    hours_accumulated: list[dict[str, Any]],
) -> tuple[Decimal | None, date_type | None]:
    """Pick the canonical "latest" hours reading from an accumulated-hours
    series (``analytics_data["hours_accumulated"]``, already ordered by
    date ascending — see ``get_hours_accumulated_series``).

    Mirrors the ``engine_hours DESC, date DESC`` tie-break used by the
    canonical ``latest_engine_hours_and_date`` DB helper (a physical meter
    is monotonic, so "latest" = highest reading, tie-broken to the newest
    date). The ``id``-level tie-break isn't available here — this render
    layer has no DB access, only the already-computed series — which is an
    acceptable approximation for a display surface, not a source of truth.
    """
    best_hours: Decimal | None = None
    best_date: date_type | None = None
    for point in hours_accumulated:
        hours = _safe_decimal(point.get("engine_hours"))
        if hours is None:
            continue
        point_date = _parse_date(point.get("date"))
        is_better = (
            best_hours is None
            or hours > best_hours
            or (
                hours == best_hours and (point_date or date_type.min) > (best_date or date_type.min)
            )
        )
        if is_better:
            best_hours = hours
            best_date = point_date
    return best_hours, best_date


def _build_usage_efficiency_cards(
    analytics_data: dict[str, Any],
    currency_code: str,
    locale: str,
    render_context: RenderContext,
) -> list[dict[str, Any]]:
    """Build KPI cards for the "Usage & Efficiency" section.

    Distance cards appear only when the vehicle has real odometer history
    (``total_km_driven`` present); hours cards appear only when the vehicle
    has real hours history (``hours_accumulated`` non-empty). A pure-hours
    vehicle therefore never shows a distance/MPG placeholder, a
    pure-distance vehicle gets no cards here at all (the caller skips the
    whole section in that case — see ``generate_vehicle_analytics_pdf``),
    and a dual-track vehicle gets both.

    Distance, consumption and fuel-rate cards render in ``render_context``'s
    units; the engine-hours card does not, because hours are dimensionless
    (R6, see ``format_hours``). Storage stays metric-canonical either way:
    conversion happens here, at the render boundary, and nowhere else.
    """
    cards: list[dict[str, Any]] = []

    total_km_driven = _safe_decimal(analytics_data.get("total_km_driven"))
    if total_km_driven is not None:
        average_km_per_month = _safe_decimal(analytics_data.get("average_km_per_month"))
        sub = (
            f"Avg {format_rate(average_km_per_month, render_context, 'distance', '/mo')}"
            if average_km_per_month is not None
            else ""
        )
        cards.append(
            {
                "label": "Distance Driven",
                "value": format_quantity(total_km_driven, render_context, "distance"),
                "sub": sub,
                "color": "blue",
            }
        )

        fuel_economy = analytics_data.get("fuel_economy") or {}
        avg_l_100km = _safe_decimal(fuel_economy.get("average_l_per_100km"))
        cards.append(
            {
                "label": "Fuel Economy",
                "value": format_quantity(avg_l_100km, render_context, "consumption"),
                "sub": "",
                "color": "green",
            }
        )

    hours_accumulated = analytics_data.get("hours_accumulated") or []
    if hours_accumulated:
        latest_hours, latest_date = _latest_hours_point(hours_accumulated)
        cards.append(
            {
                "label": "Engine Hours",
                "value": format_hours(latest_hours),
                "sub": f"As of {_format_date(latest_date)}" if latest_date is not None else "",
                "color": "amber",
            }
        )

        hours_economy = analytics_data.get("hours_economy") or {}
        avg_l_hr = _safe_decimal(hours_economy.get("average_l_per_hr"))
        avg_cost_hr = _safe_decimal(hours_economy.get("average_cost_per_hr"))
        cost_sub = (
            f"{format_currency(avg_cost_hr, currency_code, locale)}/hr"
            if avg_cost_hr is not None
            else ""
        )
        cards.append(
            {
                "label": "Hours Economy",
                "value": format_fuel_rate(avg_l_hr, render_context),
                "sub": cost_sub,
                "color": "red",
            }
        )

    return cards


def _build_hours_history_table(
    hours_accumulated: list[dict[str, Any]],
    styles: dict[str, Any],
) -> Table:
    """Build the hours-records history table (date, engine hours, source) —
    the hours analog of an odometer history table. Newest first, capped to
    the most recent 20 readings to keep the report a reasonable length
    (mirrors the ``monthly_data[-12:]`` cap used for the spending chart).

    ``source``/``notes`` are optional per-point keys (not part of the
    ``HoursAccumulatedDataPoint`` analytics series today) — rendered when a
    caller supplies them, "—" otherwise, so this table is forward-compatible
    with a richer data source without further changes here.
    """
    cell_style = styles["TableCell"]
    amt_style = styles["TableAmount"]

    ordered = sorted(
        hours_accumulated,
        key=lambda p: _parse_date(p.get("date")) or date_type.min,
        reverse=True,
    )[:20]

    rows = []
    for point in ordered:
        engine_hours = _safe_decimal(point.get("engine_hours"))
        source = point.get("source") or point.get("notes") or "—"
        rows.append(
            [
                Paragraph(_format_date(_parse_date(point.get("date"))), cell_style),
                Paragraph(format_hours(engine_hours), amt_style),
                Paragraph(str(source), cell_style),
            ]
        )

    return make_data_table(
        headers=["Date", "Engine Hours", "Source"],
        rows=rows,
        col_widths=[CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.3, CONTENT_WIDTH * 0.4],
        amount_columns=[1],
    )


def _reminder_due_text(reminder: dict[str, Any], render_context: RenderContext) -> str:
    """Render a reminder's target as readable text.

    ``due_hours`` takes priority over ``due_mileage_km`` when both happen to
    be set on one reminder (not expected in practice, but keeps an
    hours-targeted reminder from ever silently falling back to a mileage
    figure). ``due_hours`` is dimensionless (R6) and stays in ``hr``;
    ``due_mileage_km`` is canonical km and renders in ``render_context``'s
    distance unit.
    """
    parts: list[str] = []
    due_date = _parse_date(reminder.get("due_date"))
    if due_date is not None:
        parts.append(_format_date(due_date))

    due_hours = _safe_decimal(reminder.get("due_hours"))
    due_mileage_km = _safe_decimal(reminder.get("due_mileage_km"))
    if due_hours is not None:
        parts.append(format_hours(due_hours))
    elif due_mileage_km is not None:
        parts.append(format_quantity(due_mileage_km, render_context, "distance"))

    return " · ".join(parts) if parts else "N/A"


def _build_reminders_table(
    reminders_data: list[dict[str, Any]],
    styles: dict[str, Any],
    render_context: RenderContext,
) -> Table:
    """Build the upcoming-reminders table. A reminder with ``due_hours`` set
    renders its target in hours (see ``_reminder_due_text``), never blank
    and never a mileage figure.
    """
    cell_style = styles["TableCell"]

    rows = []
    for reminder in reminders_data:
        rows.append(
            [
                Paragraph(str(reminder.get("title", "")), cell_style),
                Paragraph(str(reminder.get("reminder_type", "")).title(), cell_style),
                Paragraph(_reminder_due_text(reminder, render_context), cell_style),
            ]
        )

    return make_data_table(
        headers=["Reminder", "Type", "Due"],
        rows=rows,
        col_widths=[CONTENT_WIDTH * 0.4, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.4],
    )


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
    currency_code: str = "USD",
    locale: str = "en-US",
    reminders_data: list[dict[str, Any]] | None = None,
    *,
    render_context: RenderContext,
) -> BytesIO:
    """Generate a branded vehicle analytics PDF report.

    Args:
        analytics_data: VehicleAnalytics.model_dump() output. The
            "Usage & Efficiency" and "Hours History" sections render from
            its existing ``total_km_driven``/``average_km_per_month``/
            ``fuel_economy``/``hours_economy``/``hours_accumulated``
            fields — no extra plumbing required for those.
        vendor_data: VendorAnalyticsSummary.model_dump() output, or None.
        seasonal_data: SeasonalAnalyticsSummary.model_dump() output, or None.
        currency_code: ISO 4217 currency code (default "USD") used in PDF rendering.
        locale: BCP 47 locale for currency symbol selection (default "en-US").
        reminders_data: Optional list of reminder dicts (mirroring
            ``schemas.reminder.ReminderResponse``: ``title``,
            ``reminder_type``, ``due_date``, ``due_mileage_km``,
            ``due_hours``) rendered as an "Upcoming Reminders" section when
            provided. An hours-targeted reminder (``due_hours`` set) shows
            its target in hours, never blank or a mileage figure. Follows
            the same optional-section pattern as ``vendor_data``/
            ``seasonal_data`` — omitted entirely when None.
        render_context: Whose units this report renders in. Keyword-only and
            required, with no default: every distance, consumption and
            fuel-rate figure below depends on it, and a defaulted context
            would let a new call site silently render one instance-wide unit
            for every reader. Hours are exempt (R6, ``format_hours``).

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
    cost_per_km = _safe_decimal(cost.get("cost_per_km"))
    avg_monthly = _safe_float(cost.get("average_monthly_cost", 0))
    projected_12m = _safe_float(projection.get("twelve_month_projection", 0))
    service_count = _safe_int(cost.get("service_count", 0))
    fuel_count = _safe_int(cost.get("fuel_count", 0))
    rolling_3m = _safe_float(cost.get("rolling_avg_3m"))
    trend_dir = str(cost.get("trend_direction", "stable"))

    kpi_cards = [
        {
            "label": "Total Cost",
            "value": format_currency_short(total_cost, currency_code, locale),
            "sub": f"{service_count} services · {fuel_count} fuel",
            "color": "blue",
        },
        {
            # Not "Cost Per km": the value string names its own denominator
            # (D4c pairs a km reader with "/100 km" and a mile reader with
            # "/1,000 mi"), so a label hardcoding one unit would contradict
            # the number underneath it for every imperial reader.
            "label": "Cost Per Distance",
            "value": (
                format_cost_per_distance(cost_per_km, render_context, currency_code, locale)
                if cost_per_km
                else "N/A"
            ),
            "sub_html": _trend_badge_html(trend_dir),
            "color": "green",
        },
        {
            "label": "Avg Monthly",
            "value": format_currency_short(avg_monthly, currency_code, locale),
            "sub": (
                f"3-mo rolling: {format_currency(rolling_3m, currency_code, locale)}"
                if rolling_3m
                else ""
            ),
            "color": "amber",
        },
        {
            "label": "Projected 12-Mo",
            "value": format_currency_short(projected_12m, currency_code, locale),
            "sub": "Based on recent avg",
            "color": "red",
        },
    ]

    story.append(make_kpi_row(kpi_cards))
    story.append(Spacer(1, SECTION_SPACING))

    # ── 2b. Usage & Efficiency (hours-usage-model) ─────────────
    # Distance cards only appear when total_km_driven is present; hours
    # cards only when hours_accumulated is non-empty. A pure-distance
    # vehicle (neither) skips this whole block — report unchanged.
    usage_cards = _build_usage_efficiency_cards(
        analytics_data, currency_code, locale, render_context
    )
    if usage_cards:
        story.append(make_section_header("Usage & Efficiency"))
        story.append(Spacer(1, 10))
        story.append(make_kpi_row(usage_cards))
        story.append(Spacer(1, SECTION_SPACING))

    # ── 2c. Hours History ───────────────────────────────────────
    hours_accumulated = analytics_data.get("hours_accumulated") or []
    if hours_accumulated:
        story.append(
            make_section_header(
                "Hours History",
                annotation=(
                    f"{len(hours_accumulated)} reading{'s' if len(hours_accumulated) != 1 else ''}"
                ),
            )
        )
        story.append(Spacer(1, 10))
        # style_as_card (not wrap_in_card) — this table can run to 20 rows,
        # and wrap_in_card nests it in a non-splittable single-cell
        # container that reportlab can't paginate (see style_as_card's
        # docstring; the same LayoutError the service-breakdown table
        # avoids above by skipping wrap_in_card past 10 rows).
        story.append(style_as_card(_build_hours_history_table(hours_accumulated, styles)))
        story.append(Spacer(1, SECTION_SPACING))

    # ── 2d. Upcoming Reminders ──────────────────────────────────
    if reminders_data:
        story.append(
            make_section_header(
                "Upcoming Reminders",
                annotation=(
                    f"{len(reminders_data)} reminder{'s' if len(reminders_data) != 1 else ''}"
                ),
            )
        )
        story.append(Spacer(1, 10))
        # style_as_card, not wrap_in_card — reminders_data is caller-sized
        # and unbounded; keep the table splittable across pages.
        story.append(style_as_card(_build_reminders_table(reminders_data, styles, render_context)))
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
                    Paragraph(
                        format_currency_compact(svc.get("total_cost", 0), currency_code, locale),
                        amt_style,
                    ),
                    Paragraph(
                        format_currency_compact(svc.get("average_cost", 0), currency_code, locale),
                        amt_style,
                    ),
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
            currency_code=currency_code,
            locale=locale,
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
                annotation=f"Annual avg: {format_currency(annual_avg, currency_code, locale)}",
            )
        )
        story.append(Spacer(1, 10))

        season_grid = make_season_row(
            seasons=seasons,
            highest_season=highest,
            lowest_season=lowest,
            currency_code=currency_code,
            locale=locale,
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
