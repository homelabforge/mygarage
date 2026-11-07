"""AutoRef client (#219 takeover): requests, status mapping, the field mapping, no key leaks.

Fixtures are built from the field names in AutoRef's OpenAPI spec; no live
response has been seen yet (plan Q1), so the fuel and drivetrain words here
are the spec's examples and English guesses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.services.autoref import (
    BASE_URL,
    MAX_CANDIDATES,
    NOTE_AUTOREF_BEST_GUESS,
    NOTE_AUTOREF_EXTERNAL,
    NOTE_AUTOREF_PICK_VERSION,
    AutoRefAuthError,
    AutoRefQuotaError,
    AutoRefService,
    AutoRefUnavailableError,
    agreed_answer,
    candidates_of,
    map_vehicle,
)

KEY = "sk-test-SECRET-1234567890"
VIN = "WAUZZZ8V5KA123456"

ROW: dict[str, Any] = {
    "id": 4242,
    "VIN": "WAUZZZ8V5K",
    "BRAND": "AUDI",
    "BRAND_MODEL": "AUDI A3 1.5 TFSI 5T",
    "MODEL_FULL": "A3 1.5 TFSI 5T",
    "MODEL_RESOLVED": "A3",
    "MODEL_LINE": "A3",
    "MOTORIZATION": "1.5 TFSI 5T",
    "POWER_KW": 110,
    "POWER_DIN": 150,
    "FUEL": "Petrol",
    "GEARBOX": "Automatique",
    "CODE_GEARBOX": "A",
    "DATE_FIRST_CIRCULATION": 2019,
    "RECORD_TYPE": "COC",
    "registrations": 812,
    "configurations": None,
}
DETAIL: dict[str, Any] = {
    "VIN_INFO": {
        "BODY": "Sportback",
        "DOORS": 5,
        "DISPLACEMENT": 1498,
        "CYLINDERS": 4,
        "DRIVETRAIN": "Front-Wheel Drive",
        "CODE_DRIVETRAIN": "V",
        "MANUFACTURER": "AUDI AG",
        "GEARBOX": ["Automatique"],
        "GEARBOX_DETAILS": [
            {
                "code": None,
                "type": "Automatic",
                "description": None,
                "additionnal_mode": None,
                "gears": 7,
            }
        ],
    }
}


# Real answers (probed 2026-11-06/07, nulls trimmed). A 10-character prefix
# matches every version sold under it, most registered first.
GOLF_VIN = "WVWZZZAUZFW806653"
GOLF_ROWS: list[dict[str, Any]] = [
    {
        "id": 310899,
        "VIN": "WVWZZZAUZF",
        "BRAND": "VW",
        "BRAND_MODEL": "VW GOLF VII R 5T",
        "MODEL_FULL": "Golf VII R 5T",
        "MODEL_RESOLVED": "Golf",
        "MODEL_LINE": "Golf",
        "MOTORIZATION": "VII R 5T",
        "POWER_KW": 221.0,
        "POWER_DIN": 300.0,
        "FUEL": "Gasoline",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2015,
        "RECORD_TYPE": "TG",
        "registrations": 16,
        "configurations": None,
    },
    {
        "id": 310894,
        "VIN": "WVWZZZAUZF",
        "BRAND": "VW",
        "BRAND_MODEL": "VW GOLF VII 1.4TSI 5",
        "MODEL_FULL": "Golf VII 1.4TSI 5",
        "MODEL_RESOLVED": "Golf",
        "MODEL_LINE": "Golf",
        "MOTORIZATION": "VII 1.4TSI 5",
        "POWER_KW": 90.0,
        "POWER_DIN": 122.0,
        "FUEL": "Gasoline",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2014,
        "RECORD_TYPE": "TG",
        "registrations": 13,
        "configurations": None,
    },
    {
        "id": 311017,
        "VIN": "WVWZZZAUZF",
        "BRAND": "VW",
        "BRAND_MODEL": "VW GOLF VII GTE",
        "MODEL_FULL": "Golf VII GTE",
        "MODEL_RESOLVED": "Golf",
        "MODEL_LINE": "Golf",
        "MOTORIZATION": "VII GTE",
        "POWER_KW": 110.0,
        "POWER_DIN": 150.0,
        "FUEL": "Gasoline / Electric",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2015,
        "RECORD_TYPE": "TG",
        "registrations": 9,
        "configurations": None,
    },
    {
        "id": 311026,
        "VIN": "WVWZZZAUZF",
        "BRAND": "VW",
        "BRAND_MODEL": "VW E-GOLF",
        "MODEL_FULL": "e-Golf",
        "MODEL_RESOLVED": "e-Golf",
        "MODEL_LINE": "e-Golf",
        "MOTORIZATION": None,
        "POWER_KW": 85.0,
        "POWER_DIN": 116.0,
        "FUEL": "Electric",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2015,
        "RECORD_TYPE": "TG",
        "registrations": 3,
        "configurations": None,
    },
]
GOLF_R_RECORD: dict[str, Any] = {
    "VIN_INFO": {
        "id": 310899,
        "VIN": "WVWZZZAUZF",
        "BRAND": "VW",
        "BRAND_MODEL": "VW GOLF VII R 5T",
        "POWER_KW": 221.0,
        "POWER_DIN": 300.0,
        "GEARBOX": ["Manual"],
        "GEARBOX_DETAILS": [
            {
                "code": None,
                "type": "Manual",
                "description": None,
                "additionnal_mode": "A",
                "gears": 6,
            }
        ],
        "MODEL_FULL": "Golf VII R 5T",
        "MODEL_RESOLVED": "Golf",
        "MOTORIZATION": "VII R 5T",
        "MODEL_LINE": "Golf",
        "BODY": "Limousine",
        "DOORS": None,
        "DISPLACEMENT": 1984,
        "CYLINDERS": 4,
        "MANUFACTURER": None,
        "CODE_FUEL": "B",
        "FUEL": "Gasoline",
        "SECOND_FUEL": None,
        "TYPE_HYBRID": "",
        "ELECTRIC_RANGE_MIN_MAX": None,
        "CODE_DRIVETRAIN": "A",
        "DRIVETRAIN": "Front",
        "DATE_FIRST_CIRCULATION": "2015-01-01",
    }
}
COROLLA_VIN = "SB1Z93BE30E164504"
COROLLA_ROWS: list[dict[str, Any]] = [
    {
        "id": 289312,
        "VIN": "SB1Z93BE30",
        "BRAND": "TOYOTA",
        "BRAND_MODEL": "TOYOTA COROLLA 1.8HYBRID",
        "MODEL_FULL": "Corolla 1.8Hybrid",
        "MODEL_RESOLVED": "Corolla",
        "MODEL_LINE": "Corolla",
        "MOTORIZATION": "1.8Hybrid",
        "POWER_KW": 72.0,
        "POWER_DIN": 98.0,
        "FUEL": "Gasoline / Electric",
        "GEARBOX": "Continuously Variable",
        "CODE_GEARBOX": "S",
        "DATE_FIRST_CIRCULATION": 2020,
        "RECORD_TYPE": "TG",
        "registrations": 28,
        "configurations": None,
    },
    {
        "id": 289316,
        "VIN": "SB1Z93BE30",
        "BRAND": "TOYOTA",
        "BRAND_MODEL": "TOYOTA COROLLA 1.8 HYBRID",
        "MODEL_FULL": "Corolla 1.8 Hybrid",
        "MODEL_RESOLVED": "Corolla",
        "MODEL_LINE": "Corolla",
        "MOTORIZATION": "1.8 Hybrid",
        "POWER_KW": 72.0,
        "POWER_DIN": 98.0,
        "FUEL": "Gasoline / Electric",
        "GEARBOX": "Continuously Variable",
        "CODE_GEARBOX": "S",
        "DATE_FIRST_CIRCULATION": 2022,
        "RECORD_TYPE": "TG",
        "registrations": 1,
        "configurations": None,
    },
]
YARIS_VIN = "VNKKH963X0A127993"
YARIS_ROWS: list[dict[str, Any]] = [
    {
        "id": 292184,
        "VIN": "VNKKH963X0",
        "BRAND": "TOYOTA",
        "BRAND_MODEL": "TOYOTA YARIS 1.33",
        "MODEL_FULL": "Yaris 1.33",
        "MODEL_RESOLVED": "Yaris",
        "MODEL_LINE": "Yaris",
        "MOTORIZATION": "1.33",
        "POWER_KW": 74.0,
        "POWER_DIN": 101.0,
        "FUEL": "Gasoline",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2009,
        "RECORD_TYPE": "TG",
        "registrations": 4,
        "configurations": None,
    },
    {
        "id": 120375,
        "VIN": "VNKKH963X0",
        "BRAND": "DAIHATSU",
        "BRAND_MODEL": "DAIHATSU CHARADE",
        "MODEL_FULL": "Charade",
        "MODEL_RESOLVED": "Charade",
        "MODEL_LINE": "Charade",
        "MOTORIZATION": None,
        "POWER_KW": 73.0,
        "POWER_DIN": 99.0,
        "FUEL": "Gasoline",
        "GEARBOX": "Manual",
        "CODE_GEARBOX": "M",
        "DATE_FIRST_CIRCULATION": 2011,
        "RECORD_TYPE": "TG",
        "registrations": 1,
        "configurations": None,
    },
]


@pytest.fixture
def httpx_at_info() -> Iterator[None]:
    """httpx's own logger at INFO, where it prints request URLs, then put back.

    Pinned here so the leak tests don't depend on whether ``app.main`` (which
    turns it down) was imported first (Fable F-8), and restored so the rest of
    the suite sees the level ``app.main`` set.
    """
    httpx_logger = logging.getLogger("httpx")
    before = httpx_logger.level
    httpx_logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        httpx_logger.setLevel(before)


def _service(handler: Callable[[httpx.Request], httpx.Response], key: str = KEY) -> AutoRefService:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)

    return AutoRefService(key, client_factory=factory)


def _routes(seen: list[httpx.Request], **by_path: httpx.Response) -> Callable:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for prefix, response in by_path.items():
            if request.url.path.startswith(prefix.replace("__", "/")):
                return response
        return httpx.Response(404, json={"detail": "Not found"})

    return handler


@pytest.mark.unit
@pytest.mark.asyncio
class TestDecodeRequests:
    async def test_full_vin_lang_group_and_header(self):
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, __vehicles__=httpx.Response(200, json=[ROW]),
                    __vehicle__=httpx.Response(200, json=DETAIL))
        )  # fmt: skip
        await service.decode(VIN)

        first = seen[0]
        assert first.url.path == f"/vehicles/{VIN}"
        assert first.url.params["lang"] == "en"
        assert first.url.params["group"] == "car"
        assert first.headers["x-api-key"] == KEY
        assert KEY not in str(first.url)

    async def test_second_call_fetches_the_full_record(self):
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, __vehicles__=httpx.Response(200, json=[ROW]),
                    __vehicle__=httpx.Response(200, json=DETAIL))
        )  # fmt: skip
        result = await service.decode(VIN)

        assert [r.url.path for r in seen] == [f"/vehicles/{VIN}", "/vehicle/COC/4242"]
        assert KEY not in str(seen[1].url)
        assert result is not None
        assert result["doors"] == 5
        assert result["body_class"] == "Sportback"

    async def test_grouped_row_without_id_uses_the_first_configuration(self):
        # Fable F-18: under group=car a collapsed row can carry a null id.
        row = {**ROW, "id": None, "configurations": [{"id": 77, "registrations": 500}]}
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, __vehicles__=httpx.Response(200, json=[row]),
                    __vehicle__=httpx.Response(200, json=DETAIL))
        )  # fmt: skip
        await service.decode(VIN)
        assert seen[1].url.path == "/vehicle/COC/77"

    @pytest.mark.parametrize("record_type", ["UK", "US"])
    async def test_no_second_call_for_an_external_record(self, record_type):
        seen: list[httpx.Request] = []
        row = {**ROW, "RECORD_TYPE": record_type}
        service = _service(_routes(seen, __vehicles__=httpx.Response(200, json=[row])))
        result = await service.decode(VIN)
        assert len(seen) == 1
        assert result is not None
        assert NOTE_AUTOREF_EXTERNAL in result["notes"]

    async def test_no_second_call_without_any_id(self):
        seen: list[httpx.Request] = []
        row = {**ROW, "id": None, "configurations": None}
        service = _service(_routes(seen, __vehicles__=httpx.Response(200, json=[row])))
        await service.decode(VIN)
        assert len(seen) == 1

    async def test_a_failed_second_call_keeps_the_first_answer(self):
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, __vehicles__=httpx.Response(200, json=[ROW]),
                    __vehicle__=httpx.Response(500, text="boom"))
        )  # fmt: skip
        result = await service.decode(VIN)
        assert result is not None
        assert result["make"] == "Audi"

    @pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, json=[])])
    async def test_no_match_is_none(self, response):
        service = _service(lambda request: response)
        assert await service.decode(VIN) is None

    async def test_a_malformed_vin_is_refused_before_any_request(self):
        seen: list[httpx.Request] = []
        service = _service(_routes(seen))
        with pytest.raises(ValueError):
            await service.decode("WAU/../../usage?x")
        assert seen == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestStatusMapping:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth(self, status):
        service = _service(lambda request: httpx.Response(status))
        with pytest.raises(AutoRefAuthError):
            await service.decode(VIN)

    async def test_quota(self):
        service = _service(lambda request: httpx.Response(429))
        with pytest.raises(AutoRefQuotaError):
            await service.decode(VIN)

    @pytest.mark.parametrize("status", [500, 502, 503, 400])
    async def test_other_statuses_are_unavailable_with_the_status(self, status):
        service = _service(lambda request: httpx.Response(status))
        with pytest.raises(AutoRefUnavailableError) as caught:
            await service.decode(VIN)
        assert caught.value.status == status
        assert caught.value.timed_out is False

    async def test_a_body_that_is_not_json_is_unavailable(self):
        service = _service(lambda request: httpx.Response(200, text="<html>maintenance</html>"))
        with pytest.raises(AutoRefUnavailableError):
            await service.decode(VIN)

    async def test_timeout(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(AutoRefUnavailableError) as caught:
            await _service(handler).decode(VIN)
        assert caught.value.timed_out is True
        assert caught.value.status is None

    async def test_connect_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with pytest.raises(AutoRefUnavailableError) as caught:
            await _service(handler).decode(VIN)
        assert caught.value.timed_out is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestUsage:
    async def test_reads_the_plan(self):
        seen: list[httpx.Request] = []
        body = {
            "plan": "Test",
            "limit": 50,
            "used": 4,
            "remaining": 46,
            "reset_date": "2026-12-01T00:00:00",
        }
        service = _service(_routes(seen, __usage=httpx.Response(200, json=body)))
        usage = await service.usage()
        assert (usage.plan, usage.limit, usage.used, usage.remaining) == ("Test", 50, 4, 46)
        assert usage.reset_date == "2026-12-01T00:00:00"
        assert seen[0].url.params["api_key"] == KEY

    async def test_an_explicit_key_is_tested_instead_of_the_stored_one(self):
        seen: list[httpx.Request] = []
        service = _service(_routes(seen, __usage=httpx.Response(200, json={"plan": "Test"})))
        await service.usage("other-key")
        assert seen[0].url.params["api_key"] == "other-key"

    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_rejected_key(self, status):
        service = _service(lambda request: httpx.Response(status))
        with pytest.raises(AutoRefAuthError):
            await service.usage()


@pytest.mark.unit
@pytest.mark.asyncio
class TestTheKeyNeverLeaks:
    """Fable F-7/F-8: the /usage URL carries the key, so no error or log line may hold it."""

    @staticmethod
    def _chain(exc: BaseException) -> list[BaseException]:
        out: list[BaseException] = []
        current: BaseException | None = exc
        while current is not None and current not in out:
            out.append(current)
            current = current.__cause__ or current.__context__
        return out

    @pytest.mark.parametrize("status", [403, 503])
    async def test_usage_errors_hold_no_key(self, status, caplog, httpx_at_info):
        caplog.set_level(logging.DEBUG)
        service = _service(lambda request: httpx.Response(status, text=f"bad key {KEY}"))
        with pytest.raises((AutoRefAuthError, AutoRefUnavailableError)) as caught:
            await service.usage()
        for exc in self._chain(caught.value):
            assert KEY not in str(exc)
            assert KEY not in repr(exc)
        assert len(self._chain(caught.value)) == 1
        for record in caplog.records:
            assert KEY not in record.getMessage()

    async def test_transport_errors_hold_no_key(self, caplog, httpx_at_info):
        caplog.set_level(logging.DEBUG)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"refused {request.url}", request=request)

        with pytest.raises(AutoRefUnavailableError) as caught:
            await _service(handler).usage()
        assert len(self._chain(caught.value)) == 1
        assert KEY not in str(caught.value)
        for record in caplog.records:
            assert KEY not in record.getMessage()

    async def test_a_decode_logs_no_key(self, caplog, httpx_at_info):
        caplog.set_level(logging.DEBUG)
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, __vehicles__=httpx.Response(200, json=[ROW]),
                    __vehicle__=httpx.Response(200, json=DETAIL))
        )  # fmt: skip
        await service.decode(VIN)
        for record in caplog.records:
            assert KEY not in record.getMessage()

    async def test_a_version_lookup_logs_no_key(self, caplog, httpx_at_info):
        caplog.set_level(logging.DEBUG)
        seen: list[httpx.Request] = []
        service = _service(_routes(seen, __vehicle__=httpx.Response(200, json=GOLF_R_RECORD)))
        await service.decode_version(
            GOLF_VIN, "TG", "310899", gearbox_code="M", expect_model="Golf VII R 5T",
            expect_kw=221, grouped=False,
        )  # fmt: skip
        assert seen
        for record in caplog.records:
            assert KEY not in record.getMessage()

    @pytest.mark.parametrize("bad", ["sk-clé-SECRET-1234", "sk SECRET 1234", "sk-SECRET\n1234"])
    @pytest.mark.parametrize("call", ["decode", "usage", "decode_version"])
    async def test_a_malformed_key_is_rejected_before_any_request(self, bad, call):
        # Codex diff R1-M2: httpx encodes headers as ASCII, so a non-ASCII
        # key raised UnicodeEncodeError (a ValueError, read as a bad VIN)
        # holding the whole key. It reads as a rejected key, sends nothing,
        # and no exception in the chain carries it.
        seen: list[httpx.Request] = []
        service = _service(_routes(seen), key=bad)
        calls = {
            "decode": lambda: service.decode(VIN),
            "usage": lambda: service.usage(),
            "decode_version": lambda: service.decode_version(
                VIN, "TG", "1", gearbox_code="M", expect_model="x", expect_kw=None, grouped=False
            ),
        }
        with pytest.raises(AutoRefAuthError) as caught:
            await calls[call]()
        assert seen == []
        assert caught.value.status is None
        for exc in self._chain(caught.value):
            assert bad not in str(exc)
            assert bad not in repr(exc)
            assert "SECRET" not in repr(getattr(exc, "args", ()))

    async def test_a_malformed_key_given_to_usage_is_rejected_too(self):
        seen: list[httpx.Request] = []
        with pytest.raises(AutoRefAuthError):
            await _service(_routes(seen)).usage("sk-clé-SECRET")
        assert seen == []

    async def test_auth_failures_log_a_warning_with_the_status(self, caplog):
        caplog.set_level(logging.WARNING, logger="app.services.autoref")
        service = _service(lambda request: httpx.Response(403))
        with pytest.raises(AutoRefAuthError):
            await service.decode(VIN)
        warnings = [r for r in caplog.records if r.name == "app.services.autoref"]
        assert warnings and "403" in warnings[0].getMessage()


@pytest.mark.unit
class TestMapping:
    def test_maps_a_local_record(self):
        result = map_vehicle(VIN, ROW, DETAIL["VIN_INFO"])
        assert result["make"] == "Audi"
        assert result["model"] == "A3"
        assert result["trim"] == "1.5 TFSI 5T"
        assert result["year"] is None
        engine = result["engine"]
        assert engine["kw"] == 110
        assert engine["hp"] == 148  # from kW, not POWER_DIN's metric 150
        assert engine["displacement_l"] == "1.5"
        assert engine["cylinders"] == 4
        assert engine["fuel_type"] == "Petrol"
        assert engine["fuel_type_normalized"] == "gasoline"
        assert result["transmission"] == {"type": "Automatic", "speeds": "7"}
        assert result["drive_type"] == "FWD"
        assert result["doors"] == 5
        assert result["manufacturer"] == "AUDI AG"
        assert result["notes"] == []

    def test_the_year_never_comes_from_first_circulation(self):
        assert map_vehicle(VIN, ROW, {})["year"] is None

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("M", "Manual"),
            ("A", "Automatic"),
            ("S", "Continuously Variable Transmission (CVT)"),
            ("H", "Hydrostatic"),
            ("h", "Hydrostatic"),
            ("X", None),
            (None, None),
        ],
    )
    def test_gearbox_code(self, code, expected):
        row = {**ROW, "CODE_GEARBOX": code}
        assert map_vehicle(VIN, row, {})["transmission"]["type"] == expected

    @pytest.mark.parametrize(
        "words,expected",
        [
            ("Front-wheel drive", "FWD"),
            ("Rear-wheel drive", "RWD"),
            ("All-wheel drive", "AWD"),
            ("4x4", "4WD"),
            ("Traction avant", "FWD"),
            ("Propulsion", "RWD"),
            ("Something else", None),
        ],
    )
    def test_drive_type_is_never_a_raw_string(self, words, expected):
        detail = {"DRIVETRAIN": words, "CODE_DRIVETRAIN": None}
        assert map_vehicle(VIN, ROW, detail)["drive_type"] == expected

    # Live decodes, 2026-11-06 (plan Q1). The codes are the Swiss type
    # approval's German ones: a Golf read V "Front-Wheel Drive", a Porsche
    # Macan (all-wheel drive, every one of them) read A, with the words
    # "Front", as if A were French "avant". So the code wins over the words.
    # H (Hinterrad) wasn't in a sample; it's the third letter of the same set.
    @pytest.mark.parametrize(
        "code,words,expected",
        [
            ("A", "Front", "AWD"),
            ("V", "Front-Wheel Drive", "FWD"),
            ("H", None, "RWD"),
            ("v", None, "FWD"),
            ("Z", "Rear-wheel drive", "RWD"),
        ],
    )
    def test_the_drivetrain_code_wins_over_the_words(self, code, words, expected):
        detail = {"CODE_DRIVETRAIN": code, "DRIVETRAIN": words}
        assert map_vehicle(VIN, ROW, detail)["drive_type"] == expected

    def test_a_manual_with_an_automatic_mode_reads_automated_manual(self):
        # The Macan's PDK: CODE_GEARBOX M, with additionnal_mode A and 7 gears.
        row = {**ROW, "CODE_GEARBOX": "M", "GEARBOX": "Manual"}
        detail = {"GEARBOX_DETAILS": [{"code": None, "type": "Manual", "description": None,
                                       "additionnal_mode": "A", "gears": 7}]}  # fmt: skip
        assert map_vehicle(VIN, row, detail)["transmission"] == {
            "type": "Automated Manual",
            "speeds": "7",
        }

    def test_a_plain_manual_stays_manual(self):
        row = {**ROW, "CODE_GEARBOX": "M"}
        detail = {"GEARBOX_DETAILS": [{"type": "Manual", "additionnal_mode": None, "gears": 6}]}
        assert map_vehicle(VIN, row, detail)["transmission"] == {
            "type": "Manual",
            "speeds": "6",
        }

    @pytest.mark.parametrize(
        "details",
        [None, [], "7", [None], [{"gears": None}], [{"gears": "7"}], [{"gears": True}],
         [{"gears": 0}], [{"gears": 40}]],
    )  # fmt: skip
    def test_gears_that_are_not_a_gear_count_read_as_missing(self, details):
        detail = {"GEARBOX_DETAILS": details}
        assert map_vehicle(VIN, ROW, detail)["transmission"]["speeds"] is None

    def test_s_is_a_cvt_whatever_its_words_say(self):
        # AutoRef support (2026-11-07): S is CVT only; the docs' "Semi-auto/CVT"
        # was wrong. The Corolla's S also came with "Semi-automatic" words.
        row = {**ROW, "CODE_GEARBOX": "S", "GEARBOX": "Semi-automatic"}
        detail = {"GEARBOX": ["Semi-automatic"]}
        assert map_vehicle(VIN, row, detail)["transmission"]["type"] == (
            "Continuously Variable Transmission (CVT)"
        )

    def test_the_words_alone_never_make_a_cvt(self):
        row = {**ROW, "CODE_GEARBOX": "A", "GEARBOX": "Continuously Variable"}
        assert map_vehicle(VIN, row, {})["transmission"]["type"] == "Automatic"

    def test_a_cvt_hybrid_reads_cvt_and_hybrid(self):
        # A 2020 Corolla 1.8 Hybrid as AutoRef answered it (live decode
        # 2026-11-06): CODE_GEARBOX S, FUEL "Gasoline / Electric", and
        # TYPE_HYBRID blank even though it's a hybrid.
        row = {
            **ROW,
            "CODE_GEARBOX": "S",
            "GEARBOX": "Continuously Variable",
            "FUEL": "Gasoline / Electric",
        }
        detail = {
            "FUEL": "Gasoline / Electric",
            "CODE_FUEL": "C",
            "TYPE_HYBRID": "",
            "GEARBOX_DETAILS": [
                {
                    "code": None,
                    "type": "Semi-automatic (gear shift)",
                    "description": None,
                    "additionnal_mode": None,
                    "gears": None,
                }
            ],
        }
        result = map_vehicle(VIN, row, detail)
        assert result["transmission"] == {
            "type": "Continuously Variable Transmission (CVT)",
            "speeds": None,
        }
        engine = result["engine"]
        assert engine["fuel_type"] == "Gasoline / Electric"
        assert engine["fuel_type_normalized"] == "hybrid"
        assert engine["fuel_type_secondary"] == "electric"

    @pytest.mark.parametrize(
        "fuel,expected",
        [
            ("Gasoline / Electric", ("hybrid", "electric")),
            ("Diesel / Electric", ("hybrid", "electric")),
            ("Electric / Gasoline", ("hybrid", "electric")),
            ("gasoline/electric", ("hybrid", "electric")),
            ("Electric", ("electric", None)),
            ("Gasoline", ("gasoline", None)),
            ("Compressed Natural Gas (CNG) / Gasoline", (None, None)),
            ("Electric / Electric", (None, None)),
            ("Unobtainium / Electric", (None, None)),
        ],
    )  # fmt: skip
    def test_a_fuel_paired_with_electric_reads_hybrid(self, fuel, expected):
        row = {**ROW, "FUEL": fuel}
        engine = map_vehicle(VIN, row, {})["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == expected

    def test_a_second_fuel_autoref_names_wins_over_electric(self):
        row = {**ROW, "FUEL": "Gasoline / Electric"}
        engine = map_vehicle(VIN, row, {"SECOND_FUEL": "Diesel"})["engine"]
        assert engine["fuel_type_normalized"] == "hybrid"
        assert engine["fuel_type_secondary"] == "diesel"

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("B", ("gasoline", None)),
            ("D", ("diesel", None)),
            ("C", ("hybrid", "electric")),
            ("F", ("hybrid", "electric")),
            ("E", ("electric", None)),
            ("R", ("electric", "gasoline")),
            ("X", ("hydrogen", None)),
            ("N", ("cng", None)),
            ("Y", ("gasoline", "cng")),
            ("L", ("propane_lpg", None)),
            ("Z", ("gasoline", "propane_lpg")),
            ("K", ("e85", "gasoline")),
            ("J", ("e85", None)),
            ("d", ("diesel", None)),
        ],
    )
    def test_the_fuel_code_decides_the_fuel(self, code, expected):
        # AutoRef's CODE_FUEL list (support, 2026-11-07). FUEL holds words
        # no rule reads, so only the code can give the answer.
        row = {**ROW, "FUEL": "Treibstoff"}
        engine = map_vehicle(VIN, row, {"CODE_FUEL": code})["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == expected

    def test_the_fuel_code_wins_over_the_words(self):
        row = {**ROW, "FUEL": "Gasoline"}
        engine = map_vehicle(VIN, row, {"CODE_FUEL": "D"})["engine"]
        assert engine["fuel_type_normalized"] == "diesel"

    @pytest.mark.parametrize("code", ["M", "P", "Q", ""])
    def test_a_fuel_code_without_a_match_falls_back_to_the_words(self, code):
        row = {**ROW, "FUEL": "Gasoline"}
        engine = map_vehicle(VIN, row, {"CODE_FUEL": code})["engine"]
        assert engine["fuel_type_normalized"] == "gasoline"

    @pytest.mark.parametrize(
        "code,extra,expected",
        [
            ("C", {"TYPE_HYBRID": "Hybrid electric vehicle with charging station"}, "plugin_hybrid"),
            ("C", {"TYPE_HYBRID": "Plug-in hybrid"}, "plugin_hybrid"),
            ("F", {"TYPE_HYBRID": "plug-in hybrid"}, "plugin_hybrid"),
            ("C", {"ELECTRIC_RANGE_MIN_MAX": "18.6"}, "plugin_hybrid"),
            ("C", {"ELECTRIC_RANGE_MIN_MAX": 18.6}, "plugin_hybrid"),
            ("C", {"TYPE_HYBRID": "", "ELECTRIC_RANGE_MIN_MAX": ""}, "hybrid"),
            ("C", {"ELECTRIC_RANGE_MIN_MAX": 0}, "hybrid"),
            ("C", {"ELECTRIC_RANGE_MIN_MAX": True}, "hybrid"),
            ("C", {"TYPE_HYBRID": "Hybrid electric vehicle without charging station",
                   "ELECTRIC_RANGE_MIN_MAX": "18.6"}, "hybrid"),
            ("C", {"TYPE_HYBRID": "Non-rechargeable hybrid",
                   "ELECTRIC_RANGE_MIN_MAX": "18.6"}, "hybrid"),
            ("B", {"ELECTRIC_RANGE_MIN_MAX": "18.6"}, "gasoline"),
            ("E", {"TYPE_HYBRID": "Plug-in hybrid"}, "electric"),
        ],
    )  # fmt: skip
    def test_a_hybrid_that_plugs_in_reads_plugin_hybrid(self, code, extra, expected):
        # AutoRef support: TYPE_HYBRID says so when it's filled; otherwise
        # only plug-ins have ELECTRIC_RANGE_MIN_MAX (kWh/100 km, a 330e 18.6).
        detail = {"CODE_FUEL": code, **extra}
        engine = map_vehicle(VIN, ROW, detail)["engine"]
        assert engine["fuel_type_normalized"] == expected

    def test_hybrid_words_without_a_code_still_see_a_plug_in(self):
        row = {**ROW, "FUEL": "Gasoline / Electric"}
        detail = {"TYPE_HYBRID": "Plug-in hybrid"}
        engine = map_vehicle(VIN, row, detail)["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == (
            "plugin_hybrid",
            "electric",
        )

    @pytest.mark.parametrize(
        "code,fuel,type_hybrid,expected",
        [
            ("", "Gasoline", "Plug-in hybrid", ("plugin_hybrid", "electric")),
            ("", "Diesel", "Hybrid electric vehicle with charging station", ("plugin_hybrid", "electric")),
            ("", "Gasoline", "Non-rechargeable hybrid", ("hybrid", "electric")),
            ("", "Gasoline", "Hybrid electric vehicle without charging station", ("hybrid", "electric")),
            ("B", "Treibstoff", "Plug-in hybrid", ("plugin_hybrid", "electric")),
            ("D", "Treibstoff", "Non-rechargeable hybrid", ("hybrid", "electric")),
            ("Z", "Treibstoff", "Non-rechargeable hybrid", ("hybrid", "propane_lpg")),
            ("", "Gasoline", "Fuel Cell Hybrid Vehicle without Charging Station", ("gasoline", None)),
            ("", "Gasoline", "", ("gasoline", None)),
        ],
    )  # fmt: skip
    def test_a_stated_hybrid_type_turns_plain_fuel_into_a_hybrid(
        self, code, fuel, type_hybrid, expected
    ):
        # A real 330e (WBA8E1C56JA756703) and i3 REx come back as FUEL
        # "Gasoline", no CODE_FUEL, and TYPE_HYBRID "Plug-in hybrid".
        row = {**ROW, "FUEL": fuel}
        detail = {"CODE_FUEL": code, "TYPE_HYBRID": type_hybrid}
        engine = map_vehicle(VIN, row, detail)["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == expected

    def test_a_second_fuel_autoref_names_wins_over_the_code(self):
        row = {**ROW, "FUEL": "Treibstoff"}
        detail = {"CODE_FUEL": "Y", "SECOND_FUEL": "LPG"}
        engine = map_vehicle(VIN, row, detail)["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == (
            "gasoline",
            "propane_lpg",
        )

    def test_best_guess_when_several_configurations(self):
        row = {
            **ROW,
            "configurations": [{"id": 1, "registrations": 3}, {"id": 2, "registrations": 1}],
        }
        assert NOTE_AUTOREF_BEST_GUESS in map_vehicle(VIN, row, {})["notes"]

    def test_an_external_record_in_capitals_reads_title_case(self):
        row = {"id": None, "VIN": VIN, "BRAND": "MASERATI", "BRAND_MODEL": "MASERATI LEVANTE D V6 AUTO",
               "MODEL_FULL": "LEVANTE D V6 AUTO", "RECORD_TYPE": "UK"}  # fmt: skip
        result = map_vehicle(VIN, row, {})
        assert result["make"] == "Maserati"
        assert result["model"] == "Levante D V6 Auto"
        assert NOTE_AUTOREF_EXTERNAL in result["notes"]

    def test_the_brand_picks_the_model_spelling(self):
        # Fable fix-wave F-1: a Mini One, not the Mercedes-AMG ONE.
        row = {**ROW, "BRAND": "MINI", "MODEL_RESOLVED": "ONE"}
        assert map_vehicle(VIN, row, {})["model"] == "One"

    @pytest.mark.parametrize("field", ["POWER_KW", "DISPLACEMENT", "DOORS", "CYLINDERS"])
    def test_wrong_types_read_as_missing(self, field):
        row = {**ROW, field: "n/a"}
        detail = {**DETAIL["VIN_INFO"], field: "n/a"}
        result = map_vehicle(VIN, row, detail)
        assert result["make"] == "Audi"


GTE_ID = "311017"


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeveralMatches:
    """A VIN prefix that matches several versions fills only what they share."""

    async def test_several_rows_skip_the_full_record(self):
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, **{f"/vehicles/{GOLF_VIN}": httpx.Response(200, json=GOLF_ROWS)})
        )
        result = await service.decode(GOLF_VIN)
        assert [r.url.path for r in seen] == [f"/vehicles/{GOLF_VIN}"]
        assert result is not None
        assert result["notes"] == [NOTE_AUTOREF_PICK_VERSION]
        assert [c["id"] for c in result["candidates"]] == ["310899", "310894", GTE_ID, "311026"]

    async def test_only_fields_every_row_agrees_on_are_filled(self):
        three = [GOLF_ROWS[0], GOLF_ROWS[1], GOLF_ROWS[2]]  # R, 1.4TSI, GTE
        a = agreed_answer(GOLF_VIN, three)
        assert (a["make"], a["model"]) == ("Volkswagen", "Golf")
        assert a["transmission"]["type"] == "Manual"
        assert a["trim"] is None
        assert a["engine"]["fuel_type"] is None  # "Gasoline" vs "Gasoline / Electric"
        assert a["engine"]["kw"] is None and a["engine"]["hp"] is None
        assert a["engine"]["fuel_type_normalized"] is None
        assert a["engine"]["fuel_type_secondary"] is None
        # body, drive and displacement aren't asserted: rows carry none, so
        # they'd pass without any agreement logic (F-8)
        assert a["year"] is None
        assert a["vin"] == GOLF_VIN

    async def test_spacing_and_case_differences_still_agree(self):
        a = agreed_answer(COROLLA_VIN, COROLLA_ROWS)
        assert a["trim"] == "1.8Hybrid"  # the first row's spelling
        assert a["engine"]["kw"] == 72
        assert a["engine"]["fuel_type_normalized"] == "hybrid"
        assert a["transmission"]["type"] == "Continuously Variable Transmission (CVT)"

    async def test_a_row_missing_a_field_is_a_disagreement(self):
        rows = [COROLLA_ROWS[0], {**COROLLA_ROWS[1], "MOTORIZATION": None}]
        assert agreed_answer(COROLLA_VIN, rows)["trim"] is None

    async def test_another_make_blanks_make_and_model(self):
        a = agreed_answer(YARIS_VIN, YARIS_ROWS)
        assert a["make"] is None and a["model"] is None

    async def test_the_e_golf_blanks_the_model(self):
        assert agreed_answer(GOLF_VIN, GOLF_ROWS)["model"] is None

    async def test_candidates_list_every_row_in_order(self):
        c = candidates_of(GOLF_ROWS)
        assert [x["id"] for x in c] == ["310899", "310894", GTE_ID, "311026"]
        assert c[2] == {
            "record_type": "TG",
            "id": GTE_ID,
            "label": "Golf VII GTE",
            "model_full": "Golf VII GTE",
            "fuel_type": "hybrid",
            "kw": 110,
            "transmission": "Manual",
            "gearbox_code": "M",
            "grouped": False,
        }

    async def test_a_row_that_cant_be_checked_is_not_a_candidate(self):
        bare = {**GOLF_ROWS[1], "MODEL_FULL": None, "POWER_KW": None}
        assert [x["id"] for x in candidates_of([GOLF_ROWS[0], bare])] == ["310899"]

    async def test_candidates_use_the_first_configuration_when_the_row_has_no_id(self):
        row = {**GOLF_ROWS[0], "id": None, "RECORD_TYPE": "TG", "configurations": [{"id": 77}]}
        first = candidates_of([row])[0]
        assert (first["record_type"], first["id"]) == ("COC", "77")
        assert first["grouped"] is False

    async def test_a_row_with_several_configurations_is_grouped(self):
        row = {**GOLF_ROWS[0], "configurations": [{"id": 1}, {"id": 2}]}
        assert candidates_of([row])[0]["grouped"] is True

    async def test_rows_without_a_record_are_not_candidates(self):
        us = {**GOLF_ROWS[1], "RECORD_TYPE": "US", "id": None}
        assert [x["id"] for x in candidates_of([GOLF_ROWS[0], us])] == ["310899"]

    async def test_identical_versions_are_listed_once(self):
        twin = {**GOLF_ROWS[0], "id": 999999, "MODEL_FULL": "golf vii r  5t"}
        ids = [x["id"] for x in candidates_of([GOLF_ROWS[0], twin, GOLF_ROWS[2]])]
        assert ids == ["310899", GTE_ID]

    async def test_rows_that_are_one_version_decode_as_one(self):
        seen: list[httpx.Request] = []
        service = _service(
            _routes(seen, **{f"/vehicles/{COROLLA_VIN}": httpx.Response(200, json=COROLLA_ROWS)})
        )
        result = await service.decode(COROLLA_VIN)
        assert [r.url.path for r in seen] == [f"/vehicles/{COROLLA_VIN}", "/vehicle/TG/289312"]
        assert result is not None
        assert "candidates" not in result
        assert result["notes"] == []
        assert result["trim"] == "1.8Hybrid"

    async def test_one_candidate_among_other_rows_is_still_a_best_guess(self):
        us = {**COROLLA_ROWS[0], "RECORD_TYPE": "US", "id": None, "MODEL_FULL": "COROLLA LE"}
        service = _service(
            _routes(
                [], **{f"/vehicles/{COROLLA_VIN}": httpx.Response(200, json=[COROLLA_ROWS[0], us])}
            )
        )
        result = await service.decode(COROLLA_VIN)
        assert result is not None
        assert "candidates" not in result
        assert NOTE_AUTOREF_BEST_GUESS in result["notes"]

    async def test_several_registry_rows_are_still_a_best_guess(self):
        uk = {**ROW, "RECORD_TYPE": "UK", "id": None}
        rows = [uk, {**uk, "MODEL_FULL": "A3 2.0 TDI"}]
        service = _service(_routes([], __vehicles__=httpx.Response(200, json=rows)))
        result = await service.decode(VIN)
        assert result is not None
        assert result["notes"][0] == NOTE_AUTOREF_BEST_GUESS

    async def test_a_power_that_isnt_a_number_reads_as_missing(self):
        assert candidates_of([{**GOLF_ROWS[0], "POWER_KW": "221"}])[0]["kw"] is None

    async def test_candidates_are_capped(self):
        rows = [
            {**GOLF_ROWS[0], "id": 1000 + i, "POWER_KW": 100 + i}
            for i in range(MAX_CANDIDATES + 50)
        ]
        assert len(candidates_of(rows)) == MAX_CANDIDATES

    async def test_label_falls_back_to_brand_model_then_model_and_motorization(self):
        no_full = {**GOLF_ROWS[0], "MODEL_FULL": None}
        assert candidates_of([no_full])[0]["label"] == "VW GOLF VII R 5T"
        neither = {**no_full, "BRAND_MODEL": None}
        assert candidates_of([neither])[0]["label"] == "Golf VII R 5T"


def _version(
    record: Any,
    *,
    record_type: str = "TG",
    record_id: str = "310899",
    expect_model: str | None = "Golf VII R 5T",
    expect_kw: int | None = 221,
    grouped: bool = False,
    seen: list[httpx.Request] | None = None,
) -> Any:
    response = record if isinstance(record, httpx.Response) else httpx.Response(200, json=record)
    service = _service(_routes(seen if seen is not None else [], __vehicle__=response))
    return service.decode_version(
        GOLF_VIN,
        record_type,
        record_id,
        gearbox_code="M",
        expect_model=expect_model,
        expect_kw=expect_kw,
        grouped=grouped,
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestDecodeVersion:
    """A picked version's full record, checked against the VIN and the pick."""

    async def test_fetches_the_record_and_maps_it(self):
        seen: list[httpx.Request] = []
        result = await _version(GOLF_R_RECORD, seen=seen)
        assert [r.url.path for r in seen] == ["/vehicle/TG/310899"]
        assert seen[0].url.params["lang"] == "en"
        assert seen[0].headers["x-api-key"] == KEY
        assert KEY not in str(seen[0].url)
        assert result is not None
        assert result["engine"]["kw"] == 221
        assert result["engine"]["displacement_l"] == "2.0"
        assert result["engine"]["fuel_type_normalized"] == "gasoline"
        assert result["body_class"] == "Limousine"
        assert result["drive_type"] == "AWD"
        # the full record has no CODE_GEARBOX: the pick's "M" plus additionnal_mode A
        assert result["transmission"] == {"type": "Automated Manual", "speeds": "6"}
        assert (result["make"], result["model"], result["trim"]) == (
            "Volkswagen",
            "Golf",
            "VII R 5T",
        )
        assert result["notes"] == []

    async def test_a_record_for_another_vin_is_none(self):
        other = {"VIN_INFO": {**GOLF_R_RECORD["VIN_INFO"], "VIN": "WVWZZZ1KZA"}}
        assert await _version(other) is None

    async def test_a_reassigned_id_with_the_same_prefix_is_none(self):
        # R1-H1: the GTE was picked, but AutoRef rebuilt and its id now holds
        # the R, which shares the prefix. Never the R's specs.
        assert (
            await _version(
                GOLF_R_RECORD, record_id=GTE_ID, expect_model="Golf VII GTE", expect_kw=110
            )
            is None
        )

    async def test_the_power_alone_catches_a_reassigned_id(self):
        assert await _version(GOLF_R_RECORD, expect_model=None, expect_kw=110) is None

    async def test_spacing_and_case_in_the_model_still_match(self):
        assert (
            await _version(GOLF_R_RECORD, expect_model="golf vii  r 5t", expect_kw=221) is not None
        )

    async def test_an_expectation_the_record_lacks_is_none(self):
        bare = {"VIN_INFO": {**GOLF_R_RECORD["VIN_INFO"], "POWER_KW": None}}
        assert await _version(bare, expect_kw=221) is None

    async def test_a_grouped_pick_keeps_the_best_guess_note(self):
        result = await _version(GOLF_R_RECORD, grouped=True)
        assert result is not None
        assert result["notes"] == [NOTE_AUTOREF_BEST_GUESS]

    async def test_a_record_without_a_vin_is_accepted(self):
        no_vin = {"VIN_INFO": {**GOLF_R_RECORD["VIN_INFO"], "VIN": None}}
        assert await _version(no_vin) is not None

    async def test_a_body_without_vin_info_is_none(self):
        assert await _version({"SPECS": {}}) is None

    async def test_404_is_none(self):
        assert await _version(httpx.Response(404)) is None

    async def test_quota_is_the_typed_error(self):
        with pytest.raises(AutoRefQuotaError):
            await _version(httpx.Response(429))

    @pytest.mark.parametrize(
        ("record_type", "record_id", "gearbox", "expect_model", "expect_kw"),
        [
            ("US", "1", "M", "x", None),
            ("TG", "../1", "M", "x", None),
            ("TG", "", "M", "x", None),
            ("TG", "1" * 33, "M", "x", None),
            ("TG", "1", "Q", "x", None),
            ("TG", "1", "M", None, None),
        ],
    )
    async def test_refuses_a_bad_record_before_any_request(
        self, record_type, record_id, gearbox, expect_model, expect_kw
    ):
        seen: list[httpx.Request] = []
        service = _service(_routes(seen))
        with pytest.raises(ValueError):
            await service.decode_version(
                GOLF_VIN,
                record_type,
                record_id,
                gearbox_code=gearbox,
                expect_model=expect_model,
                expect_kw=expect_kw,
                grouped=False,
            )
        assert seen == []
