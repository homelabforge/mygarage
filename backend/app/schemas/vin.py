"""Pydantic schemas for VIN-related operations."""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants.countries import is_country_code, normalize_country_code

#: The decoders (#219 takeover).
Provider = Literal["nhtsa", "autoref"]
#: AutoRef's own record types, the ones with a full record to pick.
AutoRefRecordType = Literal["TG", "COC", "OLD", "OC", "X"]
#: AutoRef's gearbox codes.
AutoRefGearboxCode = Literal["M", "A", "S", "H"]


def vin_input(v: str) -> str:
    """Uppercase a VIN and refuse the letters a VIN never holds."""
    v = v.strip().upper()
    if any(char in v for char in ["I", "O", "Q"]):
        raise ValueError("VIN cannot contain the letters I, O, or Q")
    return v


def country_input(v: str | None) -> str | None:
    """Uppercase an ISO 3166-1 alpha-2 code and refuse an unknown one."""
    code = normalize_country_code(v)
    if code is None:
        return None
    if not is_country_code(code):
        raise ValueError("country must be an ISO 3166-1 alpha-2 code")
    return code


class VINDecodeRequest(BaseModel):
    """Request schema for VIN decode endpoint."""

    vin: str = Field(
        ...,
        description="17-character Vehicle Identification Number",
        min_length=17,
        max_length=17,
    )

    @field_validator("vin")
    @classmethod
    def validate_vin_format(cls, v: str) -> str:
        """Validate VIN format."""
        return vin_input(v)

    provider: Provider | None = Field(
        default=None,
        description=(
            "The decoder the person chose. Omitted means Automatic: the preferred "
            "decoder first, NHTSA when AutoRef has no answer"
        ),
    )
    country: str | None = Field(
        default=None,
        description=(
            "The country deciding which decoder Automatic asks first (the vehicle's "
            "registration country, else the person's); omitted reads the account's"
        ),
    )

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str | None) -> str | None:
        """Uppercase and check the country code."""
        return country_input(v)

    model_config = {"json_schema_extra": {"examples": [{"vin": "JA32U2FU9KU005963"}]}}


class EngineInfo(BaseModel):
    """Engine information from VIN decode."""

    displacement_l: str | None = Field(default=None, description="Engine displacement in liters")
    cylinders: int | None = Field(default=None, description="Number of cylinders")
    hp: int | None = Field(default=None, description="Horsepower")
    kw: int | None = Field(default=None, description="Kilowatts")
    fuel_type: str | None = Field(default=None, description="Primary fuel type (raw NHTSA string)")
    fuel_type_normalized: str | None = Field(
        default=None,
        description="Primary fuel type normalized to FuelTypeEnum vocabulary",
    )
    fuel_type_secondary: str | None = Field(
        default=None,
        description=(
            "Secondary fuel capability (PHEV / flex / dual-fuel), normalized to "
            "FuelTypeEnum vocabulary. Sourced from NHTSA FuelTypeSecondary, with "
            "fallback decoding of combined FuelTypePrimary strings."
        ),
    )


class TransmissionInfo(BaseModel):
    """Transmission information from VIN decode."""

    type: str | None = Field(default=None, description="Transmission type")
    speeds: str | None = Field(default=None, description="Number of speeds")


class AutoRefCandidate(BaseModel):
    """One version AutoRef matched for a VIN, to pick from."""

    record_type: AutoRefRecordType = Field(..., description="The record type of its full record")
    id: str = Field(..., description="The id of its full record (ephemeral: pick it right away)")
    label: str = Field(..., description="AutoRef's name for the version")
    model_full: str | None = Field(
        default=None, description="AutoRef's MODEL_FULL, echoed on a pick"
    )
    fuel_type: str | None = Field(
        default=None, description="Fuel normalized to FuelTypeEnum vocabulary"
    )
    kw: int | None = Field(default=None, description="Power in kW, echoed on a pick")
    transmission: str | None = Field(default=None, description="Transmission type")
    gearbox_code: AutoRefGearboxCode | None = Field(
        default=None,
        description="AutoRef's gearbox code, echoed on a pick (the full record has none)",
    )
    grouped: bool = Field(default=False, description="It stands for several configurations")


