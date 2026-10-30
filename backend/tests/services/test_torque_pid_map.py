import re
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import QueryParams

from app.models.drive_session import DriveSession
from app.services.torque_pid_map import (
    TORQUE_DEFAULT_UNITS,
    TORQUE_OBD_PID_MAP,
    TORQUE_PID_NAMES,
    _storage_key,
    parse_torque_query,
    torque_unit,
)


def test_maps_common_obd_pids_to_canonical_keys():
    # Torque metric raw values; k0c=RPM, k0d=speed, k05=coolant, k11=throttle, k2f=fuel
    q = {
        "session": "1499658078071",
        "id": "abc123",
        "time": "1499658087444",
        "k0c": "1800",
        "k0d": "60",
        "k05": "89",
        "k11": "22.5",
        "k2f": "48",
    }
    r = parse_torque_query(q)
    assert r.session == "1499658078071"
    assert r.time_ms == 1499658087444
    assert r.obd["ENGINE_RPM"] == 1800.0
    assert r.obd["SPEED"] == 60.0
    assert r.obd["COOLANT_TMP"] == 89.0
    assert r.obd["THROTTLE"] == 22.5
    assert r.obd["FUEL"] == 48.0
    assert r.gps == {}


def test_splits_gps_pids_out_of_obd():
    q = {
        "kff1006": "37.4219",
        "kff1005": "-122.084",
        "kff1001": "55.0",
        "kff1007": "270.0",
        "kff1010": "12.0",
        "k0c": "1000",
    }
    r = parse_torque_query(q)
    assert r.gps["latitude"] == 37.4219
    assert r.gps["longitude"] == -122.084
    assert r.gps["speed"] == 55.0
    assert r.gps["heading"] == 270.0
    assert r.gps["altitude"] == 12.0
    # Exactly one OBD key (k0c→ENGINE_RPM); no GPS PID leaked into obd under any name.
    assert set(r.obd) == {"ENGINE_RPM"}


def test_unknown_pid_auto_canonicalizes_uppercase():
    r = parse_torque_query({"k1a": "5"})
    assert r.obd["K1A"] == 5.0  # unmapped → uppercased raw key (auto-registers downstream)


def test_test_request_minimal_params_no_readings():
    r = parse_torque_query({"eml": "user@x", "v": "3", "session": "1", "id": "abc"})
    assert r.obd == {} and r.gps == {} and r.email == "user@x"


def test_non_numeric_values_ignored():
    r = parse_torque_query({"k0d": "NaN", "k0c": "", "k05": "abc"})
    assert r.obd == {}  # unparseable values dropped, not crashed


def test_unpadded_obd_pids_map_like_padded_ones():
    """#223: Torque Pro 1.12 uploads PIDs below 0x10 without the leading zero."""
    # The reporter's upload, verbatim.
    r = parse_torque_query(
        {"k4": "8.6", "k5": "69.0", "kc": "2549.0", "kd": "48.0", "kf": "48.0", "k11": "16.47"}
    )
    assert r.obd == {
        "ENGINE_LOAD": 8.6,
        "COOLANT_TMP": 69.0,
        "ENGINE_RPM": 2549.0,
        "SPEED": 48.0,
        "INTAKE_TEMP": 48.0,
        "THROTTLE": 16.47,
    }


def test_every_padded_single_digit_pid_has_an_unpadded_spelling():
    """Every `k0X` in the map is reachable as `kX` too, so no future entry is padded-only."""
    padded = [k for k in TORQUE_OBD_PID_MAP if len(k) == 3 and k.startswith("k0")]
    assert padded  # the map does carry single-digit PIDs; an empty list proves nothing
    for key in padded:
        assert parse_torque_query({f"k{key[2]}": "1"}).obd == {TORQUE_OBD_PID_MAP[key]: 1.0}


def test_unpadded_pid_key_is_case_insensitive():
    assert parse_torque_query({"KC": "900"}).obd == {"ENGINE_RPM": 900.0}


_HEX = "0123456789abcdef"


def test_an_unmapped_one_digit_pid_is_padded_too():
    """F-3: `k3` and `ka` land where `k03` and `k0a` do, mapped or not."""
    assert parse_torque_query({"k3": "2", "ka": "7"}).obd == {"K03": 2.0, "K0A": 7.0}


