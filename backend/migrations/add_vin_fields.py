"""
Migration: Add VIN decoded fields to vehicles table

Adds fields from NHTSA VIN decode:
- trim, body_class, drive_type, doors, gvwr_class, displacement_l,
- cylinders, fuel_type, transmission_type, transmission_speeds
"""

import os
import sqlite3


def migrate():
    db_path = os.environ.get("DATABASE_PATH", "/data/mygarage.db")

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if columns already exist
    cursor.execute("PRAGMA table_info(vehicles)")
    existing_columns = [row[1] for row in cursor.fetchall()]

    columns_to_add = [
        ("trim", "VARCHAR(50)"),
        ("body_class", "VARCHAR(50)"),
        ("drive_type", "VARCHAR(30)"),
        ("doors", "INTEGER"),
        ("gvwr_class", "VARCHAR(50)"),
        ("displacement_l", "VARCHAR(20)"),
        ("cylinders", "INTEGER"),
        ("fuel_type", "VARCHAR(50)"),
        ("transmission_type", "VARCHAR(50)"),
        ("transmission_speeds", "VARCHAR(20)"),
    ]

    added_count = 0
    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            try:
                sql = f"ALTER TABLE vehicles ADD COLUMN {col_name} {col_type}"
                print(f"Adding column: {col_name}")
                cursor.execute(sql)
                added_count += 1
            except sqlite3.OperationalError as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists, skipping")

    conn.commit()
    conn.close()

    print(f"\nMigration complete! Added {added_count} new columns.")


if __name__ == "__main__":
    migrate()
