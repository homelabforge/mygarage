"""Analytics service with pandas-based data processing."""

import calendar
from datetime import date as date_type
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from app.models import DEFRecord, FuelRecord, ServiceRecord, ServiceVisit, SpotRentalBilling


def visits_to_dataframe(
    service_visits: list[ServiceVisit],
    fuel_records: list[FuelRecord],
    def_records: list[DEFRecord] | None = None,
    spot_rental_billings: list[SpotRentalBilling] | None = None,
) -> pd.DataFrame:
    """
    Convert ServiceVisit records to a unified pandas DataFrame.

    One row per visit (not per line item) for financial accuracy.
    Uses visit.calculated_total_cost which includes tax/fees.

    Args:
        service_visits: List of ServiceVisit objects (with line_items loaded)
        fuel_records: List of FuelRecord objects
        def_records: Optional list of DEFRecord objects
        spot_rental_billings: Optional list of SpotRentalBilling objects

    Returns:
        DataFrame with columns: date, cost, type, vendor, mileage, service_type, etc.
    """
    # Convert service visits — one row per visit
    service_data = []
    for visit in service_visits:
        total = visit.calculated_total_cost
        if total is None or (total == 0 and not visit.line_items):
            continue

        # Use first line item description for DataFrame service_type field
        first_desc = None
        if visit.line_items:
            first_desc = visit.line_items[0].description
        service_type_label = first_desc or visit.notes or "Service"

        service_data.append(
            {
                "date": pd.Timestamp(visit.date),
                "cost": float(total),
                "type": "service",
                "vendor": visit.vendor.name if visit.vendor else "Unknown",
                "mileage": visit.mileage,
                "service_type": service_type_label,
                "service_category": visit.service_category or "Maintenance",
                "description": visit.notes,
            }
        )

    # Convert fuel records
    fuel_data = []
    for record in fuel_records:
        if record.date and record.cost:
            fuel_data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "cost": float(record.cost),
                    "type": "fuel",
                    "vendor": "Fuel Station",
                    "mileage": record.mileage,
                    "service_type": "Fuel",
                    "gallons": float(record.gallons) if record.gallons else None,
                }
            )

    # Convert DEF records
    def_data = []
    if def_records:
        for record in def_records:
            if record.date and record.cost:
                def_data.append(
                    {
                        "date": pd.Timestamp(record.date),
                        "cost": float(record.cost),
                        "type": "def",
                        "vendor": record.source or "DEF",
                        "mileage": record.mileage,
                        "service_type": "DEF",
                    }
                )

    # Convert spot rental billing records
    spot_rental_data = []
    if spot_rental_billings:
        for record in spot_rental_billings:
            if record.billing_date and record.total:
                spot_rental_data.append(
                    {
                        "date": pd.Timestamp(record.billing_date),
                        "cost": float(record.total),
                        "type": "spot_rental",
                        "vendor": "RV Park",
                        "mileage": None,
                        "service_type": "Spot Rental",
                        "description": record.notes or "Monthly RV spot rental",
                    }
                )

    # Combine and create DataFrame
    all_data = service_data + fuel_data + def_data + spot_rental_data

    if not all_data:
        return pd.DataFrame(
            columns=[
                "date",
                "cost",
                "type",
                "vendor",
                "mileage",
                "service_type",
                "service_category",
                "description",
                "gallons",
            ]
        )

    df = pd.DataFrame(all_data)
    df = df.sort_values("date").reset_index(drop=True)

    return df


