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
    NOTE_AUTOREF_BEST_GUESS,
    NOTE_AUTOREF_EXTERNAL,
    AutoRefAuthError,
    AutoRefQuotaError,
    AutoRefService,
    AutoRefUnavailableError,
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

    @pytest.mark.parametrize("bad", ["sk-clé-SECRET-1234", "sk SECRET 1234", "sk-SECRET\n1234"])
    @pytest.mark.parametrize("call", ["decode", "usage"])
    async def test_a_malformed_key_is_rejected_before_any_request(self, bad, call):
        # Codex diff R1-M2: httpx encodes headers as ASCII, so a non-ASCII
        # key raised UnicodeEncodeError (a ValueError, read as a bad VIN)
        # holding the whole key. It reads as a rejected key, sends nothing,
        # and no exception in the chain carries it.
        seen: list[httpx.Request] = []
        service = _service(_routes(seen), key=bad)
        with pytest.raises(AutoRefAuthError) as caught:
            await (service.decode(VIN) if call == "decode" else service.usage())
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
        result = map_vehicle(VIN, ROW, DETAIL["VIN_INFO"], multiple=False)
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
        assert map_vehicle(VIN, ROW, {}, multiple=False)["year"] is None

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("M", "Manual"),
            ("A", "Automatic"),
            ("S", "Semi-Automatic"),
            ("H", "Hydrostatic"),
            ("h", "Hydrostatic"),
            ("X", None),
            (None, None),
        ],
    )
    def test_gearbox_code(self, code, expected):
        row = {**ROW, "CODE_GEARBOX": code}
        assert map_vehicle(VIN, row, {}, multiple=False)["transmission"]["type"] == expected

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
        assert map_vehicle(VIN, ROW, detail, multiple=False)["drive_type"] == expected

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
        assert map_vehicle(VIN, ROW, detail, multiple=False)["drive_type"] == expected

    def test_a_manual_with_an_automatic_mode_reads_automated_manual(self):
        # The Macan's PDK: CODE_GEARBOX M, with additionnal_mode A and 7 gears.
        row = {**ROW, "CODE_GEARBOX": "M", "GEARBOX": "Manual"}
        detail = {"GEARBOX_DETAILS": [{"code": None, "type": "Manual", "description": None,
                                       "additionnal_mode": "A", "gears": 7}]}  # fmt: skip
        assert map_vehicle(VIN, row, detail, multiple=False)["transmission"] == {
            "type": "Automated Manual",
            "speeds": "7",
        }

    def test_a_plain_manual_stays_manual(self):
        row = {**ROW, "CODE_GEARBOX": "M"}
        detail = {"GEARBOX_DETAILS": [{"type": "Manual", "additionnal_mode": None, "gears": 6}]}
        assert map_vehicle(VIN, row, detail, multiple=False)["transmission"] == {
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
        assert map_vehicle(VIN, ROW, detail, multiple=False)["transmission"]["speeds"] is None

    @pytest.mark.parametrize(
        "words",
        [
            "Continuously Variable",
            ["Continuously Variable"],
            "CVT",
            "Variation continue",
            "e-CVT",
        ],
    )
    def test_s_reads_cvt_when_the_words_say_so(self, words):
        # S is AutoRef's "Semi-auto/CVT": one code for both, so the words decide.
        row = {**ROW, "CODE_GEARBOX": "S", "GEARBOX": "Semi-automatic"}
        detail = {"GEARBOX": words}
        assert map_vehicle(VIN, row, detail, multiple=False)["transmission"]["type"] == (
            "Continuously Variable Transmission (CVT)"
        )

    def test_the_words_alone_never_make_a_cvt(self):
        row = {**ROW, "CODE_GEARBOX": "A", "GEARBOX": "Continuously Variable"}
        assert map_vehicle(VIN, row, {}, multiple=False)["transmission"]["type"] == "Automatic"

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
        result = map_vehicle(VIN, row, detail, multiple=False)
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
        engine = map_vehicle(VIN, row, {}, multiple=False)["engine"]
        assert (engine["fuel_type_normalized"], engine["fuel_type_secondary"]) == expected

    def test_a_second_fuel_autoref_names_wins_over_electric(self):
        row = {**ROW, "FUEL": "Gasoline / Electric"}
        engine = map_vehicle(VIN, row, {"SECOND_FUEL": "Diesel"}, multiple=False)["engine"]
        assert engine["fuel_type_normalized"] == "hybrid"
        assert engine["fuel_type_secondary"] == "diesel"

    def test_best_guess_when_several_rows(self):
        assert NOTE_AUTOREF_BEST_GUESS in map_vehicle(VIN, ROW, {}, multiple=True)["notes"]

    def test_best_guess_when_several_configurations(self):
        row = {
            **ROW,
            "configurations": [{"id": 1, "registrations": 3}, {"id": 2, "registrations": 1}],
        }
        assert NOTE_AUTOREF_BEST_GUESS in map_vehicle(VIN, row, {}, multiple=False)["notes"]

    def test_an_external_record_in_capitals_reads_title_case(self):
        row = {"id": None, "VIN": VIN, "BRAND": "MASERATI", "BRAND_MODEL": "MASERATI LEVANTE D V6 AUTO",
               "MODEL_FULL": "LEVANTE D V6 AUTO", "RECORD_TYPE": "UK"}  # fmt: skip
        result = map_vehicle(VIN, row, {}, multiple=False)
        assert result["make"] == "Maserati"
        assert result["model"] == "Levante D V6 Auto"
        assert NOTE_AUTOREF_EXTERNAL in result["notes"]

    def test_the_brand_picks_the_model_spelling(self):
        # Fable fix-wave F-1: a Mini One, not the Mercedes-AMG ONE.
        row = {**ROW, "BRAND": "MINI", "MODEL_RESOLVED": "ONE"}
        assert map_vehicle(VIN, row, {}, multiple=False)["model"] == "One"

    @pytest.mark.parametrize("field", ["POWER_KW", "DISPLACEMENT", "DOORS", "CYLINDERS"])
    def test_wrong_types_read_as_missing(self, field):
        row = {**ROW, field: "n/a"}
        detail = {**DETAIL["VIN_INFO"], field: "n/a"}
        result = map_vehicle(VIN, row, detail, multiple=False)
        assert result["make"] == "Audi"
