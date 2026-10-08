"""RappelConso, the French government's product recall register, as a recall
provider (#211).

The open dataset (data.economie.gouv.fr, Licence Ouverte 2.0) lists every
consumer product recall published in France, cars included, with the make
(``marque_produit``, lowercase), the models or references as free text
(``modeles_ou_references``), the production or registration date ranges as
free text (``identification_produits``), the risk, what to do, and a link
to the notice. There is no VIN, so a notice is matched to a vehicle by:

1. the make, through a few aliases (Citroën and DS, Mercedes and
   Mercedes-Benz, VW and Volkswagen…), which is also the API filter;
2. the model, every word of the vehicle's model appearing as a WHOLE word
   in the notice's models (« 3 » never matches « 3008 »);
3. the first registration date against the notice's date ranges, when
   both exist: inside one of them scores 95, outside every one 55, no
   range printed 75.

Only a match at 60 or more is stored, with its score, and a stored notice
is never resolved automatically: the register says which vehicles are
concerned, not whether this one was fixed. Fetched per make with a short
cache, so the weekly job asks once for a household of Renaults.

Captured on 2026-10-07: about 1 900 « Automobiles » notices, fields
``marque_produit``, ``modeles_ou_references``, ``identification_produits``,
``libelle``, ``risques_encourus_par_le_consommateur``,
``conduites_a_tenir_par_le_consommateur``, ``date_publication``,
``lien_vers_la_fiche_rappel``, ``sous_categorie_produit``.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile
from app.services.recalls.base import SOURCE_RAPPELCONSO, RecallHit
from app.services.settings_service import SettingsService
from app.utils.logging_utils import sanitize_for_log
from app.utils.url_validation import validate_data_economie_url

logger = logging.getLogger(__name__)

DEFAULT_API_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "rappelconso-v2-gtin-espaces/records"
)
API_URL_SETTING = "rappelconso_api_url"
ENABLED_SETTING = "rappelconso_enabled"
LAST_CHECK_SETTING = "rappelconso_last_check"

#: The dataset's category for cars, vans and motorcycles.
CATEGORY = "Automobiles"
PAGE_SIZE = 100
MAX_RECORDS = 500
TIMEOUT_SECONDS = 20.0
#: A notice is stored from this score up.
MIN_CONFIDENCE = 60
#: How long a make's notices are kept in memory.
CACHE_TTL_SECONDS = 600
#: A production range may end some months before the car is registered.
REGISTRATION_LAG = timedelta(days=270)

#: Makes the register may file under another name, both ways. Keys and
#: values are normalised spellings (see ``normalise``); the API query is a
#: word search, so « mercedes » already finds « mercedes-benz ».
BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "citroen": ("ds",),
    "ds": ("citroen",),
    "vw": ("volkswagen",),
    "volkswagen": ("vw",),
    "mercedes benz": ("mercedes",),
    "alfa romeo": ("alfa",),
    "land rover": ("landrover",),
}

_DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def normalise(text: str | None) -> str:
    """Lowercase, accent-free, alphanumerics and single spaces."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def brand_variants(make: str | None) -> tuple[str, ...]:
    """The make as the register may file it, the vehicle's own spelling first."""
    base = normalise(make)
    if not base:
        return ()
    variants: list[str] = [base]
    for alias in BRAND_ALIASES.get(base, ()):
        if alias not in variants:
            variants.append(alias)
    return tuple(variants)


def brand_matches(record_brand: str | None, brand: str) -> bool:
    """The record's make is the brand, or starts with it as a word (« ds
    automobiles » for « ds », « mercedes-benz » for « mercedes »)."""
    folded = normalise(record_brand)
    return folded == brand or folded.startswith(brand + " ")


def model_tokens(model: str | None) -> tuple[str, ...]:
    return tuple(normalise(model).split())


def model_matches(model: str | None, record_models: str | None) -> bool:
    """Every word of the vehicle's model is a whole word of the notice's."""
    tokens = model_tokens(model)
    if not tokens:
        return False
    haystack = f" {normalise(record_models)} "
    return all(f" {token} " in haystack for token in tokens)


def date_ranges(text: str | None) -> list[tuple[date, date]]:
    """``(start, end)`` pairs from the dates printed in the identification text,
    in order; a lone trailing date is a range of one day."""
    dates: list[date] = []
    for day, month, year in _DATE_RE.findall(text or ""):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    ranges: list[tuple[date, date]] = []
    for index in range(0, len(dates), 2):
        start = dates[index]
        end = dates[index + 1] if index + 1 < len(dates) else start
        if end < start:
            start, end = end, start
        ranges.append((start, end))
    return ranges


