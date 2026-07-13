# pyright: reportOptionalOperand=false
"""Fuel economy and propane cost calculations.

Metric-canonical since v3: source columns are `odometer_km` and `liters`,
the per-fillup metric is L/100km. Lower L/100km = better fuel economy.
"""

import calendar
from decimal import Decimal
from typing import Any

import pandas as pd

from app.models import FuelRecord
from app.services.analytics_service.trends import calculate_trend_direction
from app.services.fuel_service import compute_full_tank_economy

# Realistic L/100km band (~5–100 MPG). A fill-up outside it is almost always a
# data-entry slip (mistyped odometer/volume); dropping it keeps the trend chart
# and its tiles readable. The raw figure still appears in the fuel-history list.
_MIN_REALISTIC_L_PER_100KM = 2.35
_MAX_REALISTIC_L_PER_100KM = 47.0


def _l_per_100km_trend(values: pd.Series) -> str:
    """Map a numeric trend on L/100km to fuel-economy semantics.

    Lower L/100km is better, so an increasing slope means fuel economy is
    *declining*, and a decreasing slope means it is *improving*.
    """
    direction = calculate_trend_direction(values)
    if direction == "increasing":
        return "declining"
    if direction == "decreasing":
        return "improving"
    return "stable"


def calculate_fuel_economy_with_pandas(
    fuel_records: list[FuelRecord],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Calculate fuel economy statistics (L/100km) using pandas.

    Args:
        fuel_records: List of FuelRecord objects

    Returns:
        Tuple of (DataFrame with L/100km data points, statistics dict)
    """
    if not fuel_records or len(fuel_records) < 2:
        return pd.DataFrame(), {}

    # One economy figure per FULL tank, with every partial fill-up since the
    # previous full tank folded into its numerator (issue #113). This is the
    # same model as the fuel-history list, vehicle average, garage card, and
    # homepage widget, so the Analytics chart and tiles can't tell a different
    # story than the rest of the app. Ordered by odometer, as that model
    # requires; a partial fill-up gets no point of its own.
    records_asc = sorted(
        (r for r in fuel_records if r.odometer_km is not None),
        key=lambda r: (r.odometer_km, r.date),
    )
    economy = compute_full_tank_economy(records_asc, exclude_hauling=False)

    data = []
    for record, l_per_100km in economy:
        value = float(l_per_100km)
        if not (_MIN_REALISTIC_L_PER_100KM <= value <= _MAX_REALISTIC_L_PER_100KM):
            continue
        data.append(
            {
                "date": pd.Timestamp(record.date),
                "odometer_km": float(record.odometer_km),
                "liters": float(record.liters) if record.liters else 0.0,
                "cost": float(record.cost) if record.cost else 0.0,
                "l_per_100km": value,
            }
        )

    if not data:
        return pd.DataFrame(), {}

    # Display in chronological order (== odometer order for sane data) so the
    # chart's X-axis and "recent" tile track the most recent fill-up.
    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    values = df["l_per_100km"]

    # Simple mean of per-full-tank figures — matches calculate_average_l_per_100km.
    # Best is *lowest* L/100km, worst is *highest* (semantic flip from MPG).
    stats = {
        "average_l_per_100km": Decimal(str(round(values.mean(), 2))),
        "best_l_per_100km": Decimal(str(round(values.min(), 2))),
        "worst_l_per_100km": Decimal(str(round(values.max(), 2))),
        "recent_l_per_100km": Decimal(str(round(values.iloc[-1], 2))),
        "trend": _l_per_100km_trend(values.tail(10)),
        "std_dev": (Decimal(str(round(values.std(), 2))) if len(values) > 1 else Decimal("0")),
    }

    return df, stats


def calculate_propane_costs(fuel_records: list[FuelRecord]) -> dict[str, Any]:
    """Calculate propane-specific costs and statistics for fifth wheels.

    Source column is now `propane_liters` and tank size is `tank_size_kg`.

    Args:
        fuel_records: List of FuelRecord objects (filtered for propane)

    Returns:
        Dictionary with propane statistics, monthly trends, and tank breakdown
    """
    # Filter for propane records (propane_liters > 0 and liters is None)
    propane_records = [
        r for r in fuel_records if r.propane_liters and r.propane_liters > 0 and not r.liters
    ]

    if not propane_records:
        return {
            "total_spent": Decimal("0.00"),
            "total_liters": Decimal("0.00"),
            "avg_price_per_liter": None,
            "record_count": 0,
            "monthly_trend": [],
            "tank_breakdown": {},
            "tank_timeline": [],
            "refill_frequency": {},
        }

    # Convert to DataFrame for analysis
    data = []
    for record in propane_records:
        if record.date and record.cost and record.propane_liters:
            data.append(
                {
                    "date": pd.Timestamp(record.date),
                    "cost": float(record.cost),
                    "liters": float(record.propane_liters),
                    "price_per_liter": float(record.price_per_unit)
                    if record.price_per_unit
                    else None,
                    "tank_size_kg": float(record.tank_size_kg) if record.tank_size_kg else None,
                    "tank_quantity": int(record.tank_quantity) if record.tank_quantity else None,
                }
            )

    if not data:
        return {
            "total_spent": Decimal("0.00"),
            "total_liters": Decimal("0.00"),
            "avg_price_per_liter": None,
            "record_count": 0,
            "monthly_trend": [],
            "tank_breakdown": {},
            "tank_timeline": [],
            "refill_frequency": {},
        }

    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    # Calculate totals
    total_spent = df["cost"].sum()
    total_liters = df["liters"].sum()
    avg_price = total_spent / total_liters if total_liters > 0 else 0

    # Monthly trend
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    monthly = df.groupby(["year", "month"]).agg({"cost": "sum", "liters": "sum"}).reset_index()
    monthly["month_name"] = monthly["month"].apply(lambda x: calendar.month_name[int(x)])
    monthly["avg_price"] = monthly["cost"] / monthly["liters"]

    monthly_trend = [
        {
            "year": int(row["year"]),
            "month": int(row["month"]),
            "month_name": row["month_name"],
            "total_cost": round(row["cost"], 2),
            "total_liters": round(row["liters"], 2),
            "avg_price_per_liter": round(row["avg_price"], 2),
        }
        for _, row in monthly.iterrows()
    ]

    # Tank breakdown analytics
    tank_breakdown = {}
    tank_timeline = []
    refill_frequency = {}

    # Group by tank size
    df["tank_key"] = (
        df["tank_size_kg"]
        .fillna("unknown")
        .apply(lambda x: str(int(x)) if x != "unknown" else "unknown")
    )

    for tank_key in df["tank_key"].unique():
        tank_records = df[df["tank_key"] == tank_key]
        total_tank_liters = tank_records["liters"].sum()
        total_tank_cost = tank_records["cost"].sum()
        refill_count = len(tank_records)

        avg_price_per_liter = total_tank_cost / total_tank_liters if total_tank_liters > 0 else 0

        tank_breakdown[tank_key] = {
            "total_liters": round(total_tank_liters, 2),
            "total_cost": round(total_tank_cost, 2),
            "refill_count": refill_count,
            "avg_price_per_liter": round(avg_price_per_liter, 2),
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
                "tank_size_kg": int(row["tank_size_kg"]) if pd.notna(row["tank_size_kg"]) else None,
                "tank_quantity": int(row["tank_quantity"])
                if pd.notna(row["tank_quantity"])
                else None,
                "liters": round(row["liters"], 2),
                "cost": round(row["cost"], 2),
            }
        )

    return {
        "total_spent": Decimal(str(round(total_spent, 2))),
        "total_liters": Decimal(str(round(total_liters, 2))),
        "avg_price_per_liter": Decimal(str(round(avg_price, 2))) if avg_price > 0 else None,
        "record_count": len(propane_records),
        "monthly_trend": monthly_trend,
        "tank_breakdown": tank_breakdown,
        "tank_timeline": tank_timeline,
        "refill_frequency": refill_frequency,
    }
