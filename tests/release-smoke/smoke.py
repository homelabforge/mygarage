"""End-to-end smoke test for MyGarage.

Run against a freshly-installed MyGarage instance (PG-backed or SQLite-backed)
to verify the high-value paths that unit tests can't catch:

- All migrations apply on a fresh DB (implicit — if migrations fail,
  registration succeeds but later CRUD breaks because schema is incomplete;
  see #038/#048 in v2.26.3).
- Auth flow: register first admin → login → CSRF-protected request.
- Fuel record CRUD round-trip — the canonical-SI storage from #67 means
  price_per_unit must come back exactly as submitted, and PUT must not
  corrupt it (the bug fixed in v2.26.3).
- LIST endpoint returns canonical units for downstream display conversion.

Usage:
    python smoke.py http://app-pg:8686
    python smoke.py http://app-sqlite:8686
"""

from __future__ import annotations

import json
import sys
from datetime import date

import httpx


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def main(base: str) -> int:
    fails = 0
    with httpx.Client(base_url=base, timeout=20.0, follow_redirects=True) as c:
        banner("Register first admin user")
        r = c.post(
            "/api/auth/register",
            json={
                "username": "smoke",
                "email": "smoke@example.com",
                "full_name": "Smoke Test",
                "password": "SmokePass123!",
            },
        )
        print(f"  POST /register -> {r.status_code}")
        if r.status_code != 201:
            print("  body:", r.text[:200])
            return 1

        banner("Login")
        r = c.post(
            "/api/auth/login",
            json={
                "username": "smoke",
                "password": "SmokePass123!",
            },
        )
        print(f"  POST /login -> {r.status_code}")
        if r.status_code != 200:
            print("  body:", r.text[:200])
            return 1
        login = r.json()
        csrf = login["csrf_token"]
        c.headers["X-CSRF-Token"] = csrf
        print(f"  csrf token len: {len(csrf)}")

        banner("Create vehicle (Mitsubishi Mirage)")
        vin = "ML32A5HJ9KH009478"
        r = c.post(
            "/api/vehicles/",
            json={
                "vin": vin,
                "nickname": "Mirage",
                "vehicle_type": "Car",
                "year": 2019,
                "make": "MITSUBISHI",
                "model": "MIRAGE",
                "fuel_type": "Gasoline",
            },
        )
        print(f"  POST /vehicles -> {r.status_code}")
        if r.status_code not in (200, 201):
            print("  body:", r.text[:300])
            fails += 1
            return fails

        banner("Create fuel record (canonical SI)")
        # The screenshot record: 6.22 gal, $4.30/gal, $26.76 -> canonical: 23.54 L, $1.136/L
        post_payload = {
            "vin": vin,
            "date": date(2026, 4, 4).isoformat(),
            "odometer_km": 141897.5,  # 88,171 mi
            "liters": 23.547,
            "price_per_unit": 1.136,
            "price_basis": "per_volume",
            "cost": 26.76,
            "fuel_type": "Gasoline",
            "is_full_tank": True,
            "missed_fillup": False,
            "is_hauling": False,
        }
        r = c.post(f"/api/vehicles/{vin}/fuel", json=post_payload)
        print(f"  POST /fuel -> {r.status_code}")
        if r.status_code not in (200, 201):
            print("  body:", r.text[:400])
            fails += 1
            return fails
        created = r.json()
        record_id = created["id"]
        print(f"  Created record id={record_id}")

        banner("GET fuel record back")
        r = c.get(f"/api/vehicles/{vin}/fuel/{record_id}")
        print(f"  GET /fuel/{record_id} -> {r.status_code}")
        got = r.json()
        for k in ("liters", "price_per_unit", "price_basis", "cost", "odometer_km"):
            print(f"    {k}: {got.get(k)!r}")

        banner("Round-trip assertions")

        def approx(a, b, tol=0.001):
            return abs(float(a) - float(b)) < tol

        checks = [
            ("liters", got["liters"], 23.547),
            ("price_per_unit (canonical $/L)", got["price_per_unit"], 1.136),
            ("price_basis", got["price_basis"], "per_volume"),
            ("cost", got["cost"], 26.76),
            ("odometer_km", got["odometer_km"], 141897.5),
        ]
        for label, actual, expected in checks:
            if isinstance(expected, str):
                ok = actual == expected
            else:
                ok = approx(actual, expected)
            status = "✓" if ok else "✗"
            print(f"  {status} {label}: got {actual} expected {expected}")
            if not ok:
                fails += 1

        banner("Imperial display conversion sanity check (frontend math)")
        gal = float(got["liters"]) / 3.78541
        usd_per_gal = float(got["price_per_unit"]) * 3.78541
        derived_cost = gal * usd_per_gal
        print(f"  liters {got['liters']} L -> {gal:.3f} gal")
        print(f"  price {got['price_per_unit']} $/L -> ${usd_per_gal:.3f}/gal")
        print(
            f"  derived cost: gal * $/gal = ${derived_cost:.2f} (stored: ${got['cost']})"
        )
        if not approx(derived_cost, float(got["cost"]), tol=0.05):
            print("  ✗ Cost reconciliation off by more than $0.05")
            fails += 1
        else:
            print("  ✓ Cost reconciles within $0.05")

        banner("PUT update (simulate edit)")
        put_payload = dict(post_payload)
        put_payload["cost"] = 28.00
        r = c.put(f"/api/vehicles/{vin}/fuel/{record_id}", json=put_payload)
        print(f"  PUT /fuel/{record_id} -> {r.status_code}")
        if r.status_code != 200:
            print("  body:", r.text[:300])
            fails += 1
        updated = r.json()
        if not approx(updated["price_per_unit"], 1.136):
            print(f"  ✗ price_per_unit drifted on update: {updated['price_per_unit']}")
            fails += 1
        else:
            print(f"  ✓ price_per_unit preserved: {updated['price_per_unit']}")
        if not approx(updated["cost"], 28.00, tol=0.01):
            print(f"  ✗ cost not updated: {updated['cost']}")
            fails += 1
        else:
            print(f"  ✓ cost updated to: {updated['cost']}")

        banner("LIST endpoint sanity")
        r = c.get(f"/api/vehicles/{vin}/fuel")
        print(f"  GET /fuel -> {r.status_code}")
        listing = r.json()
        records = listing.get("records", [])
        print(f"  records returned: {len(records)}")
        if records:
            r0 = records[0]
            print(f"    record[0].price_per_unit: {r0.get('price_per_unit')}")
            print(f"    record[0].liters: {r0.get('liters')}")

    banner("RESULT")
    if fails:
        print(f"  ✗ {fails} check(s) failed")
        return 1
    print("  ✓ all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:18686"))
