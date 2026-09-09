"""Integration tests for the _on_pre_gateway_dispatch hook.

Covers the full hook lifecycle:
  - Platform filtering (INTERCEPT_PLATFORMS)
  - Internal/system event bypass
  - Daemon dispatch: handle, allow, unreachable, silence, multi-reply
  - truncate_message on long replies
  - Empty text guard (no text + no media → skip)
"""

from __future__ import annotations

import enum
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Module loader ────────────────────────────────────────────────────────────
_PLUGIN_PATH = Path(__file__).resolve().parent.parent / "__init__.py"

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
    spec = importlib.util.spec_from_file_location(
        "gateway_interceptor_hook_test",
        str(_PLUGIN_PATH),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Hashable platform enum (mirrors a real harness platform enum) ────────────


class _Platform(enum.Enum):
    QQBOT = "qqbot"
    TELEGRAM = "telegram"
    WECHAT = "wechat"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def plugin(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Freshly-imported plugin with clean env."""
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return _load_plugin()


def _make_event(
    text: str = "hello",
    internal: bool = False,
    platform: str = "qqbot",
    user_id: str = "test_user",
    chat_id: str = "test_chat",
    chat_type: str = "dm",
    media_urls: list | None = None,
    attachments: list | None = None,
) -> SimpleNamespace:
    """Build a minimal event object matching the hook's expectations."""
    return SimpleNamespace(
        text=text,
        internal=internal,
        source=SimpleNamespace(
            platform=_Platform(platform),
            user_id=user_id,
            chat_id=chat_id,
            chat_type=chat_type,
        ),
        media_urls=media_urls or [],
        attachments=attachments or [],
    )


def _make_gateway(
    platform: str = "qqbot",
    adapter: Any = None,
) -> SimpleNamespace:
    """Build a minimal gateway mock with an adapters dict.

    The adapters dict key is the same _Platform enum instance that
    appears on event.source.platform, so adapters.get(platform) works.
    """
    plat = _Platform(platform)
    if adapter is None:
        adapter = MagicMock()
        adapter.send = AsyncMock(return_value=SimpleNamespace(success=True))
    return SimpleNamespace(adapters={plat: adapter})


def _make_daemon_response(
    action: str = "allow",
    reply: str = "",
    replies: list[str] | None = None,
) -> MagicMock:
    """Build a mock requests.Response for the daemon."""
    resp = MagicMock()
    resp.status_code = 200
    payload: dict[str, Any] = {"action": action}
    if reply:
        payload["reply"] = reply
    if replies is not None:
        payload["replies"] = replies
    resp.json.return_value = payload
    return resp


# ── 1. Platform filter: non-matching platform → returns None ────────────────


def test_non_matching_platform_returns_none(plugin: Any) -> None:
    """Events from a platform not in INTERCEPT_PLATFORMS are ignored."""
    event = _make_event(platform="telegram")
    gateway = _make_gateway()

    with patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result is None


# ── 2. Internal event → returns None ────────────────────────────────────────


def test_internal_event_returns_none(plugin: Any) -> None:
    """Internal/system events are always skipped."""
    event = _make_event(internal=True)
    gateway = _make_gateway()

    with patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result is None


# ── 3. Daemon handle → reply sent, returns {action:"skip"} ──────────────────


def test_daemon_handle_reply_sent_returns_skip(plugin: Any) -> None:
    """When daemon says 'handle' with a reply, the reply is sent and hook
    returns {action: 'skip'} to suppress normal agent flow."""
    event = _make_event(text="what time is it")
    gateway = _make_gateway()
    adapter = list(gateway.adapters.values())[0]

    daemon_resp = _make_daemon_response(action="handle", reply="It's 3 PM")

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp) as mock_post,
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "skip"}
    mock_post.assert_called_once()
    mock_send.assert_called_once_with(gateway, event.source.platform, "test_chat", "It's 3 PM")


# ── 4. Daemon allow → returns {action:"allow"} ─────────────────────────────


def test_daemon_allow_returns_allow(plugin: Any) -> None:
    """When daemon says 'allow', the hook passes through to the agent."""
    event = _make_event(text="tell me a joke")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(action="allow")

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}


# ── 5. Daemon unreachable → fail-open returns {action:"allow"} ─────────────


