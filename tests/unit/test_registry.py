import textwrap

import pytest

from query_refinement_module.schema import registry

# monkeypatch fixture is used to modify environment variables for testing
def test_reload_from_env_loads_framework(monkeypatch, tmp_path):
    """Test that reloading from environment variable loads the framework correctly."""

    # Arrange: create a temporary YAML framework file
    yaml_content = textwrap.dedent(
        """
        demo:
          - id: aspect_a
            aspect_name: Aspect A
            aspect_description: Test aspect
            evaluation_instructions: |
              Analyze {query}
            examples:
              clear:
                - query: "What is the effect of drug X on condition Y in population Z?"
                  rationale: "The query clearly specifies the intervention, condition, and population."
              needs_refinement:
                - query: "What is the effect of drug X?"
                  issue: "The query does not specify the condition or population."
                  clarifying_question: "Which condition are you interested in?"
                  missing: "condition, population"
              partial:
                - query: "What is the effect of drug X on condition Y?"
                  has: "intervention, condition"
                  missing: "population"
                  clarifying_question: "Which population are you studying?"
              vague_ambiguous:
                - query: "How does drug X work?"
                  issue: "The query is too vague and could refer to multiple conditions."
                  clarifying_question: "What condition are you interested in regarding drug X?"
            response_format:
              type: json
        """
    )
    framework_file = tmp_path / "framework.yaml"
    framework_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(framework_file))
    
    # Act: reload the registry from the environment variable
    store = registry.reload_from_env(raise_on_error=True)

    # Assert: verify the framework was loaded correctly
    assert "demo" in store
    assert registry.list_frameworks() == ["demo"]
    framework = registry.get_framework("demo")
    assert framework[0].id == "aspect_a"
    assert framework[0].examples is not None


def test_reload_from_env_raises_on_missing_file(monkeypatch, tmp_path):
    """Test that reloading from a non-existent file raises FrameworkLoadError."""
    # Arrange: set environment variable to a non-existent file path
    missing_file = tmp_path / "missing.yaml"
    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(missing_file))

    # Act & Assert: verify that FrameworkLoadError is raised
    with pytest.raises(registry.FrameworkLoadError):
        registry.reload_from_env(raise_on_error=True)

    # Assert: verify that the last load error is recorded
    assert registry.get_last_load_error()

def test_list_frameworks_empty(monkeypatch):
    """Test that listing frameworks returns empty when no frameworks are loaded."""
    # Arrange: ensure no framework path is set
    monkeypatch.delenv("REFINEMENT_FRAMEWORK_PATH", raising=False)
    
    # Act: reload the registry
    registry.reload_from_env(raise_on_error=False)
    frameworks = registry.list_frameworks()
    
    # Assert: verify that no frameworks are listed
    assert frameworks == []

def test_list_frameworks_multiple(monkeypatch, tmp_path):
    """Test that listing frameworks returns multiple loaded frameworks."""
    # Arrange: create two temporary YAML framework files
    yaml_content_1 = textwrap.dedent(
        """
        framework_one:
          - id: aspect_1
            aspect_name: Aspect 1
            aspect_description: First framework aspect
            evaluation_instructions: |
              Analyze {query}
            response_format:
              type: json
        """
    )
    yaml_content_2 = textwrap.dedent(
        """
        framework_two:
          - id: aspect_2
            aspect_name: Aspect 2
            aspect_description: Second framework aspect
            evaluation_instructions: |
              Analyze {query}
            response_format:
              type: json
        """
    )
    framework_file_1 = tmp_path / "framework_one.yaml"
    framework_file_1.write_text(yaml_content_1, encoding="utf-8")
    
    framework_file_2 = tmp_path / "framework_two.yaml"
    framework_file_2.write_text(yaml_content_2, encoding="utf-8")

    # Combine both frameworks into one file for testing
    combined_yaml_content = yaml_content_1 + "\n" + yaml_content_2
    combined_framework_file = tmp_path / "combined_framework.yaml"
    combined_framework_file.write_text(combined_yaml_content, encoding="utf-8")

    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(combined_framework_file))
    
    # Act: reload the registry
    registry.reload_from_env(raise_on_error=True)
    frameworks = registry.list_frameworks()
    
    # Assert: verify that both frameworks are listed
    assert set(frameworks) == {"framework_one", "framework_two"}

def test_get_last_load_error(monkeypatch, tmp_path):
    """Successful reload should clear any previously stored load error."""

    yaml_content = textwrap.dedent(
        """
        framework_ok:
          - id: aspect_ok
            aspect_name: Aspect OK
            aspect_description: Valid aspect
            evaluation_instructions: |
              Analyze {query}
            response_format:
              type: json
        """
    )
    framework_file = tmp_path / "framework.yaml"
    framework_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(framework_file))

    # Act: successful reload should reset _LAST_LOAD_ERROR
    registry.reload_from_env(raise_on_error=True)
    last_error = registry.get_last_load_error()

    # Assert: no error recorded after successful load
    assert last_error is None

