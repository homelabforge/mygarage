# pyright: reportOptionalOperand=false
"""Fuel economy and propane cost calculations."""

import calendar
from decimal import Decimal
from typing import Any

import pandas as pd

from app.models import FuelRecord
from app.services.analytics_service.trends import calculate_trend_direction


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
