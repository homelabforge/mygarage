"""Analytics service with pandas-based data processing."""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import date as date_type, datetime, timedelta
from decimal import Decimal
from collections import defaultdict
import calendar

from app.models import ServiceRecord, FuelRecord


def records_to_dataframe(
    service_records: List[ServiceRecord],
    fuel_records: List[FuelRecord],
) -> pd.DataFrame:
    """
    Convert SQLAlchemy records to a unified pandas DataFrame.

    Args:
        service_records: List of ServiceRecord objects
        fuel_records: List of FuelRecord objects

    Returns:
        DataFrame with columns: date, cost, type, vendor, mileage, service_type, etc.
    """
    # Convert service records
    service_data = []
    for record in service_records:
        if record.date and record.cost:
            service_data.append({
                'date': pd.Timestamp(record.date),
                'cost': float(record.cost),
                'type': 'service',
                'vendor': record.vendor_name or 'Unknown',
                'mileage': record.mileage,
                'service_type': record.service_type or 'Other',
                'description': record.description,
            })

    # Convert fuel records
    fuel_data = []
    for record in fuel_records:
        if record.date and record.cost:
            fuel_data.append({
                'date': pd.Timestamp(record.date),
                'cost': float(record.cost),
                'type': 'fuel',
                'vendor': 'Fuel Station',  # FuelRecord doesn't have a station/vendor field
                'mileage': record.mileage,
                'service_type': 'Fuel',
                'gallons': float(record.gallons) if record.gallons else None,
            })

    # Combine and create DataFrame
    all_data = service_data + fuel_data

    if not all_data:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(columns=[
            'date', 'cost', 'type', 'vendor', 'mileage',
            'service_type', 'description', 'gallons'
        ])

    df = pd.DataFrame(all_data)
    df = df.sort_values('date').reset_index(drop=True)

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
        return pd.DataFrame(columns=[
            'year', 'month', 'service_cost', 'fuel_cost',
            'service_count', 'fuel_count', 'total_cost'
        ])

    # Add year and month columns
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    # Separate service and fuel
    service_df = df[df['type'] == 'service'].copy()
    fuel_df = df[df['type'] == 'fuel'].copy()

    # Aggregate service by month
    service_monthly = service_df.groupby(['year', 'month']).agg({
        'cost': ['sum', 'count']
    }).reset_index()
    service_monthly.columns = ['year', 'month', 'service_cost', 'service_count']

    # Aggregate fuel by month
    fuel_monthly = fuel_df.groupby(['year', 'month']).agg({
        'cost': ['sum', 'count']
    }).reset_index()
    fuel_monthly.columns = ['year', 'month', 'fuel_cost', 'fuel_count']

    # Merge service and fuel
    monthly = pd.merge(
        service_monthly,
        fuel_monthly,
        on=['year', 'month'],
        how='outer'
    ).fillna(0)

    # Calculate totals
    monthly['total_cost'] = monthly['service_cost'] + monthly['fuel_cost']
    monthly['month_name'] = monthly['month'].apply(lambda x: calendar.month_name[int(x)])

    # Convert to integers where appropriate
    monthly['service_count'] = monthly['service_count'].astype(int)
    monthly['fuel_count'] = monthly['fuel_count'].astype(int)

    return monthly.sort_values(['year', 'month'])


def calculate_rolling_averages(
    monthly_df: pd.DataFrame,
    windows: List[int] = [3, 6, 12]
) -> Dict[str, Optional[Decimal]]:
    """
    Calculate rolling averages for different time windows.

    Args:
        monthly_df: DataFrame with monthly cost data
        windows: List of window sizes in months (default: [3, 6, 12])

    Returns:
        Dictionary with rolling averages for each window
    """
    if monthly_df.empty or len(monthly_df) < 2:
        return {f'rolling_{w}m': None for w in windows}

    # Ensure sorted by date
    monthly_df = monthly_df.sort_values(['year', 'month']).copy()

    result = {}
    for window in windows:
        if len(monthly_df) >= window:
            rolling_avg = monthly_df['total_cost'].rolling(window=window).mean().iloc[-1]
            result[f'rolling_{window}m'] = Decimal(str(round(rolling_avg, 2)))
        else:
            result[f'rolling_{window}m'] = None

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


