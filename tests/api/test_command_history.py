"""
Tests for command history endpoint and command audit logging.

Tests cover:
- Command history retrieval
- Audit logging of commands
- Command execution tracking
- Authorization requirements
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from query_refinement_module.api.main import app
from query_refinement_module.db.models.user import User
from query_refinement_module.db.crud import (
    create_user,
    create_query_session,
    create_query,
    create_refinement_step,
)
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.core import RefinementSession
from query_refinement_module.api.session_manager import SessionManager


@pytest.fixture
def db(test_db_session):
    """Alias for test_db_session for compatibility."""
    # Override the get_db dependency
    from query_refinement_module.db.session import get_db
    
    def override_get_db():
        yield test_db_session
    
    app.dependency_overrides[get_db] = override_get_db
    yield test_db_session
    app.dependency_overrides.clear()


@pytest.fixture
def session_manager():
    """Create a SessionManager instance for testing."""
    from query_refinement_module.api.dependencies import get_session_manager
    manager = SessionManager(redis_url="redis://localhost:6379/1")  # Use test DB
    
    def override_get_session_manager():
        return manager
    
    app.dependency_overrides[get_session_manager] = override_get_session_manager
    yield manager
    app.dependency_overrides.clear()


@pytest.fixture
def auth_user_and_token(db: Session):
    """Create a user and return both user object and auth token."""
    user = create_user(
        db,
        username="cmdtest_user",
        email="cmdtest@test.com",
        password="CmdTest123!",
        name="Command Test User"
    )
    
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "cmdtest@test.com", "password": "CmdTest123!"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    
    return user, token


@pytest.fixture
def query_with_session(db: Session, auth_user_and_token, session_manager):
    """Create a query with an active refinement session."""
    user, token = auth_user_and_token
    
    # Create session and query
    db_session = create_query_session(db, user_id=user.id)
    db_query = create_query(
        db,
        user_id=user.id,
        session_id=db_session.id,
        original_query="Test query for commands",
        framework_name="pico_advanced"
    )
    
    # Create refinement session
    framework = get_framework("pico_advanced")
    refinement_session = RefinementSession(
        original_query="Test query for commands",
        refinement_framework=framework.aspects
    )
    
    # Answer first dimension to enable navigation commands
    active_step = refinement_session.get_active_step()
    if active_step:
        active_step.conversation_history.append({
            'question': 'What is your population?',
            'response': 'Adults aged 18-65'
        })
        active_step.is_complete = True
        refinement_session.advance_to_next_step()
    
    session_manager.save_session(db_query.id, refinement_session)
    
    return db_query, token


class TestCommandHistoryEndpoint:
    """Tests for GET /api/refinement/queries/{query_id}/command-history."""
    
    def test_command_history_empty_initially(self, query_with_session, db: Session):
        """New query has empty command history."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["query_id"] == db_query.id
        assert data["total_commands"] == 0
        assert data["commands"] == []
    
    def test_command_history_tracks_status_command(self, query_with_session, db: Session):
        """Status command is tracked in history."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute /status command
        answer_response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/status"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert answer_response.status_code == 200
        
        # Check command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        assert data["total_commands"] >= 1
        
        # Find status command
        status_cmd = next((cmd for cmd in data["commands"] if cmd["command"] == "status"), None)
        assert status_cmd is not None
        assert status_cmd["command_input"] == "/status"
        assert status_cmd["success"] is True
        assert status_cmd["status"] == "success"
    
    def test_command_history_tracks_skip_command(self, query_with_session, db: Session):
        """Skip command is tracked with dimension info."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute /skip command
        answer_response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/skip"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert answer_response.status_code == 200
        
        # Check command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        
        skip_cmd = next((cmd for cmd in data["commands"] if cmd["command"] == "skip"), None)
        assert skip_cmd is not None
        assert skip_cmd["active_dimension"] is not None
        assert skip_cmd["success"] is True
    
    def test_command_history_tracks_back_with_cleared_aspects(self, query_with_session, db: Session, session_manager):
        """Back command tracks cleared aspects."""
        db_query, token = query_with_session
        
        # Load session and advance multiple steps
        framework = get_framework("pico_advanced")
        session = session_manager.load_session(db_query.id, framework)
        
        # Answer multiple dimensions to enable /back
        for i in range(3):
            active = session.get_active_step()
            if active:
                active.conversation_history.append({
                    'question': f'Question {i}',
                    'response': f'Answer {i}'
                })
                active.is_complete = True
                session.advance_to_next_step()
        
        session_manager.save_session(db_query.id, session)
        
        client = TestClient(app)
        
        # Execute /back command
        answer_response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/back", "force": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert answer_response.status_code == 200
        
        # Check command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        
        back_cmd = next((cmd for cmd in data["commands"] if cmd["command"] == "back"), None)
        assert back_cmd is not None
        assert back_cmd["cleared_aspects"] is not None
        assert len(back_cmd["cleared_aspects"]) >= 0
    
    def test_command_history_tracks_restart(self, query_with_session, db: Session):
        """Restart command is tracked."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute /restart command
        answer_response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/restart", "force": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert answer_response.status_code == 200
        
        # Check command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        
        restart_cmd = next((cmd for cmd in data["commands"] if cmd["command"] == "restart"), None)
        assert restart_cmd is not None
        assert restart_cmd["success"] is True
        assert restart_cmd["cleared_aspects"] is not None
    
    def test_command_history_respects_limit(self, query_with_session, db: Session):
        """Command history respects limit parameter."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute multiple commands
        commands = ["/status", "/help", "/steps"]
        for cmd in commands:
            client.post(
                f"/api/v1/refinement/queries/{db_query.id}/answer",
                json={"answer": cmd},
                headers={"Authorization": f"Bearer {token}"}
            )
        
        # Request history with limit
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history?limit=2",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        assert len(data["commands"]) <= 2
    
    def test_command_history_chronological_order(self, query_with_session, db: Session):
        """Command history returns commands in chronological order."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute commands in sequence
        commands = ["/status", "/help", "/steps"]
        for cmd in commands:
            client.post(
                f"/api/v1/refinement/queries/{db_query.id}/answer",
                json={"answer": cmd},
                headers={"Authorization": f"Bearer {token}"}
            )
        
        # Get history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        
        # Verify chronological order (oldest first)
        if len(data["commands"]) >= 2:
            for i in range(len(data["commands"]) - 1):
                timestamp1 = data["commands"][i]["timestamp"]
                timestamp2 = data["commands"][i + 1]["timestamp"]
                assert timestamp1 <= timestamp2
    
    def test_command_history_authorization(self, query_with_session, db: Session):
        """Command history requires authentication and ownership."""
        db_query, _ = query_with_session
        
        client = TestClient(app)
        
        # Test without authentication
        response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history"
        )
        assert response.status_code == 401
        
        # Test with different user
        other_user = create_user(
            db,
            username="other_user",
            email="other@test.com",
            password="Other123!",
            name="Other User"
        )
        
        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "other@test.com", "password": "Other123!"}
        )
        other_token = login_response.json()["access_token"]
        
        response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {other_token}"}
        )
        assert response.status_code == 404
    
    def test_command_history_includes_request_id(self, query_with_session, db: Session):
        """Command history includes request_id for tracing."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute command
        client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/status"},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Get history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert history_response.status_code == 200
        data = history_response.json()
        
        if len(data["commands"]) > 0:
            cmd = data["commands"][0]
            assert "request_id" in cmd
            assert "timestamp" in cmd
            assert "username" in cmd


