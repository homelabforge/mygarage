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
from app.services.fuel_service import (
    L_PER_100KM_PLACES,
    average_l_per_100km,
    compute_full_tank_hours_economy,
    economy_periods,
    is_bottle_refill,
)


def _lower_is_better_trend(values: pd.Series) -> str:
    """Map a numeric trend to fuel-economy semantics where LOWER is better.

    Shared by the distance (L/100km) and hours (L/hr) consumption trends:
    an increasing slope means consumption is rising, i.e. efficiency is
    *declining*; a decreasing slope means efficiency is *improving*.
    """
    direction = calculate_trend_direction(values)
    if direction == "increasing":
        return "declining"
    if direction == "decreasing":
        return "improving"
    return "stable"


def _l_per_100km_trend(values: pd.Series) -> str:
    """Map a numeric trend on L/100km to fuel-economy semantics.

    Lower L/100km is better, so an increasing slope means fuel economy is
    *declining*, and a decreasing slope means it is *improving*.
    """
    return _lower_is_better_trend(values)


def _l_per_hr_trend(values: pd.Series) -> str:
    """Map a numeric trend on L/hr to fuel-economy semantics.

    The hours mirror of :func:`_l_per_100km_trend` — lower L/hr is better
    (less fuel burned per hour of engine operation), same direction mapping.
    """
    return _lower_is_better_trend(values)


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
        key=lambda r: (r.odometer_km, r.date, r.id),
    )
    # Every tank, towing included: the chart plots each one. A tank outside the
    # realistic band (fuel_service.MIN_REALISTIC_L_PER_100KM) is almost always a
    # data-entry slip; it drops out of the points AND the average, and its raw
    # figure still appears in the fuel-history list.
    plotted = [period for period in economy_periods(records_asc) if period.plausible]

    data = []
    for period in plotted:
        record = period.record
        value = float(period.l_per_100km)
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

    # The average is total fuel over total distance, as everywhere else; best,
    # worst and recent are per tank. Best is *lowest* L/100km, worst is
    # *highest* (semantic flip from MPG).
    stats = {
        "average_l_per_100km": average_l_per_100km(plotted),
        "best_l_per_100km": Decimal(str(round(values.min(), L_PER_100KM_PLACES))),
        "worst_l_per_100km": Decimal(str(round(values.max(), L_PER_100KM_PLACES))),
        "recent_l_per_100km": Decimal(str(round(values.iloc[-1], L_PER_100KM_PLACES))),
        "trend": _l_per_100km_trend(values.tail(10)),
        "std_dev": (Decimal(str(round(values.std(), 2))) if len(values) > 1 else Decimal("0")),
    }

    return df, stats


def calculate_hours_economy_with_pandas(
    fuel_records: list[FuelRecord],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Calculate engine-hours fuel economy statistics (L/hr + cost/hr).

    The hours mirror of :func:`calculate_fuel_economy_with_pandas`: one row
    per full-tank hours-economy endpoint (partials folded into the interval
    by :func:`compute_full_tank_hours_economy`), displayed in chronological
    order. Two deliberate differences from the distance function:

    - No realistic-range filter. L/100km has a physically sane band (~5-100
      MPG) because every vehicle covers the same km with its wheels; L/hr has
      no such band — a lawn tractor and a diesel generator both report
      "hours" but burn wildly different rates, so a universal filter would
      silently drop legitimate readings for one device class or another.
    - Values stay ``Decimal`` end to end, no float round-trip: the inputs
      from :func:`compute_full_tank_hours_economy` are already exact
      ``Decimal`` figures (unlike the distance path, which downgrades to
      ``float`` for the realistic-range comparison above). ``pandas`` holds
      them as an ``object``-dtype column, so ``None`` survives untouched
      (no silent coercion to ``NaN``); aggregates (best/worst/recent) are
      computed in plain Python rather than ``Series.mean()``/``.min()``,
      which require a numeric dtype.

    A zero-liters interval (P3 backlog fix in ``calculate_hours_economy``)
    still produces a row — ``cost_per_hr`` is always valid for a scored
    interval — but with ``l_per_hr`` set to ``None`` rather than a phantom
    ``0.00``. It is excluded from ``best``/``worst``/``recent_l_per_hr``/
    ``trend`` the same way :func:`calculate_average_hours_economy` excludes
    it from the vehicle-level average.

    Args:
        fuel_records: Every fuel record for the vehicle, any order.

    Returns:
        Tuple of (DataFrame with one row per scored full-tank endpoint,
        statistics dict). Both are empty when fewer than 2 records carry an
        ``engine_hours`` reading (mirrors the distance function's <2-record
        floor).
    """
    if not fuel_records or len(fuel_records) < 2:
        return pd.DataFrame(), {}

    # Consecutive full-tank endpoints tile the hours axis, so records must be
    # fed in engine_hours order for the accumulator in
    # compute_full_tank_hours_economy to fold partials correctly.
    records_asc = sorted(
        (r for r in fuel_records if r.engine_hours is not None),
        key=lambda r: (r.engine_hours, r.date, r.id),
    )
    figures = compute_full_tank_hours_economy(records_asc, exclude_hauling=False)

    data = []
    for record, l_per_hr, cost_per_hr in figures:
        data.append(
            {
                "date": pd.Timestamp(record.date),
                "engine_hours": record.engine_hours,
                "liters": record.liters if record.liters is not None else Decimal("0"),
                "cost": record.cost if record.cost is not None else Decimal("0"),
                "l_per_hr": l_per_hr,
                "cost_per_hr": cost_per_hr,
            }
        )

    if not data:
        return pd.DataFrame(), {}

    # Display in chronological order, matching calculate_fuel_economy_with_pandas.
    df = pd.DataFrame(data).sort_values("date").reset_index(drop=True)

    l_values = [v for v in df["l_per_hr"] if v is not None]
    l_series = df["l_per_hr"].dropna()

    stats: dict[str, Any] = {
        "best_l_per_hr": min(l_values) if l_values else None,
        "worst_l_per_hr": max(l_values) if l_values else None,
        "recent_l_per_hr": df["l_per_hr"].iloc[-1],
        "recent_cost_per_hr": df["cost_per_hr"].iloc[-1],
        "trend": _l_per_hr_trend(l_series.tail(10)) if l_values else "stable",
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
    # Bottle refills only: one rule, shared with the dashboard's propane rate.
    propane_records = [r for r in fuel_records if is_bottle_refill(r)]

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
        # A $0 refill still put propane in the bottle; only a missing cost stays out.
        if record.date and record.cost is not None and record.propane_liters:
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
        # Free refills average 0.00; it's only unknown with no litres to divide by.
        "avg_price_per_liter": Decimal(str(round(avg_price, 2))) if total_liters > 0 else None,
        "record_count": len(propane_records),
        "monthly_trend": monthly_trend,
        "tank_breakdown": tank_breakdown,
        "tank_timeline": tank_timeline,
        "refill_frequency": refill_frequency,
    }
