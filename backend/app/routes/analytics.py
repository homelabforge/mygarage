"""Analytics and reporting routes."""

# pyright: reportArgumentType=false, reportOptionalOperand=false, reportCallIssue=false, reportMissingImports=false

import calendar
import logging
from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import get_db
from app.models import (
    FuelRecord,
    OdometerRecord,
    ServiceRecord,
    SpotRentalBilling,
    Vehicle,
)
from app.models.reminder import Reminder
from app.models.spot_rental import SpotRental
from app.models.user import User
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
from app.services.auth import require_auth
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

    # Get all service records with costs
    service_result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin, ServiceRecord.cost.isnot(None))
        .order_by(ServiceRecord.date)
    )
    service_records = service_result.scalars().all()

    # Get all fuel records with costs
    fuel_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin, FuelRecord.cost.isnot(None))
        .order_by(FuelRecord.date)
    )
    fuel_records = fuel_result.scalars().all()

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

    # Calculate totals
    total_service_cost = sum((r.cost for r in service_records if r.cost), Decimal("0.00"))
    total_fuel_cost = sum((r.cost for r in fuel_records if r.cost), Decimal("0.00"))
    total_spot_rental_cost = sum(
        (r.total for r in spot_rental_billings if r.total), Decimal("0.00")
    )
    total_cost = total_service_cost + total_fuel_cost + total_spot_rental_cost

    # Use pandas for monthly aggregation
    df = analytics_service.records_to_dataframe(service_records, fuel_records, spot_rental_billings)
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
                total_spot_rental_cost=Decimal(str(row["spot_rental_cost"])),
                total_cost=Decimal(str(row["total_cost"])),
                service_count=int(row["service_count"]),
                fuel_count=int(row["fuel_count"]),
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

    # Group service costs by type
    service_type_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": Decimal("0.00"),
            "count": 0,
            "last_date": None,
        }
    )

    for record in service_records:
        if record.service_type and record.cost:
            service_type = record.service_type
            service_type_data[service_type]["total"] += record.cost
            service_type_data[service_type]["count"] += 1
            if (
                not service_type_data[service_type]["last_date"]
                or record.date > service_type_data[service_type]["last_date"]
            ):
                service_type_data[service_type]["last_date"] = record.date

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
    # Collect mileage readings from odometer, fuel, and service records
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

    # Get mileage from service records
    for record in service_records:
        if record.mileage:
            all_mileages.append(record.mileage)

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
        total_cost=total_cost,
        average_monthly_cost=average_monthly_cost,
        service_count=len(service_records),
        fuel_count=len(fuel_records),
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
    """Get service history with timeline context."""

    result = await db.execute(
        select(ServiceRecord).where(ServiceRecord.vin == vin).order_by(ServiceRecord.date.desc())
    )
    service_records = list(result.scalars().all())

    timeline = []
    for i, record in enumerate(service_records):
        # Calculate days/miles since last service of same type
        days_since_last = None
        miles_since_last = None

        # Find previous service of same type
        for prev_record in service_records[i + 1 :]:
            if prev_record.service_type == record.service_type:
                if record.date and prev_record.date:
                    days_since_last = (record.date - prev_record.date).days
                if record.mileage and prev_record.mileage:
                    miles_since_last = record.mileage - prev_record.mileage
                break

        timeline.append(
            ServiceHistoryItem(
                date=record.date,
                service_type=record.service_type,  # Now specific service type (e.g., "Oil Change")
                description=record.notes,  # Additional notes/details
                mileage=record.mileage,
                cost=record.cost,
                vendor_name=record.vendor_name,
                days_since_last=days_since_last,
                miles_since_last=miles_since_last,
            )
        )

    return timeline


