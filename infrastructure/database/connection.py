"""
Database Connection Manager

Provides database connection management with transaction support.

Validates: Requirements 10.1, 10.2, 10.4
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections and sessions.

    Features:
    - SQLite backend
    - Session management with transaction support
    - Automatic table creation
    - Connection pooling and health checks
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        db_url: str | None = None,
        backend: str | None = None,
    ):
        """
        Initialize the database manager.

        Args:
            db_path: Path to SQLite database file, or ":memory:"
            db_url: Explicit SQLite SQLAlchemy URL
            backend: 已废弃，仅为兼容旧调用
        """
        if backend and backend.strip().lower() != "sqlite":
            logger.warning("Only SQLite backend is supported now, ignore backend=%s", backend)

        resolved_backend, resolved_db_url, resolved_db_path = self._resolve_connection_target(
            db_path=db_path,
            db_url=db_url,
            backend="sqlite",
        )

        self.backend = resolved_backend
        self.db_url = resolved_db_url
        self.db_path = resolved_db_path

        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._initialized = False

    @staticmethod
    def _resolve_connection_target(
        db_path: str | Path | None,
        db_url: str | None,
        backend: str | None,
    ) -> tuple[str, str, Optional[Path]]:
        _ = backend
        normalized_url = (db_url or "").strip()

        if normalized_url:
            if normalized_url.startswith("sqlite://"):
                try:
                    parsed = make_url(normalized_url)
                    sqlite_db = parsed.database
                    sqlite_path = Path(sqlite_db) if sqlite_db and sqlite_db != ":memory:" else None
                except Exception:
                    sqlite_path = None
                return "sqlite", normalized_url, sqlite_path
            logger.warning("Only sqlite:// URL is supported now, ignore db_url=%s", normalized_url)

        if db_path is None:
            raise ValueError("SQLite backend requires db_path when db_url is not set")

        db_path_str = str(db_path).strip()
        if db_path_str == ":memory:":
            return "sqlite", "sqlite:///:memory:", None

        sqlite_path = Path(db_path)
        return "sqlite", f"sqlite:///{sqlite_path}", sqlite_path

    @property
    def engine(self) -> Engine:
        """Get the database engine, creating it if necessary."""
        if self._engine is None:
            self._create_engine()
        return self._engine

    def _create_engine(self) -> None:
        """Create the SQLAlchemy engine."""
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        engine_kwargs = {
            "echo": False,
            "pool_pre_ping": True,
        }

        engine_kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }

        self._engine = create_engine(self.db_url, **engine_kwargs)

        @event.listens_for(self._engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

        target = str(self.db_path) if self.db_path else self.db_url
        logger.info("Database engine created (%s): %s", self.backend, target)

    def init_db(self) -> None:
        """Initialize the database, creating all tables."""
        if self._initialized:
            return

        self._health_check_or_raise()
        Base.metadata.create_all(self.engine)
        self._apply_migrations()
        self._initialized = True
        logger.info("Database tables initialized")

    def _health_check_or_raise(self) -> None:
        """Check connection availability before full initialization."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.error("Database health check failed (%s): %s", self.backend, e)
            raise

    def get_session(self) -> Session:
        """
        Get a new database session.

        Returns:
            Session: A new SQLAlchemy session
        """
        if self._session_factory is None:
            self._create_engine()
        return self._session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope around a series of operations.

        Usage:
            with db_manager.session_scope() as session:
                session.add(obj)
                # Automatically commits on success, rolls back on exception

        Yields:
            Session: Database session
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
            return
        except Exception:
            session.rollback()
            raise
        finally:
            try:
                session.close()
            except Exception as e:
                logger.error("Failed to close session: %s", e)

    def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connection closed")

    def _apply_migrations(self) -> None:
        """Apply lightweight schema migrations (additive only)."""
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("PRAGMA table_info(audio_files)"))
                columns = [row[1] for row in result.fetchall()]

                new_columns = [
                    ("original_filename", "original_filename VARCHAR(512) NOT NULL DEFAULT ''"),
                    ("translated_name", "translated_name VARCHAR(512)"),
                    ("index_status", "index_status INTEGER DEFAULT 0"),
                    ("index_version", "index_version VARCHAR(64) NOT NULL DEFAULT ''"),
                    ("tag_status", "tag_status INTEGER DEFAULT 0"),
                    ("tag_version", "tag_version VARCHAR(64) NOT NULL DEFAULT ''"),
                    ("translation_status", "translation_status INTEGER DEFAULT 0"),
                ]

                for name, ddl in new_columns:
                    if name in columns:
                        continue
                    conn.execute(text(f"ALTER TABLE audio_files ADD COLUMN {ddl}"))

                if "original_filename" in columns or any(name == "original_filename" for name, _ in new_columns):
                    conn.execute(
                        text(
                            "UPDATE audio_files "
                            "SET original_filename = filename "
                            "WHERE original_filename = '' OR original_filename IS NULL"
                        )
                    )

                index_sql = [
                    "CREATE INDEX IF NOT EXISTS idx_audio_files_index_status ON audio_files (index_status)",
                    "CREATE INDEX IF NOT EXISTS idx_audio_files_tag_status ON audio_files (tag_status)",
                    "CREATE INDEX IF NOT EXISTS idx_audio_files_translation_status ON audio_files (translation_status)",
                ]
                for sql in index_sql:
                    conn.execute(text(sql))
        except Exception as e:
            logger.error("Database migration failed: %s", e)