def confidence_for(first_registration: date | None, identification: str | None) -> int:
    """95 inside a printed range (production may end months before
    registration), 55 outside every one, 75 when nothing can be checked."""
    ranges = date_ranges(identification)
    if first_registration is None or not ranges:
        return 75
    for start, end in ranges:
        if start <= first_registration <= end + REGISTRATION_LAG:
            return 95
    return 55


def _text(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value if item)
    text = str(value).strip()
    return text or None


def _published(record: dict[str, Any]) -> date | None:
    raw = _text(record, "date_publication") or _text(record, "date_de_publication")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        match = _DATE_RE.search(raw)
        if match is None:
            return None
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None


def hit_from_record(record: dict[str, Any], vehicle: Vehicle) -> RecallHit | None:
    """The notice as a hit for the vehicle, or None when the model does not
    match or the notice has no identifier."""
    external_id = _text(record, "numero_fiche") or _text(record, "id")
    if not external_id:
        return None
    models = _text(record, "modeles_ou_references") or _text(
        record, "noms_des_modeles_ou_references"
    )
    if not model_matches(vehicle.model, models):
        return None
    identification = _text(record, "identification_produits")
    confidence = confidence_for(vehicle.first_registration_date, identification)
    title = _text(record, "libelle") or _text(record, "nom_de_la_marque_du_produit") or models
    risk = _text(record, "risques_encourus_par_le_consommateur")
    summary_parts = [part for part in (title, models, identification) if part]
    summary = "\n".join(summary_parts) if summary_parts else "RappelConso notice"
    return RecallHit(
        source=SOURCE_RAPPELCONSO,
        external_id=external_id[:64],
        external_url=_text(record, "lien_vers_la_fiche_rappel"),
        component=(_text(record, "sous_categorie_produit") or "Vehicle")[:200],
        summary=summary,
        consequence=risk,
        remedy=_text(record, "conduites_a_tenir_par_le_consommateur"),
        date_announced=_published(record),
        match_confidence=confidence,
    )


@dataclass
class RappelConsoProvider:
    name: str = SOURCE_RAPPELCONSO

    def applies_to(self, vehicle: Vehicle, profile: CountryProfile | None) -> bool:
        return (
            profile is not None
            and SOURCE_RAPPELCONSO in profile.data_sources.recalls
            and bool(normalise(vehicle.make))
        )

    async def enabled(self, db: AsyncSession) -> bool:
        return await SettingsService.get_bool(db, ENABLED_SETTING, default=True)

    async def api_url(self, db: AsyncSession) -> str:
        row = await SettingsService.get(db, API_URL_SETTING)
        stored = (row.value or "").strip() if row is not None else ""
        if not stored:
            return DEFAULT_API_URL
        try:
            validate_data_economie_url(stored)
        except Exception as exc:  # noqa: BLE001 - any refusal means the default
            logger.error(
                "RappelConso API URL refused, using the default: %s", sanitize_for_log(exc)
            )
            return DEFAULT_API_URL
        return stored

    async def records_for_brand(self, db: AsyncSession, brand: str) -> list[dict[str, Any]]:
        """Every « Automobiles » notice of a make, newest first, cached briefly."""
        now = time.monotonic()
        cached = _cache.get(brand)
        if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        url = await self.api_url(db)
        # `like` is ODSQL's word search: « mercedes » finds « mercedes-benz ».
        # The records are checked again on the way back (`brand_matches`).
        where = f'categorie_produit like "{CATEGORY}" and marque_produit like "{brand}"'
        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            offset = 0
            while offset < MAX_RECORDS:
                params = {
                    "where": where,
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "order_by": "date_publication desc",
                }
                response = await client.get(url, params=params)
                response.raise_for_status()
                page = response.json().get("results", [])
                if not isinstance(page, list):
                    break
                records.extend(record for record in page if isinstance(record, dict))
                if len(page) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
        _cache[brand] = (now, records)
        return records

    async def fetch(self, db: AsyncSession, vehicle: Vehicle) -> list[RecallHit]:
        hits: dict[str, RecallHit] = {}
        for brand in brand_variants(vehicle.make):
            for record in await self.records_for_brand(db, brand):
                if not brand_matches(_text(record, "marque_produit"), brand):
                    continue
                hit = hit_from_record(record, vehicle)
                if hit is None or hit.match_confidence < MIN_CONFIDENCE:
                    continue
                hits.setdefault(hit.external_id, hit)
        logger.info(
            "RappelConso: %d notice(s) match %s %s",
            len(hits),
            sanitize_for_log(vehicle.make),
            sanitize_for_log(vehicle.model),
        )
        return list(hits.values())


def clear_cache() -> None:
    _cache.clear()
