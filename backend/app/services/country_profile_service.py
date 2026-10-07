"""Country profiles: loading, ``extends`` resolution and country resolution.

A vehicle's country is resolved in this order:

1. ``vehicle.registration_country`` (a cross-border household registers a
   car abroad);
2. the owner's ``user.country``;
3. the instance setting ``default_country``;
4. nothing: today's behaviour, no profile, US-oriented defaults.

A code with a profile file loads that file. An EU member state without one
loads the ``EU`` baseline. Anything else has no profile; the code is still
stored and shown (toll guess, VIN hints), it just drives no national rule.

Profiles are read once per process (``functools.cache``): they are shipped
data, not user data. Tests call ``clear_cache()`` after monkeypatching the
directory.
"""

from __future__ import annotations

import json
import logging
import re
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.countries import EU_MEMBER_STATES, normalize_country_code
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile, CountryProfileSummary
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "country_profiles"
EU_BASELINE = "EU"
DEFAULT_COUNTRY_SETTING = "default_country"

_PROFILE_ID = re.compile(r"^[A-Z]{2}$")


class ProfileError(ValueError):
    """A profile file is missing, unreadable or refers to itself."""


def _profile_path(profile_id: str) -> Path:
    # The id is the file stem, so it is matched against a strict pattern before
    # it is used in a path: ``../x`` is refused rather than resolved.
    if not _PROFILE_ID.match(profile_id):
        raise ProfileError(f"invalid profile id {profile_id!r}")
    return PROFILES_DIR / f"{profile_id}.json"


def _raw(profile_id: str) -> dict[str, Any] | None:
    path = _profile_path(profile_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProfileError(f"{path.name} must hold a JSON object")
    return data


def _resolve(profile_id: str, seen: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """The raw profile with its ``extends`` chain merged in.

    A child section replaces the parent's section wholesale (no deep merge):
    a country that restates ``inspection`` restates all of it, so the file
    reads as what applies there, not as a diff against the baseline.
    """
    if profile_id in seen:
        raise ProfileError(f"profile {profile_id} extends itself: {' -> '.join(seen)}")
    raw = _raw(profile_id)
    if raw is None:
        return None
    parent_id = raw.get("extends")
    if parent_id is None:
        return raw
    parent = _resolve(parent_id, (*seen, profile_id))
    if parent is None:
        raise ProfileError(f"profile {profile_id} extends unknown profile {parent_id}")
    merged = {**parent, **raw}
    # These describe the child alone, never inherited.
    merged["country"] = raw["country"]
    merged["sources"] = [*parent.get("sources", []), *raw.get("sources", [])]
    return merged


@cache
def load_profile(profile_id: str) -> CountryProfile | None:
    """The validated profile for a file id (``FR``, ``EU``…), or None."""
    merged = _resolve(profile_id)
    if merged is None:
        return None
    return CountryProfile.model_validate(merged)


@cache
def available_profile_ids() -> tuple[str, ...]:
    """File ids shipped with the app, sorted."""
    if not PROFILES_DIR.is_dir():
        return ()
    return tuple(sorted(p.stem for p in PROFILES_DIR.glob("*.json") if _PROFILE_ID.match(p.stem)))


def clear_cache() -> None:
    load_profile.cache_clear()
    available_profile_ids.cache_clear()


def profile_id_for_country(country: str | None) -> str | None:
    """Which file a country code reads: its own, the EU baseline, or none."""
    code = normalize_country_code(country)
    if code is None:
        return None
    if code in available_profile_ids():
        return code
    if code in EU_MEMBER_STATES:
        return EU_BASELINE
    return None


def profile_for_country(country: str | None) -> CountryProfile | None:
    profile_id = profile_id_for_country(country)
    return load_profile(profile_id) if profile_id else None


def list_profiles() -> list[CountryProfileSummary]:
    """One summary per shipped profile, the EU baseline included."""
    out: list[CountryProfileSummary] = []
    for profile_id in available_profile_ids():
        profile = load_profile(profile_id)
        if profile is None:
            continue
        out.append(
            CountryProfileSummary(
                country=profile.country,
                names=profile.names,
                has_inspection=profile.inspection is not None,
                lez_scheme=profile.lez.scheme,
                octane_scale=profile.fuel.octane_scale,
            )
        )
    return out


async def instance_default_country(db: AsyncSession) -> str | None:
    row = await SettingsService.get(db, DEFAULT_COUNTRY_SETTING)
    return normalize_country_code(row.value if row else None)


async def resolve_country(db: AsyncSession, vehicle: Vehicle) -> str | None:
    """The country whose rules apply to this vehicle (see module docstring)."""
    code = normalize_country_code(vehicle.registration_country)
    if code:
        return code
    owner: User | None = None
    if vehicle.user_id is not None:
        owner = await db.get(User, vehicle.user_id)
    if owner is not None:
        code = normalize_country_code(owner.country)
        if code:
            return code
    return await instance_default_country(db)


async def profile_for_vehicle(db: AsyncSession, vehicle: Vehicle) -> CountryProfile | None:
    return profile_for_country(await resolve_country(db, vehicle))
