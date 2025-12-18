"""
Database connection and session management for query refinement web app.

Supports both SQLite (development) and PostgreSQL (production) with optimized
connection pooling for high-concurrency deployments.
"""
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Set dummy value for REFINEMENT_FRAMEWORK_PATH if not set (for migrations)
REFINEMENT_FRAMEWORK_PATH = os.getenv("REFINEMENT_FRAMEWORK_PATH", "/dev/null")

# Database configuration from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///query_refinement.db")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Connection pool settings (only for PostgreSQL)
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "30.0"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))
DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"

# Determine if we're using PostgreSQL or SQLite
is_postgresql = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgresql+psycopg2://")

# SQLAlchemy engine configuration with appropriate pooling
if is_postgresql:
    # PostgreSQL with connection pooling for production
    logger.info(
        f"Configuring PostgreSQL connection pool: "
        f"pool_size={DB_POOL_SIZE}, max_overflow={DB_MAX_OVERFLOW}, "
        f"pool_recycle={DB_POOL_RECYCLE}s, pre_ping={DB_POOL_PRE_PING}"
    )
    
    engine = create_engine(
        DATABASE_URL,
        echo=DB_ECHO,
        future=True,
        # Connection pooling settings
        poolclass=QueuePool,
        pool_size=DB_POOL_SIZE,  # Number of persistent connections
        max_overflow=DB_MAX_OVERFLOW,  # Max connections beyond pool_size
        pool_timeout=DB_POOL_TIMEOUT,  # Seconds to wait for available connection
        pool_recycle=DB_POOL_RECYCLE,  # Recycle connections after N seconds
        pool_pre_ping=DB_POOL_PRE_PING,  # Test connections before using
        # Performance optimizations
        connect_args={
            "connect_timeout": 10,  # Connection timeout in seconds
            "options": "-c timezone=utc"  # Force UTC timezone
        }
    )
    
    # Log connection pool events for monitoring
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_conn, connection_record):
        """Log successful database connections."""
        logger.debug("New database connection established")
    
    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_conn, connection_record, connection_proxy):
        """Log connection checkouts from pool."""
        logger.debug("Connection checked out from pool")
    
    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        """Log connection returns to pool."""
        logger.debug("Connection returned to pool")
        
else:
    # SQLite without pooling (single-threaded, development only)
    logger.info("Using SQLite database (development mode)")
    engine = create_engine(
        DATABASE_URL,
        echo=DB_ECHO,
        future=True,
        # SQLite-specific settings
        connect_args={"check_same_thread": False},  # Allow multi-threading
        poolclass=NullPool  # No connection pooling for SQLite
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import all models to ensure they are registered with SQLAlchemy
from query_refinement_module.db.models.user import Base
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.refinement_step import RefinementStep
from query_refinement_module.db.models.refinement_step_metadata import RefinementStepMetadata
from query_refinement_module.db.models.feedback import Feedback
from query_refinement_module.db.models.followup_history import FollowUpHistory

# Create tables (for dev/testing; use Alembic for migrations in production)
def init_db():
    from query_refinement_module.db.models.user import Base
    Base.metadata.create_all(bind=engine)
