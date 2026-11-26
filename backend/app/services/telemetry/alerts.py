"""Threshold alerts half of TelemetryService."""

import logging
from datetime import timedelta
from functools import partial

from sqlalchemy import select

from app.services.livelink_alerts import ThresholdAlert, deliver_threshold_alert
from app.services.post_commit import after_commit
from app.services.telemetry.base import TelemetryBase
from app.utils.datetime_utils import utc_now
from app.utils.odometer_units import is_miles_odometer_key

logger = logging.getLogger(__name__)


class TelemetryAlertsMixin(TelemetryBase):
    """Alert lines: check a reading against them and send behind the commit."""

    async def check_thresholds(
        self,
        vin: str,
        param_key: str,
        value: float,
        *,
        once: bool = False,
        odometer_normalised: bool = False,
        declared_odometer_key: str | None = None,
    ) -> None:
        """Notify when a value crosses one of its parameter's alert lines.

        `once`: notify once per crossing (`alert_state`, see `livelink_alerts`),
        as a preset sensor's readings do. Otherwise every breaching reading
        notifies again, held back by the alert cooldown.

        `odometer_normalised`: storage normalised this batch's odometer
        (`normalises_odometer`), so an odometer key, by the same match
        normalisation used (`declared_odometer_key` is the device's
        `odometer_param_key`), holds km. So does `ODOMETER_MI`, on every path.
        The alert then reads in the owner's distance unit whatever the
        parameter row's unit says. An odometer-named key that wasn't
        normalised prints raw unless its row says km.
        """
        from app.services.livelink_alerts import (
            alert_band,
            alert_quantity,
            band_line,
            crossing,
            note_reading,
            send_started,
        )

        param = await self.get_parameter(param_key)
        if not param:
            return

        now = utc_now()
        if once:
            # A send that's still out stores its band when it's delivered,
            # unless this reading clears it first.
            note_reading(param.id, value, param)
            # Held, or re-armed by a value back clear of its line: the state
            # is stored as is. A band to notify leaves it unchanged.
            band, param.alert_state = crossing(param.alert_state, value, param)
            if band is None:
                return
            # A send no service accepted is tried again once the cooldown has
            # passed, not on every reading: a tank sits below its line for
            # days, and each send to a service that is down retries inline.
            if param.alert_retry_at is not None and now < param.alert_retry_at:
                return
        else:
            band = alert_band(value, param)
            if band is None:
                return
            # Same hold as above (R2): without it a webhook outage retried
            # inline on every breaching frame, and stalled MQTT ingest.
            if param.alert_retry_at is not None and now < param.alert_retry_at:
                return

        from app.services.livelink_service import LiveLinkService

        livelink = LiveLinkService(self.db)

        # Cooldown - skip dispatch while a prior notification for this
        # parameter is still within the admin-configured cooldown window
        # (Settings -> LiveLink, `livelink_alert_cooldown_minutes`, default
        # 30). WiCAN can emit several breaching frames a minute; without
        # this every one would dispatch. Thresholds live on the param (not
        # per-vehicle), so the cooldown is global-per-param. The setting is
        # only read once a prior stamp exists; first-ever breaches skip
        # the extra settings query. A notify-once reading has no cooldown:
        # it notifies each band once, whenever it enters it.
        if not once and param.warning_last_notified_at is not None:
            cooldown_minutes = await livelink.get_alert_cooldown_minutes()
            if now - param.warning_last_notified_at < timedelta(minutes=cooldown_minutes):
                return

        # Get vehicle name for notification
        from app.models.vehicle import Vehicle

        result = await self.db.execute(
            select(Vehicle.nickname, Vehicle.year, Vehicle.make, Vehicle.model).where(
                Vehicle.vin == vin
            )
        )
        row = result.first()
        # The nickname first: it's required, and a mower with no year or make
        # would otherwise read "None None None" (#226).
        if row:
            vehicle_name = row[0] or " ".join(str(p) for p in row[1:] if p) or "Vehicle"
        else:
            vehicle_name = "Vehicle"

        # Lines are canonical metric, so the alert reads in the owner's units,
        # but only for a value known to be canonical. A custom key whose row
        # says psi holds psi, and prints as it is (D2a).
        from app.utils.render_context import render_context_for_vehicle

        # Odometer-named counts too: on a device that declares another key it
        # wasn't normalised, and a unitless row isn't proof of km (carry 15).
        # Normalised is the declared match, or ODOMETER_MI, which every path
        # converts (R1-M1).
        odometer_key = self._is_odometer_param(
            param_key, declared_odometer_key
        ) or self._is_odometer_param(param_key)
        normalised = (
            odometer_normalised and self._is_odometer_param(param_key, declared_odometer_key)
        ) or is_miles_odometer_key(param_key)
        quantity = alert_quantity(
            param.param_class,
            param.unit,
            odometer_key=odometer_key,
            odometer_normalised=normalised,
        )

        # Held from here, as a send nothing took would be: the frames that land
        # while this one is out wait like the rest. A delivered send clears it
        # and stamps the cooldown instead (`deliver_threshold_alert`).
        cooldown_minutes = await livelink.get_alert_cooldown_minutes()
        param.alert_retry_at = now + timedelta(minutes=cooldown_minutes)
        await self._send_alert(
            ThresholdAlert(
                param_id=param.id,
                param_key=param_key,
                band=band,
                once=once,
                at=now,
                vehicle_name=vehicle_name,
                parameter_name=param.display_name or param_key,
                value=value,
                threshold_value=band_line(band, param),
                unit=param.unit,
                ctx=await render_context_for_vehicle(self.db, vin),
                quantity=quantity,
                flight=send_started(param.id, band) if once else None,
            )
        )

    async def _send_alert(self, alert: ThresholdAlert) -> None:
        """Send it once the caller's transaction commits, in the background.

        Not inline (B6-1): a slow notification service held up the MQTT frame,
        and every frame queued behind it, once per cooldown. A rollback drops
        it, so a frame that failed to store alerts nobody.
        """
        after_commit(
            self.db,
            partial(deliver_threshold_alert, alert=alert),
            label=f"threshold alert for {alert.param_key}",
        )
