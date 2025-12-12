# MyGarage Database Migrations

This directory contains database migration scripts for MyGarage.

## Overview

MyGarage uses a custom migration system with automatic discovery and tracking. Migrations are Python scripts that execute database schema changes in a controlled, versioned manner.

## Running Migrations

### Automatic Execution

Migrations run **automatically** on application startup via the `init_db()` function in `database.py`. When you start MyGarage, pending migrations are detected and executed automatically.

### Manual Execution

To run migrations manually:

```bash
cd /srv/raid0/docker/build/mygarage/backend
python -m app.migrations.runner
```

Or run a specific migration:

```bash
cd /srv/raid0/docker/build/mygarage/backend
python app/migrations/016_add_unit_preference.py
```

## Migration Naming Convention

Format: `NNN_descriptive_name.py`
- `NNN`: Three-digit sequential number (001, 002, 003...)
- `descriptive_name`: Snake_case description

Example: `016_add_unit_preference.py`

## Creating a New Migration

1. Create file in `/srv/raid0/docker/build/mygarage/backend/app/migrations/`
2. Use next sequential number
3. Implement `upgrade()` function
4. Optional: Implement `downgrade()` function (limited in SQLite)
5. Document the migration in this README

### Migration Template

```python
"""Brief description of migration."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Perform migration."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if already applied (idempotency)
        result = conn.execute(text("PRAGMA table_info(table_name)"))
        existing_columns = {row[1] for row in result}

        if 'new_column' in existing_columns:
            print("  → Migration already applied, skipping")
            return

        # Perform migration
        conn.execute(text("""
            ALTER TABLE table_name
            ADD COLUMN new_column VARCHAR(50)
        """))

        print("✓ Migration completed successfully")


def downgrade():
    """Rollback migration (if possible)."""
    print("ℹ Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()
```

## Migration Tracking

Migrations are tracked in the `schema_migrations` table:
- `id`: Auto-increment primary key
- `migration_name`: Filename without extension
- `applied_at`: Timestamp

To view applied migrations:

```bash
sqlite3 /srv/raid0/docker/build/mygarage/data/mygarage.db "SELECT * FROM schema_migrations ORDER BY id;"
```

## SQLite Limitations

SQLite does not support:
- `DROP COLUMN`
- `ALTER COLUMN` (modify type, constraints)
- Most `ALTER TABLE` operations

**Workarounds:**
1. Create new table with desired schema
2. Copy data from old table
3. Drop old table
4. Rename new table

## Best Practices

1. **Idempotency**: Always check if migration already applied
2. **Logging**: Print clear progress messages
3. **Validation**: Verify migration results
4. **Backup**: Backup database before running migrations
5. **Testing**: Test on copy of production database first

### Backup Command

```bash
cp /srv/raid0/docker/build/mygarage/data/mygarage.db /srv/raid0/docker/build/mygarage/data/mygarage.db.backup
```

## Current Migrations

| # | Name | Description |
|---|------|-------------|
| 001 | add_vin_fields | Initial VIN-related fields |
| 002 | update_address_book_schema | Address book schema update |
| 003 | add_window_sticker_fields | Window sticker fields |
| 004 | add_window_sticker_enhanced_fields | Enhanced window sticker data |
| 005 | add_vehicle_photo_thumbnails | Photo thumbnail support |
| 006 | update_service_type_constraint | Service type constraint update |
| 007 | add_fuel_hauling_column | Fuel hauling tracking |
| 008 | add_spot_rental_utilities | Spot rental utilities |
| 009 | add_fuel_propane_column | Propane fuel tracking |
| 010 | migrate_to_argon2 | Password hashing upgrade to Argon2 |
| 011 | add_oidc_fields | OIDC authentication support |
| 012 | security_hardening | Security improvements |
| 013 | add_user_id_to_vehicles | Multi-user vehicle ownership |
| 014 | hydrate_legacy_photos | Photo path migration |
| 015 | add_oidc_pending_links | OIDC account linking |
| **016** | **add_unit_preference** | **Per-user imperial/metric preference** |
| **017** | **add_vehicle_archive** | **Soft-delete vehicle archive system** |

## Verifying Migrations

After running migrations, verify they succeeded:

### Check for new columns

```bash
# Check users table for unit_preference
sqlite3 /srv/raid0/docker/build/mygarage/data/mygarage.db "PRAGMA table_info(users);" | grep unit

# Check vehicles table for archive columns
sqlite3 /srv/raid0/docker/build/mygarage/data/mygarage.db "PRAGMA table_info(vehicles);" | grep archive
```

### Check for new indexes

```bash
sqlite3 /srv/raid0/docker/build/mygarage/data/mygarage.db "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%unit%' OR name LIKE '%archive%';"
```

## Rollback

If you need to rollback a migration:

1. **Restore from backup** (recommended):
   ```bash
   cp /srv/raid0/docker/build/mygarage/data/mygarage.db.backup /srv/raid0/docker/build/mygarage/data/mygarage.db
   ```

2. **Manual rollback** (if downgrade supported):
   ```bash
   python app/migrations/NNN_migration_name.py
   # Then call the downgrade() function manually
   ```

Note: Most MyGarage migrations do not support automatic rollback due to SQLite limitations.

## Troubleshooting

### Migration fails with "column already exists"

The migration is idempotent - it's safe to run again. The check failed to detect the existing column. This is harmless and can be ignored.

### Migration fails with other errors

1. Check the migration logs for specific error messages
2. Verify database file permissions
3. Ensure database is not locked by another process
4. Restore from backup and retry

### Container won't start after migration

Check backend logs:
```bash
docker logs mygarage-backend-dev --tail 50
```

If migration failed, restore from backup and investigate the error.

## Development Workflow

When developing new migrations:

1. **Create migration file** with next number
2. **Test locally** on a copy of your database
3. **Verify idempotency** (run twice, should succeed both times)
4. **Document** in this README
5. **Commit** migration file to git

## Production Deployment

1. **Backup database** before deploying
2. **Test migrations** on staging/copy first
3. **Deploy** new code (migrations run automatically)
4. **Verify** migrations succeeded
5. **Monitor** application logs for errors

## Additional Resources

- SQLAlchemy Alembic: https://alembic.sqlalchemy.org/
- SQLite ALTER TABLE docs: https://www.sqlite.org/lang_altertable.html
- MyGarage migration runner: `app/migrations/runner.py`
