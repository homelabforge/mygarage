"""AutoRef, the European VIN decoder (#219 takeover).

AutoRef (autoref.eu) answers from Swiss type approvals, EU certificates of
conformity and 1985-1995 records, then falls back to the UK DVSA and US NHTSA
registries. Its own tables read only the first 10 VIN characters; the two
registry fallbacks need all 17, so the full VIN is sent (plan D1).

A decode costs two quota units: ``/vehicles/{vin}`` for the best match, then
``/vehicle/{type}/{id}`` for body, doors, displacement and drivetrain. The
second call is skipped for a registry (UK/US) answer, which has no record to
fetch. ``/usage`` costs nothing.

The key goes in the ``x-api-key`` header, except on ``/usage``, which only
takes it as ``?api_key=``. So no httpx error may escape this module: an
``HTTPStatusError``'s text holds the full URL. Every failure is one of the
errors below, raised outside the ``except`` that caught httpx's, carrying a
status code at most.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx

from app.constants.fuel import FuelTypeEnum, normalize_fuel_type
from app.services.registration_certificate_service import displacement_litres
from app.utils.vehicle_names import normalize_make, normalize_model
from app.utils.vin import validate_vin

logger = logging.getLogger(__name__)

BASE_URL = "https://api-gateway.autoref.eu"
TIMEOUT = httpx.Timeout(10.0)

#: SAE horsepower per kilowatt. AutoRef's POWER_DIN is metric PS, not what
#: the form's hp means, so hp comes from POWER_KW.
HP_PER_KW = 1.34102

#: AutoRef's own records, which have a full record behind them.
LOCAL_RECORD_TYPES = frozenset({"TG", "COC", "OLD", "OC", "X"})
#: Answers from the UK DVSA and US NHTSA registries.
EXTERNAL_RECORD_TYPES = frozenset({"UK", "US"})

#: More than one vehicle matched; this is the most registered one.
NOTE_AUTOREF_BEST_GUESS = "autoref_best_guess"
#: The answer came from the UK or US registry, as written there.
NOTE_AUTOREF_EXTERNAL = "autoref_external_record"

#: AutoRef's gearbox codes, from its gearboxes endpoint: A automatic, M
#: manual, S semi-auto or CVT, H hydrostatic (tractors, mowers).
_GEARBOX_CODES = {
    "M": "Manual",
    "A": "Automatic",
    "S": "Semi-Automatic",
    "H": "Hydrostatic",
}
#: S is one code for two gearboxes, so its words decide: a Corolla hybrid's
#: S came with "Continuously Variable" (live decode 2026-11-06). Spelled the
#: way NHTSA spells it. English and French.
CVT = "Continuously Variable Transmission (CVT)"
_CVT_WORDS = ("continuously variable", "cvt", "variation continue")
#: A manual with an automatic mode (``additionnal_mode`` A): a Porsche PDK
#: reads this way.
AUTOMATED_MANUAL = "Automated Manual"
#: More gears than any car has means the number isn't a gear count.
_MAX_GEARS = 12

#: The Swiss type approval's drivetrain codes, in German: Vorderrad,
#: Hinterrad, Allrad. Read before the words, which are translated from the
#: code and got A wrong: a Porsche Macan's A came back as "Front", as if it
#: were French "avant" (live decodes 2026-11-06, plan Q1).
_DRIVE_CODES = {"V": "FWD", "H": "RWD", "A": "AWD"}

#: Drivetrain words to the form's codes, checked in order, for a code that
#: isn't one of the above. English and French.
_DRIVE_WORDS: tuple[tuple[str, str], ...] = (
    ("4x4", "4WD"),
    ("four-wheel", "4WD"),
    ("4wd", "4WD"),
    ("all-wheel", "AWD"),
    ("awd", "AWD"),
    ("intégrale", "AWD"),
    ("integrale", "AWD"),
    ("front", "FWD"),
    ("avant", "FWD"),
    ("fwd", "FWD"),
    ("rear", "RWD"),
    ("arrière", "RWD"),
    ("propulsion", "RWD"),
    ("rwd", "RWD"),
)


#: What an API key may hold: visible ASCII. httpx sends headers as ASCII, so
#: anything else raised UnicodeEncodeError carrying the whole key (Codex diff R1-M2).
_KEY_SHAPE = re.compile(r"[\x21-\x7e]+")


def _checked_key(key: str) -> str:
    """The key, or AutoRefAuthError(None) when it can't go on the wire.

    Raised before any request, and the error never holds the key.
    """
    if not _KEY_SHAPE.fullmatch(key):
        logger.warning("AutoRef API key is malformed (only visible ASCII); not sent")
        raise AutoRefAuthError(None)
    return key


_API_KEY_IN_TEXT = re.compile(r"(api_key=)[^&\s\"']+")


class _RedactApiKey(logging.Filter):
    """Blank ``api_key=`` in httpx's own log lines.

    httpx logs every request URL at INFO. ``main.py`` turns that logger down to
    WARNING, but only once ``app.main`` is imported, and a log level is one
    setting away from ``/usage?api_key=<key>`` in the container log (Fable F-8).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "api_key=" in message:
            record.msg = _API_KEY_IN_TEXT.sub(r"\1[redacted]", message)
            record.args = None
        return True


