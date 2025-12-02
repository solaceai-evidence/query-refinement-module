"""
Database connection and session management for query refinement web app.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

REFINEMENT_FRAMEWORK_PATH=os.getenv("REFINEMENT_FRAMEWORK_PATH", "/dev/null")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///query_refinement.db")

engine = create_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import all models to ensure they are registered with SQLAlchemy
from query_refinement_module.db.models.user import Base
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.refinement_step import RefinementStep
from query_refinement_module.db.models.feedback import Feedback
from query_refinement_module.db.models.followup_history import FollowUpHistory

# Create tables (for dev/testing; use Alembic for migrations in production)
def init_db():
    from query_refinement_module.db.models.user import Base
    Base.metadata.create_all(bind=engine)