def test_daemon_unreachable_returns_allow(plugin: Any) -> None:
    """When daemon is unreachable (requests.post raises), fail-open
    returns {action: 'allow'}."""
    event = _make_event(text="hello daemon")
    gateway = _make_gateway()

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(
            plugin._requests, "post", side_effect=ConnectionError("refused")
        ),
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}


# ── 6. Daemon returns silence → filtered, returns {action:"allow"} ──────────


def test_daemon_silence_reply_filtered_returns_allow(plugin: Any) -> None:
    """When daemon replies with a silence narration (e.g. 'silent'),
    the reply is filtered out and the hook returns {action: 'allow'}."""
    event = _make_event(text="are you there")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(action="handle", reply="silent")

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}
    mock_send.assert_not_called()


# ── 7. Daemon returns long reply → truncate_message called, multi-part ──────


def test_long_reply_truncated_and_sent_as_parts(plugin: Any) -> None:
    """A long single reply is split by truncate_message and each chunk
    is sent separately."""
    long_reply = "x" * 5000
    event = _make_event(text="explain everything")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(action="handle", reply=long_reply)

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "skip"}
    # truncate_message should have split it into multiple parts
    assert mock_send.call_count > 1
    # Each call should be to the same gateway/platform/chat_id
    for call in mock_send.call_args_list:
        args, _ = call
        assert args[0] is gateway
        assert args[1] is event.source.platform
        assert args[2] == "test_chat"


# ── 8. Daemon returns {action:"handle", replies:["a","b"]} → both sent ─────


def test_daemon_multi_reply_both_sent(plugin: Any) -> None:
    """When daemon provides a replies list, each reply is sent individually."""
    event = _make_event(text="give me two answers")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(
        action="handle", replies=["first answer", "second answer"]
    )

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "skip"}
    assert mock_send.call_count == 2
    # Verify each chunk was sent
    sent_chunks = [call.args[3] for call in mock_send.call_args_list]
    assert sent_chunks == ["first answer", "second answer"]


# ── 9. Empty text + no media → returns None ────────────────────────────────


def test_empty_text_no_media_returns_none(plugin: Any) -> None:
    """When text is empty and there are no voice/image attachments,
    the hook returns None (pass through)."""
    event = _make_event(text="", media_urls=[], attachments=[])
    gateway = _make_gateway()

    with patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result is None


# ── Bonus: Daemon HTTP non-200 → returns {action:"allow"} ──────────────────


def test_daemon_non_200_returns_allow(plugin: Any) -> None:
    """When daemon returns a non-200 status code, fail-open."""
    event = _make_event(text="test")
    gateway = _make_gateway()

    daemon_resp = MagicMock()
    daemon_resp.status_code = 500

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}


# ── Bonus: Daemon returns silence in multi-reply list ──────────────────────


def test_daemon_multi_reply_with_silence_filtered(plugin: Any) -> None:
    """Silence narrations in a replies list are filtered out.
    If all replies are silence, returns allow."""
    event = _make_event(text="say something")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(
        action="handle", replies=["silent", "🔇"]
    )

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}
    mock_send.assert_not_called()


def test_daemon_multi_reply_partial_silence(plugin: Any) -> None:
    """In a multi-reply list, silence entries are filtered but
    non-silence entries are still sent."""
    event = _make_event(text="say something")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(
        action="handle", replies=["silent", "actual reply"]
    )

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
        patch.object(plugin, "_send_reply_sync") as mock_send,
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "skip"}
    assert mock_send.call_count == 1
    assert mock_send.call_args.args[3] == "actual reply"


# ── Bonus: Multiple platforms in INTERCEPT_PLATFORMS ────────────────────────


def test_multiple_platforms_allowed(plugin: Any) -> None:
    """INTERCEPT_PLATFORMS with comma-separated values allows any listed platform."""
    event = _make_event(platform="telegram")
    gateway = _make_gateway()

    daemon_resp = _make_daemon_response(action="allow")

    with (
        patch.object(plugin, "INTERCEPT_PLATFORMS", "qqbot,telegram,wechat"),
        patch.object(plugin._requests, "post", return_value=daemon_resp),
    ):
        result = plugin._on_pre_gateway_dispatch(event, gateway)

    assert result == {"action": "allow"}
