"""Shared by the migration 135 tests: the 14 columns batch 7 widened (R7).

Pinned here as 135 has them, not read from the models, so a later widening
can't move 135's targets.
"""

#: table.column -> (precision, scale) before batch 7, as the models declared them.
PRE_135_TYPES: dict[str, tuple[int, int]] = {
    "def_records.price_per_unit": (12, 3),
    "fuel_records.obc_l_per_100km": (5, 2),
    "fuel_records.outside_temp_c": (4, 1),
    "fuel_records.price_per_unit": (12, 3),
    "fuel_records.tank_size_kg": (6, 2),
    "supply_purchases.quantity": (12, 3),
    "supply_usages.quantity": (12, 3),
    "trailer_details.gvwr_kg": (7, 2),
    "trailer_details.height_m": (5, 2),
    "trailer_details.length_m": (5, 2),
    "trailer_details.width_m": (5, 2),
    "vehicles.fuel_economy_city_l_per_100km": (5, 2),
    "vehicles.fuel_economy_combined_l_per_100km": (5, 2),
    "vehicles.fuel_economy_highway_l_per_100km": (5, 2),
}

#: table.column -> the type 135 widens it to (R7).
R7_TYPES: dict[str, tuple[int, int]] = {
    "def_records.price_per_unit": (13, 4),
    "fuel_records.obc_l_per_100km": (7, 4),
    "fuel_records.outside_temp_c": (5, 2),
    "fuel_records.price_per_unit": (13, 4),
    "fuel_records.tank_size_kg": (7, 3),
    "supply_purchases.quantity": (25, 13),
    "supply_usages.quantity": (25, 13),
    "trailer_details.gvwr_kg": (8, 3),
    "trailer_details.height_m": (6, 3),
    "trailer_details.length_m": (6, 3),
    "trailer_details.width_m": (6, 3),
    "vehicles.fuel_economy_city_l_per_100km": (7, 4),
    "vehicles.fuel_economy_combined_l_per_100km": (7, 4),
    "vehicles.fuel_economy_highway_l_per_100km": (7, 4),
}
