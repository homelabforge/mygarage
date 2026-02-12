"""Analytics and reporting routes."""

# pyright: reportOptionalOperand=false

import calendar
import logging
from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    OdometerRecord,
    ServiceVisit,
    SpotRentalBilling,
    Vehicle,
)
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.spot_rental import SpotRental
from app.models.user import User
from app.models.vehicle_share import VehicleShare
from app.schemas.analytics import (
    AnomalyAlert,
    CategoryChange,
    CostAnalysis,
    CostProjection,
    FuelEconomyDataPoint,
    FuelEconomyTrend,
    FuelEfficiencyAlert,
    GarageAnalytics,
    GarageCostByCategory,
    GarageCostTotals,
    GarageMonthlyTrend,
    GarageVehicleCost,
    MaintenancePrediction,
    MonthlyCostSummary,
    PeriodComparison,
    SeasonalAnalysis,
    SeasonalAnalyticsSummary,
    ServiceHistoryItem,
    ServiceTypeCostBreakdown,
    VehicleAnalytics,
    VendorAnalysis,
    VendorAnalyticsSummary,
)
from app.services import analytics_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.utils.cache import cached

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Initialize rate limiter for export endpoints
limiter = Limiter(key_func=get_remote_address)


def calculate_trend(values: list[float]) -> str:
    """Calculate trend from list of values (improving/declining/stable)."""
    if len(values) < 3:
        return "stable"

    # Compare first half to second half
    mid = len(values) // 2
    first_half = sum(values[:mid]) / mid
    second_half = sum(values[mid:]) / (len(values) - mid)

    diff_percent = ((second_half - first_half) / first_half) * 100 if first_half > 0 else 0

    if diff_percent > 5:
        return "improving"
    elif diff_percent < -5:
        return "declining"
    else:
        return "stable"


def _load_service_visits_query(vin: str):
    """Build a ServiceVisit query with line_items + vendor eager-loaded."""
    return (
        select(ServiceVisit)
        .options(selectinload(ServiceVisit.line_items))
        .options(selectinload(ServiceVisit.vendor))
        .where(ServiceVisit.vin == vin)
        .order_by(ServiceVisit.date)
    )


