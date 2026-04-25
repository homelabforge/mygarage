"""DataFrame conversion utilities for analytics service."""

import pandas as pd

from app.models import DEFRecord, FuelRecord, ServiceVisit, SpotRentalBilling


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
        DataFrame with columns: date, cost, type, vendor, odometer_km, service_type, etc.
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
                "odometer_km": visit.odometer_km,
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
                    "odometer_km": record.odometer_km,
                    "service_type": "Fuel",
                    "liters": float(record.liters) if record.liters else None,
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
                        "odometer_km": record.odometer_km,
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
                        "odometer_km": None,
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
                "odometer_km",
                "service_type",
                "service_category",
                "description",
                "liters",
            ]
        )

    df = pd.DataFrame(all_data)
    df = df.sort_values("date").reset_index(drop=True)

    return df
