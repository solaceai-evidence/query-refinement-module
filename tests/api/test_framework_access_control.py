import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from query_refinement_module.api.config import get_settings
from query_refinement_module.api import auth as api_auth

from query_refinement_module.api.main import app
from query_refinement_module.db.crud import (
    create_user,
    assign_user_framework_access,
    get_user_by_username,
)
from query_refinement_module.schema.registry import list_frameworks


@pytest.fixture
def db(test_db_session):
    from query_refinement_module.db.session import get_db

    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield test_db_session
    app.dependency_overrides.clear()


@pytest.fixture
def framework_name():
    frameworks = list_frameworks()
    if not frameworks:
        pytest.skip("No refinement frameworks available in test environment")
    return frameworks[0]


@pytest.fixture
def superuser_token(db: Session, login_and_get_auth_token) -> str:
    user = create_user(
        db,
        username="framework_admin",
        email="framework_admin@test.com",
        password="AdminSecret123!",
        name="Framework Admin",
    )
    setattr(user, "is_superuser", True)
    db.commit()

    client = TestClient(app)
    return login_and_get_auth_token(client, "framework_admin@test.com", "AdminSecret123!")


@pytest.fixture
def regular_user(db: Session):
    user = create_user(
        db,
        username="framework_user",
        email="framework_user@test.com",
        password="UserSecret123!",
        name="Framework User",
    )
    db.commit()
    return user


@pytest.fixture
def regular_user_token(regular_user, login_and_get_auth_token) -> str:
    client = TestClient(app)
    return login_and_get_auth_token(client, regular_user.email, "UserSecret123!")


class TestFrameworkAccessAdminEndpoints:
    def test_admin_can_assign_list_and_revoke_framework_access(
        self,
        regular_user,
        superuser_token,
        framework_name,
    ):
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {superuser_token}"}

        assign_response = client.post(
            f"/api/v1/api/admin/frameworks/users/{regular_user.id}/access",
            json={"framework_name": framework_name},
            headers=headers,
        )
        assert assign_response.status_code == 200
        assigned = assign_response.json()
        assert framework_name in assigned["framework_names"]

        list_response = client.get(
            f"/api/v1/api/admin/frameworks/users/{regular_user.id}/access",
            headers=headers,
        )
        assert list_response.status_code == 200
        listed = list_response.json()
        assert framework_name in listed["framework_names"]

        revoke_response = client.delete(
            f"/api/v1/api/admin/frameworks/users/{regular_user.id}/access/{framework_name}",
            headers=headers,
        )
        assert revoke_response.status_code == 200
        revoked = revoke_response.json()
        assert framework_name not in revoked["framework_names"]

    def test_regular_user_cannot_manage_framework_access(
        self,
        regular_user,
        regular_user_token,
        framework_name,
    ):
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {regular_user_token}"}

        response = client.post(
            f"/api/v1/api/admin/frameworks/users/{regular_user.id}/access",
            json={"framework_name": framework_name},
            headers=headers,
        )
        assert response.status_code == 403


class TestFrameworkAccessRefinementEndpoints:
    def test_user_sees_only_assigned_frameworks(
        self,
        db,
        regular_user,
        regular_user_token,
        framework_name,
    ):
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {regular_user_token}"}

        response_before = client.get("/api/v1/refinement/frameworks", headers=headers)
        assert response_before.status_code == 200
        assert framework_name not in response_before.json()["frameworks"]

        assign_user_framework_access(db, regular_user.id, framework_name)

        response_after = client.get("/api/v1/refinement/frameworks", headers=headers)
        assert response_after.status_code == 200
        assert framework_name in response_after.json()["frameworks"]

    def test_start_refinement_denied_when_framework_not_assigned(
        self,
        regular_user_token,
        framework_name,
    ):
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {regular_user_token}"}

        response = client.post(
            "/api/v1/refinement/start",
            json={
                "original_query": "effects of aspirin on stroke prevention",
                "framework_name": framework_name,
            },
            headers=headers,
        )

        assert response.status_code == 403
        assert "not authorized to use framework" in response.json()["detail"]

    def test_start_refinement_denied_when_workflow_limit_enabled_and_completed(
        self,
        db,
        regular_user,
        regular_user_token,
        framework_name,
        monkeypatch,
    ):
        monkeypatch.setenv("ENFORCE_WORKFLOW_LIMIT", "true")
        get_settings.cache_clear()

        try:
            assign_user_framework_access(db, regular_user.id, framework_name)
            regular_user.has_completed_workflow = True
            db.commit()

            client = TestClient(app)
            headers = {"Authorization": f"Bearer {regular_user_token}"}
            response = client.post(
                "/api/v1/refinement/start",
                json={
                    "original_query": "effects of aspirin on stroke prevention",
                    "framework_name": framework_name,
                },
                headers=headers,
            )

            assert response.status_code == 403
            assert "already completed one refinement workflow" in response.json()["detail"]
        finally:
            get_settings.cache_clear()

    def test_user_status_allows_new_workflow_when_limit_disabled(
        self,
        db,
        regular_user,
        regular_user_token,
        monkeypatch,
    ):
        monkeypatch.setenv("ENFORCE_WORKFLOW_LIMIT", "false")
        get_settings.cache_clear()

        try:
            regular_user.has_completed_workflow = True
            db.commit()

            client = TestClient(app)
            headers = {"Authorization": f"Bearer {regular_user_token}"}
            response = client.get("/api/v1/auth/me/status", headers=headers)

            assert response.status_code == 200
            payload = response.json()
            assert payload["has_completed_workflow"] is True
            assert payload["can_start_new_workflow"] is True
        finally:
            get_settings.cache_clear()

    def test_integration_api_key_creates_service_user_and_filters_frameworks(
        self,
        db,
        framework_name,
        monkeypatch,
    ):
        monkeypatch.setattr(api_auth.settings, "integration_api_key", "integration-test-key")

        client = TestClient(app)
        headers = {"X-API-Key": "integration-test-key"}

        response_before = client.get("/api/v1/refinement/frameworks", headers=headers)
        assert response_before.status_code == 200
        assert framework_name not in response_before.json()["frameworks"]

        integration_user = get_user_by_username(db, api_auth.settings.integration_service_username)
        assert integration_user is not None

        assign_user_framework_access(db, integration_user.id, framework_name)

        response_after = client.get("/api/v1/refinement/frameworks", headers=headers)
        assert response_after.status_code == 200
        assert framework_name in response_after.json()["frameworks"]

    def test_integration_api_key_cannot_start_unassigned_framework(
        self,
        db,
        framework_name,
        monkeypatch,
    ):
        monkeypatch.setattr(api_auth.settings, "integration_api_key", "integration-test-key")

        client = TestClient(app)
        headers = {"X-API-Key": "integration-test-key"}

        response = client.post(
            "/api/v1/refinement/start",
            json={
                "original_query": "effects of aspirin on stroke prevention",
                "framework_name": framework_name,
                "source": "api_integration",
            },
            headers=headers,
        )

        assert response.status_code == 403
        assert "not authorized to use framework" in response.json()["detail"]