@cached(ttl_seconds=600)  # Cache for 10 minutes
async def get_cost_analysis(db: AsyncSession, vin: str) -> CostAnalysis:
    """Calculate cost analysis for a vehicle."""

    # Get vehicle to check type for spot rental filtering
    vehicle_result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = vehicle_result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Determine if vehicle has spot rentals (only RVs, FifthWheels, TravelTrailers)
    has_spot_rentals = vehicle.vehicle_type in ["FifthWheel", "RV", "TravelTrailer"]

    # Get all service visits with line items + vendor
    visit_result = await db.execute(_load_service_visits_query(vin))
    service_visits = list(visit_result.scalars().all())

    # Get all fuel records with costs
    fuel_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin, FuelRecord.cost.isnot(None))
        .order_by(FuelRecord.date)
    )
    fuel_records = fuel_result.scalars().all()

    # Get all DEF records with costs
    def_result = await db.execute(
        select(DEFRecord)
        .where(DEFRecord.vin == vin, DEFRecord.cost.isnot(None))
        .order_by(DEFRecord.date)
    )
    def_records = list(def_result.scalars().all())

    # Get spot rental billings via spot_rentals (only if vehicle type supports it)
    spot_rental_billings = []
    if has_spot_rentals:
        spot_rental_result = await db.execute(
            select(SpotRentalBilling)
            .join(SpotRental)
            .where(SpotRental.vin == vin, SpotRentalBilling.total.isnot(None))
            .order_by(SpotRentalBilling.billing_date)
        )
        spot_rental_billings = spot_rental_result.scalars().all()

    # Calculate totals — use visit-level calculated_total_cost for financial accuracy
    total_service_cost = sum(
        (v.calculated_total_cost for v in service_visits if v.calculated_total_cost),
        Decimal("0.00"),
    )
    total_fuel_cost = sum((r.cost for r in fuel_records if r.cost), Decimal("0.00"))
    total_def_cost = sum((r.cost for r in def_records if r.cost), Decimal("0.00"))
    total_spot_rental_cost = sum(
        (r.total for r in spot_rental_billings if r.total), Decimal("0.00")
    )
    total_cost = total_service_cost + total_fuel_cost + total_def_cost + total_spot_rental_cost

    # Use pandas for monthly aggregation (one row per visit)
    df = analytics_service.visits_to_dataframe(
        service_visits, fuel_records, def_records, spot_rental_billings
    )
    monthly_df = analytics_service.calculate_monthly_aggregation(df)

    # Convert monthly DataFrame to Pydantic models
    monthly_breakdown = []
    for _, row in monthly_df.iterrows():
        monthly_breakdown.append(
            MonthlyCostSummary(
                year=int(row["year"]),
                month=int(row["month"]),
                month_name=row["month_name"],
                total_service_cost=Decimal(str(row["service_cost"])),
                total_fuel_cost=Decimal(str(row["fuel_cost"])),
                total_def_cost=Decimal(str(row.get("def_cost", 0))),
                total_spot_rental_cost=Decimal(str(row["spot_rental_cost"])),
                total_cost=Decimal(str(row["total_cost"])),
                service_count=int(row["service_count"]),
                fuel_count=int(row["fuel_count"]),
                def_count=int(row.get("def_count", 0)),
                spot_rental_count=int(row["spot_rental_count"]),
            )
        )

    # Calculate average monthly cost
    months_tracked = len(monthly_df)
    average_monthly_cost = total_cost / months_tracked if months_tracked > 0 else Decimal("0.00")

    # Calculate rolling averages and trend
    rolling_avgs = analytics_service.calculate_rolling_averages(monthly_df)
    trend_direction = (
        analytics_service.calculate_trend_direction(monthly_df["total_cost"])
        if not monthly_df.empty
        else "stable"
    )

    # Group service costs by type — iterate line items directly (not DataFrame)
    service_type_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": Decimal("0.00"),
            "count": 0,
            "last_date": None,
        }
    )

    for visit in service_visits:
        for item in visit.line_items:
            if item.description and item.cost:
                service_type_data[item.description]["total"] += item.cost
                service_type_data[item.description]["count"] += 1
                if (
                    not service_type_data[item.description]["last_date"]
                    or visit.date > service_type_data[item.description]["last_date"]
                ):
                    service_type_data[item.description]["last_date"] = visit.date

    service_type_breakdown = []
    for service_type, data in sorted(
        service_type_data.items(), key=lambda x: x[1]["total"], reverse=True
    ):
        service_type_breakdown.append(
            ServiceTypeCostBreakdown(
                service_type=service_type,
                total_cost=data["total"],
                count=data["count"],
                average_cost=data["total"] / data["count"]
                if data["count"] > 0
                else Decimal("0.00"),
                last_service_date=data["last_date"],
            )
        )

    # Calculate cost per mile
    all_mileages = []

    # Get odometer readings
    odometer_result = await db.execute(
        select(OdometerRecord.mileage)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date)
    )
    all_mileages.extend([r for r in odometer_result.scalars().all()])

    # Get mileage from fuel records
    for record in fuel_records:
        if record.mileage:
            all_mileages.append(record.mileage)

    # Get mileage from service visits
    for visit in service_visits:
        if visit.mileage:
            all_mileages.append(visit.mileage)

    cost_per_mile = None
    if len(all_mileages) >= 2:
        min_mileage = min(all_mileages)
        max_mileage = max(all_mileages)
        miles_driven = max_mileage - min_mileage
        if miles_driven > 0:
            cost_per_mile = total_cost / miles_driven

    # Detect cost anomalies
    anomalies = []
    if not monthly_df.empty and len(monthly_df) >= 3:
        monthly_costs = monthly_df["total_cost"]
        anomaly_indices = analytics_service.detect_anomalies(monthly_costs, std_threshold=2.0)

        if anomaly_indices:
            mean_cost = monthly_costs.mean()
            for idx in anomaly_indices:
                row = monthly_df.iloc[idx]
                amount = Decimal(str(row["total_cost"]))
                baseline = Decimal(str(mean_cost))
                deviation_percent = (
                    ((amount - baseline) / baseline * 100) if baseline > 0 else Decimal("0.00")
                )

                # Determine severity
                severity = "critical" if abs(deviation_percent) >= 50 else "warning"

                # Create message
                direction = "above" if amount > baseline else "below"
                message = f"Spending in {row['month_name']} {int(row['year'])} was ${amount:.2f}, {abs(deviation_percent):.1f}% {direction} your average of ${baseline:.2f}."

                anomalies.append(
                    AnomalyAlert(
                        month=f"{int(row['year'])}-{int(row['month']):02d}",
                        amount=amount,
                        baseline=baseline,
                        deviation_percent=deviation_percent,
                        severity=severity,
                        message=message,
                    )
                )

    return CostAnalysis(
        total_service_cost=total_service_cost,
        total_fuel_cost=total_fuel_cost,
        total_def_cost=total_def_cost,
        total_cost=total_cost,
        average_monthly_cost=average_monthly_cost,
        service_count=len(service_visits),
        fuel_count=len(fuel_records),
        def_count=len(def_records),
        months_tracked=months_tracked,
        cost_per_mile=cost_per_mile,
        rolling_avg_3m=rolling_avgs.get("rolling_3m"),
        rolling_avg_6m=rolling_avgs.get("rolling_6m"),
        rolling_avg_12m=rolling_avgs.get("rolling_12m"),
        trend_direction=trend_direction,
        monthly_breakdown=monthly_breakdown,
        service_type_breakdown=service_type_breakdown,
        anomalies=anomalies,
    )


def build_cost_projection(cost_analysis: CostAnalysis) -> CostProjection:
    """Create simple projections based on recent averages."""
    avg = cost_analysis.average_monthly_cost or Decimal("0.00")
    six_month_projection = (avg * Decimal(6)).quantize(Decimal("0.01"))
    twelve_month_projection = (avg * Decimal(12)).quantize(Decimal("0.01"))

    return CostProjection(
        monthly_average=avg,
        six_month_projection=six_month_projection,
        twelve_month_projection=twelve_month_projection,
        assumptions="Projection assumes spending remains at recent averages.",
    )


@cached(ttl_seconds=600)  # Cache for 10 minutes
async def get_fuel_economy_trend(db: AsyncSession, vin: str) -> FuelEconomyTrend:
    """Calculate fuel economy trends using pandas."""

    # Get all fuel records
    result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date)
    )
    fuel_records = list(result.scalars().all())

    if not fuel_records:
        return FuelEconomyTrend()

    # Use pandas for fuel economy calculation
    mpg_df, stats = analytics_service.calculate_fuel_economy_with_pandas(fuel_records)

    if mpg_df.empty or not stats:
        return FuelEconomyTrend()

    # Convert DataFrame to data points
    data_points = []
    for _, row in mpg_df.iterrows():
        data_points.append(
            FuelEconomyDataPoint(
                date=row["date"].date(),
                mpg=Decimal(str(round(row["mpg"], 2))),
                mileage=int(row["mileage"]),
                gallons=Decimal(str(round(row["gallons"], 3))),
                cost=Decimal(str(round(row["cost"], 2))),
            )
        )

    return FuelEconomyTrend(
        average_mpg=stats.get("average_mpg"),
        best_mpg=stats.get("best_mpg"),
        worst_mpg=stats.get("worst_mpg"),
        recent_mpg=stats.get("recent_mpg"),
        trend=stats.get("trend", "stable"),
        data_points=data_points,
    )


