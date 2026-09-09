"""Tests for gateway-interceptor env-variable config fallback chain.

The plugin __init__.py reads config from env vars at module import time
(module-level constants).  Testing overrides requires re-importing the
module after setting env vars.  We use importlib.reload() with
monkeypatch.setenv() for this.

Fallback chains tested:
  DAEMON_URL:         GATEWAY_DAEMON_URL → SECRETARY_GATEWAY_URL → 'http://127.0.0.1:8901'
  DAEMON_TIMEOUT:     GATEWAY_DAEMON_TIMEOUT → SECRETARY_TIMEOUT → 3.0
  DAEMON_ENDPOINT:    GATEWAY_DAEMON_ENDPOINT → '/api/inbound'
  INTERCEPT_PLATFORMS: GATEWAY_INTERCEPT_PLATFORMS → SECRETARY_INTERCEPT_PLATFORMS → 'qqbot'
  ASR_MODELS:         ASR_MODELS env → ['MiMo-V2.5-ASR']
  OCR_MODELS:         OCR_MODELS env → ['deepseek-v4-flash', 'deepseek-v4-pro']
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

# Path to the plugin __init__.py
_PLUGIN_PATH = Path(__file__).resolve().parent.parent / "__init__.py"

# All env vars the module reads — must be cleared between tests
_CONFIG_ENV_VARS = [
    "GATEWAY_DAEMON_URL",
    "SECRETARY_GATEWAY_URL",
    "GATEWAY_DAEMON_TIMEOUT",
    "SECRETARY_TIMEOUT",
    "GATEWAY_DAEMON_ENDPOINT",
    "GATEWAY_INTERCEPT_PLATFORMS",
    "SECRETARY_INTERCEPT_PLATFORMS",
    "NEWAPI_API_BASE",
    "VISION_API_BASE",
    "NEWAPI_API_KEY",
    "VISION_API_KEY",
    "OCR_MODELS",
    "OCR_TIMEOUT",
    "ASR_API_BASE",
    "ASR_API_KEY",
    "ASR_MODELS",
    "ASR_TIMEOUT",
    "ASR_LANGUAGE",
]


def _load_plugin() -> Any:
    """Load (or reload) the gateway-interceptor plugin from disk.

    Uses a unique module name each time to avoid stale-cached-module issues
    when the caller has already imported it under a different name.
    """
    spec = importlib.util.spec_from_file_location(
        "gateway_interceptor_test",
        str(_PLUGIN_PATH),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def plugin(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the plugin with a clean env (all config vars removed).

    Each test gets a freshly-imported module so module-level constants
    reflect only the env vars the test explicitly sets.
    """
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return _load_plugin()


# ── 1. Default values (no env vars set) ──────────────────────────────────────


def test_default_daemon_url(plugin: Any) -> None:
    assert plugin.DAEMON_URL == "http://127.0.0.1:8901"


def test_default_daemon_timeout(plugin: Any) -> None:
    assert plugin.DAEMON_TIMEOUT == 3.0


def test_default_daemon_endpoint(plugin: Any) -> None:
    assert plugin.DAEMON_ENDPOINT == "/api/inbound"


def test_default_intercept_platforms(plugin: Any) -> None:
    assert plugin.INTERCEPT_PLATFORMS == "qqbot"


def test_default_asr_models(plugin: Any) -> None:
    assert plugin._ASR_MODELS == ["MiMo-V2.5-ASR"]


def test_default_ocr_models(plugin: Any) -> None:
    assert plugin._OCR_MODELS == ["deepseek-v4-flash", "deepseek-v4-pro"]


# ── 2. GATEWAY_DAEMON_URL overrides SECRETARY_GATEWAY_URL ────────────────────


def test_gateway_daemon_url_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both GATEWAY_DAEMON_URL and SECRETARY_GATEWAY_URL are set,
    GATEWAY_DAEMON_URL wins."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GATEWAY_DAEMON_URL", "http://gateway-primary:9999")
    monkeypatch.setenv("SECRETARY_GATEWAY_URL", "http://secretary-fallback:7777")

    mod = _load_plugin()
    assert mod.DAEMON_URL == "http://gateway-primary:9999"


# ── 3. SECRETARY_GATEWAY_URL works alone (backward compat) ──────────────────


def test_secretary_gateway_url_backward_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECRETARY_GATEWAY_URL is used when GATEWAY_DAEMON_URL is absent."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SECRETARY_GATEWAY_URL", "http://old-secretary:5555")

    mod = _load_plugin()
    assert mod.DAEMON_URL == "http://old-secretary:5555"


# ── 4. ASR_MODELS comma-separated parsing ────────────────────────────────────


def test_asr_models_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """ASR_MODELS env var is split on commas and stripped."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ASR_MODELS", "model-a, model-b , model-c")

    mod = _load_plugin()
    assert mod._ASR_MODELS == ["model-a", "model-b", "model-c"]


def test_asr_models_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single ASR model with no commas."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ASR_MODELS", "whisper-large-v3")

    mod = _load_plugin()
    assert mod._ASR_MODELS == ["whisper-large-v3"]


# ── 5. OCR_MODELS comma-separated parsing ────────────────────────────────────


def test_ocr_models_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """OCR_MODELS env var is split on commas and stripped."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OCR_MODELS", "gpt-4o, claude-sonnet , gemini-flash")

    mod = _load_plugin()
    assert mod._OCR_MODELS == ["gpt-4o", "claude-sonnet", "gemini-flash"]


def test_ocr_models_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single OCR model with no commas."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OCR_MODELS", "vision-only")

    mod = _load_plugin()
    assert mod._OCR_MODELS == ["vision-only"]


# ── 6. Empty INTERCEPT_PLATFORMS means all platforms ─────────────────────────


def test_empty_intercept_platforms_allows_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string for INTERCEPT_PLATFORMS means intercept all platforms."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GATEWAY_INTERCEPT_PLATFORMS", "")

    mod = _load_plugin()
    # Empty string is falsy → plugin skips platform filtering (allows all)
    assert mod.INTERCEPT_PLATFORMS == ""


# ── Bonus: timeout & endpoint fallback chains ────────────────────────────────


def test_gateway_timeout_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """GATEWAY_DAEMON_TIMEOUT overrides SECRETARY_TIMEOUT."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GATEWAY_DAEMON_TIMEOUT", "10")
    monkeypatch.setenv("SECRETARY_TIMEOUT", "99")

    mod = _load_plugin()
    assert mod.DAEMON_TIMEOUT == 10.0


def test_secretary_timeout_backward_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECRETARY_TIMEOUT is used when GATEWAY_DAEMON_TIMEOUT is absent."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SECRETARY_TIMEOUT", "15")

    mod = _load_plugin()
    assert mod.DAEMON_TIMEOUT == 15.0


def test_gateway_endpoint_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """GATEWAY_DAEMON_ENDPOINT overrides default /api/inbound."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GATEWAY_DAEMON_ENDPOINT", "/custom/hook")

    mod = _load_plugin()
    assert mod.DAEMON_ENDPOINT == "/custom/hook"
