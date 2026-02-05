#!/usr/bin/env python3
"""
LiveLink Mock Sender - CLI tool for simulating WiCAN device payloads.

Usage:
    python -m app.utils.livelink_mock_sender \\
        --url https://mygarage.local/api/v1/livelink/ingest \\
        --token YOUR_TOKEN \\
        --device-id AABBCCDDEEFF \\
        --duration 300 \\
        --interval 5

Scenarios:
    - warmup: Engine warm-up sequence
    - driving: Normal driving with varying speed/RPM
    - idle: Engine idling
    - shutdown: ECU goes offline
    - mixed: Realistic mixed scenario (default)

Nasty mode (--nasty):
    - Burst traffic (1-second intervals)
    - Random dropped posts
    - Duplicate posts
    - New parameters mid-session
    - Out-of-order timestamps
    - Multiple device IDs
"""

import argparse
import logging
import random
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class TelemetryGenerator:
    """Generates realistic telemetry values."""

    def __init__(self, scenario: str = "mixed"):
        self.scenario = scenario
        self.ecu_online = False
        self.engine_started_at: float | None = None
        self.current_speed = 0.0
        self.current_rpm = 0.0
        self.coolant_temp = 20.0  # Starts cold
        self.battery_voltage = 12.6
        self.throttle_pos = 0.0
        self.intake_temp = 25.0
        self.fuel_level = 75.0

    def start_engine(self) -> None:
        """Start the engine."""
        self.ecu_online = True
        self.engine_started_at = time.time()
        self.current_rpm = 800 + random.uniform(-50, 50)  # Idle RPM
        logger.info("Engine started")

    def stop_engine(self) -> None:
        """Stop the engine."""
        self.ecu_online = False
        self.engine_started_at = None
        self.current_rpm = 0
        self.current_speed = 0
        self.throttle_pos = 0
        logger.info("Engine stopped")

    def update_warmup(self) -> None:
        """Update values during warmup phase."""
        if not self.ecu_online:
            return

        # Gradually increase coolant temp
        if self.coolant_temp < 90:
            self.coolant_temp += random.uniform(0.5, 1.5)
        else:
            self.coolant_temp = 90 + random.uniform(-2, 2)

        # Idle RPM (slightly higher when cold)
        if self.coolant_temp < 60:
            self.current_rpm = 900 + random.uniform(-50, 100)
        else:
            self.current_rpm = 750 + random.uniform(-50, 50)

        self.current_speed = 0
        self.throttle_pos = random.uniform(0, 5)

    def update_driving(self) -> None:
        """Update values during driving phase."""
        if not self.ecu_online:
            return

        # Vary speed randomly
        speed_change = random.uniform(-5, 8)
        self.current_speed = max(0, min(85, self.current_speed + speed_change))

        # RPM correlates with speed (simplified)
        if self.current_speed > 0:
            # Simulate gear changes
            gear = min(6, int(self.current_speed / 15) + 1)
            base_rpm = (self.current_speed / gear) * 100 + 800
            self.current_rpm = base_rpm + random.uniform(-100, 100)
        else:
            self.current_rpm = 750 + random.uniform(-50, 50)

        # Throttle based on speed change
        if speed_change > 3:
            self.throttle_pos = 30 + random.uniform(0, 40)
        elif speed_change < -3:
            self.throttle_pos = random.uniform(0, 5)
        else:
            self.throttle_pos = 10 + random.uniform(0, 20)

        # Maintain operating temp
        self.coolant_temp = 88 + random.uniform(-3, 5)

        # Fuel consumption
        if self.fuel_level > 10:
            self.fuel_level -= random.uniform(0.01, 0.05)

    def update_idle(self) -> None:
        """Update values during idle phase."""
        if not self.ecu_online:
            return

        self.current_speed = 0
        self.current_rpm = 750 + random.uniform(-50, 50)
        self.throttle_pos = random.uniform(0, 3)
        self.coolant_temp = 90 + random.uniform(-3, 3)

    def update_mixed(self, elapsed: float, duration: float) -> None:
        """Run a realistic mixed scenario."""
        progress = elapsed / duration

        if progress < 0.05:
            # Just started - warmup
            if not self.ecu_online:
                self.start_engine()
            self.update_warmup()
        elif progress < 0.15:
            # Continue warmup
            self.update_warmup()
        elif progress < 0.85:
            # Driving with occasional stops
            if random.random() < 0.1:
                self.update_idle()  # Stop at light
            else:
                self.update_driving()
        elif progress < 0.95:
            # Arriving - slowing down
            self.current_speed = max(0, self.current_speed - random.uniform(2, 8))
            self.current_rpm = 750 + random.uniform(-50, 100)
        else:
            # Shutdown
            if self.ecu_online:
                self.stop_engine()

    def get_values(self) -> list[dict[str, Any]]:
        """Get current telemetry values as WiCAN config entries."""
        values = []

        if self.ecu_online:
            values.extend(
                [
                    {
                        "name": "SPEED",
                        "value": round(self.current_speed, 1),
                        "unit": "km/h",
                        "class": "Speed",
                    },
                    {
                        "name": "ENGINE_RPM",
                        "value": round(self.current_rpm, 0),
                        "unit": "RPM",
                        "class": "Engine",
                    },
                    {
                        "name": "COOLANT_TMP",
                        "value": round(self.coolant_temp, 1),
                        "unit": "°C",
                        "class": "Temperature",
                    },
                    {
                        "name": "THROTTLE_POS",
                        "value": round(self.throttle_pos, 1),
                        "unit": "%",
                        "class": "Engine",
                    },
                    {
                        "name": "INTAKE_TMP",
                        "value": round(self.intake_temp + random.uniform(-2, 2), 1),
                        "unit": "°C",
                        "class": "Temperature",
                    },
                    {
                        "name": "FUEL_LEVEL",
                        "value": round(self.fuel_level, 1),
                        "unit": "%",
                        "class": "Fuel",
                    },
                ]
            )

        # Battery voltage always available when device is on
        values.append(
            {
                "name": "BATTERY_VOLTAGE",
                "value": round(self.battery_voltage + random.uniform(-0.3, 0.3), 2),
                "unit": "V",
                "class": "Electrical",
            }
        )

        return values


