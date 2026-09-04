"""Pydantic schemas for Analytics and Reports."""

from datetime import date as date_type
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.tire import TireResponse


class MonthlyCostSummary(BaseModel):
    """Monthly cost summary."""

    year: int
    month: int
    month_name: str
    total_service_cost: Decimal = Field(default=Decimal("0.00"))
    total_fuel_cost: Decimal = Field(default=Decimal("0.00"))
    total_def_cost: Decimal = Field(default=Decimal("0.00"))
    total_spot_rental_cost: Decimal = Field(default=Decimal("0.00"))
    total_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    fuel_count: int = 0
    def_count: int = 0
    spot_rental_count: int = 0

    model_config = {"from_attributes": True}


class ServiceTypeCostBreakdown(BaseModel):
    """Cost breakdown by service type."""

    service_type: str
    total_cost: Decimal
    count: int
    average_cost: Decimal
    last_service_date: date_type | None = None

    model_config = {"from_attributes": True}


class FuelEconomyDataPoint(BaseModel):
    """Single fuel economy data point (metric canonical)."""

    date: date_type
    l_per_100km: Decimal
    odometer_km: Decimal
    liters: Decimal
    cost: Decimal

    model_config = {"from_attributes": True}


class FuelEconomyTrend(BaseModel):
    """Fuel economy trend analysis (metric canonical — lower L/100km is better)."""

    average_l_per_100km: Decimal | None = None
    best_l_per_100km: Decimal | None = None
    worst_l_per_100km: Decimal | None = None
    recent_l_per_100km: Decimal | None = None  # Last 5 fill-ups
    trend: str = "stable"  # "improving", "declining", "stable"
    data_points: list[FuelEconomyDataPoint] = []

    model_config = {"from_attributes": True}


class HoursEconomyDataPoint(BaseModel):
    """Single engine-hours fuel-economy data point (dimensionless — no unit
    conversion; canonical and display units are the same for hours).

    The hours mirror of :class:`FuelEconomyDataPoint`. ``l_per_hr`` is
    nullable: a full-tank interval with zero liters (a $0 top-off logged
    purely for the hours reading) still scores a valid ``cost_per_hr``, so
    the point is kept rather than dropped — see
    :func:`app.services.fuel_service.calculate_hours_economy`. ``cost_per_hr``
    is never null for a point that exists in the series at all.
    """

    date: date_type
    engine_hours: Decimal
    l_per_hr: Decimal | None = None
    cost_per_hr: Decimal
    liters: Decimal
    cost: Decimal

    model_config = {"from_attributes": True}


class HoursEconomyTrend(BaseModel):
    """Engine-hours fuel economy trend (canonical L/hr + cost/hr; lower L/hr
    is better, mirroring the L/100km convention — less fuel burned per hour
    of engine operation).

    The hours mirror of :class:`FuelEconomyTrend`. ``average_l_per_hr`` /
    ``average_cost_per_hr`` are the canonical vehicle-level averages from
    :func:`app.services.fuel_service.calculate_average_hours_economy`
    (``exclude_hauling=True``) — this is where ``average_l_per_100km`` lives
    on the distance side, so the two hours averages live in the equivalent
    place here. ``best``/``worst``/``recent``/``trend`` come from the trend's
    own full-tank-endpoint pass (``exclude_hauling=False``), matching the
    distance trend's internal convention. All are ``None`` for a vehicle with
    no ``engine_hours``-bearing fuel records (pure-distance vehicle).
    """

    average_l_per_hr: Decimal | None = None
    average_cost_per_hr: Decimal | None = None
    best_l_per_hr: Decimal | None = None
    worst_l_per_hr: Decimal | None = None
    recent_l_per_hr: Decimal | None = None  # Last full-tank hours-economy endpoint
    recent_cost_per_hr: Decimal | None = None
    trend: str = "stable"  # "improving", "declining", "stable"
    data_points: list[HoursEconomyDataPoint] = []

    model_config = {"from_attributes": True}


class HoursAccumulatedDataPoint(BaseModel):
    """Single (date, engine_hours) reading from ``hours_records`` history.

    The hours analog of an odometer-over-time series — no such point series
    is currently exposed for distance in Analytics (``total_km_driven`` /
    ``average_km_per_month`` on :class:`VehicleAnalytics` are summary
    scalars, not a series), so this is a new, clearly-named series rather
    than a literal mirror. Every ``hours_records`` row is a real observation
    (manual, fuel-synced, or service-synced); neither field is nullable —
    a row with a null reading cannot exist in the table.
    """

    date: date_type
    engine_hours: Decimal

    model_config = {"from_attributes": True}


class ServiceHistoryItem(BaseModel):
    """Service history timeline item."""

    date: date_type
    service_type: str
    description: str | None = None
    odometer_km: Decimal | None = None
    cost: Decimal | None = None
    vendor_name: str | None = None
    days_since_last: int | None = None
    km_since_last: Decimal | None = None

    model_config = {"from_attributes": True}


