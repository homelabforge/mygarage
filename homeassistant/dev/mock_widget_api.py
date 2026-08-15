#!/usr/bin/env python3
"""Minimal MyGarage widget API stub for Home Assistant screenshot capture."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "0.0.0.0"
PORT = 8686

VEHICLES = {
    "1HGCM82633A004352": {
        "label": "Daily Driver",
        "year": 2022,
        "make": "Honda",
        "model": "Civic",
        "odometer": 28450,
        "odometer_km": 45790,
        "odometer_date": "2026-08-10",
        "recent_l_per_100km": 7.2,
        "average_l_per_100km": 7.5,
        "recent_km_per_l": 13.9,
        "average_km_per_l": 13.3,
        "recent_mpg": 32.7,
        "average_mpg": 31.4,
        "latest_hours": None,
        "average_l_per_hr": None,
        "average_cost_per_hr": None,
        "upcoming_maintenance": 2,
        "overdue_maintenance": 1,
        "service_records": 12,
        "fuel_records": 48,
        "last_service_date": "2026-06-15",
        "last_fuel_date": "2026-08-10",
        "documents": 4,
        "notes": 3,
        "photos": 6,
    },
    "5YJ3E1EA1KF000001": {
        "label": "EV Commuter",
        "year": 2019,
        "make": "Tesla",
        "model": "Model 3",
        "odometer": 41200,
        "odometer_km": 66300,
        "odometer_date": "2026-08-12",
        "recent_l_per_100km": None,
        "average_l_per_100km": None,
        "recent_km_per_l": None,
        "average_km_per_l": None,
        "recent_mpg": None,
        "average_mpg": None,
        "latest_hours": None,
        "average_l_per_hr": None,
        "average_cost_per_hr": None,
        "upcoming_maintenance": 1,
        "overdue_maintenance": 0,
        "service_records": 5,
        "fuel_records": 0,
        "last_service_date": "2026-03-01",
        "last_fuel_date": None,
        "documents": 2,
        "notes": 1,
        "photos": 2,
    },
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[mock] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, {"status": "ok", "version": "3.0.0-mock"})
            return
        if path == "/api/v2/widget/summary":
            overdue = sum(v["overdue_maintenance"] for v in VEHICLES.values())
            upcoming = sum(v["upcoming_maintenance"] for v in VEHICLES.values())
            self._send(
                200,
                {
                    "total_vehicles": len(VEHICLES),
                    "active_vehicles": len(VEHICLES),
                    "archived_vehicles": 0,
                    "total_overdue_maintenance": overdue,
                    "total_upcoming_maintenance": upcoming,
                    "total_service_records": sum(
                        v["service_records"] for v in VEHICLES.values()
                    ),
                    "total_fuel_records": sum(
                        v["fuel_records"] for v in VEHICLES.values()
                    ),
                    "total_documents": sum(v["documents"] for v in VEHICLES.values()),
                    "total_notes": sum(v["notes"] for v in VEHICLES.values()),
                    "total_photos": sum(v["photos"] for v in VEHICLES.values()),
                },
            )
            return
        if path == "/api/v2/widget/vehicles":
            self._send(
                200,
                {
                    "vehicles": [
                        {"vin": vin, "label": data["label"]}
                        for vin, data in VEHICLES.items()
                    ]
                },
            )
            return
        if path.startswith("/api/v2/widget/vehicle/"):
            vin = path.rsplit("/", 1)[-1]
            data = VEHICLES.get(vin)
            if not data:
                self._send(404, {"detail": "Not found"})
                return
            self._send(200, data)
            return
        self._send(404, {"detail": "Not found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MyGarage widget mock listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
