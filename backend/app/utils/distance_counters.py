"""Telemetry keys whose increase measures distance travelled.

An odometer is the obvious source and on some hardware it is the worst one
available. A 2019 Mirage, measured over 165 days of its own stored telemetry:

    ODOMETER                   17,052 samples,   149 changes, ~23.75 km per step
    31-DISTANCESINCECODECLEAR  11,027 samples, 1,712 changes,  ~1.00 km per step

Both agree with the vehicle's recorded mileage in aggregate, to +0.3% and +1.0%.
They differ only in resolution, and resolution decides whether a drive gets a
distance at all: a counter that ticks 149 times in five months can attribute
distance to at most 149 drives, and the average trip is shorter than one of its
steps. That instance held 2,781 zero-distance sessions against 172 with a
number, and the 172 were wrong as well -- each had swallowed a ~24 km step that
mostly accrued while the vehicle was parked.

So the odometer is not privileged here. ``_calculate_session_distance`` reads
every source in the window and takes the one that resolves finest.

WHY THE PID PREFIX IS REQUIRED, AND THE ODOMETER SET IS NOT REUSED
------------------------------------------------------------------
``31-DISTANCESINCECODECLEAR`` is kilometres because SAE J1979 defines PID 0x31
as kilometres. The same NAME without a prefix is a WiCAN autopid -- a
user-defined CAN expression reading the dash, which on a US-market car is
miles. `app/utils/odometer_units.py` turns on exactly this distinction, but the
odometer survives the ambiguity only because ``LiveLinkDevice.odometer_unit``
lets a device declare its units. Nothing declares units for a distance counter,
so an unprefixed key is refused rather than assumed metric; reading a miles
counter as kilometres under-reports by 38%.

This also means the two sets must stay DISJOINT. A distance counter may supply
``distance_km`` and must never supply ``start_odometer`` / ``end_odometer``:
PID 0x31 resets to zero when a technician clears a code, so stamping it into
the odometer columns would report a vehicle with 3,000 km on it. The counters
are enumerated here rather than folded into ``_ODOMETER_BARE_KEYS`` so that
mistake requires a deliberate edit to two files.
"""

from __future__ import annotations

from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass

from app.utils.odometer_units import (
    OBD2_PID_PREFIX_RE,
    bare_param_key,
    is_odometer_param_key,
)

#: Standard SAE J1979 cumulative-distance PIDs, prefix stripped, in kilometres.
#: Deliberately an exact set rather than a "DISTANCE" substring scan, which
#: would swallow `DISTANCE_TO_EMPTY` (a fuel-range estimate that FALLS as the
#: vehicle is driven) and every trip-computer field a firmware exposes.
#:
#: PID 0x21, `DISTANCEMILON`, is excluded even though it is a standard metric
#: distance PID with the same 1 km resolution. It counts only the distance
#: driven with the malfunction light lit, so it is a SUBSET of the distance
#: travelled, and a subset that begins mid-drive when a fault appears. On a
#: vehicle whose odometer never ticks within a drive it would out-resolve the
#: odometer and win, then report the 5 km since the light came on as the length
#: of a 12 km trip. A source has to measure the whole journey to be ranked
#: against sources that do.
_DISTANCE_COUNTER_BARE_KEYS = frozenset(
    {
        "DISTANCESINCECODECLEAR",  # PID 0x31, km since diagnostic codes cleared
    }
)


def is_distance_counter_param_key(param_key: str) -> bool:
    """True if ``param_key`` is a standard cumulative-distance PID.

    Requires the two-hex-digit PID prefix: that prefix is the only evidence
    that the value is metric, and there is no per-device override to correct a
    wrong guess with. An odometer is never a distance counter -- see the module
    docstring for why the sets stay disjoint.
    """
    upper = param_key.upper()
    if not OBD2_PID_PREFIX_RE.match(upper):
        return False
    return bare_param_key(param_key) in _DISTANCE_COUNTER_BARE_KEYS


def is_distance_source_param_key(param_key: str) -> bool:
    """True if this key's increase measures distance travelled, in kilometres.

    The union of odometers and standard distance counters. Both read as
    kilometres out of ``vehicle_telemetry``, by two different routes:
    ``TelemetryService._normalize_odometer_units`` converts odometer values at
    ingest, while a prefixed distance counter is stored raw and is already
    metric by specification.
    """
    return is_odometer_param_key(param_key) or is_distance_counter_param_key(param_key)


@dataclass(frozen=True)
class TravelledSpan:
    """What one distance source says about one window of telemetry.

    ``low``/``high`` are the readings at the edges, which is what the odometer
    columns want: they answer "what did the clock read", not "how far did it
    move". ``distance_km`` is the sum of positive steps, which is what the
    vehicle travelled. ``steps`` is how many times the source changed, and is
    the resolution measure :func:`select_distance_source` ranks on.
    """

    low: float
    high: float
    steps: int
    distance_km: float


def measure_travelled(values: Sequence[float]) -> TravelledSpan:
    """Reduce one source's readings, in time order, to what they say about a drive.

    Distance is the sum of POSITIVE steps rather than ``max - min``. For a
    monotonic source the two are identical, so an odometer measures exactly what
    it always did; they part company on a counter that resets, where a code
    clear mid-window makes the span read 806 km on a 15 km drive.

    A source seen once has no steps and no distance. That is the honest answer
    and not a missing value: one reading proves the vehicle was somewhere, never
    that it went anywhere.
    """
    distance = 0.0
    steps = 0
    low = high = values[0]
    for previous, current in zip(values, values[1:], strict=False):
        if current > previous:
            distance += current - previous
            steps += 1
        low = min(low, current)
        high = max(high, current)
    return TravelledSpan(low=low, high=high, steps=steps, distance_km=distance)


def select_distance_source(
    spans: Mapping[str, TravelledSpan], odometer_keys: Container[str]
) -> str | None:
    """Pick the source whose readings describe this window most finely.

    Most steps wins, because steps are resolution: a counter that ticks twelve
    times in a window can place distance inside it, and one that ticks once can
    only say a step happened somewhere. A source that never ticks describes the
    drive not at all.

    **An odometer wins its own ties**, so another source displaces it only by
    resolving STRICTLY finer here. That is what keeps this change additive: a
    device whose odometer was already adequate computes what it always did, and
    nothing quietly restates a session that was being measured correctly.
    """
    if not spans:
        return None
    return max(spans, key=lambda key: (spans[key].steps, key in odometer_keys))
