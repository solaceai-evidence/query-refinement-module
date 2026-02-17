"""
User to framework access mapping model.

Allows assigning zero or more refinement frameworks to each user.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from query_refinement_module.db.models.user import Base


def _utcnow():
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class UserFrameworkAccess(Base):
    __tablename__ = "user_framework_access"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "framework_name",
            name="uq_user_framework_access_user_framework",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    framework_name = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    user = relationship("User", back_populates="framework_access")

    def __repr__(self):
        return f"<UserFrameworkAccess(user_id={self.user_id}, framework='{self.framework_name}')>"
