from app.services.firmware_service import FirmwareService


def test_classify_release_track_pro_and_obd():
    assert FirmwareService.classify_release_track("v4.50p") == "pro"
    assert FirmwareService.classify_release_track("v4.49p_beta-06") == "pro"
    assert FirmwareService.classify_release_track("v4.21") == "obd"
    assert FirmwareService.classify_release_track("v4.20_beta-01") == "obd"


def test_classify_release_track_title_fallback():
    # Non-numeric/odd tag falls back to the release title.
    assert FirmwareService.classify_release_track("nightly", "WiCAN-PRO build") == "pro"
    assert FirmwareService.classify_release_track("nightly", "WiCAN-OBD build") == "obd"


def test_device_firmware_track():
    assert FirmwareService.device_firmware_track("WiCAN-OBD-PRO") == "pro"
    assert FirmwareService.device_firmware_track("WiCAN-OBD") == "obd"
    assert FirmwareService.device_firmware_track("WiCAN-USB") == "obd"
    assert FirmwareService.device_firmware_track(None) is None
    assert FirmwareService.device_firmware_track("") is None
