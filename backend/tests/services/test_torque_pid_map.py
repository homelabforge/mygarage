from app.services.torque_pid_map import TORQUE_OBD_PID_MAP, parse_torque_query


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


def test_the_odometer_is_the_only_mapped_extended_pid():
    assert [key for key in TORQUE_OBD_PID_MAP if key.startswith("kff")] == ["kff120c"]
