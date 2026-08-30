"""PDF report generation utilities using ReportLab."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.utils.render_context import RenderContext
from app.utils.unit_adapters import adapter_for
from app.utils.unit_formatting import format_label


class PDFReportGenerator:
    """Generate PDF reports for vehicle maintenance tracking.

    Handles service history, cost summary, and tax deduction reports.
    For analytics reports (vehicle + garage), see pdf_vehicle_report.py
    and pdf_garage_report.py.

    Every report is rendered in one caller's units. `render_context` is
    required rather than defaulted, so a new report or a new route cannot
    silently fall back to a hardcoded unit; the two reports that render no
    unit-bearing quantity at all (cost summary, tax deduction) still take
    one, because the context belongs to the generator, not to one method.
    """

    def __init__(
        self,
        render_context: RenderContext,
        currency_code: str = "USD",
        locale: str = "en-US",
    ):
        """Build a generator bound to one render context and currency."""
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        self.currency_code = currency_code
        self.locale = locale
        self.render_context = render_context

    def _odometer_header(self) -> str:
        """The odometer column's header cell, e.g. `"Odometer (km)"`.

        `format_label`, not `format_quantity`: a header names one column and
        has no value to format, and a header stating two units for one
        column would be a defect even under show-both.
        """
        return f"Odometer ({format_label(self.render_context, 'distance')})"

    def _format_odometer(self, odometer_km: Any) -> str:
        """Render a canonical-km odometer reading for a unit-labelled column.

        A bare number with no unit: `_odometer_header` already names the
        column's unit once, so repeating it on every row (or appending a
        show-both counterpart inside a 0.9-inch column) would be noise.

        RECORDED EXCEPTION to the "every human-readable `UnitSet` quantity
        goes through the composition layer" rule (phase exit criterion 8,
        custom-units phase 2a). These two table cells are the one distance
        site in the phase that never gains a ` (counterpart)`, whatever the
        reader's `show_both_units` says -- see the call site below.

        Falsy input stays `"N/A"`, exactly as before: a zero odometer is a
        missing reading rather than a real one, and that predates this
        becoming unit-aware.

        AUTHORISED BEHAVIOUR CHANGE: both odometer columns now round through
        the distance adapter (precision 0). The service-history report used
        to truncate (`int()`) and the sale report used to print the raw
        `Decimal`, so `123.90` rendered `123` in one and `123.90` in the
        other; one adapter precision cannot reproduce both, and it now
        renders `124` in both.
        """
        if not odometer_km:
            return "N/A"
        # DELIBERATE conversion-layer call from a human-readable surface, and
        # the only one in the phase (exit criterion 8 names it explicitly).
        # `format_quantity` cannot serve this site twice over: it always emits
        # the unit label the header already carries, and under `show_both` it
        # appends a counterpart a fixed-width table cell cannot hold. Measured
        # in the 9 pt Helvetica these cells use: the service-history odometer
        # column is 0.9 inch = 64.80 pt, while `"123,457 km (76,713 mi)"` is
        # 95.04 pt. The cell is a bare `str`, not a `Paragraph`, so ReportLab
        # does not wrap it -- it spills into the Date and Type columns either
        # side. The sale report's 1.4 inch = 100.80 pt column holds today's
        # six-figure pairing and not a seven-figure one, so it follows the same
        # rule rather than diverging by column width. The unit is stated once,
        # in `_odometer_header`, which is `format_label` from the composition
        # layer. Pinned by
        # `test_pdf_generator.py::TestOdometerCellsStaySingleRepresentationUnderShowBoth`.
        adapter = adapter_for(self.render_context.units, "distance")
        return adapter.format(Decimal(str(odometer_km)), with_label=False)

    def _setup_custom_styles(self):
        """Setup custom paragraph styles."""
        # Title style
        self.styles.add(
            ParagraphStyle(
                name="CustomTitle",
                parent=self.styles["Heading1"],
                fontSize=24,
                textColor=colors.HexColor("#2563eb"),
                spaceAfter=30,
                alignment=TA_CENTER,
            )
        )

        # Subtitle style
        self.styles.add(
            ParagraphStyle(
                name="CustomSubtitle",
                parent=self.styles["Heading2"],
                fontSize=16,
                textColor=colors.HexColor("#3b82f6"),
                spaceAfter=12,
            )
        )

        # Info style
        self.styles.add(
            ParagraphStyle(
                name="InfoText",
                parent=self.styles["Normal"],
                fontSize=10,
                textColor=colors.HexColor("#6b7280"),
            )
        )

    def _format_currency(self, amount: Decimal | None) -> str:
        """Format decimal as currency using the instance's currency_code/locale."""
        from app.utils.currency import get_currency_symbol

        if amount is None:
            return "N/A"
        symbol = get_currency_symbol(self.currency_code, self.locale)
        return f"{symbol}{float(amount):,.2f}"

    def _format_date(self, date_obj: date_type | None) -> str:
        """Format date object."""
        if date_obj is None:
            return "N/A"
        if isinstance(date_obj, str):
            return date_obj
        return date_obj.strftime("%m/%d/%Y")

    def generate_service_history_pdf(
        self,
        vehicle_info: dict[str, Any],
        service_records: list[dict[str, Any]],
        start_date: date_type | None = None,
        end_date: date_type | None = None,
    ) -> BytesIO:
        """Generate service history PDF report."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        # Title
        title = Paragraph("Service History Report", self.styles["CustomTitle"])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Vehicle Info
        vehicle_text = f"""
        <b>Vehicle:</b> {vehicle_info["year"]} {vehicle_info["make"]} {vehicle_info["model"]}<br/>
        <b>VIN:</b> {vehicle_info["vin"]}<br/>
        <b>License Plate:</b> {vehicle_info.get("license_plate", "N/A")}<br/>
        """
        if start_date and end_date:
            vehicle_text += f"<b>Period:</b> {self._format_date(start_date)} - {self._format_date(end_date)}<br/>"

        vehicle_text += f"<b>Report Generated:</b> {datetime.now().strftime('%m/%d/%Y %I:%M %p')}"

        story.append(Paragraph(vehicle_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        # Service Records Table
        if service_records:
            story.append(Paragraph("Service Records", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            # Table headers
            headers = ["Date", self._odometer_header(), "Type", "Description", "Cost", "Vendor"]
            header_style = ParagraphStyle(
                "TableHeader",
                parent=self.styles["Normal"],
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=colors.whitesmoke,
                alignment=TA_CENTER,
            )
            table_data = [[Paragraph(h, header_style) for h in headers]]

            # Table rows
            total_cost = Decimal("0")
            for record in service_records:
                cost = record.get("cost")
                if cost:
                    total_cost += Decimal(str(cost))

                table_data.append(
                    [
                        self._format_date(record.get("date")),
                        self._format_odometer(record.get("odometer_km")),
                        Paragraph(
                            str(record.get("service_category") or "Service"),
                            self.styles["Normal"],
                        ),
                        Paragraph(
                            str(record.get("service_type") or "N/A")[:50],
                            self.styles["Normal"],
                        ),
                        self._format_currency(cost),
                        Paragraph(str(record.get("vendor_name") or "N/A"), self.styles["Normal"]),
                    ]
                )

            # Add total row
            table_data.append(
                [
                    "",
                    "",
                    "",
                    Paragraph("<b>Total:</b>", self.styles["Normal"]),
                    Paragraph(
                        f"<b>{self._format_currency(total_cost)}</b>",
                        self.styles["Normal"],
                    ),
                    "",
                ]
            )

            # Create table
            table = Table(
                table_data,
                colWidths=[
                    0.8 * inch,
                    0.9 * inch,
                    1.0 * inch,
                    1.8 * inch,
                    0.8 * inch,
                    1.4 * inch,
                ],
            )
            table.setStyle(
                TableStyle(
                    [
                        # Header row
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        # Data rows
                        ("BACKGROUND", (0, 1), (-1, -2), colors.white),
                        ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                        ("ALIGN", (1, 1), (1, -1), "CENTER"),  # Mileage
                        ("ALIGN", (4, 1), (4, -1), "RIGHT"),  # Cost
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        # Total row
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                        ("LINEABOVE", (0, -1), (-1, -1), 2, colors.HexColor("#3b82f6")),
                        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ]
                )
            )

            story.append(table)
        else:
            story.append(
                Paragraph("No service records found for this period.", self.styles["Normal"])
            )

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_sale_history_pdf(
        self,
        vehicle_info: dict[str, Any],
        service_records: list[dict[str, Any]],
    ) -> BytesIO:
        """Buyer-facing sanitized service history (no costs, vendors, plate, or full VIN)."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        story.append(Paragraph("Vehicle History Summary", self.styles["CustomTitle"]))
        story.append(Spacer(1, 0.2 * inch))

        vin = str(vehicle_info.get("vin") or "")
        vin_tail = vin[-6:] if len(vin) >= 6 else vin
        vehicle_text = f"""
        <b>Vehicle:</b> {vehicle_info.get("year") or ""} {vehicle_info.get("make") or ""} {vehicle_info.get("model") or ""}<br/>
        <b>VIN (last 6):</b> {vin_tail or "N/A"}<br/>
        <b>Report Generated:</b> {datetime.now().strftime("%m/%d/%Y %I:%M %p")}<br/>
        <i>Sanitized for prospective buyers — costs, vendors, plate, and full VIN omitted.</i>
        """
        story.append(Paragraph(vehicle_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        if service_records:
            story.append(Paragraph("Service History", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))
            table_data = [["Date", self._odometer_header(), "Service"]]
            for record in service_records:
                desc = record.get("service_type") or record.get("description") or "Service"
                table_data.append(
                    [
                        self._format_date(record.get("date")),
                        self._format_odometer(record.get("odometer_km")),
                        Paragraph(str(desc)[:80], self.styles["Normal"]),
                    ]
                )
            table = Table(table_data, colWidths=[1.2 * inch, 1.4 * inch, 4.2 * inch])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(table)
        else:
            story.append(Paragraph("No service records available.", self.styles["Normal"]))

        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_cost_summary_pdf(
        self,
        vehicle_info: dict[str, Any],
        cost_data: dict[str, Any],
        year: int,
    ) -> BytesIO:
        """Generate annual cost summary PDF."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        # Title
        title = Paragraph(f"Annual Cost Summary - {year}", self.styles["CustomTitle"])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Vehicle Info
        vehicle_text = f"""
        <b>Vehicle:</b> {vehicle_info["year"]} {vehicle_info["make"]} {vehicle_info["model"]}<br/>
        <b>VIN:</b> {vehicle_info["vin"]}<br/>
        <b>Report Generated:</b> {datetime.now().strftime("%m/%d/%Y %I:%M %p")}
        """
        story.append(Paragraph(vehicle_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        # Cost Summary
        story.append(Paragraph("Cost Breakdown", self.styles["CustomSubtitle"]))
        story.append(Spacer(1, 0.1 * inch))

        # Summary table
        table_data = [["Category", "Count", "Total Cost", "Average"]]

        # Check if vehicle is motorized (not a trailer or fifth wheel)
        is_motorized = vehicle_info.get("vehicle_type") not in [
            "Trailer",
            "FifthWheel",
            "TravelTrailer",
        ]

        # Build categories list - exclude Fuel for non-motorized vehicles
        categories = [
            (
                "Service & Maintenance",
                cost_data.get("service_count", 0),
                cost_data.get("service_total", 0),
            ),
        ]

        if is_motorized:
            categories.append(
                ("Fuel", cost_data.get("fuel_count", 0), cost_data.get("fuel_total", 0))
            )

        categories.extend(
            [
                (
                    "Collisions & Repairs",
                    cost_data.get("collision_count", 0),
                    cost_data.get("collision_total", 0),
                ),
                (
                    "Upgrades",
                    cost_data.get("upgrade_count", 0),
                    cost_data.get("upgrade_total", 0),
                ),
            ]
        )

        grand_total = Decimal("0")
        for category_name, count, total in categories:
            total_dec = Decimal(str(total)) if total else Decimal("0")
            grand_total += total_dec
            avg = total_dec / count if count > 0 else Decimal("0")

            table_data.append(
                [
                    category_name,
                    str(count),
                    self._format_currency(total_dec),
                    self._format_currency(avg),
                ]
            )

        # Grand total
        table_data.append(
            [
                Paragraph("<b>Grand Total:</b>", self.styles["Normal"]),
                "",
                Paragraph(
                    f"<b>{self._format_currency(grand_total)}</b>",
                    self.styles["Normal"],
                ),
                "",
            ]
        )

        table = Table(table_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -2), colors.white),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                    ("LINEABOVE", (0, -1), (-1, -1), 2, colors.HexColor("#3b82f6")),
                ]
            )
        )

        story.append(table)
        story.append(Spacer(1, 0.3 * inch))

        # Monthly breakdown if available
        if "monthly_totals" in cost_data:
            story.append(Paragraph("Monthly Breakdown", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            monthly_data = [["Month", "Total Cost"]]
            for month, total in cost_data["monthly_totals"].items():
                monthly_data.append([month, self._format_currency(Decimal(str(total)))])

            monthly_table = Table(monthly_data, colWidths=[2 * inch, 2 * inch])
            monthly_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(monthly_table)

        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_tax_deduction_pdf(
        self,
        vehicle_info: dict[str, Any],
        deductible_records: list[dict[str, Any]],
        year: int,
    ) -> BytesIO:
        """Generate tax deduction report PDF."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        # Title
        title = Paragraph(f"Tax Deduction Report - {year}", self.styles["CustomTitle"])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Warning notice
        notice = Paragraph(
            "<b>Notice:</b> This report is for informational purposes only. "
            "Please consult with a tax professional for accurate tax advice.",
            self.styles["InfoText"],
        )
        story.append(notice)
        story.append(Spacer(1, 0.2 * inch))

        # Vehicle Info
        vehicle_text = f"""
        <b>Vehicle:</b> {vehicle_info["year"]} {vehicle_info["make"]} {vehicle_info["model"]}<br/>
        <b>VIN:</b> {vehicle_info["vin"]}<br/>
        <b>Tax Year:</b> {year}<br/>
        <b>Report Generated:</b> {datetime.now().strftime("%m/%d/%Y %I:%M %p")}
        """
        story.append(Paragraph(vehicle_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        # Deductible expenses
        story.append(Paragraph("Potentially Deductible Expenses", self.styles["CustomSubtitle"]))
        story.append(Spacer(1, 0.1 * inch))

        if deductible_records:
            table_data = [["Date", "Category", "Description", "Amount"]]

            total_deductible = Decimal("0")
            for record in deductible_records:
                amount = Decimal(str(record.get("cost", 0)))
                total_deductible += amount

                table_data.append(
                    [
                        self._format_date(record.get("date")),
                        record.get("category", "Service"),
                        Paragraph(record.get("description", "")[:60], self.styles["Normal"]),
                        self._format_currency(amount),
                    ]
                )

            table_data.append(
                [
                    "",
                    "",
                    Paragraph("<b>Total Deductible:</b>", self.styles["Normal"]),
                    Paragraph(
                        f"<b>{self._format_currency(total_deductible)}</b>",
                        self.styles["Normal"],
                    ),
                ]
            )

            table = Table(table_data, colWidths=[1 * inch, 1.5 * inch, 3 * inch, 1.5 * inch])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("BACKGROUND", (0, 1), (-1, -2), colors.white),
                        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                        ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                        ("LINEABOVE", (0, -1), (-1, -1), 2, colors.HexColor("#3b82f6")),
                    ]
                )
            )

            story.append(table)
        else:
            story.append(
                Paragraph(
                    "No deductible expenses found for this period.",
                    self.styles["Normal"],
                )
            )

        doc.build(story)
        buffer.seek(0)
        return buffer
