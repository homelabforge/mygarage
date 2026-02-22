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


class PDFReportGenerator:
    """Generate PDF reports for vehicle maintenance tracking.

    Handles service history, cost summary, and tax deduction reports.
    For analytics reports (vehicle + garage), see pdf_vehicle_report.py
    and pdf_garage_report.py.
    """

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

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
        """Format decimal as currency."""
        if amount is None:
            return "N/A"
        return f"${float(amount):,.2f}"

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
            table_data = [["Date", "Mileage", "Type", "Description", "Cost", "Vendor"]]

            # Table rows
            total_cost = Decimal("0")
            for record in service_records:
                cost = record.get("cost")
                if cost:
                    total_cost += Decimal(str(cost))

                table_data.append(
                    [
                        self._format_date(record.get("date")),
                        f"{record.get('mileage', 'N/A'):,}" if record.get("mileage") else "N/A",
                        record.get("service_type", "N/A"),
                        Paragraph(record.get("description", "N/A")[:50], self.styles["Normal"]),
                        self._format_currency(cost),
                        record.get("vendor_name", "N/A")[:20]
                        if record.get("vendor_name")
                        else "N/A",
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
                    0.9 * inch,
                    0.8 * inch,
                    1 * inch,
                    2 * inch,
                    0.9 * inch,
                    1.2 * inch,
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
                        ("ALIGN", (1, 1), (1, -1), "RIGHT"),  # Mileage
                        ("ALIGN", (4, 1), (4, -1), "RIGHT"),  # Cost
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
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
        is_motorized = vehicle_info.get("vehicle_type") not in ["Trailer", "FifthWheel"]

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
