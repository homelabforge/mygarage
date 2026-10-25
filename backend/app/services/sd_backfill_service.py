"""Pull SD-card logs from a WiCAN device and backfill telemetry (no live side-effects)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.sd_log_ingest_state import SdLogIngestState
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import Capability
from app.services.livelink_sources.registry import default_registry
from app.services.sd_log_client import SdLogClient, SdLogClientError
from app.services.sd_log_parser import SdLogParser, SdLogSchemaError
from app.services.telemetry_service import TelemetryService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    """Aggregate outcome of one backfill_device() call."""

    files_seen: int = 0
    rows_ingested: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class SdBackfillService:
    """Orchestrates SD-card log retrieval and bulk telemetry backfill for one device."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._parser = SdLogParser()

    def _client_for(self, address: str) -> SdLogClient:
        """Return an SdLogClient for the given device address.

        Monkeypatch this method in tests to inject a fake client.
        """
        base = address if address.startswith("http") else f"http://{address}"
        return SdLogClient(base)

    async def backfill_device(self, device_id: str) -> BackfillResult:
        """Fetch all SD log files for device_id and bulk-insert missing telemetry rows.

        Skips, returning an empty result, while LiveLink is switched off, and
        for a device that's unknown, has no vin, no device_address or
        sd_backfill_enabled=False, or is of a kind with no SD card to pull
        (only WiCAN has one). An address that no longer resolves to a private
        host is skipped too, with an error and a log line (FB-7).
        Per-file state is tracked in sd_log_ingest_state so re-runs are idempotent.
        Errors (network, schema) are collected into result.errors rather than raised.
        """
        result = BackfillResult()

        # The master switch. Checked here, not only in the route, because a
        # backfill queued before the switch went off (run_sd_backfill) still
        # runs through this method afterwards.
        if not await LiveLinkService(self.db).is_enabled():
            return result

        device = (
            await self.db.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one_or_none()

        # The kind check is the one gate both the manual route and the queued
        # worker go through, so a stray address on a sensor is never pulled.
        if (
            not device
            or not device.vin
            or not device.device_address
            or not device.sd_backfill_enabled
            or Capability.SD_BACKFILL not in default_registry().capabilities_for(device.kind)
        ):
            return result

        # Checked again here, at connect time, not just when it was saved: a
        # LAN hostname can resolve somewhere public by the next pull (FB-7).
        # Both the manual pull and the queued one come through here. Off the
        # event loop, since a hostname means a DNS lookup.
        address = device.device_address
        if not await asyncio.to_thread(LiveLinkService.is_private_address, address):
            logger.warning(
                "SD backfill %s: %s doesn't resolve to a private address now; skipped",
                sanitize_for_log(device_id),
                sanitize_for_log(address),
            )
            result.errors.append(f"{address} doesn't resolve to a private address")
            return result

        client = self._client_for(address)
        try:
            logs = await client.list_logs()
        except SdLogClientError as exc:
            result.errors.append(f"list_logs: {exc}")
            return result

        telemetry_svc = TelemetryService(self.db)

        for entry in logs:
            filename = entry.get("filename", "")
            if not filename.endswith(".db"):
                continue

            result.files_seen += 1
            state = await self._get_state(device_id, filename)

            if state and state.completed:
                # Non-active file fully read on a previous run — skip re-download.
                continue

            since_ts = state.last_timestamp if state else 0

            try:
                raw = await client.download_log(filename)
                rows = self._parser.parse(raw, since_ts=since_ts)
            except (SdLogClientError, SdLogSchemaError, ValueError) as exc:
                result.errors.append(f"{filename}: {exc}")
                continue

            if rows:
                inserted = await telemetry_svc.bulk_backfill(device.vin, device_id, rows)
                result.rows_ingested += inserted
                result.rows_skipped += len(rows) - inserted
                # Advance the watermark to the highest timestamp we just parsed.
                max_ts = max(int(r.timestamp.timestamp()) for r in rows)
            else:
                max_ts = since_ts

            is_completed = entry.get("status") != "active"
            await self._save_state(device_id, filename, max_ts, completed=is_completed)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_state(self, device_id: str, filename: str) -> SdLogIngestState | None:
        """Return the ingest-state record for this (device_id, filename), or None."""
        return (
            await self.db.execute(
                select(SdLogIngestState).where(
                    SdLogIngestState.device_id == device_id,
                    SdLogIngestState.filename == filename,
                )
            )
        ).scalar_one_or_none()

    async def _save_state(
        self,
        device_id: str,
        filename: str,
        last_ts: int,
        *,
        completed: bool,
    ) -> None:
        """Upsert the ingest-state record, advancing last_timestamp monotonically."""
        state = await self._get_state(device_id, filename)
        if state is None:
            state = SdLogIngestState(device_id=device_id, filename=filename)
            self.db.add(state)

        state.last_timestamp = max(last_ts, state.last_timestamp or 0)
        state.completed = completed
        await self.db.commit()
