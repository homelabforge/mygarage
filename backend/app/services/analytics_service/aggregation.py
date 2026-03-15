"""Monthly aggregation and rolling average calculations."""

import calendar
from decimal import Decimal

import pandas as pd


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
