"""Integration tests for opt-in LLM fuel receipt parse."""

import json
import math
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.settings import Setting


async def set_settings(db_session, settings_dict: dict[str, str]) -> None:
    for key, value in settings_dict.items():
        result = await db_session.execute(select(Setting).where(Setting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db_session.add(Setting(key=key, value=value))
    await db_session.commit()


_PROMPT_KEYS = (
    "date",
    "odometer",
    "odometer_unit",
    "volume",
    "volume_unit",
    "kwh",
    "cost",
    "price_per_unit",
    "price_volume_unit",
    "fuel_type_used",
    "notes",
    "station_name",
)


async def _parse_with_llm(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    llm_reply: dict[str, object],
) -> tuple[dict[str, object], str]:
    """Run the parse route against a mocked LLM; return the draft and the system prompt."""
    await set_settings(
        db_session,
        {
            "llm_receipt_parse_enabled": "true",
            "llm_base_url": "http://127.0.0.1:11434/v1",
            "llm_model": "llama3.2",
        },
    )
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={"choices": [{"message": {"content": json.dumps(llm_reply)}}]}
    )
    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value = mock_instance

        response = await client.post(
            f"/api/vehicles/{vin}/fuel/parse-receipt",
            data={"text": "Shell station receipt"},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "llm"
    payload = mock_instance.post.await_args.kwargs["json"]
    system = next(m["content"] for m in payload["messages"] if m["role"] == "system")
    return body["draft"], system


@pytest.mark.integration
@pytest.mark.asyncio
class TestReceiptParse:
    async def test_disabled_returns_403(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "false"})
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
            data={"text": "Shell 12.4 gal $45.50"},
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()

    async def test_mocked_llm_returns_draft_keys(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        # Metric receipt: litres and km pass straight through to the draft.
        draft, system = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "date": "2026-08-01",
                "odometer": 12345.0,
                "odometer_unit": "km",
                "volume": 45.4,
                "volume_unit": "L",
                "kwh": None,
                "cost": 52.10,
                "price_per_unit": 1.147,
                "price_volume_unit": "L",
                "fuel_type_used": "Regular",
                "notes": None,
                "station_name": "Shell",
            },
        )

        # The prompt asks for values and units as printed, not pre-converted.
        for key in _PROMPT_KEYS:
            assert key in system
        assert "odometer_km" not in system

        assert set(draft) >= {
            "date",
            "odometer_km",
            "liters",
            "kwh",
            "cost",
            "price_per_unit",
            "fuel_type_used",
            "notes",
            "station_name",
        }
        assert draft["date"] == "2026-08-01"
        assert draft["odometer_km"] == 12345.0
        assert draft["liters"] == 45.4
        assert draft["price_per_unit"] == 1.147
        assert draft["cost"] == 52.10
        assert draft["kwh"] is None
        assert draft["station_name"] == "Shell"
        assert draft["fuel_type_used"] == "Regular"

        count = await db_session.execute(
            select(func.count())
            .select_from(FuelRecord)
            .where(
                FuelRecord.vin == test_vehicle["vin"],
                FuelRecord.notes == "Shell station receipt",
            )
        )
        assert count.scalar_one() == 0

    async def test_us_units_convert_on_the_server(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": 1000,
                "odometer_unit": "mi",
                "volume": 10,
                "volume_unit": "gal",
                "cost": 35.00,
                "price_per_unit": 3.50,
                "price_volume_unit": "gal",
            },
        )
        # Rounded to the FuelRecord column scales: odometer_km 2, liters 3,
        # price_per_unit 4.
        assert draft["liters"] == 37.854
        assert draft["odometer_km"] == 1609.34
        assert draft["price_per_unit"] == 0.9246
        # Cost is money, not a unit: it comes through untouched.
        assert draft["cost"] == 35.0

    @pytest.mark.parametrize(
        ("odometer_unit", "volume_unit", "price_unit", "expected"),
        [
            ("Kilometres", "Litres", "litre", (500.0, 40.0, 1.5)),
            ("KILOMETER", "liter", "Liters", (500.0, 40.0, 1.5)),
            ("Miles", "Gallons", "GALLON", (804.67, 151.416, 0.3963)),
            ("mile", "GAL", "gallons", (804.67, 151.416, 0.3963)),
        ],
    )
    async def test_unit_spellings_are_case_insensitive(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        db_session,
        odometer_unit,
        volume_unit,
        price_unit,
        expected,
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": 500,
                "odometer_unit": odometer_unit,
                "volume": 40,
                "volume_unit": volume_unit,
                "price_per_unit": 1.5,
                "price_volume_unit": price_unit,
            },
        )
        assert (draft["odometer_km"], draft["liters"], draft["price_per_unit"]) == expected

    async def test_missing_or_unknown_unit_nulls_only_that_value(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                # No unit at all: we can't know km from miles, so null.
                "odometer": 1000,
                "volume": 40,
                "volume_unit": "L",
                "cost": 60,
                # Imperial gallons aren't on the list, so the price goes null
                # rather than being read as US gallons or litres.
                "price_per_unit": 1.5,
                "price_volume_unit": "imp gal",
            },
        )
        assert draft["odometer_km"] is None
        assert draft["price_per_unit"] is None
        # The values with a known unit survive their neighbours going null.
        assert draft["liters"] == 40.0
        assert draft["cost"] == 60.0

    async def test_non_numeric_values_are_null(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": True,
                "odometer_unit": "km",
                "volume": "about forty",
                "volume_unit": "L",
                "kwh": [12],
                "cost": "n/a",
                "price_per_unit": "NaN",
                "price_volume_unit": "L",
                "notes": "pump 4",
                "station_name": 76,
                "date": 20260801,
            },
        )
        assert draft["odometer_km"] is None
        assert draft["liters"] is None
        assert draft["kwh"] is None
        assert draft["cost"] is None
        assert draft["price_per_unit"] is None
        # Text fields that aren't text are null too, not a 500.
        assert draft["station_name"] is None
        assert draft["date"] is None
        assert draft["notes"] == "pump 4"

    async def test_unit_from_the_wrong_family_nulls_that_value(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        # Known spellings, wrong field: km isn't a volume, L isn't a distance.
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": 1000,
                "odometer_unit": "L",
                "volume": 40,
                "volume_unit": "km",
                "price_per_unit": 1.5,
                "price_volume_unit": "mi",
                "cost": 60,
            },
        )
        assert draft["odometer_km"] is None
        assert draft["liters"] is None
        assert draft["price_per_unit"] is None
        assert draft["cost"] == 60.0

    async def test_zero_or_negative_measurements_are_null(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": 0,
                "odometer_unit": "km",
                "volume": -5,
                "volume_unit": "gal",
                # Rounds to 0.0000 at the column's scale, so it's a zero too.
                "price_per_unit": 0.00001,
                "price_volume_unit": "L",
                "cost": -10,
                "kwh": -3,
            },
        )
        assert draft["odometer_km"] is None
        assert draft["liters"] is None
        assert draft["price_per_unit"] is None
        assert draft["cost"] is None
        assert draft["kwh"] is None

    async def test_zero_cost_and_kwh_survive(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        # A free charge is a real receipt, so zero stays zero.
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {"cost": 0, "kwh": 0},
        )
        assert draft["cost"] == 0.0
        assert draft["kwh"] == 0.0

    async def test_value_too_big_for_its_column_is_null(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                # Nine whole digits: fine for Decimal, too wide for NUMERIC(10, 2).
                "odometer": 123456789,
                "odometer_unit": "km",
                "volume": 1e30,
                "volume_unit": "L",
                # Ten whole digits against NUMERIC(13, 4), finite on purpose: 10**400
                # goes inf and serializes as null on its own. Mutation: skip _stored
                # for price only and this goes red.
                "price_per_unit": 1234567890,
                "price_volume_unit": "L",
                "cost": 1e30,
                # Six whole digits against NUMERIC(8, 3).
                "kwh": 123456,
            },
        )
        assert draft["odometer_km"] is None
        assert draft["liters"] is None
        assert draft["price_per_unit"] is None
        assert draft["cost"] is None
        assert draft["kwh"] is None

    @pytest.mark.parametrize(
        ("number_key", "unit_key", "unit", "draft_key"),
        [
            ("odometer", "odometer_unit", "mi", "odometer_km"),
            ("price_per_unit", "price_volume_unit", "gal", "price_per_unit"),
        ],
        ids=["odometer-mi", "price-per-gal"],
    )
    async def test_a_number_too_long_to_convert_is_null_not_a_500(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        db_session,
        number_key: str,
        unit_key: str,
        unit: str,
        draft_key: str,
    ):
        # A million digits is past Decimal's exponent limit, so the mi and gal
        # conversions used to overflow into a 500 before any width check.
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {number_key: "9" * 1_000_010, unit_key: unit, "cost": "12"},
        )
        assert draft[draft_key] is None
        assert draft["cost"] == 12.0

    async def test_negative_zero_cost_and_kwh_come_back_as_plain_zero(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        # "-0.00" passed the >= 0 check and came back as -0.0.
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {"cost": "-0.00", "kwh": -0.0},
        )
        assert draft["cost"] == 0.0
        assert draft["kwh"] == 0.0
        assert math.copysign(1.0, draft["cost"]) == 1.0
        assert math.copysign(1.0, draft["kwh"]) == 1.0

    async def test_largest_value_that_fits_survives(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        # Guard on the bound's edge: an off-by-one in the precision check nulls these.
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": "99999999.99",
                "odometer_unit": "km",
                "cost": "9999999999.99",
                "kwh": "99999.999",
            },
        )
        assert draft["odometer_km"] == 99999999.99
        assert draft["cost"] == 9999999999.99
        assert draft["kwh"] == 99999.999

    async def test_number_strings_must_be_plain_decimals(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "volume": "1_000",
                "volume_unit": "L",
                "odometer": "1e3",
                "odometer_unit": "km",
                "price_per_unit": "9e999999",
                "price_volume_unit": "gal",
                "cost": "12",
                "kwh": "12.5",
            },
        )
        assert draft["liters"] is None
        assert draft["odometer_km"] is None
        assert draft["price_per_unit"] is None
        assert draft["cost"] == 12.0
        assert draft["kwh"] == 12.5

    async def test_numeric_strings_are_numbers(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        draft, _ = await _parse_with_llm(
            client,
            auth_headers,
            test_vehicle["vin"],
            db_session,
            {
                "odometer": "1000",
                "odometer_unit": "mi",
                "volume": " 10.0 ",
                "volume_unit": "gal",
                "cost": "35.00",
                "kwh": "12.5",
            },
        )
        assert draft["odometer_km"] == 1609.34
        assert draft["liters"] == 37.854
        assert draft["cost"] == 35.0
        assert draft["kwh"] == 12.5

    async def test_oversized_file_returns_413(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        with patch("app.routes.fuel.MAX_RECEIPT_UPLOAD_BYTES", 16):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                files={"file": ("receipt.jpg", b"x" * 64, "image/jpeg")},
                headers=auth_headers,
            )
        assert response.status_code == 413
        assert (
            "too large" in response.json()["detail"].lower()
            or "exceeds" in response.json()["detail"].lower()
        )

    async def test_oversize_upload_is_never_read_into_memory(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        # Patch starlette's UploadFile, NOT fastapi's. fastapi.datastructures
        # .UploadFile is a distinct subclass, but the multipart parser builds the
        # starlette base class regardless of the annotation, so patching the
        # subclass intercepts nothing (verified: await_count 1 vs 0).
        with (
            patch(
                "starlette.datastructures.UploadFile.read",
                new=AsyncMock(return_value=b""),
            ) as read_mock,
            patch("app.routes.fuel.MAX_RECEIPT_UPLOAD_BYTES", 16),
        ):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                files={"file": ("receipt.jpg", b"x" * 64, "image/jpeg")},
                headers=auth_headers,
            )
        assert response.status_code == 413
        # The point of the fix: an oversize body is rejected on its spooled size,
        # never materialised as a full-size bytes object in memory.
        read_mock.assert_not_awaited()

    async def test_unreadable_image_reports_error_instead_of_calling_llm(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        with (
            patch(
                "app.services.document_ocr.DocumentOCRService.extract_text_from_bytes",
                new=AsyncMock(side_effect=RuntimeError("tesseract exploded")),
            ),
            # Patch the constructor, not .post: the test client is itself an
            # httpx.AsyncClient, and patching the method would break its own
            # request. The service builds a fresh client inside the call, so a
            # constructor that is never invoked proves no LLM request happened.
            patch("httpx.AsyncClient") as llm_client,
        ):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                files={"file": ("blurry.jpg", b"not-an-image", "image/jpeg")},
                headers=auth_headers,
            )
        assert response.status_code == 400
        assert "could not read" in response.json()["detail"].lower()
        # A receipt we could not read must not spend a 60s LLM call that can
        # only come back all-null, then report success to the user.
        llm_client.assert_not_called()

    async def test_ocr_yielding_nothing_says_so(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        # document_ocr swallows a missing OCR dependency and returns "", so this
        # is the shape a user hits when tesseract is absent, not a synthetic case.
        with patch(
            "app.services.document_ocr.DocumentOCRService.extract_text_from_bytes",
            new=AsyncMock(return_value=""),
        ):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                files={"file": ("blank.jpg", b"blank", "image/jpeg")},
                headers=auth_headers,
            )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        # Telling someone who just uploaded a photo to "provide an image" is wrong.
        assert "could not read" in detail
        assert "provide text or an image file" not in detail

    async def test_oversized_text_returns_413(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        with patch("app.routes.fuel.MAX_RECEIPT_TEXT_CHARS", 8):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                data={"text": "this is longer than eight"},
                headers=auth_headers,
            )
        assert response.status_code == 413


def test_number_caps_whole_digits() -> None:
    """The cap itself. Fifteen whole digits is more than any column holds, sixteen is refused."""
    from app.services.receipt_parse_service import _number

    assert _number("1" * 15) == Decimal("1" * 15)
    assert _number("-" + "1" * 15 + ".5") == Decimal("-" + "1" * 15 + ".5")
    assert _number("1" * 16) is None
