from __future__ import annotations

"""DTC (Diagnostic Trouble Code) definitions model.

This table is populated by a seed migration with ~5000 SAE J2012 standard codes.
Phase 1 includes code + description + category + severity only.
common_causes, symptoms, and fix_guidance are reserved for future enhancement.
"""

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DTCDefinition(Base):
    """Bundled DTC lookup database for SAE J2012 standard codes.

    Covers all generic OBD-II codes:
    - P0xxx (generic powertrain)
    - P2xxx (generic powertrain extended)
    - P34xx-P39xx (generic powertrain extended)
    - B0xxx (generic body)
    - C0xxx (generic chassis)
    - U0xxx (generic network)

    Manufacturer-specific codes (P1xxx, B1xxx, C1xxx, U1xxx) are NOT included.
    Users can manually add descriptions for those via the vehicle_dtcs table.
    """

    __tablename__ = "dtc_definitions"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)  # e.g., "P0657"
    description: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # "Actuator Supply Voltage A Circuit/Open"
    category: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # powertrain, body, chassis, network
    subcategory: Mapped[str | None] = mapped_column(
        String(50)
    )  # fuel_system, ignition, emissions, etc.
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info, warning, critical
    estimated_severity_level: Mapped[int] = mapped_column(
        Integer, default=2
    )  # 1=minor, 2=moderate, 3=serious, 4=critical
    is_emissions_related: Mapped[bool] = mapped_column(Boolean, default=False)

    # Future enhancement fields (NULL for Phase 1)
    common_causes: Mapped[str | None] = mapped_column(Text)  # JSON array
    symptoms: Mapped[str | None] = mapped_column(Text)  # JSON array
    fix_guidance: Mapped[str | None] = mapped_column(Text)  # Brief fix steps

    __table_args__ = (
        Index("idx_dtc_defs_category", "category"),
        Index("idx_dtc_defs_severity", "severity"),
    )
