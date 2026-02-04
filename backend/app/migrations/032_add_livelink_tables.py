"""Add LiveLink (WiCAN OBD2 Telemetry) tables.

This migration creates the core LiveLink infrastructure:
- livelink_devices: Discovered WiCAN devices with linking, status, tokens
- livelink_parameters: Auto-discovered PID metadata, thresholds, display settings
- drive_sessions: Detected engine on/off sessions with aggregates
- vehicle_telemetry: Historical time-series data
- vehicle_telemetry_latest: Live dashboard cache
- vehicle_dtcs: Active/historical DTCs per vehicle
- dtc_definitions: Bundled SAE J2012 codes (seeded separately in 033)
- telemetry_daily_summary: Rolled-up daily aggregates
- livelink_firmware_cache: Cached GitHub release info
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Create all LiveLink tables."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # =========================================================================
        # 1. drive_sessions (created first because livelink_devices references it)
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='drive_sessions'")
        )
        if result.fetchone():
            print("  drive_sessions table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE drive_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        device_id VARCHAR(20) NOT NULL,
                        started_at DATETIME NOT NULL,
                        ended_at DATETIME,
                        duration_seconds INTEGER,
                        start_odometer FLOAT,
                        end_odometer FLOAT,
                        distance_km FLOAT,
                        avg_speed FLOAT,
                        max_speed FLOAT,
                        avg_rpm FLOAT,
                        max_rpm FLOAT,
                        avg_coolant_temp FLOAT,
                        max_coolant_temp FLOAT,
                        avg_throttle FLOAT,
                        max_throttle FLOAT,
                        avg_fuel_level FLOAT,
                        fuel_used_estimate FLOAT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            conn.execute(
                text("CREATE INDEX idx_sessions_vehicle_time ON drive_sessions(vin, started_at)")
            )
            conn.execute(
                text("CREATE INDEX idx_sessions_device ON drive_sessions(device_id, started_at)")
            )
            conn.execute(text("CREATE INDEX idx_sessions_ended ON drive_sessions(ended_at)"))
            print("  Created drive_sessions table with indexes")

        # =========================================================================
        # 2. livelink_devices
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='livelink_devices'")
        )
        if result.fetchone():
            print("  livelink_devices table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE livelink_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id VARCHAR(20) NOT NULL UNIQUE,
                        vin VARCHAR(17) REFERENCES vehicles(vin) ON DELETE SET NULL,
                        label VARCHAR(100),
                        hw_version VARCHAR(50),
                        fw_version VARCHAR(20),
                        git_version VARCHAR(20),
                        sta_ip VARCHAR(45),
                        rssi INTEGER,
                        battery_voltage FLOAT,
                        ecu_status VARCHAR(20) DEFAULT 'unknown',
                        device_status VARCHAR(20) DEFAULT 'unknown',
                        device_token_hash VARCHAR(128),
                        last_payload_hash VARCHAR(64),
                        current_session_id INTEGER REFERENCES drive_sessions(id) ON DELETE SET NULL,
                        enabled BOOLEAN DEFAULT 1,
                        last_seen DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME
                    )
                """)
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX idx_livelink_devices_device_id ON livelink_devices(device_id)"
                )
            )
            conn.execute(text("CREATE INDEX idx_livelink_devices_vin ON livelink_devices(vin)"))
            conn.execute(
                text("CREATE INDEX idx_livelink_devices_status ON livelink_devices(device_status)")
            )
            conn.execute(
                text("CREATE INDEX idx_livelink_devices_last_seen ON livelink_devices(last_seen)")
            )
            print("  Created livelink_devices table with indexes")

        # =========================================================================
        # 3. livelink_parameters
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='livelink_parameters'")
        )
        if result.fetchone():
            print("  livelink_parameters table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE livelink_parameters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        param_key VARCHAR(100) NOT NULL UNIQUE,
                        display_name VARCHAR(100),
                        unit VARCHAR(20),
                        param_class VARCHAR(50),
                        category VARCHAR(50),
                        icon VARCHAR(50),
                        warning_min FLOAT,
                        warning_max FLOAT,
                        display_order INTEGER DEFAULT 0,
                        show_on_dashboard BOOLEAN DEFAULT 1,
                        archive_only BOOLEAN DEFAULT 0,
                        storage_interval_seconds INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME
                    )
                """)
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX idx_livelink_params_key ON livelink_parameters(param_key)"
                )
            )
            conn.execute(
                text("CREATE INDEX idx_livelink_params_category ON livelink_parameters(category)")
            )
            conn.execute(
                text("CREATE INDEX idx_livelink_params_class ON livelink_parameters(param_class)")
            )
            conn.execute(
                text("CREATE INDEX idx_livelink_params_order ON livelink_parameters(display_order)")
            )
            print("  Created livelink_parameters table with indexes")

        # =========================================================================
        # 4. vehicle_telemetry (historical time-series)
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_telemetry'")
        )
        if result.fetchone():
            print("  vehicle_telemetry table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE vehicle_telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        device_id VARCHAR(20) NOT NULL,
                        param_key VARCHAR(100) NOT NULL,
                        value FLOAT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            conn.execute(
                text("CREATE INDEX idx_telemetry_vehicle_time ON vehicle_telemetry(vin, timestamp)")
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_telemetry_param_time ON vehicle_telemetry(vin, param_key, timestamp)"
                )
            )
            conn.execute(
                text("CREATE INDEX idx_telemetry_device ON vehicle_telemetry(device_id, timestamp)")
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX idx_telemetry_dedup ON vehicle_telemetry(device_id, param_key, timestamp)"
                )
            )
            print("  Created vehicle_telemetry table with indexes")

        # =========================================================================
        # 5. vehicle_telemetry_latest (live dashboard cache)
        # =========================================================================
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_telemetry_latest'"
            )
        )
        if result.fetchone():
            print("  vehicle_telemetry_latest table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE vehicle_telemetry_latest (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        param_key VARCHAR(100) NOT NULL,
                        value FLOAT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(vin, param_key)
                    )
                """)
            )
            conn.execute(
                text("CREATE INDEX idx_telemetry_latest_vehicle ON vehicle_telemetry_latest(vin)")
            )
            print("  Created vehicle_telemetry_latest table with indexes")

        # =========================================================================
        # 6. dtc_definitions (SAE J2012 lookup, seeded in 033)
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='dtc_definitions'")
        )
        if result.fetchone():
            print("  dtc_definitions table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE dtc_definitions (
                        code VARCHAR(10) PRIMARY KEY,
                        description TEXT NOT NULL,
                        category VARCHAR(20) NOT NULL,
                        subcategory VARCHAR(50),
                        severity VARCHAR(20) DEFAULT 'warning',
                        estimated_severity_level INTEGER DEFAULT 2,
                        is_emissions_related BOOLEAN DEFAULT 0,
                        common_causes TEXT,
                        symptoms TEXT,
                        fix_guidance TEXT
                    )
                """)
            )
            conn.execute(text("CREATE INDEX idx_dtc_defs_category ON dtc_definitions(category)"))
            conn.execute(text("CREATE INDEX idx_dtc_defs_severity ON dtc_definitions(severity)"))
            print("  Created dtc_definitions table with indexes")

        # =========================================================================
        # 7. vehicle_dtcs (active/historical per vehicle)
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_dtcs'")
        )
        if result.fetchone():
            print("  vehicle_dtcs table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE vehicle_dtcs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        device_id VARCHAR(20) NOT NULL,
                        code VARCHAR(10) NOT NULL,
                        description TEXT,
                        severity VARCHAR(20) DEFAULT 'warning',
                        user_notes TEXT,
                        first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        cleared_at DATETIME,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            conn.execute(
                text("CREATE INDEX idx_dtcs_vehicle_active ON vehicle_dtcs(vin, is_active)")
            )
            conn.execute(text("CREATE INDEX idx_dtcs_vehicle_code ON vehicle_dtcs(vin, code)"))
            conn.execute(text("CREATE INDEX idx_dtcs_device ON vehicle_dtcs(device_id)"))
            conn.execute(text("CREATE INDEX idx_dtcs_first_seen ON vehicle_dtcs(first_seen)"))
            print("  Created vehicle_dtcs table with indexes")

        # =========================================================================
        # 8. telemetry_daily_summary (aggregates for long-term charts)
        # =========================================================================
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry_daily_summary'"
            )
        )
        if result.fetchone():
            print("  telemetry_daily_summary table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE telemetry_daily_summary (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        param_key VARCHAR(100) NOT NULL,
                        date DATETIME NOT NULL,
                        min_value FLOAT,
                        max_value FLOAT,
                        avg_value FLOAT,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(vin, param_key, date)
                    )
                """)
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_daily_summary_vehicle_date ON telemetry_daily_summary(vin, date)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_daily_summary_param ON telemetry_daily_summary(vin, param_key, date)"
                )
            )
            print("  Created telemetry_daily_summary table with indexes")

        # =========================================================================
        # 9. livelink_firmware_cache (GitHub release cache)
        # =========================================================================
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='livelink_firmware_cache'"
            )
        )
        if result.fetchone():
            print("  livelink_firmware_cache table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE livelink_firmware_cache (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        latest_version VARCHAR(20),
                        latest_tag VARCHAR(20),
                        release_url TEXT,
                        release_notes TEXT,
                        checked_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            # Insert initial singleton row
            conn.execute(
                text("""
                    INSERT INTO livelink_firmware_cache (id, latest_version, checked_at)
                    VALUES (1, NULL, CURRENT_TIMESTAMP)
                """)
            )
            print("  Created livelink_firmware_cache table with singleton row")

        print("  Migration 032 complete - all LiveLink tables created")


if __name__ == "__main__":
    upgrade()
