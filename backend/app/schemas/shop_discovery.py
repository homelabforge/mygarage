"""Schemas for shop discovery feature."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ShopSearchRequest(BaseModel):
    """Request to search for nearby shops."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius_meters: int | None = Field(
        default=8000,
        ge=100,
        le=161000,
        description="Search radius in meters (default: ~5 miles, max: ~100 miles)",
    )
    shop_type: Literal["auto", "rv"] | None = Field(
        default="auto",
        description="Type of repair shop to search for",
    )


class PlaceResult(BaseModel):
    """Normalized place result from any provider (TomTom or OSM)."""

    business_name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    latitude: Decimal
    longitude: Decimal
    source: str  # 'tomtom' or 'osm'
    external_id: str | None = None
    rating: Decimal | None = None
    distance_meters: float | None = None
    category: str = "service"
    website: str | None = None


class ShopSearchResponse(BaseModel):
    """Response containing search results."""

    results: list[PlaceResult]
    count: int
    source: str  # Which provider was used ('tomtom' or 'osm')
    latitude: float
    longitude: float
    radius_meters: int


class ShopRecommendation(BaseModel):
    """Recommended shop from address book based on usage."""

    id: int
    business_name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    usage_count: int
    rating: Decimal | None = None
    user_rating: int | None = None


class ShopRecommendationsResponse(BaseModel):
    """Response with recommended shops."""

    recommendations: list[ShopRecommendation]
    count: int
