"""AutoRef, the European VIN decoder (#219 takeover).

AutoRef (autoref.eu) answers from Swiss type approvals, EU certificates of
conformity and 1985-1995 records, then falls back to the UK DVSA and US NHTSA
registries. Its own tables read only the first 10 VIN characters; the two
registry fallbacks need all 17, so the full VIN is sent (plan D1).

A decode costs one or two quota units. ``/vehicles/{vin}`` lists every
version sold under the VIN's first 10 characters, which don't encode the
trim. With one version, ``/vehicle/{type}/{id}`` then adds body, doors,
displacement and drivetrain (skipped for a registry (UK/US) answer, which has
no record to fetch). With several, the decode fills only what they all agree
on and lists them; ``decode_version`` fetches the one the person picks.
``/usage`` costs nothing.

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
from typing import Any

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
#: Several versions matched; only what they share is filled until one is picked.
NOTE_AUTOREF_PICK_VERSION = "autoref_pick_version"
#: Versions listed to pick from at most. A 2015 Golf prefix has 55.
MAX_CANDIDATES = 100
#: The answer came from the UK or US registry, as written there.
NOTE_AUTOREF_EXTERNAL = "autoref_external_record"

#: AutoRef's gearbox codes, per their support (2026-11-07): S is a CVT
#: (stufenlos, Toyota e-CVTs too) even though the docs say "other", H is
#: hydrostatic (loaders, small tractors). CVT spelled the way NHTSA spells it.
_GEARBOX_CODES = {
    "M": "Manual",
    "A": "Automatic",
    "S": "Continuously Variable Transmission (CVT)",
    "H": "Hydrostatic",
}

#: AutoRef's CODE_FUEL list (support, 2026-11-07) as fuel and second fuel,
#: the same way the French certificate codes read. C and F are petrol or
#: diesel with electric, hybrid or plug-in; ``_fuels`` tells which. M
#: (methanol) and P (old petroleum) have no fuel type here, so they fall
#: back to the words.
_FUEL_CODES: dict[str, tuple[FuelTypeEnum, FuelTypeEnum | None]] = {
    "B": (FuelTypeEnum.GASOLINE, None),
    "D": (FuelTypeEnum.DIESEL, None),
    "C": (FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),
    "F": (FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),
    "E": (FuelTypeEnum.ELECTRIC, None),
    "R": (FuelTypeEnum.ELECTRIC, FuelTypeEnum.GASOLINE),  # range extender
    "X": (FuelTypeEnum.HYDROGEN, None),  # fuel cell
    "N": (FuelTypeEnum.CNG, None),
    "Y": (FuelTypeEnum.GASOLINE, FuelTypeEnum.CNG),
    "L": (FuelTypeEnum.PROPANE_LPG, None),
    "Z": (FuelTypeEnum.GASOLINE, FuelTypeEnum.PROPANE_LPG),
    "K": (FuelTypeEnum.E85, FuelTypeEnum.GASOLINE),  # flex fuel
    "J": (FuelTypeEnum.E85, None),
}
#: TYPE_HYBRID's values (lang=en). It's only filled for CoC and non-Swiss
#: records, so it's often blank on a real hybrid.
_PLUG_IN_TYPES = frozenset({"hybrid electric vehicle with charging station", "plug-in hybrid"})
_NOT_PLUG_IN_TYPES = frozenset(
    {"hybrid electric vehicle without charging station", "non-rechargeable hybrid"}
)
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


def _stated_hybrid(type_hybrid: str | None) -> bool | None:
    """What TYPE_HYBRID says: True a plug-in, False a hybrid that doesn't plug in, None unsaid."""
    kind = (type_hybrid or "").lower()
    if kind in _PLUG_IN_TYPES:
        return True
    if kind in _NOT_PLUG_IN_TYPES:
        return False
    return None


