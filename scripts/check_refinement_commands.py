import time

import requests


BASE_URL = "http://localhost:8001/api/v1"


def register_and_login() -> str:
    ts = int(time.time() * 1000)
    username = f"command_check_{ts}"
    password = "TestPass123!"

    reg = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "name": f"Command Check {ts}",
        },
        timeout=20,
    )

    if reg.status_code == 403:
        raise RuntimeError("Registration disabled on this server; cannot run this automated check.")
    reg.raise_for_status()

    login = requests.post(
        f"{BASE_URL}/auth/login",
        data={"username": username, "password": password},
        timeout=20,
    )
    login.raise_for_status()
    return login.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def start_session(token: str) -> tuple[int, dict]:
    resp = requests.post(
        f"{BASE_URL}/refinement/start",
        headers=auth_headers(token),
        json={
            "framework_name": "mph_dissertation",
            "original_query": "I want to study childhood obesity in urban low-income communities",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    prompt = data.get("next_prompt")
    if not prompt or not prompt.get("question"):
        raise RuntimeError("No initial prompt returned from /refinement/start")
    return data["query_id"], prompt


def send_command(token: str, query_id: int, command: str, force: bool = False) -> dict:
    resp = requests.post(
        f"{BASE_URL}/refinement/queries/{query_id}/answer",
        headers=auth_headers(token),
        json={"answer": command, "force": force},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def check_info_command(token: str, command: str) -> tuple[bool, str]:
    query_id, initial = start_session(token)
    data = send_command(token, query_id, command)

    next_prompt = data.get("next_prompt")
    if not data.get("success"):
        return False, f"{command}: expected success=True, got success={data.get('success')}"
    if not next_prompt or not next_prompt.get("question"):
        return False, f"{command}: missing next_prompt/question"
    if next_prompt.get("aspect_id") != initial.get("aspect_id"):
        return False, f"{command}: aspect changed unexpectedly ({initial.get('aspect_id')} -> {next_prompt.get('aspect_id')})"
    if next_prompt.get("question") != initial.get("question"):
        return False, f"{command}: question text changed unexpectedly"
    return True, f"{command}: preserved active question/context"


def check_back_on_first_step(token: str) -> tuple[bool, str]:
    query_id, initial = start_session(token)
    data = send_command(token, query_id, "/back")
    next_prompt = data.get("next_prompt")

    if data.get("success") is not False:
        return False, "/back(first step): expected graceful failure (success=False)"
    if not next_prompt or not next_prompt.get("question"):
        return False, "/back(first step): missing preserved next_prompt"
    if next_prompt.get("aspect_id") != initial.get("aspect_id"):
        return False, "/back(first step): active aspect changed unexpectedly"
    return True, "/back(first step): fails gracefully and preserves active question"


def check_clear(token: str) -> tuple[bool, str]:
    query_id, initial = start_session(token)
    data = send_command(token, query_id, "/clear")
    next_prompt = data.get("next_prompt")

    if not data.get("success"):
        return False, "/clear: expected success=True"
    if not next_prompt or not next_prompt.get("question"):
        return False, "/clear: expected regenerated question"
    if next_prompt.get("aspect_id") != initial.get("aspect_id"):
        return False, "/clear: expected to stay on same aspect"
    return True, "/clear: regenerates question on same aspect"


def check_advancing_command(token: str, command: str) -> tuple[bool, str]:
    query_id, initial = start_session(token)
    data = send_command(token, query_id, command)

    if not data.get("success"):
        return False, f"{command}: expected success=True"

    if data.get("synthesis_ready"):
        return True, f"{command}: valid (session became synthesis-ready)"

    next_prompt = data.get("next_prompt")
    if not next_prompt or not next_prompt.get("question"):
        return False, f"{command}: expected next_prompt with question or synthesis_ready"

    if next_prompt.get("aspect_id") == initial.get("aspect_id"):
        return False, f"{command}: expected workflow to advance to a different aspect"

    return True, f"{command}: advances workflow to next aspect"


def check_restart(token: str) -> tuple[bool, str]:
    query_id, _ = start_session(token)
    data = send_command(token, query_id, "/restart")

    if not data.get("success"):
        return False, "/restart: expected success=True"

    next_prompt = data.get("next_prompt")
    if not next_prompt or not next_prompt.get("question"):
        return False, "/restart: expected a valid next_prompt"

    return True, "/restart: resets flow and returns active question"


def check_submit(token: str) -> tuple[bool, str]:
    query_id, _ = start_session(token)
    data = send_command(token, query_id, "/submit")

    if not data.get("success"):
        return False, "/submit: expected success=True"
    if data.get("synthesis_ready") is not True:
        return False, "/submit: expected synthesis_ready=True"
    return True, "/submit: terminates flow and marks synthesis-ready"


def main() -> int:
    token = register_and_login()
    checks = []

    for cmd in ["/status", "/steps", "/help"]:
        checks.append(check_info_command(token, cmd))

    checks.append(check_back_on_first_step(token))
    checks.append(check_clear(token))
    checks.append(check_advancing_command(token, "/skip"))
    checks.append(check_advancing_command(token, "/done"))
    checks.append(check_restart(token))
    checks.append(check_submit(token))

    failures = [msg for ok, msg in checks if not ok]

    print("\nRefinement command behavior check")
    print("=" * 45)
    for ok, msg in checks:
        print(f"{'PASS' if ok else 'FAIL'}: {msg}")

    if failures:
        print("\nResult: FAILED")
        return 1

    print("\nResult: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())