def records_to_dataframe(
    service_records: list[ServiceRecord],
    fuel_records: list[FuelRecord],
    spot_rental_billings: list[SpotRentalBilling] | None = None,
) -> pd.DataFrame:
    """
    Convert SQLAlchemy records to a unified pandas DataFrame.

    .. deprecated::
        Use ``visits_to_dataframe()`` instead. This function reads from legacy
        ServiceRecord and will be removed when that model is dropped.

    Args:
        service_records: List of ServiceRecord objects
        fuel_records: List of FuelRecord objects
        spot_rental_billings: Optional list of SpotRentalBilling objects

    Returns:
        DataFrame with columns: date, cost, type, vendor, mileage, service_type, etc.
    """
    # Convert service records
    service_data = []
    for record in service_records:
        if record.date and record.cost:
            service_data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "cost": float(record.cost),
                    "type": "service",
                    "vendor": record.vendor_name or "Unknown",
                    "mileage": record.mileage,
                    "service_type": record.service_type,  # Now holds specific service type
                    "service_category": record.service_category,  # Category grouping
                    "description": record.notes,  # Notes field for additional details
                }
            )

    # Convert fuel records
    fuel_data = []
    for record in fuel_records:
        if record.date and record.cost:
            fuel_data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "cost": float(record.cost),
                    "type": "fuel",
                    "vendor": "Fuel Station",  # FuelRecord doesn't have a station/vendor field
                    "mileage": record.mileage,
                    "service_type": "Fuel",
                    "gallons": float(record.gallons) if record.gallons else None,
                }
            )

    # Convert spot rental billing records
    spot_rental_data = []
    if spot_rental_billings:
        for record in spot_rental_billings:
            if record.billing_date and record.total:
                spot_rental_data.append(
                    {
                        "date": pd.Timestamp(record.billing_date),
                        "cost": float(record.total),
                        "type": "spot_rental",
                        "vendor": "RV Park",
                        "mileage": None,
                        "service_type": "Spot Rental",
                        "description": record.notes or "Monthly RV spot rental",
                    }
                )

    # Combine and create DataFrame
    all_data = service_data + fuel_data + spot_rental_data

    if not all_data:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(
            columns=[
                "date",
                "cost",
                "type",
                "vendor",
                "mileage",
                "service_type",
                "service_category",
                "description",
                "gallons",
            ]
        )

    df = pd.DataFrame(all_data)
    df = df.sort_values("date").reset_index(drop=True)

    return df


def calculate_monthly_aggregation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate costs by month using pandas groupby.

    Args:
        df: DataFrame with 'date', 'cost', 'type' columns

    Returns:
        DataFrame with monthly aggregations
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "year",
                "month",
                "service_cost",
                "fuel_cost",
                "def_cost",
                "spot_rental_cost",
                "service_count",
                "fuel_count",
                "def_count",
                "spot_rental_count",
                "total_cost",
            ]
        )

    # Add year and month columns
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    # Separate service, fuel, DEF, and spot rental
    service_df = df[df["type"] == "service"].copy()
    fuel_df = df[df["type"] == "fuel"].copy()
    def_df = df[df["type"] == "def"].copy()
    spot_rental_df = df[df["type"] == "spot_rental"].copy()

    # Aggregate service by month
    service_monthly = (
        service_df.groupby(["year", "month"]).agg({"cost": ["sum", "count"]}).reset_index()
    )
    service_monthly.columns = ["year", "month", "service_cost", "service_count"]

    # Aggregate fuel by month
    fuel_monthly = fuel_df.groupby(["year", "month"]).agg({"cost": ["sum", "count"]}).reset_index()
    fuel_monthly.columns = ["year", "month", "fuel_cost", "fuel_count"]

    # Aggregate DEF by month
    if not def_df.empty:
        def_monthly = (
            def_df.groupby(["year", "month"]).agg({"cost": ["sum", "count"]}).reset_index()
        )
        def_monthly.columns = ["year", "month", "def_cost", "def_count"]
    else:
        def_monthly = pd.DataFrame(columns=["year", "month", "def_cost", "def_count"])

    # Aggregate spot rental by month
    spot_rental_monthly = (
        spot_rental_df.groupby(["year", "month"]).agg({"cost": ["sum", "count"]}).reset_index()
    )
    spot_rental_monthly.columns = [
        "year",
        "month",
        "spot_rental_cost",
        "spot_rental_count",
    ]

    # Merge service, fuel, DEF, and spot rental
    monthly = pd.merge(service_monthly, fuel_monthly, on=["year", "month"], how="outer")
    monthly = pd.merge(monthly, def_monthly, on=["year", "month"], how="outer")
    monthly = pd.merge(monthly, spot_rental_monthly, on=["year", "month"], how="outer").fillna(0)

    # Calculate totals
    monthly["total_cost"] = (
        monthly["service_cost"]
        + monthly["fuel_cost"]
        + monthly["def_cost"]
        + monthly["spot_rental_cost"]
    )
    monthly["month_name"] = monthly["month"].apply(lambda x: calendar.month_name[int(x)])

    # Convert to integers where appropriate
    monthly["service_count"] = monthly["service_count"].astype(int)
    monthly["fuel_count"] = monthly["fuel_count"].astype(int)
    monthly["def_count"] = monthly["def_count"].astype(int)
    monthly["spot_rental_count"] = monthly["spot_rental_count"].astype(int)

    return monthly.sort_values(["year", "month"])


