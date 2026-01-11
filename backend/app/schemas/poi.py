"""Schemas for POI (Points of Interest) discovery feature."""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from decimal import Decimal


class POISearchRequest(BaseModel):
    """Request to search for nearby Points of Interest."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius_meters: Optional[int] = Field(
        default=8000,
        ge=100,
        le=161000,
        description="Search radius in meters (default: ~5 miles, max: ~100 miles)",
    )
    categories: list[
        Literal["auto_shop", "rv_shop", "ev_charging", "gas_station", "propane"]
    ] = Field(
        default=["auto_shop"],
        description="POI categories to search for (can select multiple)",
    )


class EVChargingMetadata(BaseModel):
    """EV charging station specific metadata."""

    connector_types: Optional[list[str]] = Field(
        default=None,
        description="Available connector types (Type 2, CCS, CHAdeMO, etc.)",
    )
    charging_speeds: Optional[list[str]] = Field(
        default=None, description="Charging speeds (Level 1, Level 2, DC Fast)"
    )
    network: Optional[str] = Field(
        default=None, description="Charging network (ChargePoint, Tesla, etc.)"
    )
    availability: Optional[str] = Field(
        default=None, description="Real-time availability status"
    )


class POIResult(BaseModel):
    """Normalized POI result from any provider (TomTom, OSM, Google, etc.)."""

    business_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    source: str = Field(
        description="Provider that returned this result (tomtom, osm, google, etc.)"
    )
    external_id: Optional[str] = None
    rating: Optional[Decimal] = None
    distance_meters: Optional[float] = None
    website: Optional[str] = None
    poi_category: str = Field(
        description="POI category (auto_shop, rv_shop, ev_charging, gas_station, propane)"
    )
    metadata: Optional[EVChargingMetadata] = Field(
        default=None, description="Category-specific metadata"
    )


class POISearchResponse(BaseModel):
    """Response containing POI search results."""

    results: list[POIResult]
    count: int
    source: str = Field(
        description="Which provider was used (tomtom, osm, google, etc.)"
    )
    latitude: float
    longitude: float
    radius_meters: int


class POIRecommendation(BaseModel):
    """Recommended POI from address book based on usage."""

    id: int
    business_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    usage_count: int
    rating: Optional[Decimal] = None
    user_rating: Optional[int] = None
    poi_category: Optional[str] = Field(
        default=None,
        description="POI category (auto_shop, rv_shop, ev_charging, gas_station, propane)",
    )


class POIRecommendationsResponse(BaseModel):
    """Response with recommended POIs."""

    recommendations: list[POIRecommendation]
    count: int


# Backward compatibility: Keep old schemas as aliases
# TODO: Remove in version 2.0.0
ShopSearchRequest = POISearchRequest
PlaceResult = POIResult
ShopSearchResponse = POISearchResponse
ShopRecommendation = POIRecommendation
ShopRecommendationsResponse = POIRecommendationsResponse