def test_every_one_digit_pid_lands_on_its_padded_key():
    for digit in _HEX:
        unpadded = parse_torque_query({f"k{digit}": "1"}).obd
        assert unpadded == parse_torque_query({f"k0{digit}": "1"}).obd, digit


def test_extended_pids_keep_their_storage_keys():
    """R1-M1: a new key would orphan a setting saved on the old one."""
    r = parse_torque_query({"kff1238": "14.1", "kff1202": "-9.5", "kff1271": "3.79"})
    assert r.obd == {"KFF1238": 14.1, "KFF1202": -9.5, "KFF1271": 3.79}


def test_storage_key_lowercases_what_it_is_given():
    """TQ-L1: an uppercase key lands where its lowercase spelling does."""
    assert _storage_key("KC") == "ENGINE_RPM"
    assert _storage_key("KFF120C") == "TORQUE_ODOMETER"
    assert _storage_key("KFF1238") == "KFF1238"


async def test_the_aggregator_reads_the_key_each_common_pid_lands_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G1-D1: the session stats only see a Torque value if its key is in the list
    the aggregator queries. The stub hands each column back the keys it asked for."""
    from app.services.session_service import SessionService, SessionWindow

    async def keys_asked_for(
        self: SessionService,
        vin: str,
        device_id: str | None,
        param_keys: list[str],
        window: object,
    ) -> dict[str, object]:
        return {"count": 1, "avg": list(param_keys), "max": list(param_keys)}

    monkeypatch.setattr(SessionService, "_get_param_stats_multi", keys_asked_for)
    session = SimpleNamespace(vin="VIN", device_id="torque-1")
    await SessionService(cast(AsyncSession, None))._calculate_session_aggregates(
        cast(DriveSession, session), cast(SessionWindow, None)
    )
    columns = {
        "k05": "avg_coolant_temp",
        "k11": "avg_throttle",
        "k2f": "avg_fuel_level",
        "k0d": "avg_speed",
        "k0c": "avg_rpm",
    }
    for pid, column in columns.items():
        assert TORQUE_OBD_PID_MAP[pid] in getattr(session, column), pid


def test_the_odometer_is_the_only_mapped_extended_pid():
    assert [key for key in TORQUE_OBD_PID_MAP if key.startswith("kff")] == ["kff120c"]


def _torque_key(storage_key: str) -> str:
    """The `k<hex>` key Torque sends for a stored key."""
    mapped = [k for k, v in TORQUE_OBD_PID_MAP.items() if v == storage_key]
    return mapped[0] if mapped else storage_key.lower()


def test_every_name_and_unit_sits_on_a_key_the_parser_stores():
    """A row keyed some other way would never match a reading."""
    for key in {**TORQUE_PID_NAMES, **TORQUE_DEFAULT_UNITS}:
        assert set(parse_torque_query({_torque_key(key): "1"}).obd) == {key}, key


def test_the_keys_read_as_metric_say_their_metric_unit():
    """What the dashboard and the session aggregator convert from (D1)."""
    keys = (
        "SPEED",
        "COOLANT_TMP",
        "INTAKE_TEMP",
        "AMBIENT_TEMP",
        "OIL_TEMP",
        "INTAKE_PRESSURE",
        "TORQUE_ODOMETER",
        "KFF1204",
    )
    assert {k: TORQUE_DEFAULT_UNITS[k] for k in keys} == {
        "SPEED": "km/h",
        "COOLANT_TMP": "°C",
        "INTAKE_TEMP": "°C",
        "AMBIENT_TEMP": "°C",
        "OIL_TEMP": "°C",
        "INTAKE_PRESSURE": "kPa",
        "TORQUE_ODOMETER": "km",
        "KFF1204": "km",
    }


def test_the_extended_pids_have_one_readable_name_each():
    assert TORQUE_PID_NAMES["KFF1238"] == "OBD adapter voltage"
    assert TORQUE_PID_NAMES["KFF1202"] == "Turbo boost"
    assert len(TORQUE_PID_NAMES) == len(set(TORQUE_PID_NAMES.values())) == 21


def test_a_unit_in_a_name_is_spelled_like_the_unit():
    """TQ-L4: "(L/100 km)" next to a unit of "L/100km" reads as two units."""
    in_names = {
        key: match.group(1)
        for key, name in TORQUE_PID_NAMES.items()
        if (match := re.search(r"\(([^)]+)\)$", name))
    }
    assert {"KFF1201", "KFF1207", "KFF1208"} <= set(in_names)
    assert in_names == {key: TORQUE_DEFAULT_UNITS[key] for key in in_names}


#: Part of a real session-start request, bytes as the phone sent them (Torque
#: v8, 2016, surfrock66/torque debug-apache-access-logs.txt). A degree sign is
#: raw UTF-8, '/' is a space and '%' a lone space.
_V8_UNITS = (
    b"eml=x&v=8&session=1459259898221&id=abc&time=1459259898456"
    b"&defaultUnit04=%20&defaultUnit05=\xc2\xb0C&defaultUnit0b=kPa&defaultUnit0c=rpm"
    b"&defaultUnit0d=km%20h&defaultUnit0e=\xc2\xb0&defaultUnit0f=\xc2\xb0C&defaultUnit10=g%20s"
    b"&defaultUnit11=%20&defaultUnit1f=s&defaultUnit2f=%20&defaultUnit42=V"
    b"&defaultUnit46=\xc2\xb0C&defaultUnit5c=\xc2\xb0C&defaultUnitff120c=km"
    b"&defaultUnitff1201=mpg&defaultUnitff1202=psi&defaultUnitff1203=kpl&defaultUnitff1204=km"
    b"&defaultUnitff1205=mpg&defaultUnitff1206=kpl&defaultUnitff1207=l%20100km"
    b"&defaultUnitff1208=l%20100km&defaultUnitff1220=g&defaultUnitff1221=g&defaultUnitff1222=g"
    b"&defaultUnitff1223=g&defaultUnitff1225=ft-lb&defaultUnitff1226=hp&defaultUnitff1238=V"
    b"&defaultUnitff1239=m&defaultUnitff123a=&defaultUnitff1249=:1&defaultUnitff124d=:1"
    b"&defaultUnitff1269=%20&defaultUnitff1271=l&defaultUnit33=kPa"
    b"&defaultUnitff1001=km%20h&defaultUnitff1005=\xc2\xb0"
)


def test_torque_unit_cleans_up_how_torque_spells_a_unit():
    cases = {
        "Â°C": "°C",
        "\\xc2\\xb0C": "°C",
        "°C": "°C",
        "km h": "km/h",
        "km/h": "km/h",
        " ": "%",
        "%": "%",
        "": None,
        "l 100km": "L/100km",
        "kpl": "km/L",
        "l": "L",
        "g s": "g/s",
        "psi": "psi",
        "ft-lb": "ft-lb",
        "Â°": "°",
        "kPa": "kPa",
    }
    assert {raw: torque_unit(raw) for raw in cases} == cases
    assert torque_unit(None) is None


def test_a_session_start_request_declares_units_and_no_values():
    r = parse_torque_query(QueryParams(_V8_UNITS))
    assert r.obd == {} and r.gps == {}
    assert {
        k: r.default_units[k] for k in ("COOLANT_TMP", "SPEED", "ENGINE_LOAD", "K33", "KFF1207")
    } == {
        "COOLANT_TMP": "°C",
        "SPEED": "km/h",
        "ENGINE_LOAD": "%",
        "K33": "kPa",
        "KFF1207": "L/100km",
    }
    assert "KFF123A" not in r.default_units  # declared with no unit
    assert not {"KFF1001", "KFF1005"} & set(r.default_units)  # location, not telemetry


def test_real_torque_declares_every_unit_this_module_assumes():
    """D3: each static unit is what Torque itself says for that PID."""
    declared = parse_torque_query(QueryParams(_V8_UNITS)).default_units
    assert {k: declared.get(k) for k in TORQUE_DEFAULT_UNITS} == TORQUE_DEFAULT_UNITS


def test_the_display_unit_is_never_recorded():
    """D2: userUnit is what the phone shows, not what it sends."""
    assert parse_torque_query({"userUnit05": "°F", "userUnit0d": "mph"}).default_units == {}


def test_a_declaration_longer_than_a_real_pid_or_not_hex_is_ignored():
    """Torque's longest PID, ff1238, is six hex digits; anything else is made up."""
    declared = parse_torque_query(
        {"defaultUnitff12380": "V", "defaultUnitzz": "V", "defaultUnitff1238": "V"}
    ).default_units
    assert declared == {"KFF1238": "V"}
