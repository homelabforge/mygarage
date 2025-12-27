"""Pydantic schemas for VIN-related operations."""

from typing import Optional
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

    displacement_l: Optional[str] = Field(
        None, description="Engine displacement in liters"
    )
    cylinders: Optional[int] = Field(None, description="Number of cylinders")
    hp: Optional[int] = Field(None, description="Horsepower")
    kw: Optional[int] = Field(None, description="Kilowatts")
    fuel_type: Optional[str] = Field(None, description="Primary fuel type")


class TransmissionInfo(BaseModel):
    """Transmission information from VIN decode."""

    type: Optional[str] = Field(None, description="Transmission type")
    speeds: Optional[str] = Field(None, description="Number of speeds")


class VINDecodeResponse(BaseModel):
    """Response schema for VIN decode endpoint."""

    vin: str = Field(..., description="The decoded VIN")
    year: Optional[int] = Field(None, description="Model year")
    make: Optional[str] = Field(None, description="Vehicle make (manufacturer brand)")
    model: Optional[str] = Field(None, description="Vehicle model")
    trim: Optional[str] = Field(None, description="Trim level")
    vehicle_type: Optional[str] = Field(None, description="Type of vehicle")
    body_class: Optional[str] = Field(None, description="Body class/style")
    engine: Optional[EngineInfo] = Field(None, description="Engine information")
    transmission: Optional[TransmissionInfo] = Field(
        None, description="Transmission information"
    )
    drive_type: Optional[str] = Field(
        None, description="Drive type (FWD, RWD, AWD, 4WD)"
    )
    manufacturer: Optional[str] = Field(None, description="Manufacturer name")
    plant_city: Optional[str] = Field(None, description="Manufacturing plant city")
    plant_country: Optional[str] = Field(
        None, description="Manufacturing plant country"
    )
    doors: Optional[int] = Field(None, description="Number of doors")
    gvwr: Optional[str] = Field(None, description="Gross Vehicle Weight Rating")
    series: Optional[str] = Field(None, description="Vehicle series")
    steering_location: Optional[str] = Field(
        None, description="Steering wheel location"
    )
    entertainment_system: Optional[str] = Field(
        None, description="Entertainment system"
    )
    error_code: Optional[str] = Field(None, description="NHTSA error code (if any)")
    error_text: Optional[str] = Field(None, description="NHTSA error text (if any)")

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
