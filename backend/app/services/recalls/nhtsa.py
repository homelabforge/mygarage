"""NHTSA as a recall provider: what the app did before #211, behind the
provider shape. The fetch itself is still `NHTSAService.get_vehicle_recalls`."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile
from app.services.nhtsa import NHTSAService
from app.services.recalls.base import SOURCE_NHTSA, RecallHit
from app.services.settings_service import SettingsService
from app.utils.vehicle_key import has_real_vin

#: Where a campaign number leads a person.
NHTSA_RECALL_URL = "https://www.nhtsa.gov/recalls?nhtsaId={campaign}"


def hit_from_nhtsa(record: dict[str, Any]) -> RecallHit | None:
    """A RappelConso-shaped hit from one NHTSA recall record; None without a
    campaign number (nothing to key on)."""
    campaign = record.get("NHTSACampaignNumber") or record.get("nhtsa_campaign_number")
    if not campaign:
        return None
    campaign = str(campaign)[:20]
    return RecallHit(
        source=SOURCE_NHTSA,
        external_id=campaign,
        external_url=NHTSA_RECALL_URL.format(campaign=campaign),
        component=str(record.get("Component") or record.get("component") or "Unknown Component")[
            :200
        ],
        summary=str(record.get("Summary") or record.get("summary") or "No summary available"),
        consequence=record.get("Consequence") or record.get("consequence"),
        remedy=record.get("Remedy") or record.get("remedy"),
        date_announced=None,
        match_confidence=100,
    )


class NHTSARecallProvider:
    name = SOURCE_NHTSA

    def __init__(self) -> None:
        # One client for the process: NHTSAService validates its base URL with
        # a DNS lookup when it's built, and the scheduled check asks once per
        # vehicle. Upstream built it once per sweep.
        self._service: NHTSAService | None = None

    def _client(self) -> NHTSAService:
        if self._service is None:
            self._service = NHTSAService()
        return self._service

    def applies_to(self, vehicle: Vehicle, profile: CountryProfile | None) -> bool:
        # NHTSA answers by VIN, so a vehicle without one (#226) is never sent:
        # its key is a generated Q key or a fake VIN switched to a serial.
        if not has_real_vin(vehicle):
            return False
        # No profile is today's behaviour: NHTSA for everyone. A profile
        # lists its sources; North American ones name NHTSA.
        if profile is None:
            return True
        return SOURCE_NHTSA in profile.data_sources.recalls

    async def enabled(self, db: AsyncSession) -> bool:
        return await SettingsService.get_bool(db, "nhtsa_enabled", default=True)

    async def fetch(self, db: AsyncSession, vehicle: Vehicle) -> list[RecallHit]:
        # An outage raises NHTSAUnavailableError instead of reading as "no
        # recalls", so the scheduled check doesn't stamp nhtsa_last_check.
        records = await self._client().get_vehicle_recalls(vehicle.vin, db, raise_on_error=True)
        hits = [hit_from_nhtsa(record) for record in records]
        return [hit for hit in hits if hit is not None]