def _install_redaction() -> None:
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(f, _RedactApiKey) for f in httpx_logger.filters):
        httpx_logger.addFilter(_RedactApiKey())


_install_redaction()


class AutoRefError(Exception):
    """AutoRef didn't answer usably. Never carries a URL, a body or the key."""


class AutoRefAuthError(AutoRefError):
    """AutoRef refused the key (401 or 403), or the key can't be sent at all.

    Attributes:
        status: The HTTP status, or None for a malformed key that was never sent.
    """

    def __init__(self, status: int | None) -> None:
        self.status = status
        reason = "malformed, not sent" if status is None else f"HTTP {status}"
        super().__init__(f"AutoRef rejected the API key ({reason})")


class AutoRefQuotaError(AutoRefError):
    """The plan's monthly requests are used up (429)."""

    def __init__(self) -> None:
        super().__init__("AutoRef quota used up (HTTP 429)")


class AutoRefUnavailableError(AutoRefError):
    """Any other status, a body that isn't JSON, or no answer at all.

    Attributes:
        status: The HTTP status, or None when nothing usable came back.
        timed_out: The request timed out.
    """

    def __init__(self, status: int | None = None, *, timed_out: bool = False) -> None:
        self.status = status
        self.timed_out = timed_out
        if timed_out:
            reason = "timed out"
        elif status is None:
            reason = "no answer"
        else:
            reason = f"HTTP {status}"
        super().__init__(f"AutoRef unavailable ({reason})")


@dataclass(frozen=True)
class AutoRefUsage:
    """What ``/usage`` reports for a key."""

    plan: str | None
    limit: int | None
    used: int | None
    remaining: int | None
    reset_date: str | None


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _drive_type(code: Any, words: Any) -> str | None:
    known = _DRIVE_CODES.get((_text(code) or "").upper())
    if known is not None:
        return known
    for raw in (code, words):
        text = _text(raw)
        if text is None:
            continue
        lowered = text.lower()
        if lowered in ("fwd", "rwd", "awd", "4wd"):
            return lowered.upper()
        for needle, drive in _DRIVE_WORDS:
            if needle in lowered:
                return drive
    return None


def _fuels(fuel_raw: str | None, second_raw: str | None) -> tuple[str | None, str | None]:
    """The normalized fuel and second fuel.

    AutoRef writes a hybrid as a fuel paired with electric ("Gasoline /
    Electric") and leaves TYPE_HYBRID blank, so the pair reads as a hybrid
    with electric second, like a French certificate's EH. Whether it plugs in
    isn't in the answer, so it's never a plug-in hybrid.
    """
    fuel = normalize_fuel_type(fuel_raw) if fuel_raw else None
    second = normalize_fuel_type(second_raw) if second_raw else None
    if fuel_raw:
        parts = {normalize_fuel_type(part) for part in fuel_raw.split("/")}
        if len(parts) == 2 and FuelTypeEnum.ELECTRIC in parts and None not in parts:
            fuel = FuelTypeEnum.HYBRID
            second = second or FuelTypeEnum.ELECTRIC
    return (fuel.value if fuel else None, second.value if second else None)


