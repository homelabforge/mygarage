"""The RappelConso recall provider (#211): matching, scoring, the fetch and
its allowlist. Records are shaped like the dataset's (captured 2026-10-07)."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.exceptions import SSRFProtectionError
from app.models.settings import Setting
from app.models.vehicle import Vehicle
from app.services.country_profile_service import profile_for_country
from app.services.recalls import rappelconso
from app.services.recalls.base import SOURCE_RAPPELCONSO
from app.services.recalls.nhtsa import NHTSARecallProvider, hit_from_nhtsa
from app.services.recalls.rappelconso import (
    RappelConsoProvider,
    brand_matches,
    brand_variants,
    confidence_for,
    date_ranges,
    hit_from_record,
    model_matches,
    normalise,
)
from app.services.recalls.registry import providers_for
from app.utils.url_validation import validate_data_economie_url

ZOE_RECORD: dict[str, Any] = {
    "numero_fiche": "2024-03-0123",
    "categorie_produit": "Automobiles",
    "sous_categorie_produit": "Automobiles",
    "marque_produit": "renault",
    "modeles_ou_references": "ZOE (Phase 2) – Véhicules fabriqués du 12.03.2019 au 30.06.2020",
    "identification_produits": "Véhicules produits du 12.03.2019 au 30.06.2020",
    "libelle": "Rappel de véhicules Renault ZOE",
    "risques_encourus_par_le_consommateur": "Risque d'incendie",
    "conduites_a_tenir_par_le_consommateur": "Prendre rendez-vous auprès d'un réparateur agréé",
    "date_publication": "2024-03-14T10:15:00+00:00",
    "lien_vers_la_fiche_rappel": "https://rappel.conso.gouv.fr/fiche-rappel/12345/Interne",
}
CLIO_RECORD: dict[str, Any] = {
    **ZOE_RECORD,
    "numero_fiche": "2023-11-0456",
    "modeles_ou_references": "CLIO V, CAPTUR II",
    "identification_produits": "",
    "libelle": "Rappel Renault Clio V et Captur II",
}
RECORD_3008: dict[str, Any] = {
    **ZOE_RECORD,
    "numero_fiche": "2022-01-0789",
    "marque_produit": "peugeot",
    "modeles_ou_references": "3008 et 5008",
    "libelle": "Rappel Peugeot 3008",
}


def _vehicle(**fields: Any) -> Vehicle:
    base = {
        "vin": "VF1AG000X66123456",
        "nickname": "Zoé",
        "vehicle_type": "Car",
        "make": "Renault",
        "model": "Zoe",
        "registration_country": "FR",
        "first_registration_date": date(2019, 9, 2),
    }
    base.update(fields)
    return Vehicle(**base)


class TestMatching:
    def test_normalise_strips_accents_case_and_punctuation(self):
        assert normalise("Citroën C3-Aircross") == "citroen c3 aircross"
        assert normalise(None) == ""

    def test_brand_variants(self):
        assert brand_variants("Citroën") == ("citroen", "ds")
        assert brand_variants("Mercedes-Benz") == ("mercedes benz", "mercedes")
        assert brand_variants("Renault") == ("renault",)
        assert brand_variants(None) == ()
        assert brand_matches("mercedes-benz", "mercedes")
        assert brand_matches("DS Automobiles", "ds")
        assert not brand_matches("dsfoo", "ds")
        assert not brand_matches("mercedes-benz", "benz")

    def test_model_matches_whole_words_only(self):
        assert model_matches("Zoe", "ZOE (Phase 2)")
        assert model_matches("Clio", "CLIO V, CAPTUR II")
        assert model_matches("Model 3", "Model 3 et Model Y")
        assert not model_matches("3", "3008 et 5008")  # « 3 » is not « 3008 »
        assert model_matches("3008", "3008 et 5008")
        assert not model_matches("Captur", "CLIO V")
        assert not model_matches(None, "CLIO V")
        assert not model_matches("Clio", None)

    def test_date_ranges(self):
        assert date_ranges("Véhicules produits du 12.03.2019 au 30.06.2020") == [
            (date(2019, 3, 12), date(2020, 6, 30))
        ]
        assert date_ranges("du 01/01/2021 au 31/12/2021 et du 15/02/2022 au 30/04/2022") == [
            (date(2021, 1, 1), date(2021, 12, 31)),
            (date(2022, 2, 15), date(2022, 4, 30)),
        ]
        assert date_ranges("immatriculés avant le 31.12.2020") == [
            (date(2020, 12, 31), date(2020, 12, 31))
        ]
        assert date_ranges("aucune date") == []
        assert date_ranges(None) == []

    @pytest.mark.parametrize(
        ("first_registration", "identification", "expected"),
        [
            (date(2019, 9, 2), "produits du 12.03.2019 au 30.06.2020", 95),
            (
                date(2020, 12, 1),
                "produits du 12.03.2019 au 30.06.2020",
                95,
            ),  # registered months after production
            (date(2022, 1, 1), "produits du 12.03.2019 au 30.06.2020", 55),
            (date(2018, 1, 1), "produits du 12.03.2019 au 30.06.2020", 55),
            (date(2019, 9, 2), "", 75),
            (None, "produits du 12.03.2019 au 30.06.2020", 75),
        ],
    )
    def test_confidence(self, first_registration, identification, expected):
        assert confidence_for(first_registration, identification) == expected


class TestHitFromRecord:
    def test_a_matching_notice_becomes_a_hit(self):
        hit = hit_from_record(ZOE_RECORD, _vehicle())
        assert hit is not None
        assert hit.source == SOURCE_RAPPELCONSO
        assert hit.external_id == "2024-03-0123"
        assert hit.external_url == "https://rappel.conso.gouv.fr/fiche-rappel/12345/Interne"
        assert hit.component == "Automobiles"
        assert hit.summary.startswith("Rappel de véhicules Renault ZOE")
        assert "ZOE (Phase 2)" in hit.summary
        assert hit.consequence == "Risque d'incendie"
        assert hit.remedy == "Prendre rendez-vous auprès d'un réparateur agréé"
        assert hit.date_announced == date(2024, 3, 14)
        assert hit.match_confidence == 95

    def test_another_model_is_not_a_hit(self):
        assert hit_from_record(ZOE_RECORD, _vehicle(model="Clio")) is None
        assert hit_from_record(CLIO_RECORD, _vehicle(model="Clio")) is not None

    def test_no_ranges_scores_75_and_outside_scores_55(self):
        clio = hit_from_record(CLIO_RECORD, _vehicle(model="Clio"))
        assert clio is not None and clio.match_confidence == 75
        old = hit_from_record(ZOE_RECORD, _vehicle(first_registration_date=date(2023, 1, 1)))
        assert old is not None and old.match_confidence == 55

    def test_a_record_without_an_identifier_is_dropped(self):
        record = {k: v for k, v in ZOE_RECORD.items() if k != "numero_fiche"}
        assert hit_from_record(record, _vehicle()) is None
        record["id"] = "fallback-id"
        hit = hit_from_record(record, _vehicle())
        assert hit is not None and hit.external_id == "fallback-id"


class TestAppliesTo:
    def test_france_yes_united_states_no(self):
        provider = RappelConsoProvider()
        assert provider.applies_to(_vehicle(), profile_for_country("FR"))
        assert not provider.applies_to(_vehicle(), profile_for_country("DE"))
        assert not provider.applies_to(_vehicle(), None)
        assert not provider.applies_to(_vehicle(make=None), profile_for_country("FR"))

    def test_nhtsa_applies_without_a_profile_only(self):
        provider = NHTSARecallProvider()
        assert provider.applies_to(_vehicle(), None)
        assert not provider.applies_to(_vehicle(), profile_for_country("FR"))

    def test_nhtsa_hit_shape(self):
        hit = hit_from_nhtsa(
            {"NHTSACampaignNumber": "24V001", "Component": "AIR BAGS", "Summary": "s"}
        )
        assert hit is not None
        assert hit.external_id == "24V001"
        assert hit.external_url == "https://www.nhtsa.gov/recalls?nhtsaId=24V001"
        assert hit.match_confidence == 100
        assert hit_from_nhtsa({"Component": "no number"}) is None


class TestAllowlist:
    def test_only_the_open_data_portal_over_https(self):
        validate_data_economie_url(rappelconso.DEFAULT_API_URL)
        with pytest.raises(SSRFProtectionError):
            validate_data_economie_url("https://example.com/records")
        with pytest.raises((SSRFProtectionError, ValueError)):
            validate_data_economie_url("http://data.economie.gouv.fr/api/records")


def _page(records: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"results": records})
    return response


def _client(pages: list[MagicMock]) -> tuple[Any, AsyncMock]:
    instance = AsyncMock()
    instance.get = AsyncMock(side_effect=pages)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    return patch("httpx.AsyncClient", return_value=instance), instance.get


@pytest.mark.asyncio
class TestFetch:
    async def test_fetches_the_make_and_keeps_the_matches_at_60_or_more(self, db_session):
        rappelconso.clear_cache()
        patcher, get = _client([_page([ZOE_RECORD, CLIO_RECORD, RECORD_3008])])
        with patcher:
            hits = await RappelConsoProvider().fetch(db_session, _vehicle())
        assert [h.external_id for h in hits] == ["2024-03-0123"]
        url = get.call_args.args[0]
        assert url == rappelconso.DEFAULT_API_URL
        params = get.call_args.kwargs["params"]
        assert (
            params["where"]
            == 'categorie_produit like "Automobiles" and marque_produit like "renault"'
        )
        assert params["limit"] == rappelconso.PAGE_SIZE

    async def test_a_notice_outside_the_dates_is_not_stored(self, db_session):
        rappelconso.clear_cache()
        patcher, _get = _client([_page([ZOE_RECORD])])
        with patcher:
            hits = await RappelConsoProvider().fetch(
                db_session, _vehicle(first_registration_date=date(2023, 5, 1))
            )
        assert hits == []

    async def test_pages_until_a_short_page_and_caches_per_make(self, db_session):
        rappelconso.clear_cache()
        full = [dict(ZOE_RECORD, numero_fiche=f"id-{n}") for n in range(rappelconso.PAGE_SIZE)]
        patcher, get = _client([_page(full), _page([CLIO_RECORD])])
        with patcher:
            provider = RappelConsoProvider()
            first = await provider.fetch(db_session, _vehicle())
            second = await provider.fetch(db_session, _vehicle(model="Clio"))
        assert len(first) == rappelconso.PAGE_SIZE
        assert [h.external_id for h in second] == ["2023-11-0456"]
        # Two pages for the first fetch, none for the second: the make is cached.
        assert get.await_count == 2
        assert get.call_args_list[1].kwargs["params"]["offset"] == rappelconso.PAGE_SIZE

    async def test_citroen_asks_for_ds_too(self, db_session):
        rappelconso.clear_cache()
        patcher, get = _client([_page([]), _page([])])
        with patcher:
            await RappelConsoProvider().fetch(db_session, _vehicle(make="Citroën", model="C3"))
        wheres = [call.kwargs["params"]["where"] for call in get.call_args_list]
        assert wheres == [
            'categorie_produit like "Automobiles" and marque_produit like "citroen"',
            'categorie_produit like "Automobiles" and marque_produit like "ds"',
        ]

    async def test_a_refused_url_setting_falls_back_to_the_default(self, db_session):
        row = (
            await db_session.execute(
                select(Setting).where(Setting.key == rappelconso.API_URL_SETTING)
            )
        ).scalar_one_or_none()
        before = row.value if row else None
        try:
            if row is None:
                db_session.add(
                    Setting(key=rappelconso.API_URL_SETTING, value="https://evil.example/x")
                )
            else:
                row.value = "https://evil.example/x"
            await db_session.commit()
            assert await RappelConsoProvider().api_url(db_session) == rappelconso.DEFAULT_API_URL
        finally:
            row = (
                await db_session.execute(
                    select(Setting).where(Setting.key == rappelconso.API_URL_SETTING)
                )
            ).scalar_one_or_none()
            if row is not None:
                if before is None:
                    await db_session.delete(row)
                else:
                    row.value = before
            await db_session.commit()


@pytest.mark.asyncio
class TestRegistry:
    async def test_providers_follow_the_profile(self, db_session):
        assert [
            p.name for p in await providers_for(db_session, _vehicle(), profile_for_country("FR"))
        ] == ["rappelconso"]
        assert [p.name for p in await providers_for(db_session, _vehicle(), None)] == ["nhtsa"]
        assert await providers_for(db_session, _vehicle(), profile_for_country("DE")) == []
