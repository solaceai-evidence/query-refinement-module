import json
import time
import traceback

import requests

from query_refinement_module.db.crud import assign_user_framework_access, create_user
from query_refinement_module.db.session import get_db_session
from query_refinement_module.schema.registry import list_frameworks


def main() -> int:
    base_url = "http://localhost:8000/api/v1"
    uid = int(time.time() * 1000)
    frameworks = list_frameworks()
    framework = "mph_dissertation" if "mph_dissertation" in frameworks else frameworks[0]
    email = f"replay_access_{uid}@example.com"
    password = "TestPass123!"

    try:
        with get_db_session() as db:
            user = create_user(
                db,
                username=f"replay_access_{uid}",
                email=email,
                password=password,
                name="Replay Access User",
            )
            assign_user_framework_access(db, user.id, framework)

        print("user_created", email, "framework", framework)

        response = requests.post(
            f"{base_url}/auth/login",
            data={"username": email, "password": password},
            timeout=20,
        )
        print("login_status", response.status_code)
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}

        query = "Im interested in studying barriers to implementing COPD management protocols"
        response = requests.post(
            f"{base_url}/refinement/start",
            json={"original_query": query, "framework_name": framework},
            headers=headers,
            timeout=60,
        )
        print("start_status", response.status_code)
        response.raise_for_status()
        query_id = response.json()["query_id"]
        print("query_id", query_id)

        found_population = False
        for step_num in range(22):
            status_response = requests.get(
                f"{base_url}/refinement/queries/{query_id}/status",
                headers=headers,
                timeout=30,
            )
            status_response.raise_for_status()
            aspect = (status_response.json().get("current_aspect") or "").strip()
            print("aspect", step_num, repr(aspect))
            if aspect.lower() == "population":
                found_population = True
                break

            advance_response = requests.post(
                f"{base_url}/refinement/queries/{query_id}/answer",
                json={"answer": "/done"},
                headers=headers,
                timeout=60,
            )
            advance_response.raise_for_status()

        if not found_population:
            raise RuntimeError("did not reach Population")

        partial_response = requests.post(
            f"{base_url}/refinement/queries/{query_id}/answer",
            json={"answer": "adults with COPD"},
            headers=headers,
            timeout=90,
        )
        print("partial_status", partial_response.status_code)
        print("partial_body", partial_response.text[:300])
        partial_response.raise_for_status()

        done_response = requests.post(
            f"{base_url}/refinement/queries/{query_id}/answer",
            json={"answer": "/done"},
            headers=headers,
            timeout=60,
        )
        print("done_status", done_response.status_code)
        print("done_body", done_response.text[:300])
        done_response.raise_for_status()

        submit_response = requests.post(
            f"{base_url}/refinement/queries/{query_id}/answer",
            json={"answer": "/submit"},
            headers=headers,
            timeout=60,
        )
        print("submit_status", submit_response.status_code)
        submit_response.raise_for_status()

        synth_response = requests.post(
            f"{base_url}/refinement/synthesize",
            json={"query_id": query_id},
            headers=headers,
            timeout=120,
        )
        print("synth_status", synth_response.status_code)
        synth_response.raise_for_status()

        data = synth_response.json()
        structured_output = data.get("structured_output") or {}
        population = (structured_output.get("dimensions_specifications") or {}).get("population")
        print("population", json.dumps(population))

        if population in (None, "", "[SKIPPED]"):
            raise AssertionError("population missing")

        print("PASS")
        return 0
    except Exception as exc:
        print("ERROR", type(exc).__name__, str(exc))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