def _gearbox(code: str, details: Any, words: Any) -> dict[str, str | None]:
    """The transmission type and speeds from the code, its words and the first gearbox detail."""
    first = details[0] if isinstance(details, list) and details else None
    detail = first if isinstance(first, dict) else {}
    gears = detail.get("gears")
    speeds = (
        str(gears)
        if isinstance(gears, int) and not isinstance(gears, bool) and 0 < gears <= _MAX_GEARS
        else None
    )
    kind = _GEARBOX_CODES.get(code)
    if code == "S":
        listed: list[Any] = cast(list[Any], words) if isinstance(words, list) else [words]
        text = " ".join(item for item in listed if isinstance(item, str)).lower()
        if any(needle in text for needle in _CVT_WORDS):
            kind = CVT
    if kind == "Manual" and (_text(detail.get("additionnal_mode")) or "").upper() == "A":
        kind = AUTOMATED_MANUAL
    return {"type": kind, "speeds": speeds}


def map_vehicle(
    vin: str, row: dict[str, Any], detail: dict[str, Any], *, multiple: bool
) -> dict[str, Any]:
    """An AutoRef answer in the decoder's shape (the keys NHTSA's answer uses).

    Args:
        vin: The VIN that was decoded.
        row: The chosen ``/vehicles/{vin}`` result.
        detail: Its full record's ``VIN_INFO``, or ``{}`` without one.
        multiple: Whether the lookup returned more than one result.

    Returns:
        The decoded fields. ``year`` is always None: DATE_FIRST_CIRCULATION
        comes from one registration of the model, not from this car.
    """

    def pick(key: str) -> Any:
        value = detail.get(key)
        return value if value not in (None, "", []) else row.get(key)

    record_type = (_text(row.get("RECORD_TYPE")) or "").upper()
    kw_raw = pick("POWER_KW")
    kw = kw_raw if isinstance(kw_raw, (int, float)) and not isinstance(kw_raw, bool) else None
    displacement_cc = _int(pick("DISPLACEMENT"))
    fuel_raw = _text(pick("FUEL"))
    fuel, fuel_secondary = _fuels(fuel_raw, _text(pick("SECOND_FUEL")))
    gearbox_code = (_text(row.get("CODE_GEARBOX")) or "").upper()
    model_text = (
        _text(pick("MODEL_RESOLVED")) or _text(pick("MODEL_LINE")) or _text(pick("MODEL_FULL"))
    )

    make = normalize_make(_text(pick("BRAND")))

    notes: list[str] = []
    configurations = row.get("configurations")
    if multiple or (isinstance(configurations, list) and len(configurations) > 1):
        notes.append(NOTE_AUTOREF_BEST_GUESS)
    if record_type in EXTERNAL_RECORD_TYPES:
        notes.append(NOTE_AUTOREF_EXTERNAL)

    return {
        "vin": vin,
        "year": None,
        "make": make,
        "model": normalize_model(model_text, make),
        "trim": _text(pick("MOTORIZATION")),
        "body_class": _text(pick("BODY")),
        "engine": {
            "displacement_l": displacement_litres(displacement_cc) if displacement_cc else None,
            "cylinders": _int(pick("CYLINDERS")),
            "hp": round(kw * HP_PER_KW) if kw is not None else None,
            "kw": round(kw) if kw is not None else None,
            "fuel_type": fuel_raw,
            "fuel_type_normalized": fuel,
            "fuel_type_secondary": fuel_secondary,
        },
        "transmission": _gearbox(gearbox_code, detail.get("GEARBOX_DETAILS"), pick("GEARBOX")),
        "drive_type": _drive_type(pick("CODE_DRIVETRAIN"), pick("DRIVETRAIN")),
        "manufacturer": _text(pick("MANUFACTURER")),
        "doors": _int(pick("DOORS")),
        "notes": notes,
    }


def _detail_target(row: dict[str, Any]) -> tuple[str, str] | None:
    """The record type and id of the full record behind a local result."""
    record_type = (_text(row.get("RECORD_TYPE")) or "").upper()
    if record_type not in LOCAL_RECORD_TYPES:
        return None
    candidates: list[tuple[str, Any]] = [(record_type, row.get("id"))]
    configurations = row.get("configurations")
    if isinstance(configurations, list) and configurations:
        first = configurations[0]
        if isinstance(first, dict):
            candidates.append(("COC", first.get("id")))
    for target_type, raw_id in candidates:
        if isinstance(raw_id, bool) or raw_id is None:
            continue
        text_id = str(raw_id)
        if text_id.isascii() and text_id.isalnum():
            return target_type, text_id
    return None