@cached(ttl_seconds=600)  # Cache for 10 minutes
async def get_maintenance_predictions(
    db: AsyncSession, vin: str, current_mileage: int | None = None
) -> list[MaintenancePrediction]:
    """Predict upcoming maintenance based on service history."""

    # Get service history
    result = await db.execute(
        select(ServiceRecord).where(ServiceRecord.vin == vin).order_by(ServiceRecord.date)
    )
    service_records = list(result.scalars().all())

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

    # Create mapping of service types to reminders (fuzzy match)
    reminder_map: dict[str, Reminder] = {}
    for reminder in reminders:
        for service_type in set(r.service_type for r in service_records):
            # Fuzzy match: check if service type appears in reminder description
            if service_type.lower() in reminder.description.lower():
                reminder_map[service_type] = reminder
                break

    # Group by service type and calculate intervals
    service_intervals: dict[str, list[dict[str, Any]]] = defaultdict(list[Any])

    for i in range(len(service_records) - 1):
        current = service_records[i + 1]
        previous = service_records[i]

        if current.service_type == previous.service_type:
            interval_data = {}

            if current.date and previous.date:
                interval_data["days"] = (current.date - previous.date).days
                interval_data["date"] = current.date

            if current.mileage and previous.mileage:
                interval_data["miles"] = current.mileage - previous.mileage
                interval_data["mileage"] = current.mileage

            if interval_data:
                service_intervals[current.service_type].append(interval_data)

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
        most_recent = None
        for record in reversed(service_records):
            if record.service_type == service_type:
                most_recent = record
                break

        if not most_recent or not most_recent.date:
            continue

        # Predict next service
        predicted_date = None
        days_until_due = None
        if avg_days:
            predicted_date = most_recent.date + timedelta(days=avg_days)
            days_until_due = (predicted_date - today).days

        predicted_mileage = None
        miles_until_due = None
        if avg_miles and most_recent.mileage and current_mileage:
            predicted_mileage = most_recent.mileage + avg_miles
            miles_until_due = predicted_mileage - current_mileage

        # Determine confidence based on consistency of intervals
        confidence = "low"
        if len(intervals) >= 3:
            if day_intervals:
                variance = sum((x - avg_days) ** 2 for x in day_intervals) / len(day_intervals)
                std_dev = variance**0.5
                if std_dev < avg_days * 0.2:  # Less than 20% variation
                    confidence = "high"
                elif std_dev < avg_days * 0.4:  # Less than 40% variation
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
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    )