def calculate_rolling_averages(
    monthly_df: pd.DataFrame, windows: list[int] = [3, 6, 12]
) -> dict[str, Decimal | None]:
    """
    Calculate rolling averages for different time windows.

    Args:
        monthly_df: DataFrame with monthly cost data
        windows: List of window sizes in months (default: [3, 6, 12])

    Returns:
        Dictionary with rolling averages for each window
    """
    if monthly_df.empty or len(monthly_df) < 2:
        return {f"rolling_{w}m": None for w in windows}

    # Ensure sorted by date
    monthly_df = monthly_df.sort_values(["year", "month"]).copy()

    result = {}
    for window in windows:
        if len(monthly_df) >= window:
            rolling_avg = monthly_df["total_cost"].rolling(window=window).mean().iloc[-1]
            result[f"rolling_{window}m"] = Decimal(str(round(rolling_avg, 2)))
        else:
            result[f"rolling_{window}m"] = None

    return result


def calculate_trend_direction(values: pd.Series, threshold: float = 0.05) -> str:
    """
    Calculate trend direction using linear regression.

    Args:
        values: Series of numeric values
        threshold: Minimum percentage change to consider as trend (default: 5%)

    Returns:
        "increasing", "decreasing", or "stable"
    """
    if len(values) < 3:
        return "stable"

    # Use simple linear regression
    x = np.arange(len(values))
    y = values.values

    # Calculate slope
    slope = np.polyfit(x, y, 1)[0]

    # Calculate percentage change
    mean_value = y.mean()
    if mean_value == 0:
        return "stable"

    trend_pct = (slope * len(values)) / mean_value

    if trend_pct > threshold:
        return "increasing"
    elif trend_pct < -threshold:
        return "decreasing"
    else:
        return "stable"


