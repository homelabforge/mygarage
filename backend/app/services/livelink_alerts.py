"""When a LiveLink reading's alert lines notify.

A reading may carry three lines on its `LiveLinkParameter`: a low warning
(`warning_min`), a lower critical one (`critical_min`) and a high one
(`warning_max`). A value past a line is in that line's band.

Most readings (WiCAN's) notify on every reading past a line, held back only by
the alert cooldown. A preset sensor's readings notify once per crossing
instead: a propane tank below its low line stays there for days, and the
cooldown would repeat the same alert every half hour until the refill. So they
keep the band they last notified in `alert_state`, notify again only for a
worse one, and re-arm once the value is clear of the line.

Lines and `REARM_MARGIN` are in the unit the value is stored and compared in:
the reading's canonical metric unit (°C, km/h, kPa, km), or a raw-unit
reading's own unit. Only the notification converts, and only when it knows the
value is canonical (`alert_quantity`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.utils.render_context import RenderContext

AlertBand = Literal["low", "critical", "high"]

#: How far a value must come back past the line it crossed before that alert
#: can fire again. Without it a level jittering around 25% notifies on every dip.
REARM_MARGIN = 5.0


class AlertLines(Protocol):
    """A reading's lines: `LiveLinkParameter` in the app, anything alike in tests."""

    warning_min: float | None
    critical_min: float | None
    warning_max: float | None


def alert_band(value: float, lines: AlertLines) -> AlertBand | None:
    """The band `value` is in, or None. The high line is checked first, as it always was."""
    if lines.warning_max is not None and value > lines.warning_max:
        return "high"
    if lines.critical_min is not None and value < lines.critical_min:
        return "critical"
    if lines.warning_min is not None and value < lines.warning_min:
        return "low"
    return None


def band_line(band: AlertBand, lines: AlertLines) -> float:
    """The line whose crossing put a value in `band`.

    Raises ValueError when that line is not set: no value can be in its band.
    """
    line = {
        "high": lines.warning_max,
        "critical": lines.critical_min,
        "low": lines.warning_min,
    }[band]
    if line is None:
        raise ValueError(f"no {band} line is set")
    return line


def crossing(
    state: str | None, value: float, lines: AlertLines
) -> tuple[AlertBand | None, str | None]:
    """For a notify-once reading: (the band to notify now or None, the state to keep).

    Notifies on entering a band it has not notified. Climbing from critical
    back to low is a recovery, not a new alert. Re-arms (state None) only once
    the value is REARM_MARGIN clear of the low line (the critical line when
    there is no low one) or below the high line; until then it keeps its state,
    so jitter at a line is silent.

    When it returns a band to notify, the state it returns is the current one:
    the caller stores the band only once a send is delivered, so a failed send
    is tried again on the next reading.
    """
    band = alert_band(value, lines)
    if band is not None:
        if band == state or (band == "low" and state == "critical"):
            return None, state
        return band, state

    if state == "high":
        line = lines.warning_max
        clear = line is None or value <= line - REARM_MARGIN
    else:
        line = lines.warning_min if lines.warning_min is not None else lines.critical_min
        clear = line is None or value >= line + REARM_MARGIN
    return None, None if clear else state


#: The `UnitSet` quantity each reading class renders as, and the unit symbols
#: that mean a value of that class is already canonical. Compared lower-cased
#: and stripped. Anything not here (percent, volts, rpm) has no unit to convert.
_CANONICAL_SYMBOLS: dict[str, frozenset[str]] = {
    "temperature": frozenset({"°c", "c"}),
    "speed": frozenset({"km/h"}),
    "pressure": frozenset({"kpa"}),
    "distance": frozenset({"km"}),
}


