from app.services.torque_pid_map import GPS_PIDS, parse_torque_query


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
    assert "ENGINE_RPM" in r.obd and not (GPS_PIDS & set(r.obd))


def test_unknown_pid_auto_canonicalizes_uppercase():
    r = parse_torque_query({"k1a": "5"})
    assert r.obd["K1A"] == 5.0  # unmapped → uppercased raw key (auto-registers downstream)


def test_test_request_minimal_params_no_readings():
    r = parse_torque_query({"eml": "user@x", "v": "3", "session": "1", "id": "abc"})
    assert r.obd == {} and r.gps == {} and r.email == "user@x"


def test_non_numeric_values_ignored():
    r = parse_torque_query({"k0d": "NaN", "k0c": "", "k05": "abc"})
    assert r.obd == {}  # unparseable values dropped, not crashed