def build_fuel_alerts(fuel_economy: FuelEconomyTrend) -> list[FuelEfficiencyAlert]:
    """Generate alert messages based on fuel economy trends."""
    alerts: list[FuelEfficiencyAlert] = []

    avg = fuel_economy.average_mpg
    recent = fuel_economy.recent_mpg

    if avg and recent and Decimal(str(avg)) > 0:
        avg_dec = Decimal(str(avg))
        recent_dec = Decimal(str(recent))
        drop_percent = (avg_dec - recent_dec) / avg_dec

        severity = None
        if drop_percent >= Decimal("0.20"):
            severity = "critical"
        elif drop_percent >= Decimal("0.10"):
            severity = "warning"

        if severity:
            percent_value = int(drop_percent * 100)
            alerts.append(
                FuelEfficiencyAlert(
                    title="Fuel economy dropping",
                    severity=severity,
                    message=f"Recent MPG ({recent_dec:.1f}) is {percent_value}% lower than your baseline ({avg_dec:.1f}).",
                    recent_mpg=recent_dec,
                    baseline_mpg=avg_dec,
                )
            )

    if fuel_economy.trend == "declining" and not alerts:
        alerts.append(
            FuelEfficiencyAlert(
                title="Efficiency trend declining",
                severity="info",
                message="Recent fill-ups show a downward MPG trend. Consider checking tire pressure or air filters.",
                recent_mpg=fuel_economy.recent_mpg,
                baseline_mpg=fuel_economy.average_mpg,
            )
        )

    if not fuel_economy.data_points or len(fuel_economy.data_points) < 3:
        alerts.append(
            FuelEfficiencyAlert(
                title="Insufficient fuel data",
                severity="info",
                message="Log at least three full-tank fuel entries to unlock detailed MPG insights.",
                recent_mpg=None,
                baseline_mpg=None,
            )
        )

    return alerts


@cached(ttl_seconds=600)  # Cache for 10 minutes
async def get_service_history_timeline(db: AsyncSession, vin: str) -> list[ServiceHistoryItem]:
    """Get service history with timeline context from ServiceVisit line items."""

    result = await db.execute(
        select(ServiceVisit)
        .options(selectinload(ServiceVisit.line_items))
        .options(selectinload(ServiceVisit.vendor))
        .where(ServiceVisit.vin == vin)
        .order_by(ServiceVisit.date.desc())
    )
    visits = list(result.scalars().all())

    # Flatten to (visit, line_item) pairs sorted by date desc
    items: list[tuple[ServiceVisit, ServiceLineItem]] = []
    for visit in visits:
        for li in visit.line_items:
            items.append((visit, li))

    timeline = []
    for i, (visit, item) in enumerate(items):
        days_since_last = None
        miles_since_last = None

        # Find previous item with matching description
        for prev_visit, prev_item in items[i + 1 :]:
            if prev_item.description == item.description:
                if visit.date and prev_visit.date:
                    days_since_last = (visit.date - prev_visit.date).days
                if visit.mileage and prev_visit.mileage:
                    miles_since_last = visit.mileage - prev_visit.mileage
                break

        timeline.append(
            ServiceHistoryItem(
                date=visit.date,
                service_type=item.description,
                description=visit.notes,
                mileage=visit.mileage,
                cost=item.cost,
                vendor_name=visit.vendor.name if visit.vendor else None,
                days_since_last=days_since_last,
                miles_since_last=miles_since_last,
            )
        )

    return timeline


