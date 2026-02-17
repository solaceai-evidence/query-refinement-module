"""
Database connection and session management for query refinement web app.

Supports both SQLite (development) and PostgreSQL (production) with optimized
connection pooling for high-concurrency deployments.
"""
import logging
import time
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.engine import Engine
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Import tracing utilities for request correlation
from query_refinement_module.tracing import get_request_id, get_trace_id

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
    def receive_connect(dbapi_conn, _connection_record):
        """Log successful database connections."""
        logger.debug(
            "Database connection established",
            extra={"context": {"connection_id": id(dbapi_conn)}}
        )
    
    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_conn, _connection_record, _connection_proxy):
        """Log connection checkouts from pool."""
        logger.debug(
            "Connection checked out from pool",
            extra={"context": {"connection_id": id(dbapi_conn)}}
        )
    
    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_conn, _connection_record):
        """Log connection returned to pool."""
        logger.debug(
            "Connection returned to pool",
            extra={"context": {"connection_id": id(dbapi_conn)}}
        )
        
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

# Query execution tracing for performance monitoring and debugging
# Tracks query start time, duration, and correlates with request_id
# These listeners work for both PostgreSQL and SQLite
@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, _parameters, context, executemany):
    """Log SQL query execution start with request context."""
    context._query_start_time = time.time()
    
    # Get current request context for tracing
    request_id = get_request_id()
    trace_id = get_trace_id()
    
    # Truncate long SQL statements for cleaner logs
    statement_preview = statement[:200] + "..." if len(statement) > 200 else statement
    
    logger.debug(
        "Executing SQL query",
        extra={
            "context": {
                "request_id": request_id,
                "trace_id": trace_id,
                "sql_preview": statement_preview,
                "executemany": executemany
            }
        }
    )

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, _parameters, context, executemany):
    """Log SQL query completion with duration and performance metrics."""
    # Calculate query duration
    duration = time.time() - context._query_start_time
    duration_ms = duration * 1000
    
    # Get current request context
    request_id = get_request_id()
    trace_id = get_trace_id()
    
    # Truncate statement for logging
    statement_preview = statement[:200] + "..." if len(statement) > 200 else statement
    
    # Get row count if available
    try:
        row_count = cursor.rowcount if cursor.rowcount >= 0 else None
    except Exception:
        row_count = None
    
    log_context = {
        "request_id": request_id,
        "trace_id": trace_id,
        "sql_preview": statement_preview,
        "duration_ms": round(duration_ms, 2),
        "executemany": executemany
    }
    
    if row_count is not None:
        log_context["row_count"] = row_count
    
    # Warn on slow queries (>1 second)
    if duration_ms > 1000:
        logger.warning(
            f"Slow query detected ({round(duration_ms, 2)}ms)",
            extra={"context": log_context}
        )
    else:
        logger.debug(
            "Query completed",
            extra={"context": log_context}
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
from query_refinement_module.db.models.audit_log import AuditLog
from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery
from query_refinement_module.db.models.frontend_log import FrontendLog
from query_refinement_module.db.models.user_framework_access import UserFrameworkAccess

# Create tables (for dev/testing; use Alembic for migrations in production)
def init_db():
    from query_refinement_module.db.models.user import Base
    Base.metadata.create_all(bind=engine)
