"""Tests for schema registry and framework loading."""

import tempfile
import textwrap
import os

import pytest

from query_refinement_module.schema.registry import (
    _load_frameworks,
    get_framework,
    list_frameworks,
    reload_from_env,
    get_last_load_error,
    FrameworkLoadError,
)
from query_refinement_module.schema.models import RefinementAspect


@pytest.fixture
def sample_framework_yaml() -> str:
    return textwrap.dedent(
        """
        test_framework:
          - id: aspect_one
            name: "First Aspect"
            description: "Description of first aspect"
            specifications: "Check this and that"
          - id: aspect_two
            name: "Second Aspect"
            description: "Description of second aspect"
            specifications: "Simple criteria"
            depends_on:
              - aspect_one
        """
    )


@pytest.fixture
def legacy_framework_yaml() -> str:
    return textwrap.dedent(
        """
        legacy_framework:
          - id: legacy_aspect
            name: "Legacy Aspect"
            description: "Uses old field names"
            specifications: "Old style evaluation instructions"
        """
    )


@pytest.fixture
def temp_framework_file(sample_framework_yaml):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(sample_framework_yaml)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def temp_legacy_file(legacy_framework_yaml):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(legacy_framework_yaml)
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestFrameworkLoading:
    def test_load_framework(self, temp_framework_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)

        frameworks = _load_frameworks(raise_on_error=True)
        assert "test_framework" in frameworks
        aspects = frameworks["test_framework"]
        assert len(aspects) == 2

        aspect_one = aspects[0]
        assert aspect_one.id == "aspect_one"
        assert aspect_one.name == "First Aspect"

    def test_load_legacy_framework(self, temp_legacy_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_legacy_file)

        frameworks = _load_frameworks(raise_on_error=True)
        assert "legacy_framework" in frameworks
        aspects = frameworks["legacy_framework"]
        assert len(aspects) == 1
        assert aspects[0].specifications == "Old style evaluation instructions"

    def test_dependencies_preserved(self, temp_framework_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)

        frameworks = _load_frameworks(raise_on_error=True)
        aspect_two = frameworks["test_framework"][1]
        assert "aspect_one" in aspect_two.depends_on

    def test_missing_env_var(self, monkeypatch):
        monkeypatch.delenv("REFINEMENT_FRAMEWORK_PATH", raising=False)
        frameworks = _load_frameworks(raise_on_error=False)
        assert frameworks == {}
        assert "not set" in (get_last_load_error() or "")

    def test_missing_file_raises(self, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", "/nonexistent/path.yaml")
        with pytest.raises(FrameworkLoadError):
            _load_frameworks(raise_on_error=True)


class TestRegistryFunctions:
    def test_list_frameworks(self, temp_framework_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        frameworks = list_frameworks()
        assert "test_framework" in frameworks

    def test_get_framework(self, temp_framework_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        aspects = get_framework("test_framework")
        assert len(aspects) == 2
        assert all(isinstance(a, RefinementAspect) for a in aspects)

    def test_get_framework_not_found(self, temp_framework_file, monkeypatch):
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        with pytest.raises(KeyError):
            get_framework("nonexistent")


# ── Thread-safety (ISSUE-14) ───────────────────────────────────────────────────

import threading


def test_reload_from_env_is_thread_safe(temp_framework_file, monkeypatch):
    """Concurrent reload_from_env calls must not corrupt _FRAMEWORKS."""
    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
    errors = []

    def worker():
        try:
            reload_from_env()
            frameworks = list_frameworks()
            assert "test_framework" in frameworks
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
