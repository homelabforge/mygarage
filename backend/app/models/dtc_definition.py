from __future__ import annotations

"""DTC (Diagnostic Trouble Code) definitions model.

Seeded from app/data/dtc_definitions.json by 033 on a fresh install; 125
corrected older installs. 091 fills causes, symptoms and fix guidance for a
few common codes.
"""

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DTCDefinition(Base):
    """Bundled lookup of the generic (SAE-controlled) OBD-II codes: P0/P2/P34,
    B0/B3, C0, U0/U3 (the source has no P35-P39 or C3 codes), built by
    tools/build_dtc_definitions.py.

    Maker ranges (P1, P30-P33, B1/B2, C1/C2, U1/U2) are left out on purpose:
    each maker defines its own, so one maker's meaning would be wrong for the
    rest. A user can describe any code per vehicle on vehicle_dtcs.
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
    )  # 2=moderate, 3=serious, 4=critical; the bundled data never uses 1 (minor)
    is_emissions_related: Mapped[bool] = mapped_column(Boolean, default=False)

    # 091 fills these for a few common codes; NULL for the rest
    common_causes: Mapped[str | None] = mapped_column(Text)  # JSON array
    symptoms: Mapped[str | None] = mapped_column(Text)  # JSON array
    fix_guidance: Mapped[str | None] = mapped_column(Text)  # Brief fix steps

    __table_args__ = (
        Index("idx_dtc_defs_category", "category"),
        Index("idx_dtc_defs_severity", "severity"),
    )