def _resolve_runtime_database_config() -> tuple[str, str, Optional[Path]]:
    from transcriptionist_v3.core.config import AppConfig
    from transcriptionist_v3.runtime.runtime_config import get_runtime_config

    runtime_config = get_runtime_config()
    configured_url = str(AppConfig.get("database.url", "") or "").strip()
    sqlite_filename = str(AppConfig.get("database.sqlite_filename", "transcriptionist.db") or "transcriptionist.db").strip()

    env_url = (os.environ.get("TRANSCRIPTIONIST_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()

    if configured_url:
        if configured_url.startswith("sqlite://"):
            return "sqlite", configured_url, None
        logger.warning("Ignore non-sqlite database.url, fallback to local sqlite file")

    if env_url:
        if env_url.startswith("sqlite://"):
            return "sqlite", env_url, None
        logger.warning("Ignore non-sqlite database env URL, fallback to local sqlite file")

    db_path = runtime_config.paths.database_dir / sqlite_filename
    return "sqlite", "", db_path


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None
_db_init_lock = None  # Will be initialized as threading.Lock()


def get_db_manager() -> DatabaseManager:
    """
    Get the global database manager.
    Thread-safe initialization with lock to prevent race conditions.

    Returns:
        DatabaseManager: The database manager instance
    """
    global _db_manager, _db_init_lock

    if _db_init_lock is None:
        import threading

        _db_init_lock = threading.Lock()

    if _db_manager is None:
        with _db_init_lock:
            if _db_manager is None:
                backend, db_url, db_path = _resolve_runtime_database_config()
                if db_url:
                    _db_manager = DatabaseManager(db_url=db_url, backend=backend)
                else:
                    _db_manager = DatabaseManager(db_path=db_path, backend=backend)
                _db_manager.init_db()
                logger.info("Database manager initialized (thread-safe), backend=%s", _db_manager.backend)

    return _db_manager


def get_session() -> Session:
    """
    Get a new database session.

    Returns:
        Session: A new SQLAlchemy session
    """
    return get_db_manager().get_session()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Provide a transactional scope.

    Yields:
        Session: Database session
    """
    with get_db_manager().session_scope() as session:
        yield session


def get_database_backend() -> str:
    """Return the active database backend type."""
    return get_db_manager().backend