class AutoRefService:
    """One AutoRef key. Build one per request: the key is read per request."""

    def __init__(
        self,
        api_key: str,
        client_factory: Callable[[], httpx.AsyncClient] = _default_client,
    ) -> None:
        """Hold the key and how to build a client (tests pass a mock transport)."""
        self._api_key = api_key
        self._client_factory = client_factory

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET a path and return its JSON, or None on a 404.

        Raises:
            AutoRefAuthError, AutoRefQuotaError, AutoRefUnavailableError.
        """
        failure: AutoRefError | None = None
        response: httpx.Response | None = None
        try:
            response = await client.get(path, params=params, headers=headers)
        except httpx.TimeoutException:
            failure = AutoRefUnavailableError(timed_out=True)
        except httpx.HTTPError:
            failure = AutoRefUnavailableError()
        # Raised here, outside the except: the new error must not carry
        # httpx's (and its URL) as its context.
        if failure is not None or response is None:
            raise failure or AutoRefUnavailableError()

        status = response.status_code
        if status == 404:
            return None
        if status in (401, 403):
            logger.warning("AutoRef rejected the API key (HTTP %d)", status)
            raise AutoRefAuthError(status)
        if status == 429:
            logger.warning("AutoRef quota used up (HTTP 429)")
            raise AutoRefQuotaError()
        if not response.is_success:
            logger.warning("AutoRef answered HTTP %d", status)
            raise AutoRefUnavailableError(status)
        try:
            return response.json()
        except ValueError:
            body_failure = AutoRefUnavailableError(status)
        logger.warning("AutoRef answered HTTP %d with a body that isn't JSON", status)
        raise body_failure

    async def decode(self, vin: str) -> dict[str, Any] | None:
        """The most registered match for a VIN, mapped, or None when there is none.

        Raises:
            ValueError: The VIN is malformed (checked before any request).
            AutoRefAuthError, AutoRefQuotaError, AutoRefUnavailableError.
        """
        vin = vin.strip().upper()
        is_valid, error = validate_vin(vin)
        if not is_valid:
            raise ValueError(f"Invalid VIN: {error}")
        headers = {"x-api-key": _checked_key(self._api_key)}
        async with self._client_factory() as client:
            # codeql[py/partial-ssrf] - fixed host; the VIN is validated above (17 alphanumerics, no I/O/Q)
            rows = await self._get(
                client, f"/vehicles/{vin}", params={"lang": "en", "group": "car"}, headers=headers
            )
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                return None
            row: dict[str, Any] = rows[0]
            detail: dict[str, Any] = {}
            target = _detail_target(row)
            if target is not None:
                record_type, record_id = target
                try:
                    # codeql[py/partial-ssrf] - fixed host; type from a fixed set, id checked alphanumeric
                    full = await self._get(
                        client,
                        f"/vehicle/{record_type}/{record_id}",
                        params={"lang": "en"},
                        headers=headers,
                    )
                except AutoRefError as exc:
                    logger.info("AutoRef full record skipped (%s); keeping the match", exc)
                    full = None
                if isinstance(full, dict) and isinstance(full.get("VIN_INFO"), dict):
                    detail = full["VIN_INFO"]
        return map_vehicle(vin, row, detail, multiple=len(rows) > 1)

    async def usage(self, key: str | None = None) -> AutoRefUsage:
        """The plan and what's left of it. Costs no quota.

        Args:
            key: A key to test instead of this service's own.

        Raises:
            AutoRefAuthError, AutoRefUnavailableError (never an httpx error:
            the request URL holds the key).
        """
        checked = _checked_key(key or self._api_key)
        async with self._client_factory() as client:
            body = await self._get(client, "/usage", params={"api_key": checked})
        if not isinstance(body, dict):
            raise AutoRefUnavailableError(404 if body is None else 200)
        return AutoRefUsage(
            plan=_text(body.get("plan")),
            limit=_int(body.get("limit")),
            used=_int(body.get("used")),
            remaining=_int(body.get("remaining")),
            reset_date=_text(body.get("reset_date")),
        )
