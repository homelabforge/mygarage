"""Database migration runner with automatic discovery and tracking."""

import importlib.util
import inspect as python_inspect
import logging
from collections.abc import Container
from pathlib import Path
from types import ModuleType

from sqlalchemy import Connection, create_engine, text

from app.utils.pg_session import create_utc_engine

logger = logging.getLogger(__name__)

#: The PG timestamp repair. Rows written before it have to stay in the server's
#: zone so it converts them right, so sync sessions pin to UTC only once it's
#: stamped. On PG it's also the line before which no migration failure is
#: shrugged off. A renumber at merge has to update this too.
TIMESTAMP_REPAIR_STEM = "134_pg_timestamp_repair_utc"


def pins_sessions(dialect_name: str, applied: Container[str]) -> bool:
    """Whether sync sessions on this database should be pinned to UTC.

    The runner and the maintenance tools share this rule. Only PostgreSQL has a
    session zone, and only once the timestamp repair is stamped.

    Args:
        dialect_name: The engine's dialect name, e.g. ``"postgresql"``.
        applied: The stems recorded in ``schema_migrations``.
    """
    return dialect_name == "postgresql" and TIMESTAMP_REPAIR_STEM in applied


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
        # Bound values stay out of error messages, so a failed migration logs no setting value.
        # Unpinned until the timestamp repair is stamped; see _pin_once_repaired.
        self.engine = create_engine(database_url, hide_parameters=True)
        self.pinned = False

    def _pin_once_repaired(self, applied: set[str]) -> None:
        """Swap in a UTC-pinned engine once the timestamp repair is stamped.

        A fresh engine, not a listener on this one: a connection already in the
        pool never sees a new listener and would keep the server's zone.

        A failed swap is fatal whatever migration it follows. Past the repair
        nothing else stops startup, so the run would end here and the app would
        boot with the rest never run.
        """
        if self.pinned or not pins_sessions(self.engine.dialect.name, applied):
            return
        try:
            unpinned = self.engine
            self.engine = create_utc_engine(self.database_url, hide_parameters=True)
            unpinned.dispose()
        except Exception as e:
            logger.error("Couldn't pin migration sessions to UTC, so startup stops: %s", e)
            e.__migration_fatal__ = True  # type: ignore[attr-defined]
            raise
        self.pinned = True
        logger.info("Timestamp repair is applied; migration sessions now run in UTC")

    def _ensure_migration_tracking_table(self) -> None:
        """Create schema_migrations table if it doesn't exist."""
        # Ask the engine's dialect, not the URL: a SQLite file can sit in a folder called postgresql.
        is_postgres = self.engine.dialect.name == "postgresql"

        if is_postgres:
            create_sql = """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id SERIAL PRIMARY KEY,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """
        else:
            # SQLite syntax
            create_sql = """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """

        with self.engine.begin() as conn:
            conn.execute(text(create_sql))
            logger.debug("Migration tracking table verified")

    def _get_applied_migrations(self) -> set[str]:
        """
        Get set of already-applied migration names.

        Returns:
            Set of migration names (without .py extension)
        """
        with self.engine.begin() as conn:
            result = conn.execute(text("SELECT migration_name FROM schema_migrations ORDER BY id"))
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
            self._insert_stamps(conn, [name])
            logger.debug("Marked migration '%s' as applied", name)

    def _insert_stamps(self, conn: Connection, names: list[str]) -> None:
        """Record migrations as applied on the caller's connection, in its transaction."""
        for name in names:
            conn.execute(
                text("INSERT INTO schema_migrations (migration_name) VALUES (:name)"),
                {"name": name},
            )

    def _discover_migrations(self) -> list[tuple[str, Path]]:
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

    def _load_module(self, name: str, path: Path) -> ModuleType:
        """Dynamically import a migration module from its file path.

        Raises:
            ImportError: if the module cannot be loaded.
        """
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load migration module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _get_replaces(self, module: ModuleType) -> list[str]:
        """Return the migration's REPLACES list of superseded stems (default []).

        Non-list/tuple values are ignored with a warning; non-str entries are
        skipped with a warning. Order is preserved.
        """
        modname = getattr(module, "__name__", "?")
        replaces = getattr(module, "REPLACES", [])
        if not isinstance(replaces, (list, tuple)):
            logger.warning("Migration %s: REPLACES must be a list of stems; ignoring", modname)
            return []
        result: list[str] = []
        for stem in replaces:
            if not isinstance(stem, str):
                logger.warning(
                    "Migration %s: REPLACES entry %r is not a string; ignoring", modname, stem
                )
                continue
            result.append(stem)
        return result

    def _run_upgrade(self, name: str, module: ModuleType) -> None:
        """Execute an already-loaded migration module's upgrade().

        Passes the runner engine when the signature accepts it, else calls with
        no args (legacy migrations).

        Raises:
            AttributeError: if the module has no upgrade().
            Exception: whatever upgrade() raises.
        """
        if not hasattr(module, "upgrade"):
            raise AttributeError(f"Migration {name} missing upgrade() function")
        logger.info("Running migration: %s", name)
        sig = python_inspect.signature(module.upgrade)
        if "engine" in sig.parameters:
            module.upgrade(engine=self.engine)
        else:
            module.upgrade()

    def _takes_conn(self, module: ModuleType) -> bool:
        """Whether the migration's upgrade() asks for a ``conn`` (the atomic path)."""
        upgrade = getattr(module, "upgrade", None)
        return upgrade is not None and "conn" in python_inspect.signature(upgrade).parameters

    def _run_upgrade_with_stamp(self, name: str, module: ModuleType) -> None:
        """Run an ``upgrade(conn)`` migration and stamp it in ONE transaction.

        With a separate stamp, a crash in between reruns the migration next
        boot, and a data rewrite like the timestamp repair would shift every
        row twice. Here the data and the stamp commit or roll back together.
        """
        logger.info("Running migration: %s (stamped in the same transaction)", name)
        with self.engine.begin() as conn:
            module.upgrade(conn=conn)
            self._insert_stamps(conn, [name])

    def _mark_migrations_applied(self, names: list[str]) -> None:
        """Record several migrations as applied in ONE transaction (atomic).

        A squash migration must stamp itself and every replaced stem together —
        a partial commit would leave the baseline applied but its replaced
        individuals pending, so the next boot would run them against the
        baseline-built schema.
        """
        if not names:
            return
        with self.engine.begin() as conn:
            self._insert_stamps(conn, names)

    def _apply_migration(
        self, name: str, module: ModuleType, applied: set[str], discovered_stems: set[str]
    ) -> bool:
        """Run and stamp one loaded migration, honoring REPLACES. Grows ``applied``.

        Returns:
            True if the migration's upgrade() ran (a fully-migrated squash is
            stamped without running; a partial one is deferred).
        """
        replaces = self._get_replaces(module)

        atomic = self._takes_conn(module)
        if atomic and replaces:
            raise TypeError(
                f"Migration {name}: an upgrade(conn) migration can't declare REPLACES; "
                "the squash path stamps several stems"
            )

        if not replaces:
            if atomic:
                self._run_upgrade_with_stamp(name, module)
            else:
                self._run_upgrade(name, module)
                self._mark_migration_applied(name)
            applied.add(name)
            return True

        # Squash / baseline migration. Warn on unknown stems; classify
        # against real (file-backed) replaced stems only.
        for stem in replaces:
            if stem not in discovered_stems:
                logger.warning(
                    "Squash migration %s: REPLACES entry '%s' matches no migration file; ignoring",
                    name,
                    stem,
                )
        known = {stem for stem in replaces if stem in discovered_stems}
        known_applied = known & applied

        if not known_applied:
            # Fresh: run baseline, then atomically stamp it + all replaced stems.
            self._run_upgrade(name, module)
            to_stamp = [name] + [s for s in sorted(known) if s not in applied]
            self._mark_migrations_applied(to_stamp)
            applied.update(to_stamp)
            logger.info(
                "Squash migration %s: fresh install, collapsed %s replaced migration(s)",
                name,
                len(known),
            )
            return True
        if known <= applied:
            # Fully-migrated: record the collapse without running the baseline.
            self._mark_migration_applied(name)
            applied.add(name)
            logger.info(
                "Squash migration %s: history already applied, marked without running",
                name,
            )
            return False
        # Partial: defer; remaining individuals run this pass, baseline converges next boot.
        logger.info(
            "Squash migration %s: partial history, deferring (applying remaining individual migrations)",
            name,
        )
        return False

    def run_pending_migrations(self) -> None:
        """Run all pending migrations, honoring squash (REPLACES) migrations.

        A migration may declare a module-level ``REPLACES = ["001_...", ...]`` of
        filename stems it supersedes (a squash/baseline). Evaluated in stem order
        against the applied set ``A``, for a squash migration ``M`` whose real
        (file-backed) replaced stems are ``known``:

        * ``known ∩ A = ∅`` (fresh) -> run ``M``, then atomically stamp ``M`` and
          every stem in ``known`` -> the individual replaced files are then seen
          as applied and skipped.
        * ``known ⊆ A`` (fully-migrated) -> stamp ``M`` WITHOUT running it.
        * partial -> skip ``M`` this pass; the unapplied individuals run normally;
          ``M`` stamps on a later run once ``known ⊆ A``.

        A REPLACES entry matching no discovered file is warned and ignored. A
        migration with no REPLACES runs and is stamped exactly as before, unless
        its ``upgrade`` takes a ``conn``: then it runs on that connection and is
        stamped in the same transaction (an ``upgrade(conn)`` can't declare
        REPLACES).

        On PostgreSQL the runner's sessions keep the server's zone until
        ``TIMESTAMP_REPAIR_STEM`` is stamped, then a new UTC-pinned engine takes
        over. That's checked at the start and after every migration.

        Each migration's module load, upgrade(), and tracking-table writes run
        inside ONE try/except: on the first failure the runner logs, annotates
        the exception with ``__migration_fatal__`` (from the loaded module's
        FATAL flag, or False if it failed to load; always True on PostgreSQL
        while the timestamp repair is unstamped, and when the UTC pin swap
        fails), and re-raises, stopping the chain without marking the failed
        migration applied. A swap that fails at the start is annotated too.
        """
        self._ensure_migration_tracking_table()

        applied = self._get_applied_migrations()  # mutable: grows as we stamp
        self._pin_once_repaired(applied)
        all_migrations = self._discover_migrations()
        discovered_stems = {name for name, _ in all_migrations}
        pending = [(name, path) for name, path in all_migrations if name not in applied]

        if not pending:
            logger.info("No pending migrations")
            return

        logger.info("Found %s pending migration(s)", len(pending))

        ran = 0
        for name, path in pending:
            if name in applied:
                # Stamped by an earlier squash migration in this same pass.
                continue

            module = None
            try:
                module = self._load_module(name, path)
                if self._apply_migration(name, module, applied, discovered_stems):
                    ran += 1
                self._pin_once_repaired(applied)
            except Exception as e:
                logger.error("Migration '%s' failed: %s", name, e)
                fatal = bool(getattr(module, "FATAL", False)) if module is not None else False
                if getattr(e, "__migration_fatal__", False) is True:
                    fatal = True  # a failed pin swap marks itself
                if (
                    self.engine.dialect.name == "postgresql"
                    and TIMESTAMP_REPAIR_STEM not in applied
                ):
                    # The app pins to UTC, so booting with the repair pending would
                    # write UTC rows the repair later shifts. Stop instead.
                    fatal = True
                    logger.error(
                        "The PostgreSQL timestamp repair (%s) hasn't run yet, so this "
                        "failure stops startup",
                        TIMESTAMP_REPAIR_STEM,
                    )
                logger.error("Stopping migration run - fix errors and restart")
                try:
                    e.__migration_fatal__ = fatal  # type: ignore[attr-defined]
                except Exception:
                    pass
                raise

        logger.info("✓ All %s migration(s) applied successfully", ran)


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
    try:
        runner.run_pending_migrations()
    finally:
        # Whichever engine it ended on (the pinned one after a swap) still
        # holds a pooled connection, and nothing uses it after this.
        runner.engine.dispose()
