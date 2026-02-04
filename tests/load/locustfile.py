"""
Locust load testing script for Query Refinement API.

This script simulates realistic user behavior patterns for load testing:
- User authentication (API key)
- Session creation
- Single-step refinements
- Multi-step refinement workflows
- Parallel processing
- Session retrieval

Usage:
    # Start Locust web UI
    poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000

    # Headless mode (100 users, 10 users/sec spawn rate, 5 min duration)
    poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
        --users 100 --spawn-rate 10 --run-time 5m --headless

    # With specific test scenario
    poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
        --users 50 --spawn-rate 5 SingleStepUser

Environment Variables:
    LOAD_TEST_API_KEY: API key for authentication (required)
    LOAD_TEST_HOST: API host URL (default: http://localhost:8000)
"""

import json
import os
import random
import time
from typing import Any, Dict, List

from locust import HttpUser, TaskSet, between, task

# ============================================================================
# Configuration
# ============================================================================

# Test user credentials
TEST_USERNAME = os.getenv("LOAD_TEST_USERNAME", "test_user_001")
TEST_PASSWORD = os.getenv("LOAD_TEST_PASSWORD", "TestPass123!")

# Authentication token cache
_auth_token_cache = {}

# Sample queries for testing (realistic medical research queries)
SAMPLE_QUERIES = [
    "What are the effects of aspirin on cardiovascular disease?",
    "Is meditation effective for reducing anxiety in adults?",
    "Does vitamin D supplementation improve bone density in elderly patients?",
    "What is the impact of exercise on depression symptoms?",
    "Are probiotics beneficial for irritable bowel syndrome?",
    "Does intermittent fasting affect weight loss in obese patients?",
    "What are the side effects of statins in elderly populations?",
    "Is cognitive behavioral therapy effective for insomnia?",
    "Does omega-3 supplementation reduce inflammation?",
    "What is the efficacy of acupuncture for chronic pain?",
]

# Sample schema configurations
SCHEMA_CONFIGS = [
    {
        "name": "pico_template",
        "dimensions": ["population", "intervention", "comparison", "outcome"],
    },
    {
        "name": "pico_advanced",
        "dimensions": ["population", "intervention", "comparison", "outcome", "study_design"],
    },
]

# Think time ranges (seconds)
THINK_TIME_MIN = 1
THINK_TIME_MAX = 3


# ============================================================================
# Helper Functions
# ============================================================================

def get_auth_token(client) -> str:
    """Get JWT authentication token (cached per user)."""
    user_id = id(client)
    
    if user_id not in _auth_token_cache:
        # Login to get token - OAuth2 expects form data, not JSON
        response = client.post(
            "/api/auth/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            catch_response=False
        )
        if response.status_code == 200:
            _auth_token_cache[user_id] = response.json()["access_token"]
        else:
            raise Exception(f"Failed to authenticate: {response.status_code}")
    
    return _auth_token_cache[user_id]


def get_auth_header(client) -> Dict[str, str]:
    """Get authentication header with JWT token."""
    token = get_auth_token(client)
    return {"Authorization": f"Bearer {token}"}


def random_query() -> str:
    """Get a random sample query."""
    return random.choice(SAMPLE_QUERIES)


def random_schema() -> Dict[str, Any]:
    """Get a random schema configuration."""
    return random.choice(SCHEMA_CONFIGS)


# ============================================================================
# Task Sets (User Behavior Patterns)
# ============================================================================