def generate_device_id() -> str:
    """Generate a random device ID (MAC-like)."""
    return "".join(random.choices("0123456789ABCDEF", k=12))


def build_payload(
    device_id: str, generator: TelemetryGenerator, timestamp: datetime | None = None
) -> dict[str, Any]:
    """Build a WiCAN-compatible payload."""
    if timestamp is None:
        timestamp = datetime.now(UTC)

    values = generator.get_values()

    payload = {
        "device_id": device_id,
        "timestamp": timestamp.isoformat(),
        "status": {
            "hw_version": "V3.0",
            "fw_version": "3.68",
            "git_version": "abc1234",
            "ecu_status": "online" if generator.ecu_online else "offline",
            "sta_ip": "192.168.1.100",
            "rssi": -65 + random.randint(-10, 10),
        },
        "config": values,
    }

    return payload


def send_payload(url: str, token: str, payload: dict[str, Any], timeout: float = 10.0) -> bool:
    """Send a payload to the ingestion endpoint."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout, verify=False) as client:
            response = client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            logger.debug("Payload sent successfully")
            return True
        else:
            logger.warning("Failed to send payload: %s %s", response.status_code, response.text)
            return False
    except Exception as e:
        logger.error("Error sending payload: %s", e)
        return False


def run_simulation(
    url: str,
    token: str,
    device_id: str,
    duration: float,
    interval: float,
    scenario: str,
    nasty: bool = False,
) -> None:
    """Run the telemetry simulation."""
    logger.info("Starting simulation")
    logger.info("  URL: %s", url)
    logger.info("  Device ID: %s", device_id)
    logger.info("  Duration: %s seconds", duration)
    logger.info("  Interval: %s seconds", interval)
    logger.info("  Scenario: %s", scenario)
    logger.info("  Nasty mode: %s", nasty)

    generator = TelemetryGenerator(scenario)
    start_time = time.time()
    payloads_sent = 0
    payloads_failed = 0

    # Nasty mode extras
    extra_device_ids = [generate_device_id() for _ in range(3)] if nasty else []

    while True:
        elapsed = time.time() - start_time
        if elapsed >= duration:
            break

        # Update telemetry based on scenario
        if scenario == "warmup":
            if not generator.ecu_online:
                generator.start_engine()
            generator.update_warmup()
        elif scenario == "driving":
            if not generator.ecu_online:
                generator.start_engine()
                generator.coolant_temp = 90  # Already warm
            generator.update_driving()
        elif scenario == "idle":
            if not generator.ecu_online:
                generator.start_engine()
                generator.coolant_temp = 90
            generator.update_idle()
        elif scenario == "shutdown":
            if generator.ecu_online and elapsed > duration * 0.5:
                generator.stop_engine()
        else:  # mixed
            generator.update_mixed(elapsed, duration)

        # Build and send payload
        current_device_id = device_id

        # Nasty mode modifications
        if nasty:
            # Random device switching
            if random.random() < 0.1:
                current_device_id = random.choice(extra_device_ids)
                logger.debug("Switched to device %s", current_device_id)

            # Skip some payloads (simulate network issues)
            if random.random() < 0.1:
                logger.debug("Simulating dropped payload")
                time.sleep(interval if not nasty else random.uniform(0.5, 2))
                continue

        payload = build_payload(current_device_id, generator)

        # Nasty mode: duplicate payloads
        send_count = 1
        if nasty and random.random() < 0.15:
            send_count = random.randint(2, 3)
            logger.debug("Sending %d duplicate payloads", send_count)

        for _ in range(send_count):
            if send_payload(url, token, payload):
                payloads_sent += 1
            else:
                payloads_failed += 1

        # Nasty mode: inject new parameters mid-session
        if nasty and random.random() < 0.05:
            extra_param = {
                "name": f"CUSTOM_PID_{random.randint(1000, 9999)}",
                "value": random.uniform(0, 100),
                "unit": "units",
                "class": "Custom",
            }
            payload["config"].append(extra_param)
            logger.debug("Injected custom parameter: %s", extra_param["name"])

        # Calculate next interval
        sleep_time = interval
        if nasty:
            # Burst traffic
            sleep_time = random.uniform(0.5, interval * 0.5)

        # Progress update
        progress = (elapsed / duration) * 100
        logger.info(
            "Progress: %.1f%% | Speed: %.1f | RPM: %.0f | Coolant: %.1f | Sent: %d | Failed: %d",
            progress,
            generator.current_speed,
            generator.current_rpm,
            generator.coolant_temp,
            payloads_sent,
            payloads_failed,
        )

        time.sleep(sleep_time)

    # Ensure engine is off at the end
    if generator.ecu_online:
        generator.stop_engine()
        payload = build_payload(device_id, generator)
        send_payload(url, token, payload)
        payloads_sent += 1

    logger.info("Simulation complete")
    logger.info("  Payloads sent: %d", payloads_sent)
    logger.info("  Payloads failed: %d", payloads_failed)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LiveLink Mock Sender - Simulate WiCAN device telemetry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--url", required=True, help="Ingestion endpoint URL")
    parser.add_argument("--token", required=True, help="Bearer token for authentication")
    parser.add_argument("--device-id", default=None, help="Device ID (default: randomly generated)")
    parser.add_argument(
        "--duration", type=float, default=300, help="Duration in seconds (default: 300)"
    )
    parser.add_argument(
        "--interval", type=float, default=5, help="Seconds between posts (default: 5)"
    )
    parser.add_argument(
        "--scenario",
        choices=["warmup", "driving", "idle", "shutdown", "mixed"],
        default="mixed",
        help="Predefined scenario (default: mixed)",
    )
    parser.add_argument("--nasty", action="store_true", help="Enable chaos testing mode")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    device_id = args.device_id or generate_device_id()

    try:
        run_simulation(
            url=args.url,
            token=args.token,
            device_id=device_id,
            duration=args.duration,
            interval=args.interval,
            scenario=args.scenario,
            nasty=args.nasty,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
