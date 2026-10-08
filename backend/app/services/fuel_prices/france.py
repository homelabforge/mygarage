"""French pump prices: « Prix des carburants en France, flux instantané »
(data.economie.gouv.fr, open data, Licence Ouverte 2.0), #211.

Every station in France reports its prices to the government within hours
of a change; the dataset republishes them about every ten minutes. One
record per station, with a price and a timestamp per fuel the pump sells:
``gazole_prix`` (B7), ``sp95_prix`` (E5 at 95 RON), ``e10_prix`` (E10),
``sp98_prix`` (E5 at 98 RON), ``e85_prix`` (E85), ``gplc_prix`` (LPG),
each with its ``*_maj`` « mise à jour » timestamp, plus the address, the
town, the postcode and ``geom`` (lat, lon). The fields were checked live on
2026-10-07.

The query is ODSQL's ``within_distance(geom, geom'POINT(lon lat)', 2km)``,
nearest first, cached ten minutes per point rounded to about a hundred
metres: a fill-up form asks for the same station several times while it is
open, and the source itself only moves every ten minutes.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.fuel_prices.base import FuelPrice, StationPrices
from app.services.settings_service import SettingsService
from app.utils.logging_utils import sanitize_for_log
from app.utils.url_validation import validate_data_economie_url

logger = logging.getLogger(__name__)

PROVIDER_ID = "fr_instantane"
DEFAULT_API_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/records"
)
API_URL_SETTING = "fuel_prices_api_url"
ENABLED_SETTING = "fuel_prices_enabled"
CURRENCY = "EUR"
TIMEOUT_SECONDS = 15.0
#: How long a point's stations are kept in memory: the source republishes
#: about every ten minutes.
CACHE_TTL_SECONDS = 600
#: Four decimals of a degree is about eleven metres: two forms open on the
#: same station share one answer, two stations never do.
CACHE_ROUNDING = 4
MAX_RADIUS_KM = 25.0
MAX_LIMIT = 20

#: Dataset field prefix → (EN 16942 label, RON) in the order a pump lists them.
FUELS: tuple[tuple[str, str, int | None], ...] = (
    ("gazole", "B7", None),
    ("sp95", "E5", 95),
    ("e10", "E10", 95),
    ("sp98", "E5", 98),
    ("e85", "E85", None),
    ("gplc", "LPG", None),
)

_cache: dict[tuple[float, float, float, int], tuple[float, list[StationPrices]]] = {}


def _text(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    printed = " ".join(str(value).split())
    return printed or None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coordinates(record: dict[str, Any]) -> tuple[float, float] | None:
    geom = record.get("geom")
    if isinstance(geom, dict):
        lat, lon = geom.get("lat"), geom.get("lon")
    else:
        lat, lon = record.get("latitude"), record.get("longitude")
    try:
        return float(lat), float(lon)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The great-circle distance between two points, in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def prices_of(record: dict[str, Any]) -> list[FuelPrice]:
    """The pump prices one record carries, in pump order, priced ones only."""
    prices: list[FuelPrice] = []
    for prefix, grade, octane in FUELS:
        amount = _decimal(record.get(f"{prefix}_prix"))
        if amount is None:
            continue
        prices.append(
            FuelPrice(
                grade=grade,
                octane=octane,
                price=amount,
                currency=CURRENCY,
                updated_at=_timestamp(record.get(f"{prefix}_maj")),
            )
        )
    return prices


def station_from_record(
    record: dict[str, Any], latitude: float, longitude: float
) -> StationPrices | None:
    """One dataset record as a station, or None without coordinates or an id."""
    coordinates = _coordinates(record)
    external_id = _text(record, "id")
    if coordinates is None or external_id is None:
        return None
    lat, lon = coordinates
    # The dataset's own geometry is lat/lon in degrees times 100000 in the
    # older fields; ``geom`` is plain degrees. A latitude past 90 is the
    # scaled shape.
    if abs(lat) > 90 or abs(lon) > 180:
        lat, lon = lat / 100000, lon / 100000
    return StationPrices(
        external_id=external_id,
        name=_text(record, "nom") or _text(record, "enseigne"),
        address=_text(record, "adresse"),
        city=_text(record, "ville"),
        postal_code=_text(record, "cp"),
        latitude=lat,
        longitude=lon,
        distance_km=round(haversine_km(latitude, longitude, lat, lon), 3),
        prices=prices_of(record),
    )


class FrenchFuelPriceProvider:
    id = PROVIDER_ID
    currency = CURRENCY

    async def enabled(self, db: AsyncSession) -> bool:
        return await SettingsService.get_bool(db, ENABLED_SETTING, default=True)

    async def api_url(self, db: AsyncSession) -> str:
        """The configured endpoint when it passes the allowlist, else the
        default: a bad setting must not take fuel prices down."""
        row = await SettingsService.get(db, API_URL_SETTING)
        configured = (row.value or "").strip() if row is not None else ""
        if not configured:
            return DEFAULT_API_URL
        try:
            validate_data_economie_url(configured)
        except Exception as exc:  # noqa: BLE001 - SSRF or malformed, same answer
            logger.error(
                "fuel_prices_api_url refused (%s), using the default", sanitize_for_log(exc)
            )
            return DEFAULT_API_URL
        return configured

    async def nearby(
        self, db: AsyncSession, latitude: float, longitude: float, *, radius_km: float, limit: int
    ) -> list[StationPrices]:
        radius_km = min(max(radius_km, 0.1), MAX_RADIUS_KM)
        limit = min(max(limit, 1), MAX_LIMIT)
        key = (round(latitude, CACHE_ROUNDING), round(longitude, CACHE_ROUNDING), radius_km, limit)
        now = time.monotonic()
        cached = _cache.get(key)
        if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        url = await self.api_url(db)
        params = {
            # ODSQL: a point is lon then lat, and the radius carries its unit.
            "where": f"within_distance(geom, geom'POINT({longitude} {latitude})', {radius_km}km)",
            "order_by": f"distance(geom, geom'POINT({longitude} {latitude})')",
            "limit": limit,
        }
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            page = response.json().get("results", [])
        stations: list[StationPrices] = []
        for record in page if isinstance(page, list) else []:
            if not isinstance(record, dict):
                continue
            station = station_from_record(record, latitude, longitude)
            if station is not None:
                stations.append(station)
        stations.sort(key=lambda station: station.distance_km)
        _cache[key] = (now, stations)
        return stations


def clear_cache() -> None:
    _cache.clear()