def _uses_electricity(electric_use: Any) -> bool:
    """Whether ELECTRIC_RANGE_MIN_MAX is filled.

    Despite the name it's the electric use in kWh/100 km, and only plug-ins
    have one (a 330e reads 18.6). AutoRef warns it's sometimes missing on a
    plug-in too, so a blank reads as a regular hybrid.
    """
    if isinstance(electric_use, bool):
        return False
    if isinstance(electric_use, (int, float)):
        return electric_use > 0
    return bool(_text(electric_use))


def _fuels(
    code: str,
    fuel_raw: str | None,
    second_raw: str | None,
    type_hybrid: str | None,
    electric_use: Any,
) -> tuple[str | None, str | None]:
    """The normalized fuel and second fuel.

    CODE_FUEL decides when it's one AutoRef lists; otherwise the words do,
    and a fuel paired with electric ("Gasoline / Electric") reads as a
    hybrid with electric second, like a French certificate's EH. A
    TYPE_HYBRID that names a hybrid makes plain gasoline or diesel one too:
    a real 330e comes back as just "Gasoline" with "Plug-in hybrid". A
    hybrid that plugs in is a plug-in hybrid: TYPE_HYBRID decides when it
    says, the electric use otherwise. A SECOND_FUEL AutoRef names wins.
    """
    second = normalize_fuel_type(second_raw) if second_raw else None
    known = _FUEL_CODES.get(code)
    if known is not None:
        fuel, implied = known
    else:
        fuel = normalize_fuel_type(fuel_raw) if fuel_raw else None
        implied = None
        if fuel_raw:
            parts = {normalize_fuel_type(part) for part in fuel_raw.split("/")}
            if len(parts) == 2 and FuelTypeEnum.ELECTRIC in parts and None not in parts:
                fuel, implied = FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC
    stated = _stated_hybrid(type_hybrid)
    if stated is not None and fuel in (FuelTypeEnum.GASOLINE, FuelTypeEnum.DIESEL):
        fuel, implied = FuelTypeEnum.HYBRID, implied or FuelTypeEnum.ELECTRIC
    plugs_in = stated if stated is not None else _uses_electricity(electric_use)
    if fuel is FuelTypeEnum.HYBRID and plugs_in:
        fuel = FuelTypeEnum.PLUGIN_HYBRID
    second = second or implied
    return (fuel.value if fuel else None, second.value if second else None)


def _gearbox(code: str, details: Any) -> dict[str, str | None]:
    """The transmission type and speeds from the code and the first gearbox detail."""
    first = details[0] if isinstance(details, list) and details else None
    detail = first if isinstance(first, dict) else {}
    gears = detail.get("gears")
    speeds = (
        str(gears)
        if isinstance(gears, int) and not isinstance(gears, bool) and 0 < gears <= _MAX_GEARS
        else None
    )
    kind = _GEARBOX_CODES.get(code)
    if kind == "Manual" and (_text(detail.get("additionnal_mode")) or "").upper() == "A":
        kind = AUTOMATED_MANUAL
    return {"type": kind, "speeds": speeds}


