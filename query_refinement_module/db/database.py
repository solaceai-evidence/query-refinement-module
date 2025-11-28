"""
Database connection and session management for query refinement web app.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///query_refinement.db")

engine = create_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import all models to ensure they are registered with SQLAlchemy
from .user import User
from .query_session import QuerySession
from .query import Query
from .refinement_step import RefinementStep
from .feedback import Feedback

# Create tables (for dev/testing; use Alembic for migrations in production)
def init_db():
    from .user import Base
    Base.metadata.create_all(bind=engine)
