"""PDF report generation utilities using ReportLab."""

# pyright: reportMissingModuleSource=false, reportArgumentType=false

from io import BytesIO
from datetime import datetime, date as date_type
from decimal import Decimal
from typing import List, Dict, Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.lib.enums import TA_CENTER


class PDFReportGenerator:
    """Generate PDF reports for vehicle maintenance tracking."""

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

    def _format_currency(self, amount: Optional[Decimal]) -> str:
        """Format decimal as currency."""
        if amount is None:
            return "N/A"
        return f"${float(amount):,.2f}"

    def _format_date(self, date_obj: Optional[date_type]) -> str:
        """Format date object."""
        if date_obj is None:
            return "N/A"
        if isinstance(date_obj, str):
            return date_obj
        return date_obj.strftime("%m/%d/%Y")

    def generate_service_history_pdf(
        self,
        vehicle_info: Dict[str, Any],
        service_records: List[Dict[str, Any]],
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
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

        vehicle_text += (
            f"<b>Report Generated:</b> {datetime.now().strftime('%m/%d/%Y %I:%M %p')}"
        )

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
                        f"{record.get('mileage', 'N/A'):,}"
                        if record.get("mileage")
                        else "N/A",
                        record.get("service_type", "N/A"),
                        Paragraph(
                            record.get("description", "N/A")[:50], self.styles["Normal"]
                        ),
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
                Paragraph(
                    "No service records found for this period.", self.styles["Normal"]
                )
            )

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_cost_summary_pdf(
        self,
        vehicle_info: Dict[str, Any],
        cost_data: Dict[str, Any],
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

        table = Table(
            table_data, colWidths=[3 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
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
        vehicle_info: Dict[str, Any],
        deductible_records: List[Dict[str, Any]],
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
        story.append(
            Paragraph("Potentially Deductible Expenses", self.styles["CustomSubtitle"])
        )
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
                        Paragraph(
                            record.get("description", "")[:60], self.styles["Normal"]
                        ),
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

            table = Table(
                table_data, colWidths=[1 * inch, 1.5 * inch, 3 * inch, 1.5 * inch]
            )
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

    def generate_analytics_pdf(
        self,
        analytics_data: Dict[str, Any],
        vendor_data: Optional[Dict[str, Any]] = None,
        seasonal_data: Optional[Dict[str, Any]] = None,
    ) -> BytesIO:
        """Generate analytics summary PDF report."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        # Title
        title = Paragraph("Analytics Summary Report", self.styles["CustomTitle"])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Vehicle Info
        vehicle_text = f"""
        <b>Vehicle:</b> {analytics_data.get("vehicle_name", "N/A")}<br/>
        <b>VIN:</b> {analytics_data.get("vin", "N/A")}<br/>
        <b>Vehicle Type:</b> {analytics_data.get("vehicle_type", "N/A")}<br/>
        <b>Report Generated:</b> {datetime.now().strftime("%m/%d/%Y %I:%M %p")}
        """
        story.append(Paragraph(vehicle_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        # Cost Analysis Summary
        cost_analysis = analytics_data.get("cost_analysis", {})
        story.append(Paragraph("Cost Analysis Summary", self.styles["CustomSubtitle"]))
        story.append(Spacer(1, 0.1 * inch))

        cost_summary_data = [
            ["Metric", "Value"],
            [
                "Total Cost",
                self._format_currency(Decimal(str(cost_analysis.get("total_cost", 0)))),
            ],
            [
                "Average Monthly Cost",
                self._format_currency(
                    Decimal(str(cost_analysis.get("average_monthly_cost", 0)))
                ),
            ],
            ["Months Tracked", str(cost_analysis.get("months_tracked", 0))],
            ["Total Services", str(cost_analysis.get("service_count", 0))],
            ["Total Fuel Records", str(cost_analysis.get("fuel_count", 0))],
        ]

        if cost_analysis.get("cost_per_mile"):
            cost_summary_data.append(
                [
                    "Cost Per Mile",
                    self._format_currency(Decimal(str(cost_analysis["cost_per_mile"]))),
                ]
            )

        cost_summary_table = Table(cost_summary_data, colWidths=[3 * inch, 3 * inch])
        cost_summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f3f4f6")],
                    ),
                ]
            )
        )
        story.append(cost_summary_table)
        story.append(Spacer(1, 0.3 * inch))

        # Rolling Averages
        if (
            cost_analysis.get("rolling_avg_3m")
            or cost_analysis.get("rolling_avg_6m")
            or cost_analysis.get("rolling_avg_12m")
        ):
            story.append(Paragraph("Spending Trends", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            rolling_data = [["Period", "Rolling Average"]]
            if cost_analysis.get("rolling_avg_3m"):
                rolling_data.append(
                    [
                        "3-Month",
                        self._format_currency(
                            Decimal(str(cost_analysis["rolling_avg_3m"]))
                        ),
                    ]
                )
            if cost_analysis.get("rolling_avg_6m"):
                rolling_data.append(
                    [
                        "6-Month",
                        self._format_currency(
                            Decimal(str(cost_analysis["rolling_avg_6m"]))
                        ),
                    ]
                )
            if cost_analysis.get("rolling_avg_12m"):
                rolling_data.append(
                    [
                        "12-Month",
                        self._format_currency(
                            Decimal(str(cost_analysis["rolling_avg_12m"]))
                        ),
                    ]
                )

            trend_direction = cost_analysis.get(
                "trend_direction", "stable"
            ).capitalize()
            rolling_data.append(["Trend Direction", trend_direction])

            rolling_table = Table(rolling_data, colWidths=[3 * inch, 3 * inch])
            rolling_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10b981")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 11),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 10),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(rolling_table)
            story.append(Spacer(1, 0.3 * inch))

        # Cost Projection
        cost_projection = analytics_data.get("cost_projection", {})
        if cost_projection:
            story.append(Paragraph("Cost Projections", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            projection_data = [
                ["Projection Period", "Estimated Cost"],
                [
                    "Monthly Average",
                    self._format_currency(
                        Decimal(str(cost_projection.get("monthly_average", 0)))
                    ),
                ],
                [
                    "Next 6 Months",
                    self._format_currency(
                        Decimal(str(cost_projection.get("six_month_projection", 0)))
                    ),
                ],
                [
                    "Next 12 Months",
                    self._format_currency(
                        Decimal(str(cost_projection.get("twelve_month_projection", 0)))
                    ),
                ],
            ]

            projection_table = Table(projection_data, colWidths=[3 * inch, 3 * inch])
            projection_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f59e0b")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 11),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 10),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(projection_table)

            # Add assumptions note
            assumptions = cost_projection.get("assumptions", "")
            if assumptions:
                story.append(Spacer(1, 0.1 * inch))
                story.append(
                    Paragraph(
                        f"<i>Assumptions: {assumptions}</i>", self.styles["InfoText"]
                    )
                )

            story.append(PageBreak())

        # Monthly Breakdown (last 12 months)
        monthly_breakdown = cost_analysis.get("monthly_breakdown", [])
        if monthly_breakdown:
            story.append(
                Paragraph("Monthly Cost Breakdown", self.styles["CustomSubtitle"])
            )
            story.append(Spacer(1, 0.1 * inch))

            monthly_data = [["Month", "Year", "Service", "Fuel", "Total"]]
            for month in monthly_breakdown[-12:]:
                monthly_data.append(
                    [
                        month.get("month_name", "N/A")[:3],
                        str(month.get("year", "")),
                        self._format_currency(
                            Decimal(str(month.get("total_service_cost", 0)))
                        ),
                        self._format_currency(
                            Decimal(str(month.get("total_fuel_cost", 0)))
                        ),
                        self._format_currency(Decimal(str(month.get("total_cost", 0)))),
                    ]
                )

            monthly_table = Table(
                monthly_data,
                colWidths=[1.2 * inch, 0.8 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch],
            )
            monthly_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b5cf6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(monthly_table)
            story.append(Spacer(1, 0.3 * inch))

        # Service Type Breakdown
        service_breakdown = cost_analysis.get("service_type_breakdown", [])
        if service_breakdown:
            story.append(
                Paragraph("Service Type Breakdown", self.styles["CustomSubtitle"])
            )
            story.append(Spacer(1, 0.1 * inch))

            service_data = [["Service Type", "Total Cost", "Count", "Avg Cost"]]
            for service in service_breakdown[:10]:
                service_data.append(
                    [
                        service.get("service_type", "N/A"),
                        self._format_currency(
                            Decimal(str(service.get("total_cost", 0)))
                        ),
                        str(service.get("count", 0)),
                        self._format_currency(
                            Decimal(str(service.get("average_cost", 0)))
                        ),
                    ]
                )

            service_table = Table(
                service_data, colWidths=[2.5 * inch, 1.5 * inch, 1 * inch, 1.5 * inch]
            )
            service_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ec4899")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                        ("ALIGN", (0, 0), (0, -1), "LEFT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(service_table)
            story.append(PageBreak())

        # Vendor Analysis
        if vendor_data and vendor_data.get("vendors"):
            story.append(Paragraph("Vendor Analysis", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            # Summary
            vendor_summary = [
                ["Total Vendors", str(vendor_data.get("total_vendors", 0))],
            ]
            if vendor_data.get("most_used_vendor"):
                vendor_summary.append(
                    ["Most Used Vendor", vendor_data["most_used_vendor"]]
                )
            if vendor_data.get("highest_spending_vendor"):
                vendor_summary.append(
                    ["Highest Spending Vendor", vendor_data["highest_spending_vendor"]]
                )

            vendor_summary_table = Table(
                vendor_summary, colWidths=[2.5 * inch, 3.5 * inch]
            )
            vendor_summary_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                    ]
                )
            )
            story.append(vendor_summary_table)
            story.append(Spacer(1, 0.2 * inch))

            # Vendor Details
            vendor_table_data = [["Vendor", "Total Spent", "Services", "Avg Cost"]]
            for vendor in vendor_data["vendors"][:10]:
                vendor_table_data.append(
                    [
                        vendor.get("vendor_name", "N/A"),
                        self._format_currency(
                            Decimal(str(vendor.get("total_spent", 0)))
                        ),
                        str(vendor.get("service_count", 0)),
                        self._format_currency(
                            Decimal(str(vendor.get("average_cost", 0)))
                        ),
                    ]
                )

            vendor_table = Table(
                vendor_table_data,
                colWidths=[2.5 * inch, 1.5 * inch, 1 * inch, 1.5 * inch],
            )
            vendor_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                        ("ALIGN", (0, 0), (0, -1), "LEFT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(vendor_table)
            story.append(Spacer(1, 0.3 * inch))

        # Seasonal Analysis
        if seasonal_data and seasonal_data.get("seasons"):
            story.append(
                Paragraph("Seasonal Spending Patterns", self.styles["CustomSubtitle"])
            )
            story.append(Spacer(1, 0.1 * inch))

            # Summary
            seasonal_summary = [
                [
                    "Annual Average",
                    self._format_currency(
                        Decimal(str(seasonal_data.get("annual_average", 0)))
                    ),
                ],
            ]
            if seasonal_data.get("highest_cost_season"):
                seasonal_summary.append(
                    ["Highest Cost Season", seasonal_data["highest_cost_season"]]
                )
            if seasonal_data.get("lowest_cost_season"):
                seasonal_summary.append(
                    ["Lowest Cost Season", seasonal_data["lowest_cost_season"]]
                )

            seasonal_summary_table = Table(
                seasonal_summary, colWidths=[2.5 * inch, 3.5 * inch]
            )
            seasonal_summary_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                    ]
                )
            )
            story.append(seasonal_summary_table)
            story.append(Spacer(1, 0.2 * inch))

            # Seasonal Details
            seasonal_table_data = [
                ["Season", "Total Cost", "Avg Cost", "Services", "Variance"]
            ]
            for season in seasonal_data["seasons"]:
                seasonal_table_data.append(
                    [
                        season.get("season", "N/A"),
                        self._format_currency(
                            Decimal(str(season.get("total_cost", 0)))
                        ),
                        self._format_currency(
                            Decimal(str(season.get("average_cost", 0)))
                        ),
                        str(season.get("service_count", 0)),
                        f"{season.get('variance_from_annual', '0')}%",
                    ]
                )

            seasonal_table = Table(
                seasonal_table_data,
                colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1 * inch, 1 * inch],
            )
            seasonal_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10b981")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(seasonal_table)

        # Footer
        story.append(Spacer(1, 0.4 * inch))
        footer = Paragraph(
            f"Generated by MyGarage on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            ParagraphStyle(
                "Footer",
                parent=self.styles["Normal"],
                fontSize=8,
                textColor=colors.HexColor("#9ca3af"),
                alignment=TA_CENTER,
            ),
        )
        story.append(footer)

        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_garage_analytics_pdf(self, garage_data: Dict[str, Any]) -> BytesIO:
        """Generate garage analytics summary PDF report."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
        )
        story = []

        # Title
        title = Paragraph("Garage Analytics Report", self.styles["CustomTitle"])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Garage Info
        garage_text = f"""
        <b>Total Vehicles:</b> {garage_data.get("vehicle_count", 0)}<br/>
        <b>Report Generated:</b> {datetime.now().strftime("%m/%d/%Y %I:%M %p")}
        """
        story.append(Paragraph(garage_text, self.styles["InfoText"]))
        story.append(Spacer(1, 0.3 * inch))

        # Garage Cost Summary
        total_costs = garage_data.get("total_costs", {})
        story.append(Paragraph("Garage Cost Summary", self.styles["CustomSubtitle"]))
        story.append(Spacer(1, 0.1 * inch))

        garage_summary_data = [
            ["Category", "Amount"],
            [
                "Garage Value",
                self._format_currency(
                    Decimal(str(total_costs.get("total_garage_value", 0)))
                ),
            ],
            [
                "Total Maintenance",
                self._format_currency(
                    Decimal(str(total_costs.get("total_maintenance", 0)))
                ),
            ],
            [
                "Total Fuel",
                self._format_currency(Decimal(str(total_costs.get("total_fuel", 0)))),
            ],
            [
                "Total Insurance",
                self._format_currency(
                    Decimal(str(total_costs.get("total_insurance", 0)))
                ),
            ],
            [
                "Total Taxes",
                self._format_currency(Decimal(str(total_costs.get("total_taxes", 0)))),
            ],
        ]

        # Calculate grand total
        grand_total = sum(
            [
                Decimal(str(total_costs.get("total_maintenance", 0))),
                Decimal(str(total_costs.get("total_fuel", 0))),
                Decimal(str(total_costs.get("total_insurance", 0))),
                Decimal(str(total_costs.get("total_taxes", 0))),
            ]
        )
        garage_summary_data.append(
            ["Total Operating Cost", self._format_currency(grand_total)]
        )

        garage_summary_table = Table(
            garage_summary_data, colWidths=[3 * inch, 3 * inch]
        )
        garage_summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82f6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f3f4f6")],
                    ),
                    # Highlight grand total row
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e0f2fe")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        story.append(garage_summary_table)
        story.append(Spacer(1, 0.3 * inch))

        # Cost Breakdown by Category
        cost_breakdown = garage_data.get("cost_breakdown_by_category", [])
        if cost_breakdown:
            story.append(
                Paragraph("Cost Breakdown by Category", self.styles["CustomSubtitle"])
            )
            story.append(Spacer(1, 0.1 * inch))

            category_data = [["Category", "Amount"]]
            for cat in cost_breakdown:
                category_data.append(
                    [
                        cat.get("category", "N/A"),
                        self._format_currency(Decimal(str(cat.get("amount", 0)))),
                    ]
                )

            category_table = Table(category_data, colWidths=[3 * inch, 3 * inch])
            category_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10b981")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 11),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 10),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(category_table)
            story.append(PageBreak())

        # Cost by Vehicle
        cost_by_vehicle = garage_data.get("cost_by_vehicle", [])
        if cost_by_vehicle:
            story.append(Paragraph("Cost by Vehicle", self.styles["CustomSubtitle"]))
            story.append(Spacer(1, 0.1 * inch))

            vehicle_data = [["Vehicle", "Purchase", "Maintenance", "Fuel", "Total"]]
            for vehicle in cost_by_vehicle:
                vehicle_name = vehicle.get("name", "N/A")
                if len(vehicle_name) > 25:
                    vehicle_name = vehicle_name[:22] + "..."
                vehicle_data.append(
                    [
                        vehicle_name,
                        self._format_currency(
                            Decimal(str(vehicle.get("purchase_price", 0)))
                        ),
                        self._format_currency(
                            Decimal(str(vehicle.get("total_maintenance", 0)))
                        ),
                        self._format_currency(
                            Decimal(str(vehicle.get("total_fuel", 0)))
                        ),
                        self._format_currency(
                            Decimal(str(vehicle.get("total_cost", 0)))
                        ),
                    ]
                )

            vehicle_table = Table(
                vehicle_data,
                colWidths=[
                    2 * inch,
                    1.25 * inch,
                    1.25 * inch,
                    1.25 * inch,
                    1.25 * inch,
                ],
            )
            vehicle_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f59e0b")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                        ("ALIGN", (0, 0), (0, -1), "LEFT"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(vehicle_table)
            story.append(Spacer(1, 0.3 * inch))

        # Monthly Trends
        monthly_trends = garage_data.get("monthly_trends", [])
        if monthly_trends:
            story.append(
                Paragraph(
                    "Monthly Spending Trends (Last 12 Months)",
                    self.styles["CustomSubtitle"],
                )
            )
            story.append(Spacer(1, 0.1 * inch))

            trend_data = [["Month", "Maintenance", "Fuel", "Total"]]
            for trend in monthly_trends[-12:]:
                maintenance = Decimal(str(trend.get("maintenance", 0)))
                fuel = Decimal(str(trend.get("fuel", 0)))
                total = maintenance + fuel
                trend_data.append(
                    [
                        trend.get("month", "N/A"),
                        self._format_currency(maintenance),
                        self._format_currency(fuel),
                        self._format_currency(total),
                    ]
                )

            trend_table = Table(
                trend_data, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch]
            )
            trend_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b5cf6")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f3f4f6")],
                        ),
                    ]
                )
            )
            story.append(trend_table)

        # Footer
        story.append(Spacer(1, 0.4 * inch))
        footer = Paragraph(
            f"Generated by MyGarage on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            ParagraphStyle(
                "Footer",
                parent=self.styles["Normal"],
                fontSize=8,
                textColor=colors.HexColor("#9ca3af"),
                alignment=TA_CENTER,
            ),
        )
        story.append(footer)

        doc.build(story)
        buffer.seek(0)
        return buffer
