"""Unit tests for multi-provider VIN decoding router, WMI analysis, and market routing."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.vin_decoders.base import BaseVINDecoder
from app.services.vin_decoders.european import EuropeanVINDecoder
from app.services.vin_decoders.nhtsa import NHTSAVINDecoder
from app.services.vin_decoders.router import VINDecoderRouter
from app.utils.wmi import MarketRegion, detect_market_region, get_wmi, lookup_wmi


class TestWMIAndMarketDetection:
    """Test World Manufacturer Identifier analysis and market region classification."""

    def test_wmi_extraction(self):
        """get_wmi extracts the first 3 uppercase characters."""
        assert get_wmi("WF0XXXGCDP1234567") == "WF0"
        assert get_wmi("1hgbh41jxmn109186") == "1HG"
        assert get_wmi("ZAR93900007012345") == "ZAR"

    def test_market_region_north_america(self):
        """VINs starting with 1, 4, 5 (USA), 2 (Canada), 3 (Mexico) are North American."""
        # USA (1, 4, 5)
        assert detect_market_region("1HGBH41JXMN109186") == MarketRegion.NORTH_AMERICA
        assert detect_market_region("4T1BF1FK5EU123456") == MarketRegion.NORTH_AMERICA
        assert detect_market_region("5YJSA1E21HF123456") == MarketRegion.NORTH_AMERICA
        # Canada (2)
        assert detect_market_region("2T1BR32E71C123456") == MarketRegion.NORTH_AMERICA
        assert detect_market_region("2G1FC1E33H9123456") == MarketRegion.NORTH_AMERICA
        # Mexico (3)
        assert detect_market_region("3FA6P0H74HR123456") == MarketRegion.NORTH_AMERICA
        assert detect_market_region("3VW2K7AJ0HM123456") == MarketRegion.NORTH_AMERICA

    def test_market_region_europe(self):
        """VINs starting with letters S through Z are European market."""
        # W = Germany
        assert detect_market_region("WF0XXXGCDP1234567") == MarketRegion.EUROPE
        assert detect_market_region("WBA11AL0101234567") == MarketRegion.EUROPE
        assert detect_market_region("WVWZZZ3CZWE123456") == MarketRegion.EUROPE
        # Z = Italy
        assert detect_market_region("ZAR93900007012345") == MarketRegion.EUROPE
        assert detect_market_region("ZFA19900001234567") == MarketRegion.EUROPE
        # V = France / Spain / Austria
        assert detect_market_region("VF1BB0A0F23123456") == MarketRegion.EUROPE
        assert detect_market_region("VSSZZZ5FZHR123456") == MarketRegion.EUROPE
        # S = United Kingdom / Poland
        assert detect_market_region("SAJAC42407S123456") == MarketRegion.EUROPE
        assert detect_market_region("SALWR2V48LA123456") == MarketRegion.EUROPE
        # T = Czechia / Switzerland
        assert detect_market_region("TMBJJ7NE6J0123456") == MarketRegion.EUROPE
        # Y = Sweden / Belgium
        assert detect_market_region("YV1BW84A1D1123456") == MarketRegion.EUROPE

    def test_market_region_other(self):
        """VINs from Asia (J, K, L, M) or Oceania (6, 7) or South America (8, 9) are OTHER."""
        assert detect_market_region("JA32U2FU9KU005963") == MarketRegion.OTHER  # Japan
        assert detect_market_region("KMHDH4AE9EU123456") == MarketRegion.OTHER  # South Korea
        assert detect_market_region("6FPAAAJGS12345678") == MarketRegion.OTHER  # Australia

    def test_lookup_wmi_known_manufacturers(self):
        """lookup_wmi returns brand and country for known manufacturers."""
        ford_eu = lookup_wmi("WF0XXXGCDP1234567")
        assert ford_eu is not None
        assert ford_eu["make"] == "Ford"
        assert ford_eu["country"] == "Germany"

        bmw = lookup_wmi("WBA11AL0101234567")
        assert bmw is not None
        assert bmw["make"] == "BMW"

        alfa = lookup_wmi("ZAR93900007012345")
        assert alfa is not None
        assert alfa["make"] == "Alfa Romeo"
        assert alfa["country"] == "Italy"


@pytest.mark.asyncio
class TestVINDecoderRouterRouting:
    """Test the intelligent routing logic across providers."""

    async def test_north_american_routing_calls_nhtsa_first(self):
        """North American VIN calls NHTSA first."""
        mock_nhtsa = AsyncMock(spec=BaseVINDecoder)
        mock_nhtsa.name = "nhtsa"
        mock_nhtsa.is_available.return_value = True
        mock_nhtsa.decode.return_value = {
            "vin": "1HGBH41JXMN109186",
            "make": "Honda",
            "model": "Accord",
            "year": 2021,
            "decoder_source": "nhtsa",
        }

        mock_european = AsyncMock(spec=BaseVINDecoder)
        mock_european.name = "european"
        mock_european.is_available.return_value = True

        router = VINDecoderRouter(nhtsa_decoder=mock_nhtsa, european_decoder=mock_european)
        chain = router.determine_decoder_chain("1HGBH41JXMN109186")

        assert len(chain) >= 2
        assert chain[0].name == "nhtsa"
        assert chain[1].name == "european"

        result = await router.decode_vin("1HGBH41JXMN109186")
        assert result["make"] == "Honda"
        assert result["model"] == "Accord"
        assert result["market_region"] == "north_america"
        # European decoder was not called because NHTSA succeeded
        mock_european.decode.assert_not_called()

    async def test_north_american_nhtsa_error_code_1_falls_back_to_european(self):
        """When NHTSA fails with ErrorCode 1 (outside US market), router immediately falls back to European API."""
        mock_nhtsa = AsyncMock(spec=BaseVINDecoder)
        mock_nhtsa.name = "nhtsa"
        mock_nhtsa.is_available.return_value = True
        # NHTSA returns None when it encounters ErrorCode 1 or lacks model data
        mock_nhtsa.decode.return_value = None

        mock_european = AsyncMock(spec=BaseVINDecoder)
        mock_european.name = "european"
        mock_european.is_available.return_value = True
        mock_european.decode.return_value = {
            "vin": "1FA6P8CF5H5123456",
            "make": "Ford",
            "model": "Mustang",
            "year": 2017,
            "decoder_source": "european",
        }

        router = VINDecoderRouter(nhtsa_decoder=mock_nhtsa, european_decoder=mock_european)
        result = await router.decode_vin("1FA6P8CF5H5123456")

        # Verified fallback occurred
        mock_nhtsa.decode.assert_called_once()
        mock_european.decode.assert_called_once()
        assert result["make"] == "Ford"
        assert result["model"] == "Mustang"
        assert result["decoder_source"] == "european"

    async def test_european_vin_bypasses_nhtsa_and_calls_european_first(self):
        """European VIN (S-Z) bypasses NHTSA and calls European decoder directly."""
        mock_nhtsa = AsyncMock(spec=BaseVINDecoder)
        mock_nhtsa.name = "nhtsa"
        mock_nhtsa.is_available.return_value = True

        mock_european = AsyncMock(spec=BaseVINDecoder)
        mock_european.name = "european"
        mock_european.is_available.return_value = True
        mock_european.decode.return_value = {
            "vin": "WF0XXXGCDP1234567",
            "make": "Ford",
            "model": "Focus",
            "trim": "Titanium",
            "decoder_source": "european",
        }

        router = VINDecoderRouter(nhtsa_decoder=mock_nhtsa, european_decoder=mock_european)
        chain = router.determine_decoder_chain("WF0XXXGCDP1234567")

        # European decoder must be first in the chain
        assert chain[0].name == "european"

        result = await router.decode_vin("WF0XXXGCDP1234567")

        # NHTSA was bypassed completely
        mock_nhtsa.decode.assert_not_called()
        mock_european.decode.assert_called_once()
        assert result["make"] == "Ford"
        assert result["model"] == "Focus"
        assert result["market_region"] == "europe"

    async def test_european_decoder_wmi_fallback_when_api_offline(self):
        """European decoder resolves make and manufacturer from WMI when external API is offline."""
        decoder = EuropeanVINDecoder()
        # Mock _decode_from_api to simulate offline / no-key external service
        decoder._decode_from_api = AsyncMock(return_value=None)

        result = await decoder.decode("WF0XXXGCDP1234567")
        assert result is not None
        assert result["vin"] == "WF0XXXGCDP1234567"
        assert result["make"] == "Ford"
        assert result["manufacturer"] == "FORD WERKE AG"
        assert result["plant_country"] == "Germany"
        assert result["year"] == 2023
        assert result["decoder_source"] == "european_wmi"

    async def test_extensibility_adding_third_custom_decoder(self):
        """Verify that registering a 3rd/4th/Nth decoder integrates seamlessly into the router."""

        class CustomAsianVINDecoder(BaseVINDecoder):
            name = "custom_asian"

            async def decode(self, vin: str) -> dict[str, Any] | None:
                if vin.startswith("JA3"):
                    return {
                        "vin": vin,
                        "make": "Mitsubishi",
                        "model": "Mirage",
                        "year": 2019,
                        "decoder_source": self.name,
                    }
                return None

        router = VINDecoderRouter()
        router.register_decoder(CustomAsianVINDecoder())

        assert router.get_decoder("custom_asian") is not None

        # Verify Asian VIN chain includes custom decoder
        chain = router.determine_decoder_chain("JA32U2FU9KU005963")
        chain_names = [d.name for d in chain]
        assert "custom_asian" in chain_names


@pytest.mark.asyncio
class TestNHTSAVINDecoderErrorCodeHandling:
    """Test NHTSAVINDecoder handling of NHTSA error codes."""

    async def test_nhtsa_decoder_handles_error_code_1_properly(self):
        """NHTSA returns ErrorCode '1,8,400' on European VIN, decoder recognizes it and returns None for fallback."""
        mock_nhtsa_svc = AsyncMock()
        mock_nhtsa_svc.decode_vin.return_value = {
            "ErrorCode": "1,8,400",
            "ErrorText": "1 - Check Digit (9th position) does not calculate properly; 8 - No detailed data available currently; 400 - Invalid Characters Present",
            "Make": "FORD",
            "Model": "",
            "VIN": "WF0XXXGCDP1234567",
        }

        decoder = NHTSAVINDecoder(nhtsa_service=mock_nhtsa_svc)
        result = await decoder.decode("WF0XXXGCDP1234567")

        # Because ErrorCode contains 1 and Model is empty, it returns None to trigger fallback
        assert result is None


class TestEuropeanVINDecoderParsing:
    """Test AutoRef European API response parser."""

    def test_parse_autoref_response_payload(self):
        decoder = EuropeanVINDecoder()
        payload = [
            {
                "id": 55411,
                "VIN": "WBA11AL010",
                "BRAND": "BMW",
                "BRAND_MODEL": "BMW M235I XDRIVE",
                "MODEL": "M235i",
                "MODEL2": "xDrive",
                "MODEL3": "M Performance",
                "POWER_KW": 225.0,
                "POWER_DIN": 306.0,
                "FUEL": "Gasoline",
                "DATE_FIRST_CIRCULATION": 2020,
                "BODY": "Coupe",
                "DRIVETRAIN": "AWD",
                "GEARBOX": ["Automatic"],
                "MANUFACTURER": "Bayerische Motoren Werke AG",
            }
        ]

        parsed = decoder._parse_autoref_response("WBA11AL0101234567", payload)
        assert parsed is not None
        assert parsed["make"] == "BMW"
        assert parsed["model"] == "M235i"
        assert parsed["series"] == "xDrive"
        assert parsed["trim"] == "M Performance"
        assert parsed["year"] == 2020
        assert parsed["body_class"] == "Coupe"
        assert parsed["drive_type"] == "AWD"
        assert parsed["engine"]["hp"] == 306
        assert parsed["engine"]["kw"] == 225
        assert parsed["engine"]["fuel_type_normalized"] == "gasoline"
        assert parsed["transmission"]["type"] == "Automatic"

    def test_parse_real_autoref_api_payload(self):
        """Test parsing of actual AutoRef European API response with MODEL_RESOLVED and MOTORIZATION."""
        decoder = EuropeanVINDecoder()
        payload = [
            {
                "id": 130694,
                "VIN": "WF0FXXWPMH",
                "BRAND": "FORD",
                "BRAND_MODEL": "FORD KUGA 2.5 FHEV 4X4",
                "MODEL_FULL": "Kuga 2.5 FHEV 4x4",
                "MODEL_RESOLVED": "Kuga",
                "MODEL_LINE": "Kuga",
                "MOTORIZATION": "2.5 FHEV 4x4",
                "MODEL": None,
                "MODEL2": None,
                "MODEL3": None,
                "POWER_KW": 112.0,
                "POWER_DIN": 152.0,
                "FUEL": "Gasoline / Electric",
                "GEARBOX": "Continuously Variable",
                "CODE_GEARBOX": "S",
                "DATE_FIRST_CIRCULATION": 2022,
                "RECORD_TYPE": "TG",
                "DISPLACEMENT": 2488.0,
                "DOORS": "4+1",
                "DRIVETRAIN": "A (Front=Engageable)",
                "MOTOR_DETAILS": "4-stroke / 4 / inline-DI",
                "MANUFACTURER": "FORD-WERKE GmbH, D-50735 KOELN",
                "BODY": "Limousine",
            }
        ]

        parsed = decoder._parse_autoref_response("WF0FXXWPMHRC20114", payload)
        assert parsed is not None
        assert parsed["make"] == "FORD"
        assert parsed["model"] == "Kuga"
        assert parsed["trim"] == "2.5 FHEV 4x4"
        assert parsed["year"] == 2022
        assert parsed["doors"] == 4
        assert parsed["drive_type"] == "AWD"
        assert parsed["engine"]["hp"] == 152
        assert parsed["engine"]["kw"] == 112
        assert parsed["engine"]["displacement_l"] == "2.5"
        assert parsed["engine"]["cylinders"] == 4
        assert parsed["engine"]["fuel_type_secondary"] == "electric"
        assert parsed["transmission"]["type"] == "Continuously Variable"

    @pytest.mark.asyncio
    async def test_test_connection_no_key(self):
        decoder = EuropeanVINDecoder(api_key="")
        success, msg, data = await decoder.test_connection()
        assert success is False
        assert "required" in msg.lower()
        assert data is None

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        decoder = EuropeanVINDecoder(api_key="valid-test-key")
        usage_data = {
            "api_key_name": "user@example.com",
            "plan": "Test",
            "limit": 50,
            "remaining": 48,
            "used": 2,
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = usage_data

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            success, msg, data = await decoder.test_connection()
            assert success is True
            assert "Test" in msg
            assert "48/50" in msg
            assert data["remaining"] == 48

    @pytest.mark.asyncio
    async def test_test_connection_unauthorized(self):
        decoder = EuropeanVINDecoder(api_key="bad-key")

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
            success, msg, data = await decoder.test_connection()
            assert success is False
            assert "unauthorized" in msg.lower() or "invalid" in msg.lower()
            assert data is None
