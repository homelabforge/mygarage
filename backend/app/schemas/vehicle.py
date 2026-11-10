"""Pydantic schemas for Vehicle operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from app.constants import wheel_layouts
from app.constants.countries import is_country_code, normalize_country_code
from app.constants.fuel import FUEL_TYPE_VALUES, normalize_fuel_type
from app.constants.units import DistanceUnit
from app.constants.wheel_layouts import WheelLayoutId
from app.schemas._figures import to_stored_tenth
from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader
from app.utils.unit_resolution import LenientDistanceUnit
from app.utils.vehicle_key import IdentifierType


def _normalize_country_input(v: Any) -> Any:
    """Uppercase a country code and check it against ISO 3166-1 alpha-2.

    Wired on Create/Update only, like the fuel-type normaliser: a stored row
    reads back as it is, the input is what gets checked. Blank or null clears.
    """
    if v is None:
        return None
    code = normalize_country_code(str(v))
    if code is None:
        return None
    if not is_country_code(code):
        raise ValueError("registration_country must be an ISO 3166-1 alpha-2 code")
    return code


def _normalize_make_input(v: Any) -> Any:
    """Canonical make spelling for typed or decoded input (#219 takeover).

    A `mode="before"` validator on the writers only (`VehicleCreate`,
    `VehicleUpdate`, the external-vehicle schemas): a stored legacy
    `MITSUBISHI` must still read, so responses never normalize. A non-string
    is passed through for the field's own type check to refuse.
    """
    from app.utils.vehicle_names import normalize_make

    return normalize_make(v) if isinstance(v, str) else v


def _normalize_model_input(v: Any, info: ValidationInfo) -> Any:
    """Title Case for an ALL-CAPS model; mixed case stays as typed (#219 takeover).

    Reads the make validated just before it (``make`` is declared first), so
    a MINI ``ONE`` reads One; an update that leaves the make out matches the
    whole catalog.
    """
    from app.utils.vehicle_names import normalize_model

    make = info.data.get("make")
    return normalize_model(v, make if isinstance(make, str) else None) if isinstance(v, str) else v


def _normalize_fuel_type_input(v: Any) -> Any:
    """Normalize free-text / NHTSA fuel-type input to the canonical vocabulary.

    Used as a `mode="before"` validator on `VehicleCreate` / `VehicleUpdate`
    only, never on `VehicleBase`/`VehicleResponse`. Response schemas
    validate from DB attributes, and a legacy unrecognized value already
    persisted must not make a vehicle read 500.

    - `None` / empty / whitespace-only -> `None`
    - recognized (case/whitespace-insensitive) -> canonical enum value (str)
    - unrecognized -> `ValueError` (Pydantic turns this into a 422), listing
      the canonical values. Bulk import paths (see `import_data.py`) fall
      back to `other` on unrecognized input; interactive writes fail loudly
      instead.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    if not v.strip():
        return None
    normalized = normalize_fuel_type(v)
    if normalized is None:
        raise ValueError(f"fuel_type must be one of {FUEL_TYPE_VALUES}, got {v!r}")
    return normalized.value


# Shared vehicle type literal for OpenAPI schema generation
VehicleType = Literal[
    "Car",
    "Truck",
    "SUV",
    "Motorcycle",
    "ATV",
    "RV",
    "Trailer",
    "FifthWheel",
    "TravelTrailer",
    "Electric",
    "Hybrid",
    "Boat",
    "UTV",
    "Snowmobile",
    "Bicycle",
    "EBike",
    # Equipment without a VIN (#226): hour-metered by default, see the
    # frontend's HOURS_DEFAULT_TYPES. Attachment is an implement or head with
    # no engine of its own; it is not NON_MOTORIZED (that means "towed").
    "Tractor",
    "Mower",
    "Generator",
    "SmallEngine",
    "Attachment",
    "Equipment",
]

# Trailer-like types: no engine, no odometer, towed by something else.
NON_MOTORIZED_VEHICLE_TYPES: frozenset[str] = frozenset({"Trailer", "FifthWheel", "TravelTrailer"})

UsageUnit = Literal["distance", "hours"]

# For responses only. Neither column has a CHECK, so a restored backup can hold
# a type or unit we don't know, and a strict read 500s every vehicle list.
LenientVehicleType = Annotated[
    VehicleType | None, BeforeValidator(lenient_reader(VehicleType)), LenientVocab(None)
]
LenientUsageUnit = Annotated[
    UsageUnit | None, BeforeValidator(lenient_reader(UsageUnit)), LenientVocab(None)
]
LenientIdentifierType = Annotated[
    IdentifierType | None, BeforeValidator(lenient_reader(IdentifierType)), LenientVocab(None)
]
# A layout this build doesn't know reads as null, so it falls back to the type's default.
LenientWheelLayout = Annotated[
    WheelLayoutId | None, BeforeValidator(lenient_reader(WheelLayoutId)), LenientVocab(None)
]

_WHEEL_LAYOUT_DESCRIPTION = (
    "Which tire and brake corners the vehicle has; null follows the vehicle type's default (#272)"
)


def _clean_identifier(v: Any) -> Any:
    """Trim a typed identifier; a blank one is no identifier."""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class VehicleBase(BaseModel):
    """Base vehicle schema with common fields."""

    nickname: str = Field(
        ..., description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: VehicleType = Field(..., description="Type of vehicle")
    usage_unit: UsageUnit = Field(
        default="distance",
        description="Usage tracking dimension: 'distance' (odometer) or 'hours' (hour meter)",
    )
    current_hours: Annotated[Decimal | None, AfterValidator(to_stored_tenth)] = Field(
        default=None,
        description="Current engine-hour reading (used when usage_unit == 'hours')",
        ge=0,
        le=999999999.9,
    )
    secondary_usage_enabled: bool = Field(
        default=False,
        description="Also track the non-primary usage dimension (distance+hours dual tracking)",
    )
    distance_unit: DistanceUnit | None = Field(
        default=None,
        description=(
            "The unit this vehicle's odometer reads (km or mi); null follows the "
            "viewer's account. Distances and speeds for this vehicle show and are "
            "entered in it (#172)."
        ),
    )
    year: int | None = Field(default=None, description="Model year", ge=1900, le=2100)
    make: str | None = Field(default=None, description="Manufacturer brand", max_length=50)
    model: str | None = Field(default=None, description="Model name", max_length=50)
    license_plate: str | None = Field(
        default=None, description="License plate number", max_length=20
    )
    registration_country: str | None = Field(
        default=None,
        description=(
            "Country the vehicle is registered in (ISO 3166-1 alpha-2) when it differs "
            "from the owner's; drives inspection cadence, fuel pump names and tax types"
        ),
        min_length=2,
        max_length=2,
    )
    first_registration_date: date | None = Field(
        default=None,
        description="Date of first registration (field B of an EU registration certificate)",
    )
    inspection_due_date: date | None = Field(
        default=None,
        description=(
            "Next periodic inspection due by (field X.1 of an EU registration "
            "certificate); the reminder holds to it within the current cycle"
        ),
    )
    # The other EU registration-certificate fields (#211). Bounds are the
    # input's; the response reads what is stored.
    euro_emission_class: str | None = Field(
        default=None,
        description="Euro emission class, field V.9 of an EU registration certificate (Euro 6d-TEMP)",
        max_length=12,
    )
    fiscal_power: int | None = Field(
        default=None, description="National fiscal power, field P.6 (French CV)", ge=0, le=200
    )
    co2_g_km: int | None = Field(
        default=None, description="CO₂ emissions in g/km, field V.7", ge=0, le=999
    )
    power_kw: int | None = Field(
        default=None, description="Maximum net power in kW, field P.2", ge=0, le=2000
    )
    eu_category: str | None = Field(
        default=None, description="EU vehicle category, field J (M1, N1, L3e)", max_length=5
    )
    national_category: str | None = Field(
        default=None, description="National vehicle kind, field J.1 (VP, CTTE, MTL)", max_length=10
    )
    lez_class: str | None = Field(
        default=None,
        description=(
            "Low-emission-zone class set by hand (Crit'Air 0-5, Umweltplakette 2-4); "
            "overrides the class computed from the fuel and the Euro class"
        ),
        max_length=10,
    )
    color: str | None = Field(default=None, description="Vehicle color", max_length=30)
    purchase_date: date | None = Field(default=None, description="Date purchased")
    purchase_price: OptionalMoney = Field(default=None, description="Purchase price")
    sold_date: date | None = Field(default=None, description="Date sold")
    sold_price: OptionalMoney = Field(default=None, description="Sale price")
    # VIN decoded fields
    trim: str | None = Field(default=None, description="Trim level", max_length=50)
    body_class: str | None = Field(default=None, description="Body class", max_length=100)
    drive_type: str | None = Field(
        default=None, description="Drive type (FWD, RWD, AWD, etc.)", max_length=30
    )
    doors: int | None = Field(default=None, description="Number of doors")
    gvwr_class: str | None = Field(default=None, description="GVWR class", max_length=50)
    displacement_l: str | None = Field(
        default=None, description="Engine displacement in liters", max_length=20
    )
    cylinders: int | None = Field(default=None, description="Number of cylinders")
    fuel_type: str | None = Field(
        default=None, description="Fuel type (primary capability)", max_length=50
    )
    fuel_type_secondary: str | None = Field(
        default=None,
        description=(
            "Secondary fuel capability for PHEV / flex / dual-fuel vehicles. "
            "Stored as a FuelTypeEnum value."
        ),
        max_length=20,
    )
    transmission_type: str | None = Field(
        default=None, description="Transmission type", max_length=50
    )
    transmission_speeds: str | None = Field(
        default=None, description="Transmission speeds", max_length=20
    )
    # DEF tracking
    def_tank_capacity_liters: Decimal | None = Field(
        default=None, description="DEF tank capacity in liters", ge=0, le=9999.99
    )
    # Structured maintenance specs (oil / torque / fluids)
    oil_viscosity: str | None = Field(
        default=None, description="Engine oil viscosity grade (e.g. 5W-30)", max_length=30
    )
    oil_capacity_liters: Decimal | None = Field(
        default=None, description="Engine oil capacity in liters (with filter)", ge=0, le=999.99
    )
    oil_filter_part_number: str | None = Field(
        default=None, description="Oil filter part number", max_length=50
    )
    fuel_filter_part_number: str | None = Field(
        default=None, description="Fuel filter part number", max_length=50
    )
    lug_nut_torque_nm: Decimal | None = Field(
        default=None, description="Wheel lug-nut torque in Newton-meters", ge=0, le=99999.9
    )
    coolant_type: str | None = Field(
        default=None, description="Coolant / antifreeze type", max_length=50
    )
    brake_fluid_type: str | None = Field(
        default=None, description="Brake fluid type (e.g. DOT 4)", max_length=30
    )
    transmission_fluid_type: str | None = Field(
        default=None, description="Transmission fluid type", max_length=50
    )
    maintenance_specs_notes: str | None = Field(
        default=None, description="Freeform notes for other fluid/torque specs", max_length=500
    )
    # Not in reject_null on the update: an explicit null is how you go back to automatic.
    wheel_layout: WheelLayoutId | None = Field(default=None, description=_WHEEL_LAYOUT_DESCRIPTION)


class VehicleCreate(VehicleBase):
    """Schema for creating a new vehicle."""

    vin: str | None = Field(
        default=None,
        description=(
            "17-character Vehicle Identification Number. Required when identifier_type "
            "is 'vin'; omitted otherwise (the server generates the vehicle's key)."
        ),
        min_length=17,
        max_length=17,
    )
    identifier_type: IdentifierType = Field(
        default="vin",
        description=(
            "What identifies this vehicle: its VIN, or for equipment and vehicles "
            "without one a serial number, HIN, chassis number, asset tag, or none (#226)"
        ),
    )
    identifier: str | None = Field(
        default=None,
        description="The serial / HIN / chassis number / asset tag (not used for 'vin' or 'none')",
        max_length=64,
    )

    @field_validator("vin")
    @classmethod
    def validate_vin_format(cls, v: str | None) -> str | None:
        """Validate VIN format."""
        from app.utils.vin import validate_vin

        if v is None:
            return None
        v = v.strip().upper()
        is_valid, error = validate_vin(v)
        if not is_valid:
            raise ValueError(error or "Invalid VIN format")
        return v

    @field_validator("identifier", mode="before")
    @classmethod
    def clean_identifier(cls, v: Any) -> Any:
        """Trim a typed identifier; a blank one is no identifier."""
        return _clean_identifier(v)

    @model_validator(mode="after")
    def _identity_matches_its_type(self) -> Self:
        """A VIN vehicle sends a VIN; any other kind sends no VIN (#226)."""
        if self.identifier_type == "vin":
            if not self.vin:
                raise ValueError("vin is required when identifier_type is 'vin'")
            if self.identifier:
                raise ValueError("identifier is only used when identifier_type is not 'vin'")
            return self
        if self.vin:
            raise ValueError("vin must be omitted when identifier_type is not 'vin'")
        if self.identifier_type == "none":
            if self.identifier:
                raise ValueError("identifier must be empty when identifier_type is 'none'")
        elif not self.identifier:
            raise ValueError(
                f"identifier is required when identifier_type is '{self.identifier_type}'"
            )
        return self

    @field_validator("make", mode="before")
    @classmethod
    def normalize_make(cls, v: Any) -> Any:
        """Canonical make spelling (#219 takeover)."""
        return _normalize_make_input(v)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, v: Any, info: ValidationInfo) -> Any:
        """Title Case for an ALL-CAPS model (#219 takeover)."""
        return _normalize_model_input(v, info)

    @field_validator("fuel_type", "fuel_type_secondary", mode="before")
    @classmethod
    def normalize_fuel_type_fields(cls, v: Any) -> Any:
        """Normalize free-text fuel-type input to the canonical vocabulary."""
        return _normalize_fuel_type_input(v)

    @field_validator("registration_country", mode="before")
    @classmethod
    def normalize_registration_country(cls, v: Any) -> Any:
        """Uppercase and check the country code (#211)."""
        return _normalize_country_input(v)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "nickname": "Red Mirage",
                    "vehicle_type": "Car",
                    "year": 2019,
                    "make": "MITSUBISHI",
                    "model": "Mirage",
                    "license_plate": "ABC-1234",
                    "color": "Red",
                    "purchase_date": "2019-03-15",
                    "purchase_price": 15000.00,
                }
            ]
        }
    }


