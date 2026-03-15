"""Trend analysis and time period comparison functions."""

from datetime import date as date_type
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


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

    # Use simple linear regression — convert from Decimal/object dtype to float
    x = np.arange(len(values))
    y = np.array(values.tolist(), dtype=np.float64)

    # Calculate slope
    slope = np.polyfit(x, y, 1)[0]

    # Calculate percentage change
    mean_value = float(y.mean())
    if mean_value == 0:
        return "stable"

    trend_pct = (slope * len(values)) / mean_value

    if trend_pct > threshold:
        return "increasing"
    elif trend_pct < -threshold:
        return "decreasing"
    else:
        return "stable"


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
