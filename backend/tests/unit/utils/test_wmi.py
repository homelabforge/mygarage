"""The bundled WMI table and its lookups (#211)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.constants.countries import ISO_3166_ALPHA2
from app.utils import wmi

DATA = Path(wmi.__file__).resolve().parent.parent / "data" / "wmi.json"
_CODE_RE = re.compile(r"^[A-HJ-NPR-Z0-9]+$")


@pytest.fixture(scope="module")
def table() -> dict:
    with DATA.open(encoding="utf-8") as handle:
        return json.load(handle)


class TestData:
    def test_regions_cover_the_six_iso_regions(self, table):
        assert sorted({r["region"] for r in table["regions"]}) == sorted(wmi.REGIONS)
        for entry in table["regions"]:
            assert len(entry["from"]) == 1 and len(entry["to"]) == 1

    def test_country_ranges_are_well_formed_and_iso(self, table):
        for entry in table["countries"]:
            assert len(entry["from"]) == 2 and len(entry["to"]) == 2, entry
            assert _CODE_RE.match(entry["from"]) and _CODE_RE.match(entry["to"]), entry
            assert entry["country"] in ISO_3166_ALPHA2, entry
            assert wmi._rank(entry["from"]) <= wmi._rank(entry["to"]), entry

    def test_wmis_are_unique_three_character_codes_with_iso_countries(self, table):
        codes = list(table["wmi"])
        assert len(codes) == len(set(codes))
        assert len(codes) >= 150
        for code, entry in table["wmi"].items():
            assert len(code) == 3 and _CODE_RE.match(code), code
            assert entry["make"], code
            assert entry["country"] in ISO_3166_ALPHA2, code
            assert isinstance(entry.get("uses_model_year", False), bool), code
            # The WMI's country agrees with the ISO block its first two
            # characters fall in, except the assignments known to sit outside
            # their block (Opel's VXK is French; VX–V2 is Serbia's block).
            if code not in {"VXK"}:
                assert wmi.range_country(code[:2]) == entry["country"], code

    def test_a_source_is_cited(self, table):
        assert "ISO 3780" in table["_comment"] and "retrieved" in table["_comment"]


class TestLookups:
    @pytest.mark.parametrize(
        ("vin", "region", "country"),
        [
            ("VF1RFB00X56123456", "EU", "FR"),
            ("WVWZZZAUZLW123456", "EU", "DE"),
            ("W0LZZZ00000000000", "EU", "DE"),
            ("ZAR00000000000000", "EU", "IT"),
            ("Z3A00000000000000", "EU", "SI"),
            ("XX100000000000000", "EU", "LU"),
            ("U5Y00000000000000", "EU", "SK"),
            ("1HGBH41JXMN109186", "NA", "US"),
            ("40A00000000000000", "NA", "US"),
            ("7SAYGDEE0PF000000", "NA", "US"),  # Tesla's newer prefix under « 7 »
            ("3VW00000000000000", "NA", "MX"),
            ("JHM00000000000000", "AS", "JP"),
            ("KMH00000000000000", "AS", "KR"),
            ("LFV00000000000000", "AS", "CN"),
            ("6FP00000000000000", "OC", "AU"),
            ("9BW00000000000000", "SA", "BR"),
            ("93Y00000000000000", "SA", "BR"),
            ("AA000000000000000", "AF", "ZA"),
        ],
    )
    def test_region_and_country(self, vin, region, country):
        assert wmi.region_of(vin) == region
        assert wmi.country_of(vin) == country

    def test_unknown_characters_give_nothing(self):
        assert wmi.region_of("") is None
        assert wmi.region_of("I00") is None
        assert wmi.country_of("V") is None
        assert wmi.country_of("VI0") is None
        assert wmi.lookup("ZZZ00000000000000") is None

    def test_renault_volkswagen_honda(self):
        renault = wmi.lookup("vf1rfb00x56123456")
        assert renault == wmi.WMIInfo("VF1", "Renault", "Renault", "FR", False)
        volkswagen = wmi.lookup("WVWZZZAUZLW123456")
        assert volkswagen is not None
        assert (volkswagen.make, volkswagen.country, volkswagen.uses_model_year) == (
            "Volkswagen",
            "DE",
            True,
        )
        honda = wmi.lookup("1HGBH41JXMN109186")
        assert honda is not None and honda.make == "Honda" and honda.country == "US"

    def test_model_year_rule(self):
        assert wmi.model_year_applies("1HGBH41JXMN109186")  # North America: always
        assert wmi.model_year_applies("WVWZZZAUZLW123456")  # VW group: flagged
        assert not wmi.model_year_applies("VF1RFB00X56123456")  # Renault: no
        assert not wmi.model_year_applies("ZZZ00000000000000")  # unknown maker outside NA: no
        assert wmi.is_north_american("2HG00000000000000")
        assert not wmi.is_north_american("SAJ00000000000000")
