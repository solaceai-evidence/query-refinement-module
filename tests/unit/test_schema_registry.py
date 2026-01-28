"""
Tests for schema registry and framework loading.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from query_refinement_module.schema.registry import (
    _load_frameworks,
    get_framework,
    list_frameworks,
    reload_from_env,
    get_last_load_error,
    FrameworkLoadError,
)
# Import from models (Pydantic) since registry now uses Pydantic models
from query_refinement_module.schema.models import RefinementAspect, RefinementDimension


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_framework_yaml():
    """Sample YAML content with new user_context structure."""
    return """
test_framework:
  - user_context:
    user_type: "Test User"
    context: "Testing context"
    tone: "professional"
    complexity: "intermediate"
    examples_from: "testing"
    constraints:
      - "Constraint 1"
      - "Constraint 2"
    pitfalls:
      - "Pitfall 1"
  - id: aspect_one
    aspect_name: "First Aspect"
    aspect_description: "Description of first aspect"
    evaluation_criteria: |
      ### Evaluation
      - Check this
      - Check that
    response_strategies: |
      - If unclear: "Ask for clarification"
    examples:
      clear:
        - statement: "Clear example"
          rationale: "This is clear because..."
  - id: aspect_two
    aspect_name: "Second Aspect"
    aspect_description: "Description of second aspect"
    evaluation_criteria: "Simple criteria"
    depends_on:
      - aspect_one
"""


@pytest.fixture
def legacy_framework_yaml():
    """Legacy YAML content without user_context."""
    return """
legacy_framework:
  - id: legacy_aspect
    aspect_name: "Legacy Aspect"
    aspect_description: "Uses old field names"
    evaluation_instructions: "Old style evaluation instructions"
"""


@pytest.fixture
def temp_framework_file(sample_framework_yaml):
    """Create a temporary YAML file with sample framework."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(sample_framework_yaml)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def temp_legacy_file(legacy_framework_yaml):
    """Create a temporary YAML file with legacy framework."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(legacy_framework_yaml)
        f.flush()
        yield f.name
    os.unlink(f.name)


# =============================================================================
# Tests: Framework Loading
# =============================================================================

class TestFrameworkLoading:
    """Tests for _load_frameworks and registry functions."""
    
    def test_load_framework_with_user_context(self, temp_framework_file, monkeypatch):
        """Test loading framework with new user_context structure."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        
        assert "test_framework" in frameworks
        aspects = frameworks["test_framework"]
        assert len(aspects) == 2
        
        # Check first aspect
        aspect_one = aspects[0]
        assert aspect_one.id == "aspect_one"
        assert aspect_one.aspect_name == "First Aspect"
        
        # Check user_context is propagated (now a Pydantic UserContext model)
        assert aspect_one.user_context is not None
        assert aspect_one.user_context.user_type == "Test User"
        assert aspect_one.user_context.tone == "professional"
        assert "Constraint 1" in aspect_one.user_context.constraints
    
    def test_load_legacy_framework(self, temp_legacy_file, monkeypatch):
        """Test loading legacy framework without user_context."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_legacy_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        
        assert "legacy_framework" in frameworks
        aspects = frameworks["legacy_framework"]
        assert len(aspects) == 1
        
        aspect = aspects[0]
        assert aspect.id == "legacy_aspect"
        assert aspect.user_context is None
        # Legacy evaluation_instructions should still work
        assert "Old style evaluation instructions" in aspect.evaluation_instructions
    
    def test_evaluation_criteria_merged_into_instructions(self, temp_framework_file, monkeypatch):
        """Test that evaluation_criteria is merged into evaluation_instructions."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        aspect = frameworks["test_framework"][0]
        
        # evaluation_criteria should be in evaluation_instructions
        assert "### Evaluation" in aspect.evaluation_instructions
        assert "Check this" in aspect.evaluation_instructions
    
    def test_response_strategies_appended(self, temp_framework_file, monkeypatch):
        """Test that response_strategies is appended to evaluation_instructions."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        aspect = frameworks["test_framework"][0]
        
        # response_strategies should be appended
        assert "Response Strategies" in aspect.evaluation_instructions
        assert "If unclear" in aspect.evaluation_instructions
    
    def test_dependencies_preserved(self, temp_framework_file, monkeypatch):
        """Test that depends_on is correctly loaded."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        aspect_two = frameworks["test_framework"][1]
        
        assert "aspect_one" in aspect_two.depends_on
    
    def test_missing_env_var(self, monkeypatch):
        """Test behavior when REFINEMENT_FRAMEWORK_PATH not set."""
        monkeypatch.delenv("REFINEMENT_FRAMEWORK_PATH", raising=False)
        
        frameworks = _load_frameworks(raise_on_error=False)
        assert frameworks == {}
        
        error = get_last_load_error()
        assert "not set" in error
    
    def test_missing_file_raises(self, monkeypatch):
        """Test that missing file raises FrameworkLoadError."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", "/nonexistent/path.yaml")
        
        with pytest.raises(FrameworkLoadError) as exc_info:
            _load_frameworks(raise_on_error=True)
        
        assert "not found" in str(exc_info.value)


# =============================================================================
# Tests: Registry Functions
# =============================================================================

class TestRegistryFunctions:
    """Tests for public registry functions."""
    
    def test_list_frameworks(self, temp_framework_file, monkeypatch):
        """Test list_frameworks returns framework names."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        
        frameworks = list_frameworks()
        assert "test_framework" in frameworks
    
    def test_get_framework(self, temp_framework_file, monkeypatch):
        """Test get_framework returns aspect list."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        
        aspects = get_framework("test_framework")
        assert len(aspects) == 2
        assert all(isinstance(a, RefinementAspect) for a in aspects)
    
    def test_get_framework_not_found(self, temp_framework_file, monkeypatch):
        """Test get_framework raises KeyError for unknown framework."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        reload_from_env()
        
        with pytest.raises(KeyError) as exc_info:
            get_framework("nonexistent")
        
        assert "not found" in str(exc_info.value)


# =============================================================================
# Tests: User Context Parsing
# =============================================================================

class TestUserContextParsing:
    """Tests for user_context extraction from YAML."""
    
    def test_user_context_fields_extracted(self, temp_framework_file, monkeypatch):
        """Test all user_context fields are correctly extracted."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        ctx = frameworks["test_framework"][0].user_context
        
        # Access via attribute since user_context is now a Pydantic model
        assert ctx.user_type == "Test User"
        assert ctx.context == "Testing context"
        assert ctx.tone == "professional"
        assert ctx.complexity == "intermediate"
        assert ctx.examples_from == "testing"
        assert len(ctx.constraints) == 2
        assert len(ctx.pitfalls) == 1
    
    def test_user_context_propagated_to_all_aspects(self, temp_framework_file, monkeypatch):
        """Test user_context is attached to all aspects in framework."""
        monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", temp_framework_file)
        
        frameworks = _load_frameworks(raise_on_error=True)
        aspects = frameworks["test_framework"]
        
        for aspect in aspects:
            assert aspect.user_context is not None
            assert aspect.user_context.user_type == "Test User"
