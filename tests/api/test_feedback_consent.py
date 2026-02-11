"""Tests for feedback consent behavior.

Key requirement: feedback submission should complete the workflow, but data consent must be explicit.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from query_refinement_module.api.main import app
from query_refinement_module.db.crud import create_user, create_query_session, create_query
from query_refinement_module.db.session import get_db
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query import Query


@pytest.fixture
def db(test_db_session):
    """Override get_db dependency to use the test session."""

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield test_db_session
    app.dependency_overrides.clear()


@pytest.fixture
def user_token(db: Session) -> str:
    user = create_user(
        db,
        username="mph_user",
        email="mph@test.com",
        password="UserSecret123!",
        name="MPH User",
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "UserSecret123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _create_query(db: Session, user_email: str = "mph@test.com") -> int:
    user = db.query(User).filter(User.email == user_email).first()
    assert user is not None

    session = create_query_session(db, user_id=user.id)
    query = create_query(
        db,
        session_id=session.id,
        original_query="effects of aspirin",
    )
    assert query.consent_given is False
    return query.id


def test_feedback_without_consent_does_not_mark_query_consented(db: Session, user_token: str):
    client = TestClient(app)
    query_id = _create_query(db)

    response = client.post(
        "/api/v1/feedback/",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "query_id": query_id,
            "rating": 4,
            "comments": "Most helpful: X\nImprovements: Y",
            "consent_to_use_data": False,
            "additional_metadata": {"mph_survey_v1": {"overall_helpful": 4}},
        },
    )

    assert response.status_code == 201

    query = db.query(Query).filter(Query.id == query_id).first()
    assert query is not None
    assert query.consent_given is False

    user = db.query(User).filter(User.email == "mph@test.com").first()
    assert user is not None
    assert user.has_completed_workflow is True


def test_feedback_with_consent_marks_query_consented(db: Session, user_token: str):
    client = TestClient(app)
    query_id = _create_query(db)

    response = client.post(
        "/api/v1/feedback/",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "query_id": query_id,
            "rating": 5,
            "comments": "Most helpful: A\nImprovements: B",
            "consent_to_use_data": True,
            "additional_metadata": {"mph_survey_v1": {"overall_helpful": 5}},
        },
    )

    assert response.status_code == 201

    query = db.query(Query).filter(Query.id == query_id).first()
    assert query is not None
    assert query.consent_given is True
    assert query.consent_given_at is not None