def calculate_fuel_economy_with_pandas(
    fuel_records: list[FuelRecord],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Calculate fuel economy statistics using pandas.

    Args:
        fuel_records: List of FuelRecord objects

    Returns:
        Tuple of (DataFrame with MPG data points, statistics dict)
    """
    if not fuel_records or len(fuel_records) < 2:
        return pd.DataFrame(), {}

    # Convert to DataFrame
    data = []
    for record in fuel_records:
        if record.date and record.gallons and record.mileage:
            data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "mileage": record.mileage,
                    "gallons": float(record.gallons),
                    "cost": float(record.cost) if record.cost else 0.0,
                }
            )

    if not data:
        return pd.DataFrame(), {}

    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    # Calculate MPG using diff
    df["miles_driven"] = df["mileage"].diff()

    # Filter invalid trips (0/negative miles, unrealistic distances)
    # This catches odometer errors, data entry mistakes, etc.
    df = df[(df["miles_driven"] > 0) & (df["miles_driven"] <= 1000)].copy()

    df["mpg"] = df["miles_driven"] / df["gallons"]

    # Filter unrealistic MPG values (< 5 or > 100)
    # Catches remaining data quality issues
    df = df[(df["mpg"] >= 5.0) & (df["mpg"] <= 100.0)].copy()

    # Remove rows with NaN MPG
    df = df[df["mpg"].notna()].copy()

    if df.empty:
        return pd.DataFrame(), {}

    # Calculate statistics with weighted average for more accuracy
    total_miles = df["miles_driven"].sum()
    total_gallons = df["gallons"].sum()
    weighted_avg_mpg = total_miles / total_gallons if total_gallons > 0 else 0

    stats = {
        "average_mpg": Decimal(str(round(weighted_avg_mpg, 2))),
        "best_mpg": Decimal(str(round(df["mpg"].max(), 2))),
        "worst_mpg": Decimal(str(round(df["mpg"].min(), 2))),
        "recent_mpg": Decimal(str(round(df["mpg"].iloc[-1], 2))),
        "trend": calculate_trend_direction(df["mpg"].tail(10)),
        "std_dev": Decimal(str(round(df["mpg"].std(), 2))),
    }

    return df, stats


def calculate_seasonal_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze spending patterns by season.

    Args:
        df: DataFrame with date and cost columns

    Returns:
        DataFrame with seasonal aggregations (always includes all 4 seasons)
    """
    # Define all seasons
    season_order = ["Winter", "Spring", "Summer", "Fall"]

    if df.empty:
        # Return empty DataFrame with all 4 seasons and zero values
        return pd.DataFrame(
            {
                "season": season_order,
                "total_cost": [0.0, 0.0, 0.0, 0.0],
                "avg_cost": [0.0, 0.0, 0.0, 0.0],
                "count": [0, 0, 0, 0],
            }
        )

    # Define seasons based on month
    def get_season(month: int) -> str:
        if month in [12, 1, 2]:
            return "Winter"
        elif month in [3, 4, 5]:
            return "Spring"
        elif month in [6, 7, 8]:
            return "Summer"
        else:  # 9, 10, 11
            return "Fall"

    df["month"] = df["date"].dt.month
    df["season"] = df["month"].apply(get_season)

    # Aggregate by season
    seasonal = df.groupby("season").agg({"cost": ["sum", "mean", "count"]}).reset_index()

    seasonal.columns = ["season", "total_cost", "avg_cost", "count"]

    # Create DataFrame with all seasons to ensure missing ones have zero values
    all_seasons = pd.DataFrame({"season": season_order})

    # Merge to include missing seasons with zero values
    seasonal = all_seasons.merge(seasonal, on="season", how="left")

    # Fill missing values with zeros
    seasonal["total_cost"] = seasonal["total_cost"].fillna(0.0)
    seasonal["avg_cost"] = seasonal["avg_cost"].fillna(0.0)
    seasonal["count"] = seasonal["count"].fillna(0).astype(int)

    # Order seasons chronologically
    seasonal["season"] = pd.Categorical(seasonal["season"], categories=season_order, ordered=True)
    seasonal = seasonal.sort_values("season")

    return seasonal


def calculate_vendor_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze costs and service patterns by vendor.

    Args:
        df: DataFrame with vendor and cost columns

    Returns:
        DataFrame with vendor aggregations
    """
    if df.empty or "vendor" not in df.columns:
        return pd.DataFrame(
            columns=[
                "vendor",
                "total_spent",
                "service_count",
                "avg_cost",
                "last_service_date",
            ]
        )

    # Filter out fuel records for vendor analysis
    service_df = df[df["type"] == "service"].copy()

    if service_df.empty:
        return pd.DataFrame(
            columns=[
                "vendor",
                "total_spent",
                "service_count",
                "avg_cost",
                "last_service_date",
            ]
        )

    # Aggregate by vendor
    vendor_stats = (
        service_df.groupby("vendor")
        .agg(
            {
                "cost": ["sum", "mean", "count"],
                "date": "max",
                "service_type": lambda x: list(x.unique()),
            }
        )
        .reset_index()
    )

    vendor_stats.columns = [
        "vendor",
        "total_spent",
        "avg_cost",
        "service_count",
        "last_service_date",
        "service_types",
    ]

    # Sort by total spent (descending)
    vendor_stats = vendor_stats.sort_values("total_spent", ascending=False)

    return vendor_stats


def compare_time_periods(
    df: pd.DataFrame,
    period1_start: date_type,
    period1_end: date_type,
    period2_start: date_type,
    period2_end: date_type,
) -> dict[str, Any]:
    """
    Compare costs and metrics between two time periods.

    Args:
        df: DataFrame with date and cost columns
        period1_start: Start date of first period
        period1_end: End date of first period
        period2_start: Start date of second period
        period2_end: End date of second period

    Returns:
        Dictionary with comparison metrics
    """
    if df.empty:
        return {
            "period1_cost": Decimal("0.00"),
            "period2_cost": Decimal("0.00"),
            "cost_change_pct": Decimal("0.00"),
            "period1_count": 0,
            "period2_count": 0,
        }

    # Filter by periods
    period1 = df[
        (df["date"] >= pd.Timestamp(period1_start)) & (df["date"] <= pd.Timestamp(period1_end))
    ]
    period2 = df[
        (df["date"] >= pd.Timestamp(period2_start)) & (df["date"] <= pd.Timestamp(period2_end))
    ]

    # Calculate metrics
    p1_cost = period1["cost"].sum() if not period1.empty else 0.0
    p2_cost = period2["cost"].sum() if not period2.empty else 0.0

    # Calculate percentage change
    if p1_cost > 0:
        change_pct = ((p2_cost - p1_cost) / p1_cost) * 100
    else:
        change_pct = 0.0

    return {
        "period1_cost": Decimal(str(round(p1_cost, 2))),
        "period2_cost": Decimal(str(round(p2_cost, 2))),
        "cost_change_pct": Decimal(str(round(change_pct, 2))),
        "period1_count": len(period1),
        "period2_count": len(period2),
        "period1_service_count": len(period1[period1["type"] == "service"])
        if not period1.empty
        else 0,
        "period2_service_count": len(period2[period2["type"] == "service"])
        if not period2.empty
        else 0,
    }


def detect_anomalies(values: pd.Series, std_threshold: float = 2.0) -> list[int]:
    """
    Detect anomalies using standard deviation method.

    Args:
        values: Series of numeric values
        std_threshold: Number of standard deviations for outlier detection

    Returns:
        List of indices where anomalies are detected
    """
    if len(values) < 3:
        return []

    mean = values.mean()
    std = values.std()

    if std == 0:
        return []

    # Find values outside threshold
    anomalies = []
    for idx, value in enumerate(values):
        z_score = abs((value - mean) / std)
        if z_score > std_threshold:
            anomalies.append(idx)

    return anomalies


def calculate_propane_costs(fuel_records: list[FuelRecord]) -> dict[str, Any]:
    """
    Calculate propane-specific costs and statistics for fifth wheels.

    Args:
        fuel_records: List of FuelRecord objects (filtered for propane)

    Returns:
        Dictionary with propane statistics, monthly trends, and tank breakdown
    """
    # Filter for propane records (propane_gallons > 0 and gallons is None)
    propane_records = [
        r for r in fuel_records if r.propane_gallons and r.propane_gallons > 0 and not r.gallons
    ]

    if not propane_records:
        return {
            "total_spent": Decimal("0.00"),
            "total_gallons": Decimal("0.00"),
            "avg_price_per_gallon": None,
            "record_count": 0,
            "monthly_trend": [],
            "tank_breakdown": {},
            "tank_timeline": [],
            "refill_frequency": {},
        }

    # Convert to DataFrame for analysis
    data = []
    for record in propane_records:
        if record.date and record.cost and record.propane_gallons:
            data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "cost": float(record.cost),
                    "gallons": float(record.propane_gallons),
                    "price_per_gallon": float(record.price_per_unit)
                    if record.price_per_unit
                    else None,
                    "tank_size_lb": float(record.tank_size_lb) if record.tank_size_lb else None,
                    "tank_quantity": int(record.tank_quantity) if record.tank_quantity else None,
                }
            )

    if not data:
        return {
            "total_spent": Decimal("0.00"),
            "total_gallons": Decimal("0.00"),
            "avg_price_per_gallon": None,
            "record_count": 0,
            "monthly_trend": [],
            "tank_breakdown": {},
            "tank_timeline": [],
            "refill_frequency": {},
        }

    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    # Calculate totals
    total_spent = df["cost"].sum()
    total_gallons = df["gallons"].sum()
    avg_price = total_spent / total_gallons if total_gallons > 0 else 0

    # Monthly trend
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    monthly = df.groupby(["year", "month"]).agg({"cost": "sum", "gallons": "sum"}).reset_index()
    monthly["month_name"] = monthly["month"].apply(lambda x: calendar.month_name[int(x)])
    monthly["avg_price"] = monthly["cost"] / monthly["gallons"]

    monthly_trend = [
        {
            "year": int(row["year"]),
            "month": int(row["month"]),
            "month_name": row["month_name"],
            "total_cost": round(row["cost"], 2),
            "total_gallons": round(row["gallons"], 2),
            "avg_price_per_gallon": round(row["avg_price"], 2),
        }
        for _, row in monthly.iterrows()
    ]

    # Tank breakdown analytics
    tank_breakdown = {}
    tank_timeline = []
    refill_frequency = {}

    # Group by tank size
    df["tank_key"] = (
        df["tank_size_lb"]
        .fillna("unknown")
        .apply(lambda x: str(int(x)) if x != "unknown" else "unknown")
    )

    for tank_key in df["tank_key"].unique():
        tank_records = df[df["tank_key"] == tank_key]
        total_tank_gallons = tank_records["gallons"].sum()
        total_tank_cost = tank_records["cost"].sum()
        refill_count = len(tank_records)

        avg_price_per_gallon = total_tank_cost / total_tank_gallons if total_tank_gallons > 0 else 0

        tank_breakdown[tank_key] = {
            "total_gallons": round(total_tank_gallons, 2),
            "total_cost": round(total_tank_cost, 2),
            "refill_count": refill_count,
            "avg_price_per_gallon": round(avg_price_per_gallon, 2),
        }

        # Calculate refill frequency for this tank size
        if refill_count > 1:
            tank_dates = tank_records["date"].sort_values()
            days_between = [
                (tank_dates.iloc[i + 1] - tank_dates.iloc[i]).days
                for i in range(len(tank_dates) - 1)
            ]
            if days_between:
                refill_frequency[tank_key] = {
                    "avg_days_between": round(sum(days_between) / len(days_between), 1),
                    "min_days": int(min(days_between)),
                    "max_days": int(max(days_between)),
                }

    # Timeline data
    for _, row in df.iterrows():
        tank_timeline.append(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "tank_size_lb": int(row["tank_size_lb"]) if pd.notna(row["tank_size_lb"]) else None,
                "tank_quantity": int(row["tank_quantity"])
                if pd.notna(row["tank_quantity"])
                else None,
                "gallons": round(row["gallons"], 2),
                "cost": round(row["cost"], 2),
            }
        )

    return {
        "total_spent": Decimal(str(round(total_spent, 2))),
        "total_gallons": Decimal(str(round(total_gallons, 2))),
        "avg_price_per_gallon": Decimal(str(round(avg_price, 2))) if avg_price > 0 else None,
        "record_count": len(propane_records),
        "monthly_trend": monthly_trend,
        "tank_breakdown": tank_breakdown,
        "tank_timeline": tank_timeline,
        "refill_frequency": refill_frequency,
    }


async def calculate_spot_rental_costs(db: Any, vin: str) -> dict[str, Any]:
    """
    Calculate spot rental costs from billing entries for fifth wheels.

    Args:
        db: AsyncSession for database queries
        vin: Vehicle identification number

    Returns:
        Dictionary with spot rental statistics and monthly trends
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import SpotRental

    # Get all spot rentals with billings for this vehicle
    result = await db.execute(
        select(SpotRental).where(SpotRental.vin == vin).options(selectinload(SpotRental.billings))
    )
    rentals = result.scalars().all()

    # Collect all billing entries
    all_billings = []
    for rental in rentals:
        if rental.billings:
            all_billings.extend(rental.billings)

    if not all_billings:
        return {
            "total_cost": Decimal("0.00"),
            "billing_count": 0,
            "monthly_average": Decimal("0.00"),
            "monthly_trend": [],
        }

    # Convert to DataFrame for analysis
    data = []
    for billing in all_billings:
        if billing.billing_date and billing.total:
            data.append(
                {
                    "date": pd.Timestamp(billing.billing_date),
                    "total": float(billing.total),
                    "monthly_rate": float(billing.monthly_rate) if billing.monthly_rate else 0,
                    "electric": float(billing.electric) if billing.electric else 0,
                    "water": float(billing.water) if billing.water else 0,
                    "waste": float(billing.waste) if billing.waste else 0,
                }
            )

    if not data:
        return {
            "total_cost": Decimal("0.00"),
            "billing_count": 0,
            "monthly_average": Decimal("0.00"),
            "monthly_trend": [],
        }

    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    # Calculate totals
    total_cost = df["total"].sum()
    monthly_avg = df["total"].mean()

    # Monthly trend
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    monthly = (
        df.groupby(["year", "month"])
        .agg(
            {
                "total": "sum",
                "monthly_rate": "sum",
                "electric": "sum",
                "water": "sum",
                "waste": "sum",
            }
        )
        .reset_index()
    )
    monthly["month_name"] = monthly["month"].apply(lambda x: calendar.month_name[int(x)])

    monthly_trend = [
        {
            "year": int(row["year"]),
            "month": int(row["month"]),
            "month_name": row["month_name"],
            "total_cost": round(row["total"], 2),
            "monthly_rate": round(row["monthly_rate"], 2),
            "electric": round(row["electric"], 2),
            "water": round(row["water"], 2),
            "waste": round(row["waste"], 2),
        }
        for _, row in monthly.iterrows()
    ]

    return {
        "total_cost": Decimal(str(round(total_cost, 2))),
        "billing_count": len(all_billings),
        "monthly_average": Decimal(str(round(monthly_avg, 2))),
        "monthly_trend": monthly_trend,
    }