def calculate_fuel_economy_with_pandas(fuel_records: List[FuelRecord]) -> Tuple[pd.DataFrame, Dict]:
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
            data.append({
                'date': pd.Timestamp(record.date),
                'mileage': record.mileage,
                'gallons': float(record.gallons),
                'cost': float(record.cost) if record.cost else 0.0,
            })

    if not data:
        return pd.DataFrame(), {}

    df = pd.DataFrame(data).sort_values('date').reset_index(drop=True)

    # Calculate MPG using diff
    df['miles_driven'] = df['mileage'].diff()
    df['mpg'] = df['miles_driven'] / df['gallons']

    # Remove first row (no previous record to compare)
    df = df[df['mpg'].notna()].copy()

    if df.empty:
        return pd.DataFrame(), {}

    # Calculate statistics
    stats = {
        'average_mpg': Decimal(str(round(df['mpg'].mean(), 2))),
        'best_mpg': Decimal(str(round(df['mpg'].max(), 2))),
        'worst_mpg': Decimal(str(round(df['mpg'].min(), 2))),
        'recent_mpg': Decimal(str(round(df['mpg'].tail(5).mean(), 2))),
        'trend': calculate_trend_direction(df['mpg'].tail(10)),
        'std_dev': Decimal(str(round(df['mpg'].std(), 2))),
    }

    return df, stats


def calculate_seasonal_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze spending patterns by season.

    Args:
        df: DataFrame with date and cost columns

    Returns:
        DataFrame with seasonal aggregations
    """
    if df.empty:
        return pd.DataFrame(columns=['season', 'total_cost', 'avg_cost', 'count'])

    # Define seasons based on month
    def get_season(month: int) -> str:
        if month in [12, 1, 2]:
            return 'Winter'
        elif month in [3, 4, 5]:
            return 'Spring'
        elif month in [6, 7, 8]:
            return 'Summer'
        else:  # 9, 10, 11
            return 'Fall'

    df['month'] = df['date'].dt.month
    df['season'] = df['month'].apply(get_season)

    # Aggregate by season
    seasonal = df.groupby('season').agg({
        'cost': ['sum', 'mean', 'count']
    }).reset_index()

    seasonal.columns = ['season', 'total_cost', 'avg_cost', 'count']

    # Order seasons chronologically
    season_order = ['Winter', 'Spring', 'Summer', 'Fall']
    seasonal['season'] = pd.Categorical(seasonal['season'], categories=season_order, ordered=True)
    seasonal = seasonal.sort_values('season')

    return seasonal


def calculate_vendor_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze costs and service patterns by vendor.

    Args:
        df: DataFrame with vendor and cost columns

    Returns:
        DataFrame with vendor aggregations
    """
    if df.empty or 'vendor' not in df.columns:
        return pd.DataFrame(columns=[
            'vendor', 'total_spent', 'service_count',
            'avg_cost', 'last_service_date'
        ])

    # Filter out fuel records for vendor analysis
    service_df = df[df['type'] == 'service'].copy()

    if service_df.empty:
        return pd.DataFrame(columns=[
            'vendor', 'total_spent', 'service_count',
            'avg_cost', 'last_service_date'
        ])

    # Aggregate by vendor
    vendor_stats = service_df.groupby('vendor').agg({
        'cost': ['sum', 'mean', 'count'],
        'date': 'max',
        'service_type': lambda x: list(x.unique())
    }).reset_index()

    vendor_stats.columns = [
        'vendor', 'total_spent', 'avg_cost',
        'service_count', 'last_service_date', 'service_types'
    ]

    # Sort by total spent (descending)
    vendor_stats = vendor_stats.sort_values('total_spent', ascending=False)

    return vendor_stats


def compare_time_periods(
    df: pd.DataFrame,
    period1_start: date_type,
    period1_end: date_type,
    period2_start: date_type,
    period2_end: date_type,
) -> Dict:
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
            'period1_cost': Decimal("0.00"),
            'period2_cost': Decimal("0.00"),
            'cost_change_pct': Decimal("0.00"),
            'period1_count': 0,
            'period2_count': 0,
        }

    # Filter by periods
    period1 = df[
        (df['date'] >= pd.Timestamp(period1_start)) &
        (df['date'] <= pd.Timestamp(period1_end))
    ]
    period2 = df[
        (df['date'] >= pd.Timestamp(period2_start)) &
        (df['date'] <= pd.Timestamp(period2_end))
    ]

    # Calculate metrics
    p1_cost = period1['cost'].sum() if not period1.empty else 0.0
    p2_cost = period2['cost'].sum() if not period2.empty else 0.0

    # Calculate percentage change
    if p1_cost > 0:
        change_pct = ((p2_cost - p1_cost) / p1_cost) * 100
    else:
        change_pct = 0.0

    return {
        'period1_cost': Decimal(str(round(p1_cost, 2))),
        'period2_cost': Decimal(str(round(p2_cost, 2))),
        'cost_change_pct': Decimal(str(round(change_pct, 2))),
        'period1_count': len(period1),
        'period2_count': len(period2),
        'period1_service_count': len(period1[period1['type'] == 'service']) if not period1.empty else 0,
        'period2_service_count': len(period2[period2['type'] == 'service']) if not period2.empty else 0,
    }


def detect_anomalies(values: pd.Series, std_threshold: float = 2.0) -> List[int]:
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