class VehicleUpdate(VehicleBase):
    """Schema for updating an existing vehicle."""

    nickname: str | None = Field(
        default=None, description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: VehicleType | None = Field(default=None, description="Type of vehicle")
    # The key never changes; what identifies the vehicle can (#226). The rules
    # that need the stored key live in VehicleService.update_vehicle.
    identifier_type: IdentifierType | None = Field(
        default=None,
        description="vin, serial, hin, chassis, asset_tag or none (omit to leave unchanged)",
    )
    identifier: str | None = Field(
        default=None, description="Serial / HIN / chassis number / asset tag", max_length=64
    )
    # Overridden as optional: VehicleBase gives these non-null defaults, which
    # the generated OpenAPI otherwise marks REQUIRED, forcing every partial
    # update (equipment/pricing sidecars) to resend them. exclude_unset makes an
    # omitted field a no-op, so callers editing unrelated fields can drop them.
    usage_unit: UsageUnit | None = Field(
        default=None, description="Usage tracking dimension (omit to leave unchanged)"
    )
    secondary_usage_enabled: bool | None = Field(
        default=None, description="Dual distance+hours tracking (omit to leave unchanged)"
    )
    # Equipment is editable from the vehicle-detail sidecar. Declared here (not
    # only on VehicleResponse) so partial PUTs actually persist it: Pydantic's
    # default extra='ignore' silently drops unknown keys otherwise.
    standard_equipment: dict[str, Any] | None = Field(
        default=None, description="Standard equipment (category -> list of items)"
    )
    optional_equipment: dict[str, Any] | None = Field(
        default=None, description="Optional equipment (category -> list of items)"
    )
    # MSRP is editable from the pricing sidecar. Like equipment, these live only
    # on VehicleResponse otherwise, so a PUT would silently drop them.
    msrp_base: OptionalMoney = Field(default=None, description="MSRP base price")
    msrp_options: OptionalMoney = Field(default=None, description="MSRP options total")
    msrp_total: OptionalMoney = Field(default=None, description="MSRP total")
    destination_charge: OptionalMoney = Field(default=None, description="Destination charge")
    # Window-sticker / VIN-decoded descriptive fields, editable from the
    # vehicle-detail card sidecars (Basic Information / Vehicle Details /
    # Powertrain / Warranty). Same rationale as equipment/MSRP: they live only
    # on VehicleResponse otherwise, so a partial PUT would silently drop them.
    # max_length mirrors the model columns (app/models/vehicle.py).
    exterior_color: str | None = Field(default=None, description="Exterior color", max_length=100)
    interior_color: str | None = Field(default=None, description="Interior color", max_length=100)
    wheel_specs: str | None = Field(
        default=None, description="Wheel specifications", max_length=100
    )
    tire_specs: str | None = Field(default=None, description="Tire specifications", max_length=100)
    warranty_basic: str | None = Field(default=None, description="Basic warranty", max_length=100)
    warranty_powertrain: str | None = Field(
        default=None, description="Powertrain warranty", max_length=100
    )
    sticker_engine_description: str | None = Field(
        default=None, description="Engine description (window sticker)", max_length=150
    )
    sticker_transmission_description: str | None = Field(
        default=None, description="Transmission description (window sticker)", max_length=150
    )
    sticker_drivetrain: str | None = Field(
        default=None, description="Drivetrain (window sticker)", max_length=50
    )
    assembly_location: str | None = Field(
        default=None, description="Assembly location", max_length=100
    )

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null(
        "nickname", "vehicle_type", "usage_unit", "secondary_usage_enabled", "identifier_type"
    )

    @field_validator("identifier", mode="before")
    @classmethod
    def clean_identifier(cls, v: Any) -> Any:
        """Trim a typed identifier; a blank one is no identifier."""
        return _clean_identifier(v)

    @field_validator("make", mode="before")
    @classmethod
    def normalize_make(cls, v: Any) -> Any:
        """Canonical make spelling (#219 takeover)."""
        return _normalize_make_input(v)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, v: Any, info: ValidationInfo) -> Any:
        """Title Case for an ALL-CAPS model (#219 takeover)."""
        return _normalize_model_input(v, info)

    @field_validator("fuel_type", "fuel_type_secondary", mode="before")
    @classmethod
    def normalize_fuel_type_fields(cls, v: Any) -> Any:
        """Normalize free-text fuel-type input to the canonical vocabulary."""
        return _normalize_fuel_type_input(v)

    @field_validator("registration_country", mode="before")
    @classmethod
    def normalize_registration_country(cls, v: Any) -> Any:
        """Uppercase and check the country code (#211)."""
        return _normalize_country_input(v)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "nickname": "My Red Mirage",
                    "license_plate": "XYZ-5678",
                    "color": "Cherry Red",
                }
            ]
        }
    }


