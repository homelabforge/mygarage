"""Add Family Multi-User System tables and columns.

This migration adds support for:
- User relationships (spouse, child, parent, sibling, etc.)
- Vehicle ownership transfers with full audit trail
- Vehicle sharing with read/write permissions
- Family dashboard configuration

Schema changes:
- users table: Add relationship, relationship_custom, show_on_family_dashboard, family_dashboard_order
- vehicle_transfers table: Audit trail for ownership transfers
- vehicle_shares table: Junction table for sharing permissions
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add family multi-user system schema."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding Family Multi-User System schema...")

        # =========================================================================
        # 1. Add columns to users table
        # =========================================================================
        result = conn.execute(text("PRAGMA table_info(users)"))
        existing_columns = {row[1] for row in result.fetchall()}

        # Add relationship column
        if "relationship" in existing_columns:
            print("  → relationship column already exists, skipping")
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN relationship VARCHAR(50)"))
            print("  Added relationship column to users")

        # Add relationship_custom column
        if "relationship_custom" in existing_columns:
            print("  → relationship_custom column already exists, skipping")
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN relationship_custom VARCHAR(100)"))
            print("  Added relationship_custom column to users")

        # Add show_on_family_dashboard column
        if "show_on_family_dashboard" in existing_columns:
            print("  → show_on_family_dashboard column already exists, skipping")
        else:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN show_on_family_dashboard INTEGER DEFAULT 0")
            )
            print("  Added show_on_family_dashboard column to users")

        # Add family_dashboard_order column
        if "family_dashboard_order" in existing_columns:
            print("  → family_dashboard_order column already exists, skipping")
        else:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN family_dashboard_order INTEGER DEFAULT 0")
            )
            print("  Added family_dashboard_order column to users")

        # =========================================================================
        # 2. Create vehicle_transfers audit table
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_transfers'")
        )
        if result.fetchone():
            print("  → vehicle_transfers table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE vehicle_transfers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vehicle_vin VARCHAR(17) NOT NULL,
                        from_user_id INTEGER NOT NULL,
                        to_user_id INTEGER NOT NULL,
                        transferred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        transferred_by INTEGER NOT NULL,
                        transfer_notes TEXT,
                        data_included TEXT,
                        FOREIGN KEY (vehicle_vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
                        FOREIGN KEY (from_user_id) REFERENCES users(id),
                        FOREIGN KEY (to_user_id) REFERENCES users(id),
                        FOREIGN KEY (transferred_by) REFERENCES users(id)
                    )
                """)
            )
            conn.execute(
                text("CREATE INDEX idx_vehicle_transfers_vin ON vehicle_transfers(vehicle_vin)")
            )
            conn.execute(
                text("CREATE INDEX idx_vehicle_transfers_from ON vehicle_transfers(from_user_id)")
            )
            conn.execute(
                text("CREATE INDEX idx_vehicle_transfers_to ON vehicle_transfers(to_user_id)")
            )
            conn.execute(
                text("CREATE INDEX idx_vehicle_transfers_date ON vehicle_transfers(transferred_at)")
            )
            print("  Created vehicle_transfers table with indexes")

        # =========================================================================
        # 3. Create vehicle_shares junction table
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_shares'")
        )
        if result.fetchone():
            print("  → vehicle_shares table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE vehicle_shares (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vehicle_vin VARCHAR(17) NOT NULL,
                        user_id INTEGER NOT NULL,
                        permission VARCHAR(10) NOT NULL DEFAULT 'read',
                        shared_by INTEGER NOT NULL,
                        shared_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (vehicle_vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (shared_by) REFERENCES users(id),
                        UNIQUE(vehicle_vin, user_id)
                    )
                """)
            )
            conn.execute(text("CREATE INDEX idx_vehicle_shares_vin ON vehicle_shares(vehicle_vin)"))
            conn.execute(text("CREATE INDEX idx_vehicle_shares_user ON vehicle_shares(user_id)"))
            conn.execute(
                text("CREATE INDEX idx_vehicle_shares_shared_by ON vehicle_shares(shared_by)")
            )
            print("  Created vehicle_shares table with indexes")

        print("\nMigration 037 complete - Family Multi-User System schema added")
        print("\nNew capabilities:")
        print("  • Users can have relationship types (spouse, child, parent, etc.)")
        print("  • Admins can transfer vehicle ownership between users")
        print("  • Vehicles can be shared with read or write permissions")
        print("  • Family dashboard can display selected family members")


def downgrade():
    """Downgrade not fully supported for SQLite.

    SQLite does not support DROP COLUMN directly. The new tables could be dropped,
    but the user columns would remain.
    """
    print("  Downgrade not supported for this migration")
    print("  The vehicle_transfers and vehicle_shares tables can be manually dropped")
    print("  User columns (relationship, etc.) would require table recreation to remove")


if __name__ == "__main__":
    upgrade()
