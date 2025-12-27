"""Database migration runner with automatic discovery and tracking."""

import logging
import importlib.util
from pathlib import Path
from typing import Set, List, Tuple
from sqlalchemy import text, create_engine

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Handles database migration discovery, tracking, and execution."""

    def __init__(self, database_url: str, migrations_dir: Path):
        """
        Initialize migration runner.

        Args:
            database_url: SQLAlchemy database URL (e.g., 'sqlite:////data/mygarage.db')
            migrations_dir: Path to directory containing migration files
        """
        self.database_url = database_url
        self.migrations_dir = Path(migrations_dir)
        self.engine = create_engine(database_url)

    def _ensure_migration_tracking_table(self) -> None:
        """Create schema_migrations table if it doesn't exist."""
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """)
            )
            logger.debug("Migration tracking table verified")

    def _get_applied_migrations(self) -> Set[str]:
        """
        Get set of already-applied migration names.

        Returns:
            Set of migration names (without .py extension)
        """
        with self.engine.begin() as conn:
            result = conn.execute(
                text("SELECT migration_name FROM schema_migrations ORDER BY id")
            )
            applied = {row[0] for row in result}
            logger.debug("Found %s applied migration(s)", len(applied))
            return applied

    def _mark_migration_applied(self, name: str) -> None:
        """
        Record migration as complete.

        Args:
            name: Migration name (without .py extension)
        """
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_migrations (migration_name) VALUES (:name)"),
                {"name": name},
            )
            logger.debug("Marked migration '%s' as applied", name)

    def _discover_migrations(self) -> List[Tuple[str, Path]]:
        """
        Find all migration files and return sorted list.

        Returns:
            List of (migration_name, file_path) tuples sorted by filename
        """
        migrations = []

        # Find all .py files in migrations directory
        for filepath in self.migrations_dir.glob("*.py"):
            # Skip __init__.py and runner.py
            if filepath.name in ("__init__.py", "runner.py"):
                continue

            # Extract name without extension
            migration_name = filepath.stem
            migrations.append((migration_name, filepath))

        # Sort by filename (numeric prefix ensures correct order)
        migrations.sort(key=lambda x: x[0])

        logger.debug("Discovered %s migration file(s)", len(migrations))
        return migrations

    def _load_and_run_migration(self, name: str, path: Path) -> None:
        """
        Dynamically import and execute a migration file.

        Args:
            name: Migration name (without .py extension)
            path: Path to migration file

        Raises:
            Exception: If migration fails to load or execute
        """
        # Load module dynamically
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load migration module: {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Execute upgrade function
        if not hasattr(module, "upgrade"):
            raise AttributeError(f"Migration {name} missing upgrade() function")

        logger.info("Running migration: %s", name)
        module.upgrade()

    def run_pending_migrations(self) -> None:
        """
        Main orchestration method - runs all pending migrations.

        This method:
        1. Ensures migration tracking table exists
        2. Gets list of already-applied migrations
        3. Discovers all available migrations
        4. Runs pending migrations in order
        5. Marks each as applied after successful execution

        Stops on first failure without marking failed migration as applied.
        """
        # Ensure tracking table exists
        self._ensure_migration_tracking_table()

        # Get applied migrations
        applied = self._get_applied_migrations()

        # Discover all migrations
        all_migrations = self._discover_migrations()

        # Filter to pending only
        pending = [(name, path) for name, path in all_migrations if name not in applied]

        if not pending:
            logger.info("No pending migrations")
            return

        logger.info("Found %s pending migration(s)", len(pending))

        # Run each pending migration
        successful = 0
        for name, path in pending:
            try:
                self._load_and_run_migration(name, path)
                self._mark_migration_applied(name)
                successful += 1
            except Exception as e:
                logger.error("Migration '%s' failed: %s", name, e)
                logger.error("Stopping migration run - fix errors and restart")
                raise

        logger.info("✓ All %s migration(s) applied successfully", successful)


def run_migrations(database_url: str, migrations_dir: Path) -> None:
    """
    Convenience function to run all pending migrations.

    Args:
        database_url: SQLAlchemy database URL (e.g., 'sqlite:////data/mygarage.db')
        migrations_dir: Path to directory containing migration files

    Example:
        >>> run_migrations('sqlite:////data/mygarage.db', Path('/app/migrations'))
    """
    runner = MigrationRunner(database_url, migrations_dir)
    runner.run_pending_migrations()
