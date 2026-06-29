"""Tests for Codex config-flow helpers."""

from __future__ import annotations

from custom_components.codex_conversation.config_flow import _model_options
from custom_components.codex_conversation.const import (
    DEFAULT_MODEL,
    MODELS,
    RECOMMENDED_REASONING_EFFORT,
)


def test_default_model_is_recommended() -> None:
    """The default model must be present in the recommended selector list."""
    assert DEFAULT_MODEL == "gpt-5.3-codex-spark"
    assert DEFAULT_MODEL in MODELS


def test_default_reasoning_effort_is_low() -> None:
    """The recommended reasoning effort should favor low-latency responses."""
    assert RECOMMENDED_REASONING_EFFORT == "low"


def test_model_options_include_current_custom_model() -> None:
    """A configured model not in the recommended list must remain selectable."""
    current_model = "gpt-5.6-codex-next"

    options = _model_options(current_model)

    assert options[: len(MODELS)] == MODELS
    assert options[-1] == current_model


def test_model_options_do_not_duplicate_recommended_model() -> None:
    """Recommended current values should not be duplicated."""
    assert _model_options(DEFAULT_MODEL).count(DEFAULT_MODEL) == 1