class VehicleResponse(VehicleBase):
    """Schema for vehicle response."""

    # Read what's stored: a type or unit outside today's list comes back null
    # (and logs once) instead of 500ing every page with this vehicle on it.
    vehicle_type: LenientVehicleType = Field(..., description="Type of vehicle")
    usage_unit: LenientUsageUnit = Field(
        default="distance",
        description="Usage tracking dimension: 'distance' (odometer) or 'hours' (hour meter)",
    )
    # Numbers without the input bounds, so a stored value past today's rules
    # (a legacy negative price, say) still reads (test_response_contract).
    current_hours: Decimal | None = Field(
        default=None, description="Current engine-hour reading (used when usage_unit == 'hours')"
    )
    year: int | None = Field(default=None, description="Model year")
    purchase_price: Decimal | None = Field(default=None, description="Purchase price")
    sold_price: Decimal | None = Field(default=None, description="Sale price")
    def_tank_capacity_liters: Decimal | None = Field(
        default=None, description="DEF tank capacity in liters"
    )
    oil_capacity_liters: Decimal | None = Field(
        default=None, description="Engine oil capacity in liters (with filter)"
    )
    lug_nut_torque_nm: Decimal | None = Field(
        default=None, description="Wheel lug-nut torque in Newton-meters"
    )
    # Text without the input rules, so a stored string past today's limits (an
    # OCR'd colour too long for the form, say) still reads (test_response_contract).
    nickname: str = Field(..., description="User-friendly display name")
    make: str | None = Field(default=None, description="Manufacturer brand")
    model: str | None = Field(default=None, description="Model name")
    license_plate: str | None = Field(default=None, description="License plate number")
    registration_country: str | None = Field(
        default=None,
        description=(
            "Country the vehicle is registered in (ISO 3166-1 alpha-2) when it differs "
            "from the owner's; drives inspection cadence, fuel pump names and tax types"
        ),
    )
    color: str | None = Field(default=None, description="Vehicle color")
    euro_emission_class: str | None = Field(
        default=None,
        description="Euro emission class, field V.9 of an EU registration certificate (Euro 6d-TEMP)",
    )
    fiscal_power: int | None = Field(
        default=None, description="National fiscal power, field P.6 (French CV)"
    )
    co2_g_km: int | None = Field(default=None, description="CO₂ emissions in g/km, field V.7")
    power_kw: int | None = Field(default=None, description="Maximum net power in kW, field P.2")
    eu_category: str | None = Field(
        default=None, description="EU vehicle category, field J (M1, N1, L3e)"
    )
    national_category: str | None = Field(
        default=None, description="National vehicle kind, field J.1 (VP, CTTE, MTL)"
    )
    lez_class: str | None = Field(
        default=None,
        description=(
            "Low-emission-zone class set by hand (Crit'Air 0-5, Umweltplakette 2-4); "
            "overrides the class computed from the fuel and the Euro class"
        ),
    )
    trim: str | None = Field(default=None, description="Trim level")
    body_class: str | None = Field(default=None, description="Body class")
    drive_type: str | None = Field(default=None, description="Drive type (FWD, RWD, AWD, etc.)")
    gvwr_class: str | None = Field(default=None, description="GVWR class")
    displacement_l: str | None = Field(default=None, description="Engine displacement in liters")
    fuel_type: str | None = Field(default=None, description="Fuel type (primary capability)")
    fuel_type_secondary: str | None = Field(
        default=None,
        description=(
            "Secondary fuel capability for PHEV / flex / dual-fuel vehicles. "
            "Stored as a FuelTypeEnum value."
        ),
    )
    transmission_type: str | None = Field(default=None, description="Transmission type")
    transmission_speeds: str | None = Field(default=None, description="Transmission speeds")
    oil_viscosity: str | None = Field(
        default=None, description="Engine oil viscosity grade (e.g. 5W-30)"
    )
    oil_filter_part_number: str | None = Field(default=None, description="Oil filter part number")
    fuel_filter_part_number: str | None = Field(default=None, description="Fuel filter part number")
    coolant_type: str | None = Field(default=None, description="Coolant / antifreeze type")
    brake_fluid_type: str | None = Field(default=None, description="Brake fluid type (e.g. DOT 4)")
    transmission_fluid_type: str | None = Field(default=None, description="Transmission fluid type")
    maintenance_specs_notes: str | None = Field(
        default=None, description="Freeform notes for other fluid/torque specs"
    )
    vin: str = Field(
        ...,
        description=(
            "The vehicle's key. The VIN when identifier_type is 'vin'; otherwise a "
            "generated key that is not a VIN and must not be shown (#226)."
        ),
    )
    identifier_type: LenientIdentifierType = Field(
        default="vin", description="What identifies this vehicle"
    )
    identifier: str | None = Field(
        default=None, description="Serial / HIN / chassis number / asset tag"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_vin(self) -> bool:
        """Whether `vin` is a real VIN (decode, recalls and VIN display apply)."""
        return self.identifier_type == "vin"

    wheel_layout: LenientWheelLayout = Field(default=None, description=_WHEEL_LAYOUT_DESCRIPTION)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_wheel_layout(self) -> WheelLayoutId:
        """The layout in force: the stored override, else the vehicle type's default (#272)."""
        return wheel_layouts.resolve_wheel_layout(
            self.wheel_layout, self.vehicle_type, vin=self.vin
        ).id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def default_wheel_layout(self) -> WheelLayoutId:
        """The layout the vehicle type gets with no override, for the Automatic option (#272)."""
        return wheel_layouts.default_wheel_layout(self.vehicle_type)

    # Served, never refused: the column has no CHECK, and a strict Literal here
    # would turn one hand-edited row into a 500 for every response carrying it.
    distance_unit: LenientDistanceUnit = Field(
        default=None,
        description=(
            "The unit this vehicle's odometer reads (km or mi); null follows the "
            "viewer's account. Distances and speeds for this vehicle show and are "
            "entered in it (#172)."
        ),
    )
    main_photo: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # Window sticker fields
    window_sticker_file_path: str | None = None
    window_sticker_uploaded_at: datetime | None = None
    msrp_base: Decimal | None = None
    msrp_options: Decimal | None = None
    msrp_total: Decimal | None = None
    fuel_economy_city_l_per_100km: Decimal | None = None
    fuel_economy_highway_l_per_100km: Decimal | None = None
    fuel_economy_combined_l_per_100km: Decimal | None = None
    standard_equipment: dict[str, Any] | None = None
    optional_equipment: dict[str, Any] | None = None
    assembly_location: str | None = None
    # Enhanced window sticker fields
    destination_charge: Decimal | None = None
    window_sticker_options_detail: dict[str, Any] | None = None
    window_sticker_packages: dict[str, Any] | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    sticker_engine_description: str | None = None
    sticker_transmission_description: str | None = None
    sticker_drivetrain: str | None = None
    wheel_specs: str | None = None
    tire_specs: str | None = None
    warranty_powertrain: str | None = None
    warranty_basic: str | None = None
    environmental_rating_ghg: str | None = None
    environmental_rating_smog: str | None = None
    window_sticker_parser_used: str | None = None
    window_sticker_confidence_score: Decimal | None = None
    window_sticker_extracted_vin: str | None = None
    # Archive fields
    archived_at: datetime | None = None
    archive_reason: str | None = None
    archive_sale_price: Decimal | None = None
    archive_sale_date: date | None = None
    archive_notes: str | None = None
    archived_visible: bool = True
    # GPS location tracking opt-out (default on), migration 075, #118
    location_tracking_enabled: bool = True

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "nickname": "Red Mirage",
                    "vehicle_type": "Car",
                    "year": 2019,
                    "make": "MITSUBISHI",
                    "model": "Mirage",
                    "license_plate": "ABC-1234",
                    "color": "Red",
                    "purchase_date": "2019-03-15",
                    "purchase_price": 15000.00,
                    "main_photo": "/data/photos/ML32A5HJ9KH009478/main.jpg",
                    "created_at": "2025-11-07T22:00:00",
                    "updated_at": None,
                }
            ]
        },
    }