class VINDecodeResponse(BaseModel):
    """Response schema for VIN decode endpoint."""

    vin: str = Field(..., description="The decoded VIN")
    year: int | None = Field(default=None, description="Model year")
    make: str | None = Field(default=None, description="Vehicle make (manufacturer brand)")
    model: str | None = Field(default=None, description="Vehicle model")
    trim: str | None = Field(default=None, description="Trim level")
    vehicle_type: str | None = Field(default=None, description="Type of vehicle")
    body_class: str | None = Field(default=None, description="Body class/style")
    engine: EngineInfo | None = Field(default=None, description="Engine information")
    transmission: TransmissionInfo | None = Field(
        default=None, description="Transmission information"
    )
    drive_type: str | None = Field(default=None, description="Drive type (FWD, RWD, AWD, 4WD)")
    manufacturer: str | None = Field(default=None, description="Manufacturer name")
    plant_city: str | None = Field(default=None, description="Manufacturing plant city")
    plant_country: str | None = Field(default=None, description="Manufacturing plant country")
    doors: int | None = Field(default=None, description="Number of doors")
    gvwr: str | None = Field(default=None, description="Gross Vehicle Weight Rating")
    series: str | None = Field(default=None, description="Vehicle series")
    steering_location: str | None = Field(default=None, description="Steering wheel location")
    entertainment_system: str | None = Field(default=None, description="Entertainment system")
    error_code: str | None = Field(default=None, description="NHTSA error code (if any)")
    error_text: str | None = Field(default=None, description="NHTSA error text (if any)")
    # What the VIN itself says (#211), read from the bundled WMI table.
    region: str | None = Field(
        default=None,
        description="Region of the first character (ISO 3780): AF, AS, EU, NA, OC, SA",
    )
    wmi_country: str | None = Field(
        default=None, description="Country of manufacture from the WMI (ISO 3166-1 alpha-2)"
    )
    decode_quality: Literal["full", "partial", "wmi_only", "none"] | None = Field(
        default=None,
        description=(
            "How much NHTSA itself decoded, before the WMI table fills anything. "
            "full: make and model; partial: make only; wmi_only: NHTSA named no make "
            "and the VIN's first three characters did; none: nothing"
        ),
    )
    make_source: Literal["nhtsa", "wmi", "autoref"] | None = Field(
        default=None,
        description="Where `make` came from: NHTSA's answer, AutoRef's, or the bundled WMI table",
    )
    decoded_by: Provider | None = Field(
        default=None, description="Which decoder answered: nhtsa or autoref"
    )
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "What to check: eu_vin_no_model, year_unreliable, check_digit_not_applicable; "
            "autoref_best_guess, autoref_pick_version, autoref_external_record; and when "
            "Automatic fell back "
            "to NHTSA, autoref_no_match, autoref_key_rejected, autoref_quota, "
            "autoref_unavailable"
        ),
    )

    candidates: list[AutoRefCandidate] | None = Field(
        default=None,
        description=(
            "AutoRef's versions for this VIN when it matched more than one, most "
            "registered first; pick one with POST /vin/autoref/version"
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "JA32U2FU9KU005963",
                    "year": 2019,
                    "make": "Mitsubishi",
                    "model": "Mirage",
                    "trim": "LE",
                    "vehicle_type": "PASSENGER CAR",
                    "body_class": "Hatchback/Liftback/Notchback",
                    "engine": {
                        "displacement_l": "1.2",
                        "cylinders": 3,
                        "fuel_type": "Gasoline",
                    },
                    "transmission": {
                        "type": "Continuously Variable (CVT)",
                    },
                    "drive_type": "FWD",
                    "manufacturer": "MITSUBISHI MOTORS CORPORATION",
                    "plant_country": "THAILAND",
                    "doors": 4,
                }
            ]
        }
    }


class AutoRefVersionRequest(BaseModel):
    """A version picked from a decode's ``candidates``, echoed back to check it."""

    vin: str = Field(..., min_length=17, max_length=17, description="The decoded VIN")
    record_type: AutoRefRecordType
    id: str = Field(..., pattern=r"^[A-Za-z0-9]{1,32}$")
    gearbox_code: AutoRefGearboxCode | None = None
    expect_model: str | None = Field(
        default=None, max_length=200, description="The candidate's model_full"
    )
    expect_kw: int | None = Field(default=None, ge=0, le=2000, description="The candidate's kw")
    grouped: bool = False

    @field_validator("vin")
    @classmethod
    def validate_vin_format(cls, v: str) -> str:
        """Validate VIN format."""
        return vin_input(v)

    @model_validator(mode="after")
    def needs_an_expectation(self) -> Self:
        """A pick carries a model or a power, or its record can't be checked."""
        if self.expect_model is None and self.expect_kw is None:
            raise ValueError("expect_model or expect_kw is required")
        return self


class VINProvidersResponse(BaseModel):
    """The decoders this instance can use, and which one Automatic asks first."""

    available: list[Provider] = Field(..., description="nhtsa always; autoref when it has a key")
    preferred: Provider = Field(..., description="The decoder Automatic asks first")


class AutoRefTestRequest(BaseModel):
    """An AutoRef key to test; null or the mask tests the stored one."""

    api_key: str | None = Field(default=None, max_length=200)


class AutoRefTestResponse(BaseModel):
    """Whether AutoRef accepts the key, and what's left of its plan."""

    valid: bool
    message: str
    plan: str | None = None
    remaining: int | None = None
    limit: int | None = None