def alert_quantity(
    param_class: str | None,
    unit: str | None,
    *,
    odometer_key: bool = False,
    odometer_normalised: bool = False,
) -> str | None:
    """The `UnitSet` quantity to render an alert's value and line in, or None.

    None means print them raw with the parameter's own unit. A class is only
    rendered when the stored value is known to be canonical: the parameter
    names no unit, or names that class's canonical one.

    An odometer key is the exception both ways. Normalised (storage converted
    it), it's km whatever the parameter's free-text unit says: an HTTPS
    `config` can register `mi` for a value ingest converted. Not normalised,
    only an explicit `km` counts, since a bare odometer is as likely miles.
    """
    symbols = _CANONICAL_SYMBOLS.get(param_class) if param_class else None
    if symbols is None:
        return None
    declared = unit.strip().lower() if unit else ""
    if odometer_key and param_class == "distance":
        return param_class if odometer_normalised or declared in symbols else None
    if not declared or declared in symbols:
        return param_class
    return None


@dataclass
class InFlight:
    """A notify-once send that's out, and whether a reading has re-armed its band since."""

    band: AlertBand
    rearmed: bool = False


#: Notify-once sends still out, by parameter id. The band is stored once the
#: send is delivered, so a refill that lands meanwhile was overwritten by it
#: and the next drop went unnoticed. Memory is enough: the send runs in this
#: process (one worker), and a restart drops it with the send.
_in_flight: dict[int, InFlight] = {}


def send_started(param_id: int, band: AlertBand) -> InFlight:
    """Track a notify-once send of `band` until it's delivered."""
    flight = InFlight(band)
    _in_flight[param_id] = flight
    return flight


def note_reading(param_id: int, value: float, lines: AlertLines) -> None:
    """Mark the send that's out re-armed if this reading would have re-armed its band."""
    flight = _in_flight.get(param_id)
    if flight is not None and crossing(flight.band, value, lines)[1] is None:
        flight.rearmed = True


@dataclass(frozen=True)
class ThresholdAlert:
    """One alert `check_thresholds` decided to send, for after the commit (B6-1).

    Everything the message needs is read at the decision, in the ingest
    session, so the send only has to deliver it and stamp the outcome.
    """

    param_id: int
    param_key: str
    band: AlertBand
    #: Notify-once (a preset sensor): a delivered send keeps `band` as the state.
    once: bool
    #: When it was decided: the cooldown stamp, if a service takes it.
    at: datetime
    vehicle_name: str
    parameter_name: str
    value: float
    threshold_value: float
    unit: str | None
    ctx: RenderContext
    quantity: str | None
    #: A notify-once send's tracking (`send_started`), None otherwise.
    flight: InFlight | None = None


async def deliver_threshold_alert(db: AsyncSession, alert: ThresholdAlert) -> None:
    """Send the alert and record how it went on its parameter.

    Stamps the cooldown, and a notify-once reading's band, only when at least
    one service accepted it: the dispatcher records False for a send that was
    tried and failed, and returns nothing at all with the event or every
    service switched off. Otherwise the hold `check_thresholds` set stays, so
    the next try waits one cooldown (R2).

    A reading that re-armed the band while the send was out wins: the band
    isn't stored, so the next crossing notifies.
    """
    from app.models.livelink_parameter import LiveLinkParameter
    from app.services.notifications.dispatcher import NotificationDispatcher

    try:
        results = await NotificationDispatcher(db).notify_livelink_threshold_alert(
            vehicle_name=alert.vehicle_name,
            parameter_name=alert.parameter_name,
            value=alert.value,
            band=alert.band,
            threshold_value=alert.threshold_value,
            unit=alert.unit,
            ctx=alert.ctx,
            quantity=alert.quantity,
        )
    finally:
        if alert.flight is not None and _in_flight.get(alert.param_id) is alert.flight:
            del _in_flight[alert.param_id]
    if not any(results.values()):
        return
    param = await db.get(LiveLinkParameter, alert.param_id)
    if param is None:
        return  # deleted while the send was out
    param.warning_last_notified_at = alert.at
    param.alert_retry_at = None
    if alert.once and not (alert.flight is not None and alert.flight.rearmed):
        param.alert_state = alert.band
