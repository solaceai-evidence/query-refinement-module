import importlib

from query_refinement_module.schema.templates import global_system
from query_refinement_module.schema.templates import global_system_open_llm
import query_refinement_module.schema.templates as templates_module


def _reload_templates_module():
    return importlib.reload(templates_module)


def test_explicit_prompt_variant_still_wins(monkeypatch):
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setenv("QUERY_REFINEMENT_PROMPT_VARIANT", "open_llm")

    templates = _reload_templates_module()

    assert templates.GLOBAL_SYSTEM_PROMPT == global_system_open_llm.GLOBAL_SYSTEM_PROMPT


def test_ollama_model_infers_open_llm_templates(monkeypatch):
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.delenv("QUERY_REFINEMENT_PROMPT_VARIANT", raising=False)

    templates = _reload_templates_module()

    assert templates.GLOBAL_SYSTEM_PROMPT == global_system_open_llm.GLOBAL_SYSTEM_PROMPT


def test_anthropic_model_uses_default_templates_without_override(monkeypatch):
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.delenv("QUERY_REFINEMENT_PROMPT_VARIANT", raising=False)

    templates = _reload_templates_module()

    assert templates.GLOBAL_SYSTEM_PROMPT == global_system.GLOBAL_SYSTEM_PROMPT