@cached(ttl_seconds=600)  # Cache for 10 minutes
async def get_maintenance_predictions(
    db: AsyncSession, vin: str, current_mileage: int | None = None
) -> list[MaintenancePrediction]:
    """Predict upcoming maintenance based on service visit line items."""

    # Get service visits with line items
    result = await db.execute(
        select(ServiceVisit)
        .options(selectinload(ServiceVisit.line_items))
        .where(ServiceVisit.vin == vin)
        .order_by(ServiceVisit.date)
    )
    visits = list(result.scalars().all())

    # Get active reminders for this vehicle
    reminder_result = await db.execute(
        select(Reminder).where(Reminder.vin == vin, ~Reminder.is_completed)
    )
    reminders = list(reminder_result.scalars().all())

    # Get current mileage if not provided
    if not current_mileage:
        odometer_result = await db.execute(
            select(OdometerRecord.mileage)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc())
            .limit(1)
        )
        current_mileage = odometer_result.scalar_one_or_none()

    # Flatten visits → line items as (date, mileage, description)
    flat_items: list[tuple[date_type, int | None, str]] = []
    for visit in visits:
        for li in visit.line_items:
            if li.description:
                flat_items.append((visit.date, visit.mileage, li.description))

    # Get all unique service types for reminder matching
    all_service_types = set(desc for _, _, desc in flat_items)

    # Create mapping of service types to reminders (fuzzy match)
    reminder_map: dict[str, Reminder] = {}
    for reminder in reminders:
        for service_type in all_service_types:
            if service_type.lower() in reminder.description.lower():
                reminder_map[service_type] = reminder
                break

    # Group by description and calculate intervals
    service_intervals: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Sort flat_items by date for interval calculation
    flat_items.sort(key=lambda x: x[0])

    for i in range(len(flat_items) - 1):
        curr_date, curr_mileage_val, curr_desc = flat_items[i + 1]
        prev_date, prev_mileage_val, prev_desc = flat_items[i]

        if curr_desc == prev_desc:
            interval_data: dict[str, Any] = {}

            if curr_date and prev_date:
                interval_data["days"] = (curr_date - prev_date).days
                interval_data["date"] = curr_date

            if curr_mileage_val and prev_mileage_val:
                interval_data["miles"] = curr_mileage_val - prev_mileage_val
                interval_data["mileage"] = curr_mileage_val

            if interval_data:
                service_intervals[curr_desc].append(interval_data)

    # Generate predictions
    predictions = []
    today = date_type.today()

    for service_type, intervals in service_intervals.items():
        if not intervals:
            continue

        # Calculate average intervals
        day_intervals = [i["days"] for i in intervals if "days" in i]
        mile_intervals = [i["miles"] for i in intervals if "miles" in i]

        if not day_intervals and not mile_intervals:
            continue

        avg_days = int(sum(day_intervals) / len(day_intervals)) if day_intervals else None
        avg_miles = int(sum(mile_intervals) / len(mile_intervals)) if mile_intervals else None

        # Find most recent service of this type
        most_recent_date = None
        most_recent_mileage = None
        for item_date, item_mileage, item_desc in reversed(flat_items):
            if item_desc == service_type:
                most_recent_date = item_date
                most_recent_mileage = item_mileage
                break

        if not most_recent_date:
            continue

        # Predict next service
        predicted_date = None
        days_until_due = None
        if avg_days:
            predicted_date = most_recent_date + timedelta(days=avg_days)
            days_until_due = (predicted_date - today).days

        predicted_mileage = None
        miles_until_due = None
        if avg_miles and most_recent_mileage and current_mileage:
            predicted_mileage = most_recent_mileage + avg_miles
            miles_until_due = predicted_mileage - current_mileage

        # Determine confidence based on consistency of intervals
        confidence = "low"
        if len(intervals) >= 3:
            if day_intervals and avg_days:
                variance = sum((x - avg_days) ** 2 for x in day_intervals) / len(day_intervals)
                std_dev = variance**0.5
                if std_dev < avg_days * 0.2:
                    confidence = "high"
                elif std_dev < avg_days * 0.4:
                    confidence = "medium"

        # Check if there's a manual reminder for this service type
        has_reminder = service_type in reminder_map
        reminder_date = reminder_map[service_type].due_date if has_reminder else None
        reminder_mileage = reminder_map[service_type].due_mileage if has_reminder else None

        predictions.append(
            MaintenancePrediction(
                service_type=service_type,
                predicted_date=predicted_date,
                predicted_mileage=predicted_mileage,
                days_until_due=days_until_due,
                miles_until_due=miles_until_due,
                average_interval_days=avg_days,
                average_interval_miles=avg_miles,
                confidence=confidence,
                has_manual_reminder=has_reminder,
                manual_reminder_date=reminder_date,
                manual_reminder_mileage=reminder_mileage,
            )
        )

    # Sort by urgency (sooner first)
    predictions.sort(key=lambda p: p.days_until_due if p.days_until_due is not None else 999999)

    return predictions


