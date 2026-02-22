"""Design system constants, font registration, and matplotlib config for PDF reports."""

import logging
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ── Color Palette (ReportLab Color objects) ────────────────
BG_PRIMARY = colors.HexColor("#ffffff")
BG_CARD = colors.HexColor("#f8f9fb")
BG_CARD_ALT = colors.HexColor("#f1f3f7")
BORDER = colors.HexColor("#e2e5ec")
BORDER_LIGHT = colors.HexColor("#edf0f4")
TEXT_PRIMARY = colors.HexColor("#1a1d2b")
TEXT_SECONDARY = colors.HexColor("#5a5f73")
TEXT_MUTED = colors.HexColor("#8c91a3")

ACCENT_BLUE = colors.HexColor("#2563eb")
ACCENT_BLUE_LIGHT = colors.HexColor("#dbeafe")
ACCENT_CYAN = colors.HexColor("#0891b2")
ACCENT_CYAN_LIGHT = colors.HexColor("#cffafe")
ACCENT_GREEN = colors.HexColor("#059669")
ACCENT_GREEN_LIGHT = colors.HexColor("#d1fae5")
ACCENT_AMBER = colors.HexColor("#d97706")
ACCENT_AMBER_LIGHT = colors.HexColor("#fef3c7")
ACCENT_RED = colors.HexColor("#dc2626")
ACCENT_RED_LIGHT = colors.HexColor("#fee2e2")
ACCENT_PURPLE = colors.HexColor("#7c3aed")
ACCENT_PURPLE_LIGHT = colors.HexColor("#ede9fe")
ACCENT_ORANGE = colors.HexColor("#ea580c")
ACCENT_TEAL = colors.HexColor("#14b8a6")
ACCENT_PINK = colors.HexColor("#ec4899")

# ── Hex Strings (for matplotlib) ──────────────────────────
MPL = {
    "bg_card": "#f8f9fb",
    "bg_card_alt": "#f1f3f7",
    "border": "#e2e5ec",
    "border_light": "#edf0f4",
    "text_primary": "#1a1d2b",
    "text_secondary": "#5a5f73",
    "text_muted": "#8c91a3",
    "blue": "#2563eb",
    "cyan": "#0891b2",
    "green": "#059669",
    "amber": "#d97706",
    "red": "#dc2626",
    "purple": "#7c3aed",
    "orange": "#ea580c",
    "teal": "#14b8a6",
    "pink": "#ec4899",
}

# Donut/pie chart color cycle (for cost distribution)
CHART_COLORS = [
    "#2563eb",  # blue - Collision / primary
    "#0891b2",  # cyan - AC / secondary service
    "#059669",  # green - Brakes / mechanical
    "#d97706",  # amber - Oil / routine
    "#ea580c",  # orange - Detailing
    "#7c3aed",  # purple - Fuel
    "#ec4899",  # pink - Insurance
    "#14b8a6",  # teal - DEF
    "#6b7280",  # gray - Taxes / other
]

# ── Layout Constants ───────────────────────────────────────
PAGE_SIZE = letter  # 8.5" x 11"
PAGE_WIDTH = letter[0]  # 612 points
PAGE_HEIGHT = letter[1]  # 792 points
MARGIN = 0.6 * inch  # 43.2 points
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)  # ~525.6 points / ~7.3 inches
CARD_RADIUS = 14
ACCENT_BAR_HEIGHT = 3
SECTION_SPACING = 24  # points

# Header/footer reserved space
HEADER_HEIGHT = 80  # points reserved for branded header
FOOTER_HEIGHT = 50  # points reserved for branded footer

# ── Font Paths ─────────────────────────────────────────────
FONT_DIR = Path(__file__).parent.parent / "fonts"
ICONS_DIR = FONT_DIR / "icons"

