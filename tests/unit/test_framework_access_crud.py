from query_refinement_module.db.crud import (
    create_user,
    assign_user_framework_access,
    revoke_user_framework_access,
    get_user_framework_names,
    user_has_framework_access,
)


def test_assign_user_framework_access_is_idempotent(test_db_session):
    user = create_user(
        test_db_session,
        username="framework_user",
        email="framework_user@example.com",
        password="FrameworkPass123!",
        name="Framework User",
    )

    first = assign_user_framework_access(test_db_session, user.id, "pico_advanced")
    second = assign_user_framework_access(test_db_session, user.id, "pico_advanced")

    assert first.id == second.id
    assert get_user_framework_names(test_db_session, user.id) == ["pico_advanced"]


def test_user_framework_access_check_and_revoke(test_db_session):
    user = create_user(
        test_db_session,
        username="framework_user_2",
        email="framework_user_2@example.com",
        password="FrameworkPass123!",
        name="Framework User 2",
    )

    assert user_has_framework_access(test_db_session, user.id, "pico_advanced") is False

    assign_user_framework_access(test_db_session, user.id, "pico_advanced")
    assert user_has_framework_access(test_db_session, user.id, "pico_advanced") is True

    revoked = revoke_user_framework_access(test_db_session, user.id, "pico_advanced")
    assert revoked is True
    assert user_has_framework_access(test_db_session, user.id, "pico_advanced") is False

    revoked_again = revoke_user_framework_access(test_db_session, user.id, "pico_advanced")
    assert revoked_again is False
