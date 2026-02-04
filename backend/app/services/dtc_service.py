"""DTC service for diagnostic trouble code lookup and tracking."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dtc_definition import DTCDefinition
from app.models.vehicle_dtc import VehicleDTC

logger = logging.getLogger(__name__)


class DTCService:
    """Service for DTC lookup and vehicle DTC tracking."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # DTC Definition Lookup
    # =========================================================================

    async def lookup_dtc(self, code: str) -> DTCDefinition | None:
        """Look up a DTC code in the definitions table.

        Args:
            code: DTC code (e.g., "P0657")

        Returns:
            DTCDefinition if found, None otherwise
        """
        # Normalize code to uppercase
        code = code.upper().strip()

        result = await self.db.execute(select(DTCDefinition).where(DTCDefinition.code == code))
        return result.scalar_one_or_none()

    async def search_dtc_definitions(
        self,
        query: str,
        limit: int = 50,
    ) -> list[DTCDefinition]:
        """Search DTC definitions by code or description.

        Args:
            query: Search query (code prefix or description keywords)
            limit: Maximum results

        Returns:
            List of matching DTCDefinitions
        """
        query = query.upper().strip()

        # Search by code prefix or description contains
        result = await self.db.execute(
            select(DTCDefinition)
            .where(
                or_(
                    DTCDefinition.code.startswith(query),
                    DTCDefinition.description.ilike(f"%{query}%"),
                )
            )
            .order_by(DTCDefinition.code)
            .limit(limit)
        )
        return list(result.scalars().all())

    # =========================================================================
    # Vehicle DTC Tracking
    # =========================================================================

    async def record_dtc(
        self,
        vin: str,
        device_id: str,
        code: str,
    ) -> VehicleDTC:
        """Record a single DTC code.

        Convenience method that wraps process_dtcs for a single code.
        """
        results = await self.process_dtcs(vin, device_id, [code])
        return results[0] if results else None

    async def process_dtcs(
        self,
        vin: str,
        device_id: str,
        dtc_codes: list[str],
    ) -> list[VehicleDTC]:
        """Process DTCs reported by a WiCAN device.

        This creates new DTC records for codes not seen before,
        updates last_seen for existing codes, and can mark codes as
        cleared if they disappear from the list.

        Args:
            vin: Vehicle VIN
            device_id: Device ID
            dtc_codes: List of DTC codes reported

        Returns:
            List of active VehicleDTC records
        """
        now = datetime.now(UTC)
        processed = []

        for code in dtc_codes:
            code = code.upper().strip()
            if not code:
                continue

            # Check if DTC already exists for this vehicle
            existing = await self._get_vehicle_dtc(vin, code)

            if existing:
                # Update last_seen
                existing.last_seen = now
                if not existing.is_active:
                    existing.is_active = True
                    existing.cleared_at = None
                processed.append(existing)
            else:
                # Create new DTC record
                dtc = await self._create_vehicle_dtc(vin, device_id, code, now)
                processed.append(dtc)

        return processed

    async def _get_vehicle_dtc(self, vin: str, code: str) -> VehicleDTC | None:
        """Get an existing DTC record for a vehicle."""
        result = await self.db.execute(
            select(VehicleDTC)
            .where(VehicleDTC.vin == vin)
            .where(VehicleDTC.code == code)
            .where(VehicleDTC.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()

    async def _create_vehicle_dtc(
        self,
        vin: str,
        device_id: str,
        code: str,
        timestamp: datetime,
    ) -> VehicleDTC:
        """Create a new vehicle DTC record with lookup enrichment."""
        # Look up the code for description and severity
        definition = await self.lookup_dtc(code)

        dtc = VehicleDTC(
            vin=vin,
            device_id=device_id,
            code=code,
            description=definition.description if definition else None,
            severity=definition.severity if definition else "warning",
            first_seen=timestamp,
            last_seen=timestamp,
            is_active=True,
        )
        self.db.add(dtc)
        await self.db.flush()

        logger.info("New DTC detected for vehicle %s: %s", vin, code)
        return dtc

    async def clear_dtc(
        self,
        dtc_id: int,
        notes: str | None = None,
    ) -> VehicleDTC | None:
        """Mark a DTC as cleared.

        Args:
            dtc_id: The DTC record ID
            notes: Optional notes about clearing

        Returns:
            The updated VehicleDTC, or None if not found
        """
        result = await self.db.execute(select(VehicleDTC).where(VehicleDTC.id == dtc_id))
        dtc = result.scalar_one_or_none()

        if not dtc:
            return None

        dtc.is_active = False
        dtc.cleared_at = datetime.now(UTC)
        if notes:
            # Append to existing notes if any
            if dtc.user_notes:
                dtc.user_notes = f"{dtc.user_notes}\n\nCleared: {notes}"
            else:
                dtc.user_notes = f"Cleared: {notes}"

        await self.db.commit()
        logger.info("DTC %s cleared for vehicle %s", dtc.code, dtc.vin)
        return dtc

    async def update_dtc(
        self,
        dtc_id: int,
        description: str | None = None,
        severity: str | None = None,
        user_notes: str | None = None,
    ) -> VehicleDTC | None:
        """Update a DTC record (user-editable fields).

        Args:
            dtc_id: The DTC record ID
            description: Custom description (for manufacturer-specific codes)
            severity: Custom severity
            user_notes: User notes

        Returns:
            The updated VehicleDTC, or None if not found
        """
        result = await self.db.execute(select(VehicleDTC).where(VehicleDTC.id == dtc_id))
        dtc = result.scalar_one_or_none()

        if not dtc:
            return None

        if description is not None:
            dtc.description = description
        if severity is not None:
            dtc.severity = severity
        if user_notes is not None:
            dtc.user_notes = user_notes

        await self.db.commit()
        return dtc

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_active_dtcs(self, vin: str) -> list[VehicleDTC]:
        """Get all active DTCs for a vehicle."""
        result = await self.db.execute(
            select(VehicleDTC)
            .where(VehicleDTC.vin == vin)
            .where(VehicleDTC.is_active == True)  # noqa: E712
            .order_by(VehicleDTC.first_seen.desc())
        )
        return list(result.scalars().all())

    async def get_dtc_history(
        self,
        vin: str,
        include_active: bool = True,
        limit: int = 100,
    ) -> list[VehicleDTC]:
        """Get DTC history for a vehicle (active and cleared)."""
        query = (
            select(VehicleDTC)
            .where(VehicleDTC.vin == vin)
            .order_by(VehicleDTC.last_seen.desc())
            .limit(limit)
        )

        if not include_active:
            query = query.where(VehicleDTC.is_active == False)  # noqa: E712

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_dtc_counts(self, vin: str) -> dict[str, int]:
        """Get DTC counts for a vehicle."""
        # Total active
        active_result = await self.db.execute(
            select(func.count(VehicleDTC.id))
            .where(VehicleDTC.vin == vin)
            .where(VehicleDTC.is_active == True)  # noqa: E712
        )
        active_row = active_result.first()
        active_count = active_row[0] if active_row else 0

        # Critical active
        critical_result = await self.db.execute(
            select(func.count(VehicleDTC.id))
            .where(VehicleDTC.vin == vin)
            .where(VehicleDTC.is_active == True)  # noqa: E712
            .where(VehicleDTC.severity == "critical")
        )
        critical_row = critical_result.first()
        critical_count = critical_row[0] if critical_row else 0

        # Total historical
        total_result = await self.db.execute(
            select(func.count(VehicleDTC.id)).where(VehicleDTC.vin == vin)
        )
        total_row = total_result.first()
        total_count = total_row[0] if total_row else 0

        return {
            "active": active_count,
            "critical": critical_count,
            "total": total_count,
        }

    async def enrich_dtc_response(self, dtc: VehicleDTC) -> dict:
        """Enrich a DTC with lookup data for response."""
        definition = await self.lookup_dtc(dtc.code)

        result = {
            "id": dtc.id,
            "vin": dtc.vin,
            "device_id": dtc.device_id,
            "code": dtc.code,
            "description": dtc.description,
            "severity": dtc.severity,
            "user_notes": dtc.user_notes,
            "first_seen": dtc.first_seen,
            "last_seen": dtc.last_seen,
            "cleared_at": dtc.cleared_at,
            "is_active": dtc.is_active,
            "created_at": dtc.created_at,
        }

        if definition:
            result.update(
                {
                    "category": definition.category,
                    "subcategory": definition.subcategory,
                    "is_emissions_related": definition.is_emissions_related,
                    "estimated_severity_level": definition.estimated_severity_level,
                }
            )

        return result
