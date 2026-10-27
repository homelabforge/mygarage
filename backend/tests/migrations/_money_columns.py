"""Shared by the migration 122 tests: the money columns as they were before it.

The registry in tests/unit/schemas/_money_names.py knows every money column's
new type. It can't know the old ones, so they're pinned here, as the models
declared them before migration 122. The two insurance limits aren't listed: they
were Numeric(12,2) from the start (migration 108).
"""

from sqlalchemy import Engine, text

#: table.column -> (precision, scale) before migration 122.
PRE_122_TYPES: dict[str, tuple[int, int]] = {
    "def_records.cost": (8, 2),
    "def_records.price_per_unit": (6, 3),
    "financing_records.amount": (10, 2),
    "fuel_records.cost": (8, 2),
    "fuel_records.price_per_unit": (6, 3),
    "fuel_records.rebate": (8, 2),
    "insurance_coverages.deductible": (10, 2),
    "insurance_coverages.premium": (10, 2),
    "insurance_policies.premium_amount": (10, 2),
    "insurance_policy_vehicles.deductible": (10, 2),
    "insurance_policy_vehicles.premium_share": (10, 2),
    "service_line_items.cost": (10, 2),
    "service_visits.misc_fees": (10, 2),
    "service_visits.shop_supplies": (10, 2),
    "service_visits.tax_amount": (10, 2),
    "service_visits.total_cost": (10, 2),
    "spot_rental_billings.electric": (8, 2),
    "spot_rental_billings.monthly_rate": (8, 2),
    "spot_rental_billings.total": (10, 2),
    "spot_rental_billings.waste": (8, 2),
    "spot_rental_billings.water": (8, 2),
    "spot_rentals.electric": (8, 2),
    "spot_rentals.monthly_rate": (8, 2),
    "spot_rentals.nightly_rate": (8, 2),
    "spot_rentals.total_cost": (10, 2),
    "spot_rentals.waste": (8, 2),
    "spot_rentals.water": (8, 2),
    "spot_rentals.weekly_rate": (8, 2),
    "supply_purchases.total_cost": (10, 2),
    "supply_usages.cost_snapshot": (10, 2),
    "supply_usages.unit_cost_snapshot": (10, 4),
    "tax_records.amount": (10, 2),
    "toll_transactions.amount": (8, 2),
    "vehicles.archive_sale_price": (10, 2),
    "vehicles.destination_charge": (10, 2),
    "vehicles.msrp_base": (10, 2),
    "vehicles.msrp_options": (10, 2),
    "vehicles.msrp_total": (10, 2),
    "vehicles.purchase_price": (10, 2),
    "vehicles.sold_price": (10, 2),
}

#: table.column -> the type migration 122 widens it to, as 122 itself has it.
#: A literal, not the registry: batch 7 has since widened the unit prices to
#: (13,4) (migration 135), and a later widening mustn't move 122's targets.
TYPES_AT_122: dict[str, tuple[int, int]] = {
    "def_records.cost": (12, 2),
    "def_records.price_per_unit": (12, 3),
    "financing_records.amount": (12, 2),
    "fuel_records.cost": (12, 2),
    "fuel_records.price_per_unit": (12, 3),
    "fuel_records.rebate": (12, 2),
    "insurance_coverages.deductible": (12, 2),
    "insurance_coverages.limit_primary": (12, 2),
    "insurance_coverages.limit_secondary": (12, 2),
    "insurance_coverages.premium": (12, 2),
    "insurance_policies.premium_amount": (12, 2),
    "insurance_policy_vehicles.deductible": (12, 2),
    "insurance_policy_vehicles.premium_share": (12, 2),
    "service_line_items.cost": (12, 2),
    "service_visits.misc_fees": (12, 2),
    "service_visits.shop_supplies": (12, 2),
    "service_visits.tax_amount": (12, 2),
    "service_visits.total_cost": (12, 2),
    "spot_rental_billings.electric": (12, 2),
    "spot_rental_billings.monthly_rate": (12, 2),
    "spot_rental_billings.total": (12, 2),
    "spot_rental_billings.waste": (12, 2),
    "spot_rental_billings.water": (12, 2),
    "spot_rentals.electric": (12, 2),
    "spot_rentals.monthly_rate": (12, 2),
    "spot_rentals.nightly_rate": (12, 2),
    "spot_rentals.total_cost": (12, 2),
    "spot_rentals.waste": (12, 2),
    "spot_rentals.water": (12, 2),
    "spot_rentals.weekly_rate": (12, 2),
    "supply_purchases.total_cost": (12, 2),
    "supply_usages.cost_snapshot": (12, 2),
    "supply_usages.unit_cost_snapshot": (15, 4),
    "tax_records.amount": (12, 2),
    "toll_transactions.amount": (12, 2),
    "vehicles.archive_sale_price": (12, 2),
    "vehicles.destination_charge": (12, 2),
    "vehicles.msrp_base": (12, 2),
    "vehicles.msrp_options": (12, 2),
    "vehicles.msrp_total": (12, 2),
    "vehicles.purchase_price": (12, 2),
    "vehicles.sold_price": (12, 2),
}


def pg_numeric_types(engine: Engine) -> dict[str, tuple[str, int | None, int | None]]:
    """table.column -> (data type, precision, scale) for every public column.

    Straight from information_schema, not SQLAlchemy reflection, so the check
    doesn't share a reflection quirk with the migration it's checking.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
        ).all()
    return {f"{row[0]}.{row[1]}": (row[2], row[3], row[4]) for row in rows}