@router.get("/vehicles/{vin}", response_model=VehicleAnalytics)
async def get_vehicle_analytics(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get comprehensive analytics for a vehicle.
    """
    # Verify vehicle access (owner, admin, or shared)
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Detect if this is a fifth wheel
    is_fifth_wheel = vehicle.vehicle_type == "FifthWheel"

    # Get cost analysis
    cost_analysis = await get_cost_analysis(db, vin)
    cost_projection = build_cost_projection(cost_analysis)

    # Get fuel economy trends (skip for fifth wheels - they don't have MPG tracking)
    if is_fifth_wheel:
        fuel_economy = FuelEconomyTrend(
            data_points=[],
            average_mpg=None,
            best_mpg=None,
            worst_mpg=None,
            recent_average=None,
            trend="stable",
        )
        fuel_alerts = []
    else:
        fuel_economy = await get_fuel_economy_trend(db, vin)
        fuel_alerts = build_fuel_alerts(fuel_economy)

    # Get service history timeline
    service_history = await get_service_history_timeline(db, vin)

    # Calculate summary stats - get odometer records first to get current mileage
    odometer_result = await db.execute(
        select(OdometerRecord.mileage, OdometerRecord.date)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date)
    )
    odometer_records = list(odometer_result.all())

    # Get current mileage from latest odometer record
    current_mileage = odometer_records[-1][0] if odometer_records else None

    # Get maintenance predictions
    predictions = await get_maintenance_predictions(db, vin, current_mileage)

    total_miles_driven = None
    average_miles_per_month = None
    days_owned = None

    if len(odometer_records) >= 2:
        first_reading, first_date = odometer_records[0]
        last_reading, last_date = odometer_records[-1]

        total_miles_driven = last_reading - first_reading
        days_owned = (last_date - first_date).days

        if days_owned > 0:
            average_miles_per_month = int((total_miles_driven / days_owned) * 30)
    elif vehicle.purchase_date:
        days_owned = (date_type.today() - vehicle.purchase_date).days

    vehicle_name = f"{vehicle.year} {vehicle.make} {vehicle.model}"

    # Fifth wheel specific analytics
    propane_analysis = None
    spot_rental_analysis = None
    if is_fifth_wheel:
        # Get all fuel records for propane analysis
        fuel_result = await db.execute(
            select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date)
        )
        all_fuel_records = fuel_result.scalars().all()
        propane_analysis = analytics_service.calculate_propane_costs(all_fuel_records)

        # Get spot rental costs
        spot_rental_analysis = await analytics_service.calculate_spot_rental_costs(db, vin)

    # DEF analysis (for diesel vehicles with DEF records)
    def_analysis = None
    def_result = await db.execute(
        select(DEFRecord).where(DEFRecord.vin == vin).order_by(DEFRecord.date)
    )
    all_def_records = def_result.scalars().all()
    if all_def_records:
        total_def_gallons = sum((r.gallons for r in all_def_records if r.gallons), Decimal("0.00"))
        total_def_spent = sum((r.cost for r in all_def_records if r.cost), Decimal("0.00"))
        avg_cost_per_gallon = total_def_spent / total_def_gallons if total_def_gallons > 0 else None

        # Calculate gallons per 1,000 miles
        gallons_per_1000_miles = None
        def_mileages = [r.mileage for r in all_def_records if r.mileage is not None]
        if len(def_mileages) >= 2:
            min_mi = min(def_mileages)
            max_mi = max(def_mileages)
            miles_span = max_mi - min_mi
            if miles_span > 0:
                gallons_per_1000_miles = float(total_def_gallons) / miles_span * 1000

        def_analysis = {
            "total_spent": str(total_def_spent),
            "total_gallons": str(total_def_gallons),
            "avg_cost_per_gallon": str(avg_cost_per_gallon) if avg_cost_per_gallon else None,
            "gallons_per_1000_miles": (
                f"{gallons_per_1000_miles:.1f}" if gallons_per_1000_miles else None
            ),
            "record_count": len(all_def_records),
        }

    return VehicleAnalytics(
        vin=vin,
        vehicle_name=vehicle_name,
        vehicle_type=vehicle.vehicle_type,
        cost_analysis=cost_analysis,
        cost_projection=cost_projection,
        fuel_economy=fuel_economy,
        fuel_alerts=fuel_alerts,
        service_history=service_history,
        predictions=predictions,
        total_miles_driven=total_miles_driven,
        average_miles_per_month=average_miles_per_month,
        days_owned=days_owned,
        propane_analysis=propane_analysis,
        spot_rental_analysis=spot_rental_analysis,
        def_analysis=def_analysis,
    )


@router.get("/garage", response_model=GarageAnalytics)
async def get_garage_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get comprehensive analytics aggregated across all vehicles in the garage.
    """
    # Build vehicle query with eager loading
    query = select(Vehicle).options(
        selectinload(Vehicle.service_visits).selectinload(ServiceVisit.line_items),
        selectinload(Vehicle.service_visits).selectinload(ServiceVisit.vendor),
        selectinload(Vehicle.fuel_records),
        selectinload(Vehicle.def_records),
        selectinload(Vehicle.insurance_policies),
        selectinload(Vehicle.tax_records),
    )

    # Scope to owned + shared vehicles for non-admin users
    if current_user is not None and not current_user.is_admin:
        shared_vins = (
            select(VehicleShare.vehicle_vin)
            .where(VehicleShare.user_id == current_user.id)
            .scalar_subquery()
        )
        query = query.where(or_(Vehicle.user_id == current_user.id, Vehicle.vin.in_(shared_vins)))

    vehicles_result = await db.execute(query)
    vehicles = vehicles_result.scalars().all()

    if not vehicles:
        return GarageAnalytics(
            total_costs=GarageCostTotals(),
            cost_breakdown_by_category=[],
            cost_by_vehicle=[],
            monthly_trends=[],
            vehicle_count=0,
        )

    # Initialize totals
    total_garage_value = Decimal("0.00")
    total_maintenance = Decimal("0.00")
    total_upgrades = Decimal("0.00")
    total_inspection = Decimal("0.00")
    total_collision = Decimal("0.00")
    total_detailing = Decimal("0.00")
    total_fuel = Decimal("0.00")
    total_def = Decimal("0.00")
    total_insurance = Decimal("0.00")
    total_taxes = Decimal("0.00")

    vehicle_costs = []

    # Track monthly trends across garage
    monthly_data: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {
            "service": Decimal("0.00"),
            "fuel": Decimal("0.00"),
            "def": Decimal("0.00"),
        }
    )

    for vehicle in vehicles:
        vin = vehicle.vin
        vehicle_name = f"{vehicle.year} {vehicle.make} {vehicle.model}"

        purchase_price = vehicle.purchase_price or Decimal("0.00")
        total_garage_value += purchase_price

        for policy in vehicle.insurance_policies:
            if policy.premium_amount:
                total_insurance += policy.premium_amount

        for tax_record in vehicle.tax_records:
            if tax_record.amount:
                total_taxes += tax_record.amount

        # Use eager-loaded service visits
        service_visits = list(vehicle.service_visits)
        service_visits.sort(key=lambda v: v.date)

        fuel_records = [r for r in vehicle.fuel_records if r.cost is not None]
        fuel_records.sort(key=lambda r: r.date)

        # Calculate vehicle totals by service category using visit-level costs
        vehicle_maintenance = Decimal("0.00")
        vehicle_upgrades = Decimal("0.00")
        vehicle_inspection = Decimal("0.00")
        vehicle_collision = Decimal("0.00")
        vehicle_detailing = Decimal("0.00")

        for visit in service_visits:
            cost = visit.calculated_total_cost
            if cost:
                category = visit.service_category or "Maintenance"
                if category == "Maintenance":
                    vehicle_maintenance += cost
                elif category == "Upgrades":
                    vehicle_upgrades += cost
                elif category == "Inspection":
                    vehicle_inspection += cost
                elif category == "Collision":
                    vehicle_collision += cost
                elif category == "Detailing":
                    vehicle_detailing += cost
                else:
                    vehicle_maintenance += cost

        vehicle_fuel = sum((r.cost for r in fuel_records if r.cost), Decimal("0.00"))

        def_records = [r for r in vehicle.def_records if r.cost is not None]
        def_records.sort(key=lambda r: r.date)

        vehicle_def = sum((r.cost for r in def_records if r.cost), Decimal("0.00"))

        vehicle_total = (
            vehicle_maintenance
            + vehicle_upgrades
            + vehicle_inspection
            + vehicle_collision
            + vehicle_detailing
            + vehicle_fuel
            + vehicle_def
        )

        total_maintenance += vehicle_maintenance
        total_upgrades += vehicle_upgrades
        total_inspection += vehicle_inspection
        total_collision += vehicle_collision
        total_detailing += vehicle_detailing
        total_fuel += vehicle_fuel
        total_def += vehicle_def

        vehicle_costs.append(
            GarageVehicleCost(
                vin=vin,
                name=vehicle_name,
                nickname=vehicle.nickname,
                purchase_price=purchase_price,
                total_maintenance=vehicle_maintenance,
                total_upgrades=vehicle_upgrades,
                total_inspection=vehicle_inspection,
                total_collision=vehicle_collision,
                total_detailing=vehicle_detailing,
                total_fuel=vehicle_fuel,
                total_def=vehicle_def,
                total_cost=vehicle_total,
            )
        )

        # Add to monthly trends — service uses visit.calculated_total_cost
        for visit in service_visits:
            cost = visit.calculated_total_cost
            if visit.date and cost:
                key = (visit.date.year, visit.date.month)
                monthly_data[key]["service"] += cost

        for record in fuel_records:
            if record.date and record.cost:
                key = (record.date.year, record.date.month)
                monthly_data[key]["fuel"] += record.cost

        for record in def_records:
            if record.date and record.cost:
                key = (record.date.year, record.date.month)
                monthly_data[key]["def"] += record.cost

    vehicle_costs.sort(key=lambda x: x.total_cost, reverse=True)

    cost_breakdown = []
    if total_maintenance > 0:
        cost_breakdown.append(
            GarageCostByCategory(category="Maintenance", amount=total_maintenance)
        )
    if total_upgrades > 0:
        cost_breakdown.append(GarageCostByCategory(category="Upgrades", amount=total_upgrades))
    if total_inspection > 0:
        cost_breakdown.append(GarageCostByCategory(category="Inspection", amount=total_inspection))
    if total_collision > 0:
        cost_breakdown.append(GarageCostByCategory(category="Collision", amount=total_collision))
    if total_detailing > 0:
        cost_breakdown.append(GarageCostByCategory(category="Detailing", amount=total_detailing))
    if total_fuel > 0:
        cost_breakdown.append(GarageCostByCategory(category="Fuel", amount=total_fuel))
    if total_def > 0:
        cost_breakdown.append(GarageCostByCategory(category="DEF", amount=total_def))
    if total_insurance > 0:
        cost_breakdown.append(GarageCostByCategory(category="Insurance", amount=total_insurance))
    if total_taxes > 0:
        cost_breakdown.append(GarageCostByCategory(category="Taxes", amount=total_taxes))

    # Create monthly trends (last 12 months)
    monthly_trends = []
    sorted_months = sorted(monthly_data.items())[-12:]

    for (year, month), data in sorted_months:
        month_name = f"{calendar.month_abbr[month]} {year}"
        monthly_trends.append(
            GarageMonthlyTrend(
                month=month_name,
                service=data["service"],
                fuel=data["fuel"],
                def_cost=data["def"],
                total=data["service"] + data["fuel"] + data["def"],
            )
        )

    return GarageAnalytics(
        total_costs=GarageCostTotals(
            total_garage_value=total_garage_value,
            total_maintenance=total_maintenance,
            total_upgrades=total_upgrades,
            total_inspection=total_inspection,
            total_collision=total_collision,
            total_detailing=total_detailing,
            total_fuel=total_fuel,
            total_def=total_def,
            total_insurance=total_insurance,
            total_taxes=total_taxes,
        ),
        cost_breakdown_by_category=cost_breakdown,
        cost_by_vehicle=vehicle_costs,
        monthly_trends=monthly_trends,
        vehicle_count=len(vehicles),
    )


