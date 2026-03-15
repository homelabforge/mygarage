"""Seasonal patterns, anomaly detection, and vendor analysis."""

import pandas as pd


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
