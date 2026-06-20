"""Pull SD-card logs from a WiCAN device and backfill telemetry (no live side-effects)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.sd_log_ingest_state import SdLogIngestState
from app.services.sd_log_client import SdLogClient, SdLogClientError
from app.services.sd_log_parser import SdLogParser, SdLogSchemaError
from app.services.telemetry_service import TelemetryService

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

        Skips devices that have no vin, no device_address, or sd_backfill_enabled=False.
        Per-file state is tracked in sd_log_ingest_state so re-runs are idempotent.
        Errors (network, schema) are collected into result.errors rather than raised.
        """
        result = BackfillResult()

        device = (
            await self.db.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one_or_none()

        if (
            not device
            or not device.vin
            or not device.device_address
            or not device.sd_backfill_enabled
        ):
            return result

        client = self._client_for(device.device_address)
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
