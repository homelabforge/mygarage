"""Pydantic schemas for Analytics and Reports."""

from typing import Any, Optional, List, Literal, Dict
from datetime import date as date_type
from decimal import Decimal
from pydantic import BaseModel, Field


class MonthlyCostSummary(BaseModel):
    """Monthly cost summary."""

    year: int
    month: int
    month_name: str
    total_service_cost: Decimal = Field(default=Decimal("0.00"))
    total_fuel_cost: Decimal = Field(default=Decimal("0.00"))
    total_spot_rental_cost: Decimal = Field(default=Decimal("0.00"))
    total_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    fuel_count: int = 0
    spot_rental_count: int = 0

    model_config = {"from_attributes": True}


class ServiceTypeCostBreakdown(BaseModel):
    """Cost breakdown by service type."""

    service_type: str
    total_cost: Decimal
    count: int
    average_cost: Decimal
    last_service_date: Optional[date_type] = None

    model_config = {"from_attributes": True}


class FuelEconomyDataPoint(BaseModel):
    """Single fuel economy data point."""

    date: date_type
    mpg: Decimal
    mileage: int
    gallons: Decimal
    cost: Decimal

    model_config = {"from_attributes": True}


class FuelEconomyTrend(BaseModel):
    """Fuel economy trend analysis."""

    average_mpg: Optional[Decimal] = None
    best_mpg: Optional[Decimal] = None
    worst_mpg: Optional[Decimal] = None
    recent_mpg: Optional[Decimal] = None  # Last 5 fill-ups
    trend: str = "stable"  # "improving", "declining", "stable"
    data_points: List[FuelEconomyDataPoint] = []

    model_config = {"from_attributes": True}


class ServiceHistoryItem(BaseModel):
    """Service history timeline item."""

    date: date_type
    service_type: str
    description: Optional[str] = None
    mileage: Optional[int] = None
    cost: Optional[Decimal] = None
    vendor_name: Optional[str] = None
    days_since_last: Optional[int] = None
    miles_since_last: Optional[int] = None

    model_config = {"from_attributes": True}


class MaintenancePrediction(BaseModel):
    """Predicted maintenance item."""

    service_type: str
    predicted_date: Optional[date_type] = None
    predicted_mileage: Optional[int] = None
    days_until_due: Optional[int] = None
    miles_until_due: Optional[int] = None
    average_interval_days: Optional[int] = None
    average_interval_miles: Optional[int] = None
    confidence: str = "low"  # "high", "medium", "low"

    # Fields to integrate manual reminders with AI predictions
    has_manual_reminder: bool = False
    manual_reminder_date: Optional[date_type] = None
    manual_reminder_mileage: Optional[int] = None

    model_config = {"from_attributes": True}


class AnomalyAlert(BaseModel):
    """Alert for detected spending anomalies."""

    month: str  # e.g., "2024-01"
    amount: Decimal
    baseline: Decimal
    deviation_percent: Decimal
    severity: Literal["warning", "critical"] = "warning"
    message: str

    model_config = {"from_attributes": True}


class CostAnalysis(BaseModel):
    """Overall cost analysis."""

    total_service_cost: Decimal = Field(default=Decimal("0.00"))
    total_fuel_cost: Decimal = Field(default=Decimal("0.00"))
    total_cost: Decimal = Field(default=Decimal("0.00"))
    average_monthly_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    fuel_count: int = 0
    months_tracked: int = 0
    cost_per_mile: Optional[Decimal] = None

    # Rolling averages
    rolling_avg_3m: Optional[Decimal] = None
    rolling_avg_6m: Optional[Decimal] = None
    rolling_avg_12m: Optional[Decimal] = None
    trend_direction: str = "stable"  # "increasing", "decreasing", "stable"

    monthly_breakdown: List[MonthlyCostSummary] = []
    service_type_breakdown: List[ServiceTypeCostBreakdown] = []

    # Anomaly detection
    anomalies: List[AnomalyAlert] = []

    model_config = {"from_attributes": True}


class CostProjection(BaseModel):
    """Forward-looking cost projection based on historical averages."""

    monthly_average: Decimal = Field(default=Decimal("0.00"))
    six_month_projection: Decimal = Field(default=Decimal("0.00"))
    twelve_month_projection: Decimal = Field(default=Decimal("0.00"))
    assumptions: str = "Projection assumes spending remains at recent averages."

    model_config = {"from_attributes": True}


class FuelEfficiencyAlert(BaseModel):
    """Alert describing changes in fuel efficiency."""

    title: str
    severity: Literal["info", "warning", "critical"] = "info"
    message: str
    recent_mpg: Optional[Decimal] = None
    baseline_mpg: Optional[Decimal] = None

    model_config = {"from_attributes": True}


