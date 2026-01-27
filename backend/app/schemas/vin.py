"""Pydantic schemas for VIN-related operations."""


from pydantic import BaseModel, Field, field_validator


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
        # Remove whitespace and convert to uppercase
        v = v.strip().upper()

        # Check for invalid characters
        if any(char in v for char in ["I", "O", "Q"]):
            raise ValueError("VIN cannot contain the letters I, O, or Q")

        return v

    model_config = {"json_schema_extra": {"examples": [{"vin": "JA32U2FU9KU005963"}]}}


class EngineInfo(BaseModel):
    """Engine information from VIN decode."""

    displacement_l: str | None = Field(
        None, description="Engine displacement in liters"
    )
    cylinders: int | None = Field(None, description="Number of cylinders")
    hp: int | None = Field(None, description="Horsepower")
    kw: int | None = Field(None, description="Kilowatts")
    fuel_type: str | None = Field(None, description="Primary fuel type")


class TransmissionInfo(BaseModel):
    """Transmission information from VIN decode."""

    type: str | None = Field(None, description="Transmission type")
    speeds: str | None = Field(None, description="Number of speeds")


class VINDecodeResponse(BaseModel):
    """Response schema for VIN decode endpoint."""

    vin: str = Field(..., description="The decoded VIN")
    year: int | None = Field(None, description="Model year")
    make: str | None = Field(None, description="Vehicle make (manufacturer brand)")
    model: str | None = Field(None, description="Vehicle model")
    trim: str | None = Field(None, description="Trim level")
    vehicle_type: str | None = Field(None, description="Type of vehicle")
    body_class: str | None = Field(None, description="Body class/style")
    engine: EngineInfo | None = Field(None, description="Engine information")
    transmission: TransmissionInfo | None = Field(
        None, description="Transmission information"
    )
    drive_type: str | None = Field(
        None, description="Drive type (FWD, RWD, AWD, 4WD)"
    )
    manufacturer: str | None = Field(None, description="Manufacturer name")
    plant_city: str | None = Field(None, description="Manufacturing plant city")
    plant_country: str | None = Field(
        None, description="Manufacturing plant country"
    )
    doors: int | None = Field(None, description="Number of doors")
    gvwr: str | None = Field(None, description="Gross Vehicle Weight Rating")
    series: str | None = Field(None, description="Vehicle series")
    steering_location: str | None = Field(
        None, description="Steering wheel location"
    )
    entertainment_system: str | None = Field(
        None, description="Entertainment system"
    )
    error_code: str | None = Field(None, description="NHTSA error code (if any)")
    error_text: str | None = Field(None, description="NHTSA error text (if any)")

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
