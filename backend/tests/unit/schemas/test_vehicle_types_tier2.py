"""New Tier-2 vehicle types are accepted by VehicleCreate."""

from app.schemas.vehicle import VehicleCreate

VIN = "1HGBH41JXMN109186"


def test_new_vehicle_types_accepted():
    for vehicle_type in ("Boat", "UTV", "Snowmobile", "Bicycle", "EBike"):
        v = VehicleCreate(
            vin=VIN,
            nickname=f"Test {vehicle_type}",
            vehicle_type=vehicle_type,
        )
        assert v.vehicle_type == vehicle_type