class MaintenancePrediction(BaseModel):
    """Predicted maintenance item."""

    service_type: str
    predicted_date: date_type | None = None
    predicted_odometer_km: Decimal | None = None
    days_until_due: int | None = None
    km_until_due: Decimal | None = None
    average_interval_days: int | None = None
    average_interval_km: Decimal | None = None
    confidence: str = "low"  # "high", "medium", "low"

    # Fields to integrate schedule items with AI predictions
    has_schedule_item: bool = False
    schedule_item_next_date: date_type | None = None
    schedule_item_next_odometer_km: Decimal | None = None

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
    total_def_cost: Decimal = Field(default=Decimal("0.00"))
    total_cost: Decimal = Field(default=Decimal("0.00"))
    average_monthly_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    fuel_count: int = 0
    def_count: int = 0
    months_tracked: int = 0
    cost_per_km: Decimal | None = None

    # Rolling averages
    rolling_avg_3m: Decimal | None = None
    rolling_avg_6m: Decimal | None = None
    rolling_avg_12m: Decimal | None = None
    trend_direction: str = "stable"  # "increasing", "decreasing", "stable"

    monthly_breakdown: list[MonthlyCostSummary] = []
    service_type_breakdown: list[ServiceTypeCostBreakdown] = []

    # Anomaly detection
    anomalies: list[AnomalyAlert] = []

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

    # Machine-readable identity so the client can render its own localised,
    # unit-aware copy. `title`/`message` are English prose with L/100km baked
    # in, which is wrong for an imperial account and untranslatable for
    # everyone — same defect as the spending-anomaly message (#131). They are
    # retained because removing response fields is a breaking API change.
    code: Literal["economy_dropping", "trend_declining", "insufficient_data"]
    #: Percent worse than baseline; only set for `economy_dropping`.
    percent: int | None = None
    title: str
    severity: Literal["info", "warning", "critical"] = "info"
    message: str
    recent_l_per_100km: Decimal | None = None
    baseline_l_per_100km: Decimal | None = None

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
    fuel_alerts: list[FuelEfficiencyAlert] = []

    # Engine-Hours Economy (hours-usage-model Phase 7) — mirrors fuel_economy.
    # Always present; individual fields are null/empty for a pure-distance
    # vehicle rather than the whole object being omitted.
    hours_economy: HoursEconomyTrend

    # Hours accumulated over time (date, engine_hours) — the hours analog of
    # an odometer-over-time series. Empty for a pure-distance vehicle.
    hours_accumulated: list[HoursAccumulatedDataPoint] = []

    # Service History
    service_history: list[ServiceHistoryItem] = []

    # Maintenance Predictions
    predictions: list[MaintenancePrediction] = []

    # Summary Stats
    total_km_driven: Decimal | None = None
    average_km_per_month: Decimal | None = None
    days_owned: int | None = None

    # Fifth Wheel / RV Specific (optional)
    propane_analysis: dict[str, Any] | None = None  # For fifth wheels with propane tracking
    spot_rental_analysis: dict[str, Any] | None = None  # For fifth wheels with spot rentals

    # DEF Specific (optional - diesel vehicles)
    def_analysis: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class GarageCostTotals(BaseModel):
    """Total costs across the garage."""

    total_garage_value: Decimal = Field(default=Decimal("0.00"))
    # Service category breakdowns
    total_maintenance: Decimal = Field(default=Decimal("0.00"))
    total_upgrades: Decimal = Field(default=Decimal("0.00"))
    total_inspection: Decimal = Field(default=Decimal("0.00"))
    total_collision: Decimal = Field(default=Decimal("0.00"))
    total_detailing: Decimal = Field(default=Decimal("0.00"))
    # Other costs
    total_fuel: Decimal = Field(default=Decimal("0.00"))
    total_def: Decimal = Field(default=Decimal("0.00"))
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
    nickname: str
    purchase_price: Decimal = Field(default=Decimal("0.00"))
    # Service category breakdowns
    total_maintenance: Decimal = Field(default=Decimal("0.00"))
    total_upgrades: Decimal = Field(default=Decimal("0.00"))
    total_inspection: Decimal = Field(default=Decimal("0.00"))
    total_collision: Decimal = Field(default=Decimal("0.00"))
    total_detailing: Decimal = Field(default=Decimal("0.00"))
    # Other costs
    total_fuel: Decimal = Field(default=Decimal("0.00"))
    total_def: Decimal = Field(default=Decimal("0.00"))
    # Running costs = all service categories + fuel + DEF (excludes purchase price)
    total_cost: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class GarageMonthlyTrend(BaseModel):
    """Monthly spending trend across garage."""

    month: str
    service: Decimal = Field(default=Decimal("0.00"))
    fuel: Decimal = Field(default=Decimal("0.00"))
    def_cost: Decimal = Field(default=Decimal("0.00"))
    total: Decimal = Field(default=Decimal("0.00"))

    model_config = {"from_attributes": True}