class VehicleListResponse(BaseModel):
    """Schema for vehicle list response."""

    vehicles: list[VehicleResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vehicles": [
                        {
                            "vin": "ML32A5HJ9KH009478",
                            "nickname": "Red Mirage",
                            "vehicle_type": "Car",
                            "year": 2019,
                            "make": "MITSUBISHI",
                            "model": "Mirage",
                            "main_photo": None,
                            "created_at": "2025-11-07T22:00:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class TrailerDetailsBase(BaseModel):
    """Base schema for trailer details."""

    gvwr_kg: Decimal | None = Field(default=None, description="Gross Vehicle Weight Rating (kg)")
    hitch_type: str | None = Field(default=None, description="Hitch type")
    axle_count: int | None = Field(default=None, description="Number of axles", ge=1, le=10)
    brake_type: str | None = Field(default=None, description="Brake type")
    length_m: Decimal | None = Field(default=None, description="Length in meters")
    width_m: Decimal | None = Field(default=None, description="Width in meters")
    height_m: Decimal | None = Field(default=None, description="Height in meters")
    tow_vehicle_vin: str | None = Field(
        default=None, description="VIN of tow vehicle", min_length=17, max_length=17
    )

    @field_validator("hitch_type")
    @classmethod
    def validate_hitch_type(cls, v: str | None) -> str | None:
        """Validate hitch type."""
        if v is None:
            return v
        valid_types = ["Ball", "Pintle", "Fifth Wheel", "Gooseneck"]
        if v not in valid_types:
            raise ValueError(f"Hitch type must be one of: {', '.join(valid_types)}")
        return v

    @field_validator("brake_type")
    @classmethod
    def validate_brake_type(cls, v: str | None) -> str | None:
        """Validate brake type."""
        if v is None:
            return v
        valid_types = ["None", "Electric", "Hydraulic"]
        if v not in valid_types:
            raise ValueError(f"Brake type must be one of: {', '.join(valid_types)}")
        return v


class TrailerDetailsCreate(TrailerDetailsBase):
    """Schema for creating trailer details."""

    vin: str = Field(..., description="VIN of the trailer", min_length=17, max_length=17)


class TrailerDetailsUpdate(TrailerDetailsBase):
    """Schema for updating trailer details."""

    pass


class TrailerDetailsResponse(TrailerDetailsBase):
    """Schema for trailer details response."""

    # No input bounds, so a stored count past today's rules still reads
    # instead of 500ing (test_response_contract).
    axle_count: int | None = Field(default=None, description="Number of axles")
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    tow_vehicle_vin: str | None = Field(default=None, description="VIN of tow vehicle")
    vin: str

    model_config = {"from_attributes": True}


class VehicleArchiveRequest(BaseModel):
    """Schema for archiving a vehicle."""

    reason: str = Field(
        ...,
        description="Reason for archiving (Sold, Totaled, Gifted, Trade-in, Other)",
        max_length=50,
    )
    sale_price: OptionalMoney = Field(default=None, description="Sale price (if applicable)")
    sale_date: date | None = Field(default=None, description="Sale/disposal date")
    notes: str | None = Field(
        default=None, description="Additional notes about the archive", max_length=1000
    )
    visible: bool = Field(
        default=True, description="Whether to show vehicle in main list with watermark"
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate archive reason."""
        valid_reasons = ["Sold", "Totaled", "Gifted", "Trade-in", "Other"]
        if v not in valid_reasons:
            raise ValueError(f"Archive reason must be one of: {', '.join(valid_reasons)}")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reason": "Sold",
                    "sale_price": 25000.00,
                    "sale_date": "2025-12-01",
                    "notes": "Sold to private buyer via Craigslist",
                    "visible": True,
                }
            ]
        }
    }


class VehicleBulkArchiveRequest(BaseModel):
    """Archive multiple vehicles with the same metadata."""

    vins: list[str] = Field(..., min_length=1, max_length=50)
    reason: str = Field(..., max_length=50)
    sale_price: OptionalMoney = None
    sale_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    visible: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        valid_reasons = ["Sold", "Totaled", "Gifted", "Trade-in", "Other"]
        if v not in valid_reasons:
            raise ValueError(f"Archive reason must be one of: {', '.join(valid_reasons)}")
        return v

    @field_validator("vins")
    @classmethod
    def normalize_vins(cls, v: list[str]) -> list[str]:
        return [vin.upper().strip() for vin in v if vin and vin.strip()]


class VehicleDetailStats(BaseModel):
    """Read-aggregation for the Vehicle Detail hero + key-facts strip.

    Metric-canonical: latest_odometer_km is raw km (frontend converts at the
    boundary). spent_this_year is currency (Decimal -> JSON string).
    """

    overdue_count: int
    upcoming_count: int
    # The subset of upcoming that is due soon: expected within DUE_SOON_WINDOW,
    # or DUE_SOON_PROGRESS along a usage span no rate can project (#192).
    # The hero badge (reminder_service.reminder_due_status, as on the dashboard).
    due_soon_count: int
    usage_unit: LenientUsageUnit  # drives the odometer/hours relabel
    # Kept for API compat only, NO LONGER the display source. The
    # canonical reading is `latest_hours` below, via `latest_engine_hours_and_date`.
    current_hours: Decimal | None  # required-but-nullable, legacy column value
    # Canonical latest engine-hours reading + hours-economy
    # figures, required-but-nullable, NO `= None` default. Null for a
    # pure-distance vehicle.
    latest_hours: Decimal | None
    average_l_per_hr: Decimal | None
    average_cost_per_hr: Decimal | None
    secondary_usage_enabled: bool
    latest_odometer_km: Decimal | None  # required-but-nullable, NO `= None` default
    latest_odometer_date: date | None  # required-but-nullable, NO `= None` default
    last_service_date: date | None  # required-but-nullable, NO `= None` default
    last_fillup_date: date | None  # required-but-nullable, NO `= None` default
    spent_this_year: Decimal
    year: int