def map_vehicle(vin: str, row: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """An AutoRef answer in the decoder's shape (the keys NHTSA's answer uses).

    Args:
        vin: The VIN that was decoded.
        row: The chosen ``/vehicles/{vin}`` result.
        detail: Its full record's ``VIN_INFO``, or ``{}`` without one.

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
    fuel, fuel_secondary = _fuels(
        (_text(pick("CODE_FUEL")) or "").upper(),
        fuel_raw,
        _text(pick("SECOND_FUEL")),
        _text(pick("TYPE_HYBRID")),
        pick("ELECTRIC_RANGE_MIN_MAX"),
    )
    gearbox_code = (_text(row.get("CODE_GEARBOX")) or "").upper()
    model_text = (
        _text(pick("MODEL_RESOLVED")) or _text(pick("MODEL_LINE")) or _text(pick("MODEL_FULL"))
    )

    make = normalize_make(_text(pick("BRAND")))

    notes: list[str] = []
    configurations = row.get("configurations")
    if isinstance(configurations, list) and len(configurations) > 1:
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
        "transmission": _gearbox(gearbox_code, detail.get("GEARBOX_DETAILS")),
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


def _fold(value: Any) -> Any:
    """Strings compared without case or spacing ("1.8Hybrid" is "1.8 Hybrid")."""
    return "".join(value.split()).casefold() if isinstance(value, str) else value


def _agree(values: list[Any]) -> Any:
    """The first value when every value is the same, otherwise None."""
    first = values[0]
    if first is None:
        return None
    folded = _fold(first)
    return first if all(v is not None and _fold(v) == folded for v in values[1:]) else None


def agreed_answer(vin: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What every matched version agrees on, in the decoder's shape.

    Each row is mapped on its own and a field (or an engine or transmission
    subfield) is kept only when all of them hold the same value. Anything
    they differ on, or that one of them lacks, is None until a pick.
    """
    mapped = [map_vehicle(vin, row, {}) for row in rows]
    answer: dict[str, Any] = {}
    for key, first in mapped[0].items():
        if isinstance(first, dict):
            answer[key] = {sub: _agree([m[key].get(sub) for m in mapped]) for sub in first}
        else:
            answer[key] = _agree([m[key] for m in mapped])
    answer["vin"] = vin
    answer["year"] = None
    answer["notes"] = [NOTE_AUTOREF_PICK_VERSION]
    return answer


def _identity(candidate: dict[str, Any]) -> tuple[Any, ...]:
    """What makes two rows the same version. Without a MODEL_FULL nothing
    says they are, so such a row is only ever itself."""
    if candidate["model_full"] is None:
        return ("record", candidate["record_type"], candidate["id"])
    return (
        _fold(candidate["model_full"]),
        candidate["kw"],
        candidate["fuel_type"],
        candidate["gearbox_code"],
    )


def _candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    """One row as a version to pick, or None when its pick couldn't be checked.

    It needs a full record behind it and a model name or a power to check
    the record against, since AutoRef reassigns ids when it rebuilds.
    """
    target = _detail_target(row)
    if target is None:
        return None
    model_full = _text(row.get("MODEL_FULL"))
    kw = _int(row.get("POWER_KW"))
    if model_full is None and kw is None:
        return None
    code = (_text(row.get("CODE_GEARBOX")) or "").upper()
    fuel, _ = _fuels(
        (_text(row.get("CODE_FUEL")) or "").upper(),
        _text(row.get("FUEL")),
        _text(row.get("SECOND_FUEL")),
        _text(row.get("TYPE_HYBRID")),
        row.get("ELECTRIC_RANGE_MIN_MAX"),
    )
    label = (
        model_full
        or _text(row.get("BRAND_MODEL"))
        or " ".join(
            part
            for part in (_text(row.get("MODEL_RESOLVED")), _text(row.get("MOTORIZATION")))
            if part
        )
    )
    configurations = row.get("configurations")
    return {
        "record_type": target[0],
        "id": target[1],
        "label": label,
        "model_full": model_full,
        "fuel_type": fuel,
        "kw": kw,
        "transmission": _GEARBOX_CODES.get(code),
        "gearbox_code": code if code in _GEARBOX_CODES else None,
        "grouped": isinstance(configurations, list) and len(configurations) > 1,
    }


def candidates_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The versions to pick from, in AutoRef's order (most registered first).

    Rows that read as the same version are listed once, and only the first
    ``MAX_CANDIDATES``.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        candidate = _candidate(row)
        if candidate is None:
            continue
        identity = _identity(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(candidate)
        if len(out) == MAX_CANDIDATES:
            break
    return out


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
        """A VIN's answer, mapped, or None when nothing matched.

        One version (or several that read the same) gets its full record.
        Several different versions get only what they agree on, plus a
        ``candidates`` list to pick from, with no second request.

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
            if not isinstance(rows, list):
                return None
            rows = [r for r in rows if isinstance(r, dict)]
            if not rows:
                return None
            candidates = candidates_of(rows) if len(rows) > 1 else []
            if len(candidates) > 1:
                return {**agreed_answer(vin, rows), "candidates": candidates}
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
        result = map_vehicle(vin, row, detail)
        # Rows that are all one version (the Corolla's "1.8Hybrid" and
        # "1.8 Hybrid") aren't a guess. Anything else left over still is.
        identities = {_identity(c) if c else None for c in map(_candidate, rows)}
        one_version = None not in identities and len(identities) == 1
        if len(rows) > 1 and not one_version and NOTE_AUTOREF_BEST_GUESS not in result["notes"]:
            result["notes"].insert(0, NOTE_AUTOREF_BEST_GUESS)
        return result

    async def decode_version(
        self,
        vin: str,
        record_type: str,
        record_id: str,
        *,
        gearbox_code: str | None,
        expect_model: str | None,
        expect_kw: int | None,
        grouped: bool,
    ) -> dict[str, Any] | None:
        """A picked version's full record, mapped, or None when it isn't that version anymore.

        The ids are ephemeral, so the record must still belong to the VIN's
        prefix and still be the version that was picked (its model name and
        power, whichever the pick carried).

        Args:
            vin: The decoded VIN.
            record_type: The candidate's record type.
            record_id: The candidate's id.
            gearbox_code: The candidate's gearbox code; the full record has none.
            expect_model: The candidate's MODEL_FULL.
            expect_kw: The candidate's power in kW.
            grouped: The candidate stood for several configurations.

        Raises:
            ValueError: The VIN or the pick is malformed (checked before any request).
            AutoRefAuthError, AutoRefQuotaError, AutoRefUnavailableError.
        """
        vin = vin.strip().upper()
        is_valid, error = validate_vin(vin)
        if not is_valid:
            raise ValueError(f"Invalid VIN: {error}")
        if record_type not in LOCAL_RECORD_TYPES:
            raise ValueError("Unknown record type")
        if not (record_id.isascii() and record_id.isalnum() and 1 <= len(record_id) <= 32):
            raise ValueError("Malformed record id")
        if gearbox_code is not None and gearbox_code not in _GEARBOX_CODES:
            raise ValueError("Unknown gearbox code")
        if expect_model is None and expect_kw is None:
            raise ValueError("A pick needs a model or a power to check")
        headers = {"x-api-key": _checked_key(self._api_key)}
        async with self._client_factory() as client:
            # codeql[py/partial-ssrf] - fixed host; type from a fixed set, id checked alphanumeric
            full = await self._get(
                client,
                f"/vehicle/{record_type}/{record_id}",
                params={"lang": "en"},
                headers=headers,
            )
        if not (isinstance(full, dict) and isinstance(full.get("VIN_INFO"), dict)):
            return None
        detail: dict[str, Any] = full["VIN_INFO"]
        record_vin = _text(detail.get("VIN"))
        if record_vin is not None and record_vin[:10].upper() != vin[:10]:
            logger.info("AutoRef record %s/%s belongs to another VIN now", record_type, record_id)
            return None
        if expect_model is not None and _fold(expect_model) != _fold(
            _text(detail.get("MODEL_FULL"))
        ):
            logger.info("AutoRef record %s/%s is another version now", record_type, record_id)
            return None
        if expect_kw is not None and expect_kw != _int(detail.get("POWER_KW")):
            logger.info("AutoRef record %s/%s is another version now", record_type, record_id)
            return None
        result = map_vehicle(
            vin, {"RECORD_TYPE": record_type, "CODE_GEARBOX": gearbox_code or ""}, detail
        )
        if grouped and NOTE_AUTOREF_BEST_GUESS not in result["notes"]:
            result["notes"].insert(0, NOTE_AUTOREF_BEST_GUESS)
        return result

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
