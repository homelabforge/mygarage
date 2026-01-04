"""Schemas for shop discovery feature."""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from decimal import Decimal


class ShopSearchRequest(BaseModel):
    """Request to search for nearby shops."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius_meters: Optional[int] = Field(
        default=8000,
        ge=100,
        le=161000,
        description="Search radius in meters (default: ~5 miles, max: ~100 miles)",
    )
    shop_type: Optional[Literal["auto", "rv"]] = Field(
        default="auto",
        description="Type of repair shop to search for",
    )


class PlaceResult(BaseModel):
    """Normalized place result from any provider (TomTom or OSM)."""

    business_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    source: str  # 'tomtom' or 'osm'
    external_id: Optional[str] = None
    rating: Optional[Decimal] = None
    distance_meters: Optional[float] = None
    category: str = "service"
    website: Optional[str] = None


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
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    usage_count: int
    rating: Optional[Decimal] = None
    user_rating: Optional[int] = None


class ShopRecommendationsResponse(BaseModel):
    """Response with recommended shops."""

    recommendations: list[ShopRecommendation]
    count: int
