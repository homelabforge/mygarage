"""Spot rental cost calculations."""

import calendar
from decimal import Decimal
from typing import Any

import pandas as pd


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
