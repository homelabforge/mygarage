"""Which fields and columns hold money.

Two answers that check each other. `is_money_name` goes by name, so a new money
field is covered the day it lands without anyone registering it. `MONEY_COLUMNS`
is the registry: every stored amount and the column type the policy gives it.
The registry is the authority, and the column scan in
tests/unit/models/test_money_columns.py fails when the two disagree.

A name is money when one of its words is a money word, or it is one of the few
money names with no money word in them (a spot rental's `electric`). A unit word
anywhere wins over a money word: `mileage_limit_km` is a distance, and
`cost_per_km` is a rate per distance, not a stored amount.
"""

#: A word that makes a name money (`tax_amount`, `premium_share`, `msrp_base`).
#: The frontend's moneyBounds.test.ts reads these three lists from this file and
#: fails if its copies differ. No `balance`: the only one is a supply's running
#: quantity. Add it the day a money balance exists.
MONEY_WORDS = frozenset(
    {
        "amount",
        "charge",
        "cost",
        "deductible",
        "fee",
        "fees",
        "limit",
        "msrp",
        "payment",
        "premium",
        "price",
        "rate",
        "rebate",
        "share",
        "spent",
        "subtotal",
        "tax",
        "taxes",
        "total",
    }
)

#: Money names with no money word in them.
MONEY_NAMES = frozenset({"electric", "shop_supplies", "waste", "water"})

#: A word that makes a name a measurement, whatever else it holds.
UNIT_WORDS = frozenset(
    {
        "100km",
        "c",
        "hours",
        "hr",
        "kg",
        "km",
        "kmh",
        "kpa",
        "kwh",
        "l",
        "liter",
        "liters",
        "m",
        "mb",
        "meters",
        "mm",
        "mpg",
        "nm",
        "pct",
        "percent",
        "seconds",
    }
)


def is_money_name(name: str) -> bool:
    """True when a field or column called `name` holds an amount of money."""
    words = set(name.lower().split("_"))
    if words & UNIT_WORDS:
        return False
    return name in MONEY_NAMES or bool(words & MONEY_WORDS)


#: Column types as (precision, scale). Each holds exactly its max in
#: app.schemas._money: MONEY_MAX, UNIT_PRICE_MAX and UNIT_COST_MAX.
MONEY_TYPE = (12, 2)
UNIT_PRICE_TYPE = (13, 4)
UNIT_COST_TYPE = (15, 4)

#: Every stored amount of money, as table.column, with its column type.
MONEY_COLUMNS: dict[str, tuple[int, int]] = {
    "def_records.cost": MONEY_TYPE,
    "def_records.price_per_unit": UNIT_PRICE_TYPE,
    "financing_records.amount": MONEY_TYPE,
    "fuel_records.cost": MONEY_TYPE,
    "fuel_records.price_per_unit": UNIT_PRICE_TYPE,
    "fuel_records.rebate": MONEY_TYPE,
    "insurance_coverages.deductible": MONEY_TYPE,
    "insurance_coverages.limit_primary": MONEY_TYPE,
    "insurance_coverages.limit_secondary": MONEY_TYPE,
    "insurance_coverages.premium": MONEY_TYPE,
    "insurance_policies.premium_amount": MONEY_TYPE,
    "insurance_policy_vehicles.deductible": MONEY_TYPE,
    "insurance_policy_vehicles.premium_share": MONEY_TYPE,
    "service_line_items.cost": MONEY_TYPE,
    "service_visits.misc_fees": MONEY_TYPE,
    "service_visits.shop_supplies": MONEY_TYPE,
    "service_visits.tax_amount": MONEY_TYPE,
    "service_visits.total_cost": MONEY_TYPE,
    "spot_rental_billings.electric": MONEY_TYPE,
    "spot_rental_billings.monthly_rate": MONEY_TYPE,
    "spot_rental_billings.total": MONEY_TYPE,
    "spot_rental_billings.waste": MONEY_TYPE,
    "spot_rental_billings.water": MONEY_TYPE,
    "spot_rentals.electric": MONEY_TYPE,
    "spot_rentals.monthly_rate": MONEY_TYPE,
    "spot_rentals.nightly_rate": MONEY_TYPE,
    "spot_rentals.total_cost": MONEY_TYPE,
    "spot_rentals.waste": MONEY_TYPE,
    "spot_rentals.water": MONEY_TYPE,
    "spot_rentals.weekly_rate": MONEY_TYPE,
    "supply_purchases.total_cost": MONEY_TYPE,
    "supply_usages.cost_snapshot": MONEY_TYPE,
    "supply_usages.unit_cost_snapshot": UNIT_COST_TYPE,
    "tax_records.amount": MONEY_TYPE,
    "toll_transactions.amount": MONEY_TYPE,
    "vehicles.archive_sale_price": MONEY_TYPE,
    "vehicles.destination_charge": MONEY_TYPE,
    "vehicles.msrp_base": MONEY_TYPE,
    "vehicles.msrp_options": MONEY_TYPE,
    "vehicles.msrp_total": MONEY_TYPE,
    "vehicles.purchase_price": MONEY_TYPE,
    "vehicles.sold_price": MONEY_TYPE,
}

#: The registry's bare column names, for checks that see fields, not columns.
MONEY_COLUMN_NAMES = frozenset(qualified.split(".", 1)[1] for qualified in MONEY_COLUMNS)