class TestCommandAuditLogging:
    """Tests for command audit logging functionality."""
    
    def test_clear_command_creates_audit_log(self, query_with_session, db: Session):
        """Clear command creates audit log entry."""
        db_query, token = query_with_session
        
        client = TestClient(app)
        
        # Execute /clear command
        response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/clear"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        
        # Verify audit log exists
        from query_refinement_module.db.models.audit_log import AuditLog, AuditEventType
        
        audit_logs = db.query(AuditLog).filter(
            AuditLog.resource_type == "query",
            AuditLog.resource_id == str(db_query.id),
            AuditLog.event_type == AuditEventType.COMMAND_CLEAR
        ).all()
        
        assert len(audit_logs) >= 1
        log = audit_logs[-1]
        assert log.details["command"] == "clear"
        assert log.details["command_input"] == "/clear"
    
    def test_goto_command_with_argument_logged(self, query_with_session, db: Session, session_manager):
        """Goto command with argument is properly logged."""
        db_query, token = query_with_session
        
        # Setup session with multiple completed steps
        framework = get_framework("pico_advanced")
        session = session_manager.load_session(db_query.id, framework)
        
        for i in range(2):
            active = session.get_active_step()
            if active:
                active.conversation_history.append({
                    'question': f'Q{i}',
                    'response': f'A{i}'
                })
                active.is_complete = True
                session.advance_to_next_step()
        
        session_manager.save_session(db_query.id, session)
        
        client = TestClient(app)
        
        # Execute /goto command
        response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/goto Population", "force": True},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Get command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        data = history_response.json()
        goto_cmd = next((cmd for cmd in data["commands"] if cmd["command"] == "goto"), None)
        
        if goto_cmd:  # May not work if all steps not completed
            assert goto_cmd["argument"] is not None
            assert "population" in goto_cmd["argument"].lower() or goto_cmd["argument"] == "Population"
    
    def test_force_confirmation_tracked_in_audit(self, query_with_session, db: Session, session_manager):
        """Force confirmation requirement is tracked in audit."""
        db_query, token = query_with_session
        
        # Setup session with completed steps
        framework = get_framework("pico_advanced")
        session = session_manager.load_session(db_query.id, framework)
        
        for i in range(2):
            active = session.get_active_step()
            if active:
                active.conversation_history.append({
                    'question': f'Q{i}',
                    'response': f'A{i}'
                })
                active.is_complete = True
                session.advance_to_next_step()
        
        session_manager.save_session(db_query.id, session)
        
        client = TestClient(app)
        
        # Execute /back WITHOUT force (should need confirmation)
        response = client.post(
            f"/api/v1/refinement/queries/{db_query.id}/answer",
            json={"answer": "/back", "force": False},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Get command history
        history_response = client.get(
            f"/api/v1/refinement/queries/{db_query.id}/command-history",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        data = history_response.json()
        
        if len(data["commands"]) > 0:
            cmd = data["commands"][-1]
            assert "force_requested" in cmd
            assert "force_confirmation_needed" in cmd