class VehicleAnalytics(BaseModel):
    """Complete vehicle analytics."""

    vin: str
    vehicle_name: str  # e.g., "2021 Honda Accord"
    vehicle_type: str  # e.g., "Car", "Motorcycle", "Trailer", "Fifth Wheel"

    # Cost Analysis
    cost_analysis: CostAnalysis
    cost_projection: CostProjection

    # Fuel Economy
    fuel_economy: FuelEconomyTrend
    fuel_alerts: List[FuelEfficiencyAlert] = []

    # Service History
    service_history: List[ServiceHistoryItem] = []

    # Maintenance Predictions
    predictions: List[MaintenancePrediction] = []

    # Summary Stats
    total_miles_driven: Optional[int] = None
    average_miles_per_month: Optional[int] = None
    days_owned: Optional[int] = None

    # Fifth Wheel / RV Specific (optional)
    propane_analysis: Optional[Dict[str, Any]] = (
        None  # For fifth wheels with propane tracking
    )
    spot_rental_analysis: Optional[Dict[str, Any]] = (
        None  # For fifth wheels with spot rentals
    )

    model_config = {"from_attributes": True}


class GarageCostTotals(BaseModel):
    """Total costs across the garage."""

    total_garage_value: Decimal = Field(default=Decimal("0.00"))
    total_maintenance: Decimal = Field(default=Decimal("0.00"))
    total_fuel: Decimal = Field(default=Decimal("0.00"))
    total_insurance: Decimal = Field(default=Decimal("0.00"))
    total_taxes: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class GarageCostByCategory(BaseModel):
    """Cost breakdown by category across garage."""

    category: str
    amount: Decimal

    model_config = {"from_attributes": True}


class GarageVehicleCost(BaseModel):
    """Cost breakdown for a single vehicle in garage view."""

    vin: str
    name: str
    purchase_price: Decimal = Field(default=Decimal("0.00"))
    total_maintenance: Decimal = Field(default=Decimal("0.00"))
    total_fuel: Decimal = Field(default=Decimal("0.00"))
    total_cost: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class GarageMonthlyTrend(BaseModel):
    """Monthly spending trend across garage."""

    month: str
    maintenance: Decimal = Field(default=Decimal("0.00"))
    fuel: Decimal = Field(default=Decimal("0.00"))
    total: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class GarageAnalytics(BaseModel):
    """Complete garage-wide analytics."""

    total_costs: GarageCostTotals
    cost_breakdown_by_category: List[GarageCostByCategory] = []
    cost_by_vehicle: List[GarageVehicleCost] = []
    monthly_trends: List[GarageMonthlyTrend] = []
    vehicle_count: int = 0

    model_config = {"from_attributes": True}


# New analytics schemas


class VendorAnalysis(BaseModel):
    """Analysis of costs and services by vendor."""

    vendor_name: str
    total_spent: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    average_cost: Decimal = Field(default=Decimal("0.00"))
    service_types: List[str] = []
    last_service_date: Optional[date_type] = None

    model_config = {"from_attributes": True}


class VendorAnalyticsSummary(BaseModel):
    """Summary of all vendor analytics for a vehicle."""

    vendors: List[VendorAnalysis] = []
    total_vendors: int = 0
    most_used_vendor: Optional[str] = None
    highest_spending_vendor: Optional[str] = None

    model_config = {"from_attributes": True}


class SeasonalAnalysis(BaseModel):
    """Analysis of spending patterns by season."""

    season: str  # "Winter", "Spring", "Summer", "Fall"
    total_cost: Decimal = Field(default=Decimal("0.00"))
    average_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    variance_from_annual: Decimal = Field(default=Decimal("0.00"))  # Percentage
    common_services: List[str] = []

    model_config = {"from_attributes": True}


class SeasonalAnalyticsSummary(BaseModel):
    """Summary of seasonal analytics for a vehicle."""

    seasons: List[SeasonalAnalysis] = []
    highest_cost_season: Optional[str] = None
    lowest_cost_season: Optional[str] = None
    annual_average: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class CategoryChange(BaseModel):
    """Change in a specific category between periods."""

    category: str
    period1_value: Decimal = Field(default=Decimal("0.00"))
    period2_value: Decimal = Field(default=Decimal("0.00"))
    change_amount: Decimal = Field(default=Decimal("0.00"))
    change_percent: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class PeriodComparison(BaseModel):
    """Comparison between two time periods."""

    period1_label: str
    period2_label: str
    period1_start: date_type
    period1_end: date_type
    period2_start: date_type
    period2_end: date_type

    # Overall metrics
    period1_total_cost: Decimal = Field(default=Decimal("0.00"))
    period2_total_cost: Decimal = Field(default=Decimal("0.00"))
    cost_change_amount: Decimal = Field(default=Decimal("0.00"))
    cost_change_percent: Decimal = Field(default=Decimal("0.00"))

    # Service counts
    period1_service_count: int = 0
    period2_service_count: int = 0
    service_count_change: int = 0

    # Category breakdowns
    category_changes: List[CategoryChange] = []

    # Fuel economy (if applicable)
    period1_avg_mpg: Optional[Decimal] = None
    period2_avg_mpg: Optional[Decimal] = None
    mpg_change_percent: Optional[Decimal] = None

    model_config = {"from_attributes": True}
