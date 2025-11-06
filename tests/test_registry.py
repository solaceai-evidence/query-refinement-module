import textwrap

import pytest

from query_refinement_module.schema import registry


def test_reload_from_env_loads_framework(monkeypatch, tmp_path):
    yaml_content = textwrap.dedent(
        """
        demo:
          - id: aspect_a
            name: Aspect A
            description: Test aspect
            analysis_prompt: |
              Analyze {query}
            response_format:
              type: json
        """
    )
    framework_file = tmp_path / "framework.yaml"
    framework_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(framework_file))

    store = registry.reload_from_env(raise_on_error=True)

    assert "demo" in store
    assert registry.list_frameworks() == ["demo"]
    framework = registry.get_framework("demo")
    assert framework[0].id == "aspect_a"


def test_reload_from_env_raises_on_missing_file(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.yaml"
    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(missing_file))

    with pytest.raises(registry.FrameworkLoadError):
        registry.reload_from_env(raise_on_error=True)

    assert registry.get_last_load_error()
