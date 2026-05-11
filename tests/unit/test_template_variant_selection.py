import importlib

from query_refinement_module.schema.templates import global_system
from query_refinement_module.schema.templates import global_system_open_llm
import query_refinement_module.schema.templates as templates_module


def _reload_templates_module():
    return importlib.reload(templates_module)


def test_explicit_prompt_variant_still_wins(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setenv("PROMPT_VARIANT", "open_llm")

    templates = _reload_templates_module()

    assert templates.using_open_llm_prompt_templates() is True
    assert templates.GLOBAL_SYSTEM_PROMPT == global_system_open_llm.GLOBAL_SYSTEM_PROMPT


def test_ollama_model_infers_open_llm_templates(monkeypatch):
    monkeypatch.delenv("PROMPT_VARIANT", raising=False)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")

    templates = _reload_templates_module()

    assert templates.using_open_llm_prompt_templates() is True
    assert templates.GLOBAL_SYSTEM_PROMPT == global_system_open_llm.GLOBAL_SYSTEM_PROMPT


def test_canonical_prompt_variant_still_wins(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setenv("PROMPT_VARIANT", "open_llm")

    templates = _reload_templates_module()

    assert templates.using_open_llm_prompt_templates() is True
    assert templates.GLOBAL_SYSTEM_PROMPT == global_system_open_llm.GLOBAL_SYSTEM_PROMPT


def test_anthropic_model_uses_default_templates_without_override(monkeypatch):
    monkeypatch.delenv("PROMPT_VARIANT", raising=False)
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")

    templates = _reload_templates_module()

    assert templates.using_open_llm_prompt_templates() is False
    assert templates.GLOBAL_SYSTEM_PROMPT == global_system.GLOBAL_SYSTEM_PROMPT