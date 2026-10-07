"""Country profiles: every shipped file validates, `extends` merges, resolution order."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.constants.countries import EU_MEMBER_STATES, ISO_3166_ALPHA2
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile
from app.services import country_profile_service as svc


@pytest.fixture(autouse=True)
def _fresh_cache():
    svc.clear_cache()
    yield
    svc.clear_cache()


def test_iso_list_has_the_249_assigned_codes():
    assert len(ISO_3166_ALPHA2) == 249
    assert all(len(c) == 2 and c.isupper() for c in ISO_3166_ALPHA2)
    assert EU_MEMBER_STATES <= ISO_3166_ALPHA2
    assert len(EU_MEMBER_STATES) == 27


def test_every_shipped_profile_validates():
    ids = svc.available_profile_ids()
    assert "EU" in ids and "FR" in ids
    for profile_id in ids:
        profile = svc.load_profile(profile_id)
        assert profile is not None, profile_id
        assert profile.country == profile_id
        if profile_id != "EU":
            assert profile.extends == "EU"
            assert profile.country in ISO_3166_ALPHA2
        assert profile.sources, f"{profile_id} cites no source"


def test_extends_replaces_sections_and_concatenates_sources():
    eu = svc.load_profile("EU")
    fr = svc.load_profile("FR")
    assert eu is not None and fr is not None
    # FR restates the inspection section wholesale.
    assert fr.inspection is not None and fr.inspection.name == "Contrôle technique"
    assert fr.inspection.lead_window_months == 6
    # Sources are the baseline's followed by the country's own.
    assert len(fr.sources) > len(eu.sources)
    assert fr.sources[: len(eu.sources)] == eu.sources
    # A section FR does not restate comes from the baseline.
    assert fr.default_reminder_packs == eu.default_reminder_packs


def test_fr_profile_facts():
    fr = svc.load_profile("FR")
    assert fr is not None and fr.inspection is not None
    cars = next(s for s in fr.inspection.schedules if "Car" in s.vehicle_types)
    assert [s.first_after_years or s.every_years for s in cars.steps] == [4, 2]
    motos = next(s for s in fr.inspection.schedules if "Motorcycle" in s.vehicle_types)
    assert [s.first_after_years or s.every_years for s in motos.steps] == [5, 3]
    assert fr.fuel.octane_scale == "RON"
    assert {g.id for g in fr.fuel.grades} >= {"sp95_e10", "sp98", "gazole", "gpl"}
    assert fr.lez.scheme == "critair"
    assert fr.registration_certificate.energy_codes["GO"] == "diesel"
    assert fr.data_sources.recalls == ["rappelconso"]


def test_nl_schedules_are_fuel_dependent():
    nl = svc.load_profile("NL")
    assert nl is not None and nl.inspection is not None
    diesel = next(s for s in nl.inspection.schedules if "diesel" in s.fuel_types)
    petrol = next(s for s in nl.inspection.schedules if "gasoline" in s.fuel_types)
    assert diesel.steps[0].first_after_years == 3
    assert petrol.steps[1].until_age_years == 8


def test_profile_id_resolution():
    assert svc.profile_id_for_country("FR") == "FR"
    assert svc.profile_id_for_country(" fr ") == "FR"
    # A member state without its own file reads the EU baseline.
    assert svc.profile_id_for_country("AT") == "EU"
    assert svc.profile_for_country("AT") is not None
    assert svc.profile_for_country("AT").country == "EU"
    # Outside the EU, no profile.
    assert svc.profile_id_for_country("US") is None
    assert svc.profile_for_country("US") is None
    assert svc.profile_for_country(None) is None
    assert svc.profile_for_country("") is None


def test_list_profiles_summaries():
    summaries = {s.country: s for s in svc.list_profiles()}
    assert summaries["FR"].has_inspection is True
    assert summaries["FR"].lez_scheme == "critair"
    assert summaries["FR"].octane_scale == "RON"
    assert summaries["EU"].lez_scheme is None


def test_extends_cycle_is_refused(tmp_path: Path, monkeypatch):
    (tmp_path / "AA.json").write_text(json.dumps({"country": "AA", "extends": "BB"}))
    (tmp_path / "BB.json").write_text(json.dumps({"country": "BB", "extends": "AA"}))
    monkeypatch.setattr(svc, "PROFILES_DIR", tmp_path)
    svc.clear_cache()
    with pytest.raises(svc.ProfileError):
        svc.load_profile("AA")


def test_unknown_parent_is_refused(tmp_path: Path, monkeypatch):
    (tmp_path / "AA.json").write_text(json.dumps({"country": "AA", "extends": "ZZ"}))
    monkeypatch.setattr(svc, "PROFILES_DIR", tmp_path)
    svc.clear_cache()
    with pytest.raises(svc.ProfileError):
        svc.load_profile("AA")


def test_bad_profile_id_never_touches_the_filesystem():
    with pytest.raises(svc.ProfileError):
        svc.load_profile("../etc")


def test_schema_refuses_unknown_keys_and_bad_steps():
    with pytest.raises(ValueError):
        CountryProfile.model_validate({"country": "FR", "bogus": 1})
    with pytest.raises(ValueError):
        CountryProfile.model_validate(
            {
                "country": "FR",
                "inspection": {
                    "name": "x",
                    "schedules": [
                        # Two first_after steps: not a cadence.
                        {
                            "vehicle_types": ["Car"],
                            "steps": [{"first_after_years": 4}, {"first_after_years": 2}],
                        }
                    ],
                },
            }
        )


@pytest.mark.asyncio
async def test_resolve_country_precedence(db_session, test_user, test_vehicle):
    vehicle = (
        await db_session.execute(select(Vehicle).where(Vehicle.vin == test_vehicle["vin"]))
    ).scalar_one()
    owner = await db_session.get(User, vehicle.user_id)
    assert owner is not None

    # Nothing set anywhere: None.
    assert await svc.resolve_country(db_session, vehicle) is None

    # Instance default is the last rung. The row may already be seeded by the
    # app's startup in another test, so upsert rather than insert.
    row = (
        await db_session.execute(select(Setting).where(Setting.key == "default_country"))
    ).scalar_one_or_none()
    if row is None:
        db_session.add(Setting(key="default_country", value="de", category="general"))
    else:
        row.value = "de"
    await db_session.commit()
    assert await svc.resolve_country(db_session, vehicle) == "DE"

    # The owner's country beats the instance.
    owner.country = "FR"
    await db_session.commit()
    assert await svc.resolve_country(db_session, vehicle) == "FR"

    # The vehicle's registration country beats both.
    vehicle.registration_country = "LU"
    await db_session.commit()
    assert await svc.resolve_country(db_session, vehicle) == "LU"
    profile = await svc.profile_for_vehicle(db_session, vehicle)
    assert profile is not None and profile.country == "LU"