@router.get("/garage/export")
@limiter.limit(settings.rate_limit_exports)
async def export_garage_analytics_pdf(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Export garage analytics as PDF report.
    """
    from app.utils.pdf_generator import PDFReportGenerator

    # Get garage analytics first
    garage_data = await get_garage_analytics(db, current_user)

    if garage_data.vehicle_count == 0:
        raise HTTPException(status_code=404, detail="No vehicles found in garage")

    # Convert Pydantic model to dict for PDF generator
    garage_dict = {
        "vehicle_count": garage_data.vehicle_count,
        "total_costs": {
            "total_garage_value": str(garage_data.total_costs.total_garage_value),
            "total_maintenance": str(garage_data.total_costs.total_maintenance),
            "total_fuel": str(garage_data.total_costs.total_fuel),
            "total_insurance": str(garage_data.total_costs.total_insurance),
            "total_taxes": str(garage_data.total_costs.total_taxes),
        },
        "cost_breakdown_by_category": [
            {
                "category": cat.category,
                "amount": str(cat.amount),
            }
            for cat in garage_data.cost_breakdown_by_category
        ],
        "cost_by_vehicle": [
            {
                "name": v.name,
                "purchase_price": str(v.purchase_price),
                "total_maintenance": str(v.total_maintenance),
                "total_fuel": str(v.total_fuel),
                "total_cost": str(v.total_cost),
            }
            for v in garage_data.cost_by_vehicle
        ],
        "monthly_trends": [
            {
                "month": t.month,
                "service": str(t.service),
                "fuel": str(t.fuel),
            }
            for t in garage_data.monthly_trends
        ],
    }

    # Generate PDF
    pdf_generator = PDFReportGenerator()
    pdf_buffer = pdf_generator.generate_garage_analytics_pdf(garage_dict)

    # Return as file download
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=garage-analytics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
        },
    )


# New endpoints for advanced analytics


@router.get("/vehicles/{vin}/vendors", response_model=VendorAnalyticsSummary)
async def get_vendor_analytics(
    vin: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Get vendor analysis for a specific vehicle."""

    # Verify access (owner, admin, or shared)
    await get_vehicle_or_403(vin, user, db)

    # Get service visits with line items + vendor
    visit_result = await db.execute(_load_service_visits_query(vin))
    service_visits = list(visit_result.scalars().all())

    if not service_visits:
        return VendorAnalyticsSummary()

    # Use visits_to_dataframe for financial totals per vendor
    df = analytics_service.visits_to_dataframe(service_visits, [])
    vendor_df = analytics_service.calculate_vendor_analysis(df)

    if vendor_df.empty:
        return VendorAnalyticsSummary()

    # Derive service_types per vendor from line items directly
    vendor_service_types: dict[str, set[str]] = defaultdict(set)
    for visit in service_visits:
        vendor_name = visit.vendor.name if visit.vendor else "Unknown"
        for item in visit.line_items:
            if item.description:
                vendor_service_types[vendor_name].add(item.description)

    # Convert to Pydantic models
    vendors = []
    for _, row in vendor_df.iterrows():
        vendor_name = row["vendor"]
        vendors.append(
            VendorAnalysis(
                vendor_name=vendor_name,
                total_spent=Decimal(str(round(row["total_spent"], 2))),
                service_count=int(row["service_count"]),
                average_cost=Decimal(str(round(row["avg_cost"], 2))),
                service_types=sorted(vendor_service_types.get(vendor_name, set())),
                last_service_date=row["last_service_date"].date()
                if row["last_service_date"]
                else None,
            )
        )

    most_used = max(vendors, key=lambda v: v.service_count) if vendors else None
    highest_spending = max(vendors, key=lambda v: v.total_spent) if vendors else None

    return VendorAnalyticsSummary(
        vendors=vendors,
        total_vendors=len(vendors),
        most_used_vendor=most_used.vendor_name if most_used else None,
        highest_spending_vendor=highest_spending.vendor_name if highest_spending else None,
    )


@router.get("/vehicles/{vin}/seasonal", response_model=SeasonalAnalyticsSummary)
async def get_seasonal_analytics(
    vin: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Get seasonal spending analysis for a specific vehicle."""

    # Verify access (owner, admin, or shared)
    await get_vehicle_or_403(vin, user, db)

    # Get service visits with line items + vendor
    visit_result = await db.execute(_load_service_visits_query(vin))
    service_visits = list(visit_result.scalars().all())

    fuel_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin, FuelRecord.cost.isnot(None))
        .order_by(FuelRecord.date)
    )
    fuel_records = fuel_result.scalars().all()

    # Get spot rental billings
    spot_rental_result = await db.execute(
        select(SpotRentalBilling)
        .join(SpotRental)
        .where(SpotRental.vin == vin, SpotRentalBilling.total.isnot(None))
        .order_by(SpotRentalBilling.billing_date)
    )
    spot_rental_billings = spot_rental_result.scalars().all()

    if not service_visits and not fuel_records and not spot_rental_billings:
        return SeasonalAnalyticsSummary()

    # Use visits_to_dataframe for financial totals per season
    df = analytics_service.visits_to_dataframe(
        service_visits, fuel_records, spot_rental_billings=spot_rental_billings
    )
    seasonal_df = analytics_service.calculate_seasonal_patterns(df)

    if seasonal_df.empty:
        return SeasonalAnalyticsSummary()

    annual_average = seasonal_df["total_cost"].mean()

    # Derive top_service_types per season from line items directly
    season_months = {
        "Winter": [12, 1, 2],
        "Spring": [3, 4, 5],
        "Summer": [6, 7, 8],
        "Fall": [9, 10, 11],
    }
    season_service_types: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for visit in service_visits:
        month = visit.date.month
        for season_name, months in season_months.items():
            if month in months:
                for item in visit.line_items:
                    if item.description:
                        season_service_types[season_name][item.description] += 1
                break

    seasons = []
    for _, row in seasonal_df.iterrows():
        variance = (
            ((row["total_cost"] - annual_average) / annual_average * 100)
            if annual_average > 0
            else 0
        )

        # Get common services from line items
        season_name = row["season"]
        type_counts = season_service_types.get(season_name, {})
        common_services = [
            k for k, _ in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        ]

        seasons.append(
            SeasonalAnalysis(
                season=season_name,
                total_cost=Decimal(str(round(row["total_cost"], 2))),
                average_cost=Decimal(str(round(row["avg_cost"], 2))),
                service_count=int(row["count"]),
                variance_from_annual=Decimal(str(round(variance, 2))),
                common_services=common_services,
            )
        )

    highest_season = max(seasons, key=lambda s: s.total_cost) if seasons else None
    lowest_season = min(seasons, key=lambda s: s.total_cost) if seasons else None

    return SeasonalAnalyticsSummary(
        seasons=seasons,
        highest_cost_season=highest_season.season if highest_season else None,
        lowest_cost_season=lowest_season.season if lowest_season else None,
        annual_average=Decimal(str(round(annual_average, 2))),
    )


@router.get("/vehicles/{vin}/compare", response_model=PeriodComparison)
async def compare_periods(
    vin: str,
    period1_start: date_type,
    period1_end: date_type,
    period2_start: date_type,
    period2_end: date_type,
    period1_label: str | None = None,
    period2_label: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_auth),
):
    """Compare costs and metrics between two time periods."""

    # Verify access (owner, admin, or shared)
    await get_vehicle_or_403(vin, user, db)

    # Get service visits with line items + vendor
    visit_result = await db.execute(_load_service_visits_query(vin))
    service_visits = list(visit_result.scalars().all())

    fuel_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin, FuelRecord.cost.isnot(None))
        .order_by(FuelRecord.date)
    )
    fuel_records = fuel_result.scalars().all()

    # Get spot rental billings
    spot_rental_result = await db.execute(
        select(SpotRentalBilling)
        .join(SpotRental)
        .where(SpotRental.vin == vin, SpotRentalBilling.total.isnot(None))
        .order_by(SpotRentalBilling.billing_date)
    )
    spot_rental_billings = spot_rental_result.scalars().all()

    # Use visits_to_dataframe for financial period totals
    df = analytics_service.visits_to_dataframe(
        service_visits, fuel_records, spot_rental_billings=spot_rental_billings
    )
    comparison = analytics_service.compare_time_periods(
        df, period1_start, period1_end, period2_start, period2_end
    )

    # Calculate MPG for both periods if fuel records exist
    period1_mpg = None
    period2_mpg = None
    mpg_change_pct = None

    if fuel_records:
        period1_fuel = [r for r in fuel_records if period1_start <= r.date <= period1_end]
        period2_fuel = [r for r in fuel_records if period2_start <= r.date <= period2_end]

        if period1_fuel:
            _p1_df, p1_stats = analytics_service.calculate_fuel_economy_with_pandas(period1_fuel)
            if p1_stats:
                period1_mpg = p1_stats.get("average_mpg")

        if period2_fuel:
            _p2_df, p2_stats = analytics_service.calculate_fuel_economy_with_pandas(period2_fuel)
            if p2_stats:
                period2_mpg = p2_stats.get("average_mpg")

        if period1_mpg and period2_mpg:
            mpg_change_pct = (period2_mpg - period1_mpg) / period1_mpg * 100

    if not period1_label:
        period1_label = f"{period1_start.strftime('%b %Y')} - {period1_end.strftime('%b %Y')}"
    if not period2_label:
        period2_label = f"{period2_start.strftime('%b %Y')} - {period2_end.strftime('%b %Y')}"

    # Derive category_changes from line items directly
    category_changes = []

    # Group line items by period
    p1_types: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    p2_types: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))

    for visit in service_visits:
        for item in visit.line_items:
            if item.description and item.cost:
                if period1_start <= visit.date <= period1_end:
                    p1_types[item.description] += item.cost
                elif period2_start <= visit.date <= period2_end:
                    p2_types[item.description] += item.cost

    all_types = set(p1_types.keys()) | set(p2_types.keys())
    for service_type in all_types:
        p1_cost = p1_types.get(service_type, Decimal("0.00"))
        p2_cost = p2_types.get(service_type, Decimal("0.00"))
        change_amount = p2_cost - p1_cost
        change_percent = ((p2_cost - p1_cost) / p1_cost * 100) if p1_cost > 0 else Decimal("0.00")

        category_changes.append(
            CategoryChange(
                category=service_type,
                period1_value=p1_cost,
                period2_value=p2_cost,
                change_amount=change_amount,
                change_percent=change_percent,
            )
        )

    return PeriodComparison(
        period1_label=period1_label,
        period2_label=period2_label,
        period1_start=period1_start,
        period1_end=period1_end,
        period2_start=period2_start,
        period2_end=period2_end,
        period1_total_cost=comparison["period1_cost"],
        period2_total_cost=comparison["period2_cost"],
        cost_change_amount=comparison["period2_cost"] - comparison["period1_cost"],
        cost_change_percent=comparison["cost_change_pct"],
        period1_service_count=comparison["period1_service_count"],
        period2_service_count=comparison["period2_service_count"],
        service_count_change=comparison["period2_service_count"]
        - comparison["period1_service_count"],
        category_changes=category_changes,
        period1_avg_mpg=period1_mpg,
        period2_avg_mpg=period2_mpg,
        mpg_change_percent=mpg_change_pct,
    )


@router.get("/vehicles/{vin}/export")
@limiter.limit(settings.rate_limit_exports)
async def export_analytics_pdf(
    request: Request,
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Export vehicle analytics as PDF report.

    Returns a PDF file with comprehensive analytics data including:
    - Cost analysis summary
    - Rolling averages and spending trends
    - Cost projections
    - Monthly breakdown
    - Service type breakdown
    - Vendor analysis (if available)
    - Seasonal patterns (if available)
    """
    from fastapi.responses import StreamingResponse

    from app.utils.pdf_generator import PDFReportGenerator

    # Verify vehicle access
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Fetch analytics data
    analytics = await get_vehicle_analytics(vin, db, current_user)

    # Fetch vendor analytics
    try:
        vendor_analytics = await get_vendor_analytics(vin, db, current_user)
        vendor_data = vendor_analytics.model_dump()
    except Exception as e:
        logger.error("Error fetching vendor analytics for %s: %s", vin, e)
        vendor_data = None

    # Fetch seasonal analytics
    try:
        seasonal_analytics = await get_seasonal_analytics(vin, db, current_user)
        seasonal_data = seasonal_analytics.model_dump()
    except Exception as e:
        logger.error("Error fetching seasonal analytics for %s: %s", vin, e)
        seasonal_data = None

    # Convert analytics to dict for PDF generator
    analytics_data = analytics.model_dump()

    # Generate PDF
    pdf_generator = PDFReportGenerator()
    pdf_buffer = pdf_generator.generate_analytics_pdf(
        analytics_data=analytics_data,
        vendor_data=vendor_data,
        seasonal_data=seasonal_data,
    )

    # Return PDF as streaming response
    filename = f"mygarage-analytics-{vin}-{datetime.now().strftime('%Y%m%d')}.pdf"

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
