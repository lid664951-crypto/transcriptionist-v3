"""
Database Connection Manager

Provides database connection management with transaction support.

Validates: Requirements 10.1, 10.2, 10.4
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections and sessions.
    
    Features:
    - SQLite database with WAL mode for better concurrency
    - Session management with transaction support
    - Automatic table creation
    - Connection pooling
    """
    
    def __init__(self, db_path: Path):
        """
        Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._initialized = False
    
    @property
    def engine(self) -> Engine:
        """Get the database engine, creating it if necessary."""
        if self._engine is None:
            self._create_engine()
        return self._engine
    
    def _create_engine(self) -> None:
        """Create the SQLAlchemy engine."""
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create engine with SQLite optimizations
        db_url = f"sqlite:///{self.db_path}"
        
        self._engine = create_engine(
            db_url,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,
            connect_args={
                "check_same_thread": False,  # Allow multi-threaded access
                "timeout": 30,  # Connection timeout
            }
        )
        
        # Enable WAL mode and other optimizations
        @event.listens_for(self._engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()
        
        # Create session factory
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False
        )
        
        logger.info(f"Database engine created: {self.db_path}")
    
    def init_db(self) -> None:
        """Initialize the database, creating all tables."""
        if self._initialized:
            return
        
        Base.metadata.create_all(self.engine)
        self._initialized = True
        logger.info("Database tables created")
    
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
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def close(self) -> None:
        """Close the database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connection closed")


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
    
    # Initialize lock on first call
    if _db_init_lock is None:
        import threading
        _db_init_lock = threading.Lock()
    
    # Double-checked locking pattern for thread safety
    if _db_manager is None:
        with _db_init_lock:
            # Check again inside lock
            if _db_manager is None:
                from transcriptionist_v3.runtime.runtime_config import get_runtime_config
                config = get_runtime_config()
                db_path = config.paths.database_dir / "transcriptionist.db"
                _db_manager = DatabaseManager(db_path)
                _db_manager.init_db()
                logger.info("Database manager initialized (thread-safe)")
    
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