# Font name constants
BODY_FONT = "DMSans"
BODY_FONT_MEDIUM = "DMSans-Medium"
BODY_FONT_SEMIBOLD = "DMSans-SemiBold"
BODY_FONT_BOLD = "DMSans-Bold"
MONO_FONT = "JetBrainsMono"
MONO_FONT_MEDIUM = "JetBrainsMono-Medium"
MONO_FONT_SEMIBOLD = "JetBrainsMono-SemiBold"

# Fallbacks
_FALLBACK_BODY = "Helvetica"
_FALLBACK_BODY_BOLD = "Helvetica-Bold"
_FALLBACK_MONO = "Courier"
_FALLBACK_MONO_BOLD = "Courier-Bold"

_fonts_registered = False
_active_fonts: tuple[str, str, str, str] | None = None


def register_fonts() -> tuple[str, str, str, str]:
    """Register custom fonts with ReportLab.

    Returns:
        Tuple of (body_font, body_bold, mono_font, mono_bold) names to use.
        Falls back to Helvetica/Courier if custom fonts are unavailable.
    """
    global _fonts_registered, _active_fonts
    if _fonts_registered and _active_fonts:
        return _active_fonts

    body = _FALLBACK_BODY
    body_bold = _FALLBACK_BODY_BOLD
    mono = _FALLBACK_MONO
    mono_bold = _FALLBACK_MONO_BOLD

    # Register DM Sans
    try:
        dm_regular = FONT_DIR / "DMSans-Regular.ttf"
        if dm_regular.exists():
            pdfmetrics.registerFont(TTFont("DMSans", str(FONT_DIR / "DMSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("DMSans-Medium", str(FONT_DIR / "DMSans-Medium.ttf")))
            pdfmetrics.registerFont(
                TTFont("DMSans-SemiBold", str(FONT_DIR / "DMSans-SemiBold.ttf"))
            )
            pdfmetrics.registerFont(TTFont("DMSans-Bold", str(FONT_DIR / "DMSans-Bold.ttf")))
            pdfmetrics.registerFontFamily(
                "DMSans",
                normal="DMSans",
                bold="DMSans-Bold",
                italic="DMSans",
                boldItalic="DMSans-Bold",
            )
            body = BODY_FONT
            body_bold = BODY_FONT_BOLD
            logger.debug("Registered DM Sans fonts")
    except Exception:
        logger.warning("Could not register DM Sans fonts, using Helvetica fallback")

    # Register JetBrains Mono
    try:
        jb_regular = FONT_DIR / "JetBrainsMono-Regular.ttf"
        if jb_regular.exists():
            pdfmetrics.registerFont(
                TTFont("JetBrainsMono", str(FONT_DIR / "JetBrainsMono-Regular.ttf"))
            )
            pdfmetrics.registerFont(
                TTFont("JetBrainsMono-Medium", str(FONT_DIR / "JetBrainsMono-Medium.ttf"))
            )
            pdfmetrics.registerFont(
                TTFont("JetBrainsMono-SemiBold", str(FONT_DIR / "JetBrainsMono-SemiBold.ttf"))
            )
            pdfmetrics.registerFontFamily(
                "JetBrainsMono",
                normal="JetBrainsMono",
                bold="JetBrainsMono-SemiBold",
                italic="JetBrainsMono",
                boldItalic="JetBrainsMono-SemiBold",
            )
            mono = MONO_FONT
            mono_bold = "JetBrainsMono-SemiBold"
            logger.debug("Registered JetBrains Mono fonts")
    except Exception:
        logger.warning("Could not register JetBrains Mono fonts, using Courier fallback")

    _fonts_registered = True
    _active_fonts = (body, body_bold, mono, mono_bold)
    return _active_fonts


def get_styles() -> dict[str, ParagraphStyle]:
    """Build the paragraph style dictionary for PDF reports.

    Call register_fonts() before calling this.
    """
    body, body_bold, mono, mono_bold = register_fonts()
    base_styles = getSampleStyleSheet()

    styles: dict[str, ParagraphStyle] = {}

    # Vehicle name / large heading
    styles["VehicleName"] = ParagraphStyle(
        "VehicleName",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=22,
        leading=28,
        textColor=ACCENT_BLUE,
        spaceAfter=4,
    )

    # Section title
    styles["SectionTitle"] = ParagraphStyle(
        "SectionTitle",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=16,
        leading=20,
        textColor=TEXT_PRIMARY,
    )

    # KPI label (uppercase, muted)
    styles["KPILabel"] = ParagraphStyle(
        "KPILabel",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=11,
        leading=14,
        textColor=TEXT_MUTED,
    )

    # KPI value (large monospace number)
    styles["KPIValue"] = ParagraphStyle(
        "KPIValue",
        parent=base_styles["Normal"],
        fontName=mono_bold,
        fontSize=20,
        leading=26,
        textColor=ACCENT_BLUE,
    )

    # KPI sub-detail
    styles["KPISub"] = ParagraphStyle(
        "KPISub",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
    )

    # Table header
    styles["TableHeader"] = ParagraphStyle(
        "TableHeader",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=10,
        leading=13,
        textColor=TEXT_MUTED,
    )

    # Table cell
    styles["TableCell"] = ParagraphStyle(
        "TableCell",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=13,
        leading=17,
        textColor=TEXT_SECONDARY,
    )

    # Table cell - monospace amount
    styles["TableAmount"] = ParagraphStyle(
        "TableAmount",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=13,
        leading=17,
        textColor=TEXT_PRIMARY,
        alignment=TA_RIGHT,
    )

    # Compact table variants (for dense multi-column tables like cost-by-vehicle)
    styles["TableHeaderCompact"] = ParagraphStyle(
        "TableHeaderCompact",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=7,
        leading=9,
        textColor=TEXT_MUTED,
    )

    styles["TableCellCompact"] = ParagraphStyle(
        "TableCellCompact",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=9,
        leading=12,
        textColor=TEXT_SECONDARY,
    )

    styles["TableAmountCompact"] = ParagraphStyle(
        "TableAmountCompact",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=8,
        leading=11,
        textColor=TEXT_PRIMARY,
        alignment=TA_RIGHT,
    )

    styles["TableHighlightCompact"] = ParagraphStyle(
        "TableHighlightCompact",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=9,
        leading=12,
        textColor=ACCENT_BLUE,
    )

    # Table cell - highlighted
    styles["TableHighlight"] = ParagraphStyle(
        "TableHighlight",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=13,
        leading=17,
        textColor=ACCENT_BLUE,
    )

    # Vendor name
    styles["VendorName"] = ParagraphStyle(
        "VendorName",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=13,
        leading=17,
        textColor=TEXT_PRIMARY,
    )

    # Vendor detail
    styles["VendorDetail"] = ParagraphStyle(
        "VendorDetail",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=11,
        leading=14,
        textColor=TEXT_MUTED,
    )

    # Vendor amount
    styles["VendorAmount"] = ParagraphStyle(
        "VendorAmount",
        parent=base_styles["Normal"],
        fontName=mono_bold,
        fontSize=14,
        leading=18,
        textColor=TEXT_PRIMARY,
        alignment=TA_RIGHT,
    )

    # Season name
    styles["SeasonName"] = ParagraphStyle(
        "SeasonName",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=12,
        leading=16,
        textColor=TEXT_SECONDARY,
        alignment=TA_CENTER,
    )

    # Season amount
    styles["SeasonAmount"] = ParagraphStyle(
        "SeasonAmount",
        parent=base_styles["Normal"],
        fontName=mono_bold,
        fontSize=20,
        leading=26,
        textColor=TEXT_PRIMARY,
        alignment=TA_CENTER,
    )

    # Season services count
    styles["SeasonServices"] = ParagraphStyle(
        "SeasonServices",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=11,
        leading=14,
        textColor=TEXT_MUTED,
        alignment=TA_CENTER,
    )

    # VIN monospace
    styles["VIN"] = ParagraphStyle(
        "VIN",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
    )

    # Badge text
    styles["Badge"] = ParagraphStyle(
        "Badge",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=12,
        leading=16,
        textColor=TEXT_SECONDARY,
        alignment=TA_CENTER,
    )

    # Report date (monospace, muted, right-aligned)
    styles["ReportDate"] = ParagraphStyle(
        "ReportDate",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=13,
        leading=17,
        textColor=TEXT_SECONDARY,
        alignment=TA_RIGHT,
    )

    styles["ReportTime"] = ParagraphStyle(
        "ReportTime",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
        alignment=TA_RIGHT,
    )

    # Brand title
    styles["BrandTitle"] = ParagraphStyle(
        "BrandTitle",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=22,
        leading=28,
        textColor=TEXT_PRIMARY,
    )

    # Brand subtitle
    styles["BrandSubtitle"] = ParagraphStyle(
        "BrandSubtitle",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=13,
        leading=17,
        textColor=TEXT_SECONDARY,
    )

    # Footer text
    styles["FooterLeft"] = ParagraphStyle(
        "FooterLeft",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
    )

    styles["FooterRight"] = ParagraphStyle(
        "FooterRight",
        parent=base_styles["Normal"],
        fontName=mono,
        fontSize=11,
        leading=14,
        textColor=TEXT_MUTED,
        alignment=TA_RIGHT,
    )

    # Projection label
    styles["ProjectionLabel"] = ParagraphStyle(
        "ProjectionLabel",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=13,
        leading=17,
        textColor=TEXT_SECONDARY,
    )

    # Garage heading (large)
    styles["GarageHeading"] = ParagraphStyle(
        "GarageHeading",
        parent=base_styles["Normal"],
        fontName=body_bold,
        fontSize=28,
        leading=34,
        textColor=ACCENT_BLUE,
        spaceAfter=4,
    )

    # Annotation (right-aligned muted text next to section headers)
    styles["Annotation"] = ParagraphStyle(
        "Annotation",
        parent=base_styles["Normal"],
        fontName=body,
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
        alignment=TA_RIGHT,
    )

    return styles


def apply_chart_rcparams() -> None:
    """Apply the design system styling to matplotlib rcParams.

    Must be called AFTER matplotlib.use('Agg').
    """
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": MPL["bg_card"],
            "axes.facecolor": MPL["bg_card"],
            "axes.edgecolor": MPL["border"],
            "axes.labelcolor": MPL["text_secondary"],
            "xtick.color": MPL["text_muted"],
            "ytick.color": MPL["text_muted"],
            "grid.color": MPL["border_light"],
            "grid.alpha": 0.6,
            "font.family": "sans-serif",
        }
    )


def get_mpl_font_dir() -> Path | None:
    """Return the font directory path if it exists, for matplotlib font registration."""
    if FONT_DIR.exists() and any(FONT_DIR.glob("*.ttf")):
        return FONT_DIR
    return None


def format_currency(amount: object) -> str:
    """Format a value as currency. Handles Decimal, str, float, int, and None."""
    if amount is None:
        return "N/A"
    try:
        val = float(str(amount))
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "N/A"


def format_currency_short(amount: object) -> str:
    """Format currency without cents for large display values."""
    if amount is None:
        return "N/A"
    try:
        val = float(str(amount))
        if val >= 10000:
            return f"${val:,.0f}"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "N/A"


def format_currency_compact(amount: object) -> str:
    """Format currency compactly for tight table columns. No cents for values >= $100."""
    if amount is None:
        return "$0"
    try:
        val = float(str(amount))
        if val == 0:
            return "$0"
        if val >= 100:
            return f"${val:,.0f}"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "$0"