class GarageAnalytics(BaseModel):
    """Complete garage-wide analytics."""

    total_costs: GarageCostTotals
    cost_breakdown_by_category: list[GarageCostByCategory] = []
    cost_by_vehicle: list[GarageVehicleCost] = []
    monthly_trends: list[GarageMonthlyTrend] = []
    vehicle_count: int = 0

    model_config = {"from_attributes": True}


# New analytics schemas


class VendorAnalysis(BaseModel):
    """Analysis of costs and services by vendor."""

    vendor_name: str
    total_spent: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    average_cost: Decimal = Field(default=Decimal("0.00"))
    service_types: list[str] = []
    last_service_date: date_type | None = None

    model_config = {"from_attributes": True}


class VendorAnalyticsSummary(BaseModel):
    """Summary of all vendor analytics for a vehicle."""

    vendors: list[VendorAnalysis] = []
    total_vendors: int = 0
    most_used_vendor: str | None = None
    highest_spending_vendor: str | None = None

    model_config = {"from_attributes": True}


class SeasonalAnalysis(BaseModel):
    """Analysis of spending patterns by season."""

    season: str  # "Winter", "Spring", "Summer", "Fall"
    total_cost: Decimal = Field(default=Decimal("0.00"))
    average_cost: Decimal = Field(default=Decimal("0.00"))
    service_count: int = 0
    variance_from_annual: Decimal = Field(default=Decimal("0.00"))  # Percentage
    common_services: list[str] = []

    model_config = {"from_attributes": True}


class SeasonalAnalyticsSummary(BaseModel):
    """Summary of seasonal analytics for a vehicle."""

    seasons: list[SeasonalAnalysis] = []
    highest_cost_season: str | None = None
    lowest_cost_season: str | None = None
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
    category_changes: list[CategoryChange] = []

    # Fuel economy (if applicable; lower L/100km is better)
    period1_avg_l_per_100km: Decimal | None = None
    period2_avg_l_per_100km: Decimal | None = None
    l_per_100km_change_percent: Decimal | None = None

    model_config = {"from_attributes": True}


class TireReadiness(BaseModel):
    """How many of a vehicle's live tires can answer each question.

    Retired tires are counted in none of these (B10). The three capabilities
    are INDEPENDENT and so are the four prompts: a tire can have a perfectly
    good distance and no projection, and telling that owner to add odometers to
    their tread readings would be advice about the wrong data.

    The prompts are what the readiness block is for. A page that only said
    "0 of 2" would be an apology; these say which number to go and write down.
    """

    #: Non-retired tires on this vehicle.
    total: int = 0
    #: Has two or more tread-bearing readings, so a trend line exists.
    can_trend: int = 0
    #: `wear_status` carries an actual figure (`projected` or the
    #: at-or-below-minimum safety case).
    can_project: int = 0
    #: `distance_status` is `complete`. A partial history counts as a prompt,
    #: not as an answer, even though it does report its measurable part.
    can_report_distance: int = 0
    #: Below `min_tread_mm` today. Surfaced as an action rather than a chart.
    under_minimum: int = 0

    #: Fewer than two tread-bearing readings. One reading is a point.
    needs_second_reading: int = 0
    #: Two readings, but one of the newest pair carries no odometer.
    needs_reading_odometer: int = 0
    #: `min_tread_mm` is null, so nothing can be projected against it. There is
    #: no 2.0 fallback: that is a column default applied at insert.
    needs_minimum_tread: int = 0
    #: Distance is blocked on a mount period's odometer bound. Excludes
    #: `spare_only` (a state, not a gap) and `odometer_rollback` (bad data,
    #: repaired by correcting a number rather than supplying one).
    needs_mount_odometer: int = 0


class TireAnalyticsSummary(BaseModel):
    """Tire wear and life for one vehicle.

    `tires` are the SAME `TireResponse` objects the tire card renders, computed
    once by `TireService`. Analytics deliberately adds no second serialisation
    of distance or wear: a copy that can disagree with the card is worse than
    no copy, and the tread trend is derivable from each tire's own readings,
    which are already on the wire.
    """

    readiness: TireReadiness = Field(default_factory=TireReadiness)
    #: Every tire, retired ones included. The retired ones carry `retired_on`
    #: and belong in the history blocks only.
    tires: list[TireResponse] = Field(default_factory=list)
    #: False when the vehicle has no `OdometerRecord` at all, which makes every
    #: OPEN mount period unbounded however complete its history is. Its own
    #: empty state, explained once rather than per tire.
    has_odometer_record: bool = False