@router.get("/garage", response_model=GarageAnalytics)
async def get_garage_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get comprehensive analytics aggregated across all vehicles in the garage.
    """
    # Get all vehicles with eager loading to avoid N+1 queries
    vehicles_result = await db.execute(
        select(Vehicle).options(
            selectinload(Vehicle.service_records),
            selectinload(Vehicle.fuel_records),
            selectinload(Vehicle.insurance_policies),
            selectinload(Vehicle.tax_records),
        )
    )
    vehicles = vehicles_result.scalars().all()

    if not vehicles:
        # Return empty analytics if no vehicles
        return GarageAnalytics(
            total_costs=GarageCostTotals(),
            cost_breakdown_by_category=[],
            cost_by_vehicle=[],
            monthly_trends=[],
            vehicle_count=0,
        )

    # Initialize totals
    total_garage_value = Decimal("0.00")
    # Service category totals
    total_maintenance = Decimal("0.00")
    total_upgrades = Decimal("0.00")
    total_inspection = Decimal("0.00")
    total_collision = Decimal("0.00")
    total_detailing = Decimal("0.00")
    # Other totals
    total_fuel = Decimal("0.00")
    total_insurance = Decimal("0.00")
    total_taxes = Decimal("0.00")

    # Track costs by vehicle
    vehicle_costs = []

    # Track monthly trends across garage
    monthly_data: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {
            "maintenance": Decimal("0.00"),
            "fuel": Decimal("0.00"),
        }
    )

    # Process each vehicle
    for vehicle in vehicles:
        vin = vehicle.vin
        vehicle_name = f"{vehicle.year} {vehicle.make} {vehicle.model}"

        # Add purchase price to garage value
        purchase_price = vehicle.purchase_price or Decimal("0.00")
        total_garage_value += purchase_price

        # Use eager-loaded insurance policies (no additional query)
        for policy in vehicle.insurance_policies:
            if policy.premium_amount:
                total_insurance += policy.premium_amount

        # Use eager-loaded tax records (no additional query)
        for tax_record in vehicle.tax_records:
            if tax_record.amount:
                total_taxes += tax_record.amount

        # Use eager-loaded service records (no additional query)
        service_records = [r for r in vehicle.service_records if r.cost is not None]
        service_records.sort(key=lambda r: r.date)

        # Use eager-loaded fuel records (no additional query)
        fuel_records = [r for r in vehicle.fuel_records if r.cost is not None]
        fuel_records.sort(key=lambda r: r.date)

        # Calculate vehicle totals by service category
        vehicle_maintenance = Decimal("0.00")
        vehicle_upgrades = Decimal("0.00")
        vehicle_inspection = Decimal("0.00")
        vehicle_collision = Decimal("0.00")
        vehicle_detailing = Decimal("0.00")

        for record in service_records:
            if record.cost:
                category = record.service_category or "Maintenance"
                if category == "Maintenance":
                    vehicle_maintenance += record.cost
                elif category == "Upgrades":
                    vehicle_upgrades += record.cost
                elif category == "Inspection":
                    vehicle_inspection += record.cost
                elif category == "Collision":
                    vehicle_collision += record.cost
                elif category == "Detailing":
                    vehicle_detailing += record.cost
                else:
                    # Default to maintenance for unknown categories
                    vehicle_maintenance += record.cost

        vehicle_fuel = sum((r.cost for r in fuel_records if r.cost), Decimal("0.00"))

        # Running costs = all service categories + fuel (excludes purchase price)
        vehicle_total = (
            vehicle_maintenance
            + vehicle_upgrades
            + vehicle_inspection
            + vehicle_collision
            + vehicle_detailing
            + vehicle_fuel
        )

        # Add to garage totals
        total_maintenance += vehicle_maintenance
        total_upgrades += vehicle_upgrades
        total_inspection += vehicle_inspection
        total_collision += vehicle_collision
        total_detailing += vehicle_detailing
        total_fuel += vehicle_fuel

        # Add to vehicle costs list
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
                total_cost=vehicle_total,
            )
        )

        # Add to monthly trends
        for record in service_records:
            if record.date and record.cost:
                key = (record.date.year, record.date.month)
                monthly_data[key]["maintenance"] += record.cost

        for record in fuel_records:
            if record.date and record.cost:
                key = (record.date.year, record.date.month)
                monthly_data[key]["fuel"] += record.cost

    # Sort vehicle costs by total cost (descending)
    vehicle_costs.sort(key=lambda x: x.total_cost, reverse=True)

    # Create cost breakdown by category (only include categories with amounts > 0)
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
    if total_insurance > 0:
        cost_breakdown.append(GarageCostByCategory(category="Insurance", amount=total_insurance))
    if total_taxes > 0:
        cost_breakdown.append(GarageCostByCategory(category="Taxes", amount=total_taxes))

    # Create monthly trends (last 12 months)
    monthly_trends = []
    sorted_months = sorted(monthly_data.items())[-12:]  # Get last 12 months

    for (year, month), data in sorted_months:
        month_name = f"{calendar.month_abbr[month]} {year}"
        monthly_trends.append(
            GarageMonthlyTrend(
                month=month_name,
                maintenance=data["maintenance"],
                fuel=data["fuel"],
                total=data["maintenance"] + data["fuel"],
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
                "maintenance": str(t.maintenance),
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

    # Verify ownership
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin, Vehicle.user_id == user.id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get service records
    service_result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin, ServiceRecord.cost.isnot(None))
        .order_by(ServiceRecord.date)
    )
    service_records = service_result.scalars().all()

    if not service_records:
        return VendorAnalyticsSummary()

    # Use pandas for vendor analysis
    df = analytics_service.records_to_dataframe(service_records, [])
    vendor_df = analytics_service.calculate_vendor_analysis(df)

    if vendor_df.empty:
        return VendorAnalyticsSummary()

    # Convert to Pydantic models
    vendors = []
    for _, row in vendor_df.iterrows():
        vendors.append(
            VendorAnalysis(
                vendor_name=row["vendor"],
                total_spent=Decimal(str(round(row["total_spent"], 2))),
                service_count=int(row["service_count"]),
                average_cost=Decimal(str(round(row["avg_cost"], 2))),
                service_types=row["service_types"],
                last_service_date=row["last_service_date"].date()
                if row["last_service_date"]
                else None,
            )
        )

    # Find most used and highest spending vendors
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

    # Verify ownership
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin, Vehicle.user_id == user.id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all records
    service_result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin, ServiceRecord.cost.isnot(None))
        .order_by(ServiceRecord.date)
    )
    service_records = service_result.scalars().all()

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

    if not service_records and not fuel_records and not spot_rental_billings:
        return SeasonalAnalyticsSummary()

    # Use pandas for seasonal analysis
    df = analytics_service.records_to_dataframe(service_records, fuel_records, spot_rental_billings)
    seasonal_df = analytics_service.calculate_seasonal_patterns(df)

    if seasonal_df.empty:
        return SeasonalAnalyticsSummary()

    # Calculate annual average
    annual_average = seasonal_df["total_cost"].mean()

    # Convert to Pydantic models
    seasons = []
    for _, row in seasonal_df.iterrows():
        # Calculate variance from annual average
        variance = (
            ((row["total_cost"] - annual_average) / annual_average * 100)
            if annual_average > 0
            else 0
        )

        # Get common services for this season
        season_df = df[
            df["date"].dt.month.isin(
                {
                    "Winter": [12, 1, 2],
                    "Spring": [3, 4, 5],
                    "Summer": [6, 7, 8],
                    "Fall": [9, 10, 11],
                }[row["season"]]
            )
        ]
        # Only get common services if there are records for this season
        common_services = (
            season_df["service_type"].value_counts().head(3).index.tolist()
            if not season_df.empty and "service_type" in season_df.columns
            else []
        )

        seasons.append(
            SeasonalAnalysis(
                season=row["season"],
                total_cost=Decimal(str(round(row["total_cost"], 2))),
                average_cost=Decimal(str(round(row["avg_cost"], 2))),
                service_count=int(row["count"]),
                variance_from_annual=Decimal(str(round(variance, 2))),
                common_services=common_services,
            )
        )

    # Find highest and lowest cost seasons
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

    # Verify ownership
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin, Vehicle.user_id == user.id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get all records
    service_result = await db.execute(
        select(ServiceRecord)
        .where(ServiceRecord.vin == vin, ServiceRecord.cost.isnot(None))
        .order_by(ServiceRecord.date)
    )
    service_records = service_result.scalars().all()

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

    # Use pandas for comparison
    df = analytics_service.records_to_dataframe(service_records, fuel_records, spot_rental_billings)
    comparison = analytics_service.compare_time_periods(
        df, period1_start, period1_end, period2_start, period2_end
    )

    # Calculate MPG for both periods if fuel records exist
    period1_mpg = None
    period2_mpg = None
    mpg_change_pct = None

    if fuel_records:
        # Filter fuel records by period
        period1_fuel = [r for r in fuel_records if period1_start <= r.date <= period1_end]
        period2_fuel = [r for r in fuel_records if period2_start <= r.date <= period2_end]

        if period1_fuel:
            p1_df, p1_stats = analytics_service.calculate_fuel_economy_with_pandas(period1_fuel)
            if p1_stats:
                period1_mpg = p1_stats.get("average_mpg")

        if period2_fuel:
            p2_df, p2_stats = analytics_service.calculate_fuel_economy_with_pandas(period2_fuel)
            if p2_stats:
                period2_mpg = p2_stats.get("average_mpg")

        if period1_mpg and period2_mpg:
            mpg_change_pct = (period2_mpg - period1_mpg) / period1_mpg * 100

    # Generate labels if not provided
    if not period1_label:
        period1_label = f"{period1_start.strftime('%b %Y')} - {period1_end.strftime('%b %Y')}"
    if not period2_label:
        period2_label = f"{period2_start.strftime('%b %Y')} - {period2_end.strftime('%b %Y')}"

    # Category breakdown (service type)
    category_changes = []

    # Get period-specific DataFrames
    p1_df = df[
        (df["date"] >= pd.Timestamp(period1_start)) & (df["date"] <= pd.Timestamp(period1_end))
    ]
    p2_df = df[
        (df["date"] >= pd.Timestamp(period2_start)) & (df["date"] <= pd.Timestamp(period2_end))
    ]

    if not p1_df.empty or not p2_df.empty:
        # Get all unique service types
        all_types = set[str](p1_df["service_type"].unique() if not p1_df.empty else []) | set(
            p2_df["service_type"].unique() if not p2_df.empty else []
        )

        for service_type in all_types:
            p1_cost = (
                p1_df[p1_df["service_type"] == service_type]["cost"].sum() if not p1_df.empty else 0
            )
            p2_cost = (
                p2_df[p2_df["service_type"] == service_type]["cost"].sum() if not p2_df.empty else 0
            )

            change_amount = p2_cost - p1_cost
            change_percent = ((p2_cost - p1_cost) / p1_cost * 100) if p1_cost > 0 else 0

            category_changes.append(
                CategoryChange(
                    category=service_type,
                    period1_value=Decimal(str(round(p1_cost, 2))),
                    period2_value=Decimal(str(round(p2_cost, 2))),
                    change_amount=Decimal(str(round(change_amount, 2))),
                    change_percent=Decimal(str(round(change_percent, 2))),
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

    # Verify vehicle ownership
    vehicle_result = await db.execute(
        select(Vehicle).where(Vehicle.vin == vin, Vehicle.user_id == current_user.id)
    )
    vehicle = vehicle_result.scalar_one_or_none()

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