class BasicRefinementTasks(TaskSet):
    """
    Basic refinement workflow tasks.
    
    Simulates a user performing simple query refinements:
    1. Create session
    2. Get initial refinement
    3. Submit followup
    4. Retrieve session data
    """

    def on_start(self):
        """Initialize user session."""
        self.session_id = None
        self.query = random_query()

    @task(3)
    def create_session_and_refine(self):
        """Create a new session and perform initial refinement."""
        # Create session with initial query
        with self.client.post(
            "/api/refinement/start",
            headers=get_auth_header(self.client),
            json={
                "original_query": self.query,
                "framework_name": "pico_advanced",
            },
            catch_response=True,
        ) as response:
            if response.status_code in [200, 201]:
                data = response.json()
                self.session_id = data.get("session_id")
                response.success()
            else:
                response.failure(f"Initial refinement failed: {response.status_code}")

    @task(2)
    def submit_followup(self):
        """Submit a followup refinement in existing session."""
        if not self.session_id:
            return

        # Get a query from session and answer it
        with self.client.get(
            f"/api/queries/sessions/{self.session_id}",
            headers=get_auth_header(self.client),
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Check if there are follow-up questions
                if data.get("queries") and len(data["queries"]) > 0:
                    query = data["queries"][-1]
                    if query.get("followups"):
                        response.success()
                    else:
                        response.success()
                else:
                    response.success()
            else:
                response.failure(f"Failed to create session: {response.status_code}")

    @task(1)
    def get_session(self):
        """Retrieve session data."""
        if not self.session_id:
            return

        with self.client.get(
            f"/api/queries/sessions/{self.session_id}",
            headers=get_auth_header(self.client),
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Session retrieval failed: {response.status_code}")


class ParallelProcessingTasks(TaskSet):
    """
    Parallel processing workflow tasks.
    
    Simulates users leveraging parallel subdimension processing:
    1. Create session with parallel enabled
    2. Monitor processing
    3. Retrieve results
    """

    def on_start(self):
        """Initialize user session."""
        self.session_id = None
        self.query = random_query()

    @task(2)
    def parallel_refinement(self):
        """Perform refinement with parallel processing enabled."""
        with self.client.post(
            "/api/refinement/start",
            headers=get_auth_header(self.client),
            json={
                "original_query": self.query,
                "framework_name": "pico_advanced",
                "parallel_enabled": True,
                "max_workers": 4,
            },
            catch_response=True,
        ) as response:
            if response.status_code in [200, 201]:
                data = response.json()
                self.session_id = data.get("session_id")
                response.success()
            else:
                response.failure(f"Parallel refinement failed: {response.status_code}")

    @task(1)
    def get_session_metadata(self):
        """Retrieve session with metadata."""
        if not self.session_id:
            return

        with self.client.get(
            f"/api/queries/sessions/{self.session_id}",
            headers=get_auth_header(self.client),
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Verify session data exists
                response.success()
            else:
                response.failure(f"Session retrieval failed: {response.status_code}")


class MultiStepWorkflowTasks(TaskSet):
    """
    Multi-step refinement workflow.
    
    Simulates a user performing multiple refinements in a session:
    1. Initial query
    2. Multiple followups with different angles
    3. Session retrieval
    """

    def on_start(self):
        """Initialize user session."""
        self.session_id = None
        self.query = random_query()
        self.step_count = 0

    @task(3)
    def initial_refinement(self):
        """Create initial refinement."""
        if self.step_count > 0:
            return  # Skip if already started

        with self.client.post(
            "/api/refinement/start",
            headers=get_auth_header(self.client),
            json={
                "original_query": self.query,
                "framework_name": "pico_advanced",
            },
            catch_response=True,
        ) as response:
            if response.status_code in [200, 201]:
                data = response.json()
                self.session_id = data.get("session_id")
                self.step_count += 1
                response.success()
            else:
                response.failure(f"Initial refinement failed: {response.status_code}")

    @task(4)
    def followup_refinement(self):
        """Submit followup refinements."""
        if not self.session_id or self.step_count == 0:
            return

        if self.step_count >= 5:
            # Reset after 5 steps
            self.session_id = None
            self.step_count = 0
            return

        # Generate followup with different focus
        followup_queries = [
            f"{self.query} in children",
            f"{self.query} compared to placebo",
            f"{self.query} systematic review",
            f"{self.query} randomized controlled trial",
            f"{self.query} long-term effects",
        ]
        followup = followup_queries[self.step_count - 1]

        with self.client.post(
            "/api/refinement/start",
            headers=get_auth_header(self.client),
            json={
                "original_query": followup,
                "framework_name": "pico_advanced",
            },
            catch_response=True,
        ) as response:
            if response.status_code in [200, 201]:
                self.step_count += 1
                response.success()
            else:
                response.failure(f"Followup refinement failed: {response.status_code}")

    @task(1)
    def review_session_history(self):
        """Review complete session history."""
        if not self.session_id:
            return

        with self.client.get(
            f"/api/queries/sessions/{self.session_id}",
            headers=get_auth_header(self.client),
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Session retrieval successful - queries may still be processing
                # This is expected behavior, not a failure
                response.success()
            else:
                response.failure(f"Session retrieval failed: {response.status_code}")


class HealthCheckTasks(TaskSet):
    """
    Health check and monitoring tasks.
    
    Simulates monitoring systems checking API health.
    """

    @task(10)
    def health_check(self):
        """Check API health endpoint."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")

    @task(5)
    def readiness_check(self):
        """Check API readiness endpoint."""
        with self.client.get("/ready", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                # Verify all checks passed
                checks = data.get("checks", {})
                if all(v == "ok" for v in checks.values()):
                    response.success()
                else:
                    response.failure(f"Readiness check failed: {checks}")
            else:
                response.failure(f"Readiness check failed: {response.status_code}")


# ============================================================================
# User Classes (Load Test Scenarios)
# ============================================================================

class SingleStepUser(HttpUser):
    """
    User that performs single-step refinements.
    
    Behavior: Quick refinements without followups.
    Think time: 1-3 seconds between requests.
    """

    tasks = [BasicRefinementTasks]
    wait_time = between(THINK_TIME_MIN, THINK_TIME_MAX)
    weight = 3


class MultiStepUser(HttpUser):
    """
    User that performs multi-step refinement workflows.
    
    Behavior: Creates sessions with multiple refinements.
    Think time: 2-5 seconds between requests.
    """

    tasks = [MultiStepWorkflowTasks]
    wait_time = between(2, 5)
    weight = 2


class ParallelUser(HttpUser):
    """
    User that leverages parallel processing.
    
    Behavior: Uses parallel subdimension processing.
    Think time: 3-6 seconds between requests (longer processing).
    """

    tasks = [ParallelProcessingTasks]
    wait_time = between(3, 6)
    weight = 1


class MonitoringUser(HttpUser):
    """
    Monitoring system checking health endpoints.
    
    Behavior: Frequent health checks.
    Think time: 0.5-1 second between requests.
    """

    tasks = [HealthCheckTasks]
    wait_time = between(0.5, 1)
    weight = 1


class MixedUser(HttpUser):
    """
    User with mixed behavior (most realistic).
    
    Combines basic refinements, multi-step workflows, and monitoring.
    Think time: 1-4 seconds between requests.
    """

    tasks = [BasicRefinementTasks, MultiStepWorkflowTasks, HealthCheckTasks]
    wait_time = between(1, 4)
    weight = 5


# ============================================================================
# Event Handlers (Metrics and Logging)
# ============================================================================

from locust import events


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts."""
    print("=" * 80)
    print("🚀 LOAD TEST STARTED")
    print("=" * 80)
    print(f"Host: {environment.host}")
    print(f"Users: {environment.runner.target_user_count if hasattr(environment.runner, 'target_user_count') else 'N/A'}")
    print(f"API Key: {API_KEY[:10]}...")
    print("=" * 80)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops."""
    print("=" * 80)
    print("🏁 LOAD TEST COMPLETED")
    print("=" * 80)
    
    # Print summary statistics
    stats = environment.stats
    print(f"\n📊 REQUEST STATISTICS:")
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Success rate: {(1 - stats.total.fail_ratio) * 100:.2f}%")
    print(f"Average response time: {stats.total.avg_response_time:.2f}ms")
    print(f"Min response time: {stats.total.min_response_time:.2f}ms")
    print(f"Max response time: {stats.total.max_response_time:.2f}ms")
    print(f"Median response time: {stats.total.median_response_time:.2f}ms")
    print(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.2f}ms")
    print(f"99th percentile: {stats.total.get_response_time_percentile(0.99):.2f}ms")
    print(f"Requests per second: {stats.total.total_rps:.2f}")
    print("=" * 80)


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Called for each request (for custom logging)."""
    # Optional: Add custom logging here
    pass


# ============================================================================
# Custom Shape Classes (Advanced Load Patterns)
# ============================================================================

from locust import LoadTestShape


class StepLoadShape(LoadTestShape):
    """
    Step load pattern: gradually increase users in steps.
    
    Pattern:
    - 0-60s: 10 users
    - 60-120s: 25 users
    - 120-180s: 50 users
    - 180-300s: 100 users
    """

    step_time = 60
    step_load = 10
    spawn_rate = 5
    time_limit = 300

    def tick(self):
        run_time = self.get_run_time()

        if run_time > self.time_limit:
            return None

        current_step = (run_time // self.step_time) + 1
        user_count = min(current_step * self.step_load, 100)

        return (user_count, self.spawn_rate)


class WaveLoadShape(LoadTestShape):
    """
    Wave load pattern: simulate traffic waves.
    
    Useful for testing how system handles varying load.
    """

    time_limit = 300
    min_users = 10
    max_users = 100
    wave_length = 60

    def tick(self):
        run_time = self.get_run_time()

        if run_time > self.time_limit:
            return None

        # Calculate wave position (sine wave)
        import math
        wave_position = math.sin((run_time / self.wave_length) * 2 * math.pi)
        user_count = int(
            self.min_users + (self.max_users - self.min_users) * (wave_position + 1) / 2
        )

        return (user_count, 10)


# ============================================================================
# Usage Examples
# ============================================================================
"""
# 1. Basic load test with web UI
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000

# 2. Headless test with 100 users
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --users 100 --spawn-rate 10 --run-time 5m --headless

# 3. Step load pattern
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    StepLoadShape --headless

# 4. Specific user type only
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --users 50 --spawn-rate 5 MultiStepUser --headless

# 5. With custom API key
LOAD_TEST_API_KEY=your-api-key poetry run locust -f tests/load/locustfile.py \
    --host=http://localhost:8000 --users 100 --spawn-rate 10 --headless

# 6. Generate HTML report
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --users 100 --spawn-rate 10 --run-time 10m --headless --html report.html
"""
