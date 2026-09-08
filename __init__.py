"""Secretary Gateway Plugin — pre_gateway_dispatch hook.

Intercepts every inbound message and routes it through Secretary's
/api/inbound endpoint for smart dispatch:

  - Secretary handles simple intents → reply directly, skip agent
  - Secretary defers complex queries → allow normal agent flow
  - Secretary unreachable → fail-open (allow agent)

This plugin is self-contained — it has NO dependency on the secretary
Python package.  All it needs is a running Secretary Gateway HTTP server
(configured via SECRETARY_GATEWAY_URL).

Optional integration points (auto-detected at runtime):
  - secretary.memory.auto_memorize — if the secretary package happens to
    be installed, user messages are automatically fed to its memory system.
  - Built-in OCR via OpenAI-compatible vision API (NEWAPI_API_BASE).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Dict, List, Optional

import requests as _requests

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

# Secretary Gateway URL (default: localhost:8901)
SECRETARY_URL = os.environ.get(
    "SECRETARY_GATEWAY_URL", "http://127.0.0.1:8901"
)
# Timeout for Secretary API call (seconds)
SECRETARY_TIMEOUT = float(os.environ.get("SECRETARY_TIMEOUT", "3"))
# Platforms to intercept (comma-separated). Empty = all platforms.
INTERCEPT_PLATFORMS = os.environ.get("SECRETARY_INTERCEPT_PLATFORMS", "qqbot")

# ── OCR Configuration ────────────────────────────────────────────────────────

_OCR_API_BASE = os.environ.get("NEWAPI_API_BASE", "http://127.0.0.1:3300/v1")
_OCR_API_KEY = os.environ.get("NEWAPI_API_KEY", "")
_OCR_MODELS = [
    m.strip()
    for m in os.environ.get("OCR_MODELS", "deepseek-v4-flash,deepseek-v4-pro").split(",")
    if m.strip()
]
_OCR_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "30"))


# ── Plugin Entry Point ───────────────────────────────────────────────────────


def register(ctx: Any) -> None:
    """Called by Hermes plugin loader at startup."""
    logger.info("[Secretary-Gateway] register() called, registering pre_gateway_dispatch hook...")
    try:
        ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
        logger.info("[Secretary-Gateway] ✅ Hook registered successfully!")
    except Exception as e:
        logger.error("[Secretary-Gateway] ❌ Hook registration FAILED: %s", e)
    logger.info(
        "[Secretary-Gateway] Plugin configured (url=%s, platforms=%s)",
        SECRETARY_URL,
        INTERCEPT_PLATFORMS or "all",
    )


# ── Hook Implementation ──────────────────────────────────────────────────────


def _on_pre_gateway_dispatch(
    event: Any,
    gateway: Any,
    session_store: Any = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Pre-dispatch hook — ask Secretary if it wants to handle this message.

    MUST be synchronous (hook dispatcher calls cb(**kwargs) directly).

    Returns:
        {"action": "skip"}   — Secretary handled it (already replied)
        {"action": "allow"}  — let normal agent flow proceed
        None                 — same as allow
    """
    # ── Platform filter ──────────────────────────────────────────────
    platform = getattr(getattr(event, "source", None), "platform", None)
    platform_name = platform.value if platform else "unknown"

    if INTERCEPT_PLATFORMS:
        allowed = {p.strip() for p in INTERCEPT_PLATFORMS.split(",")}
        if platform_name not in allowed:
            return None  # not our platform, pass through

    # ── Skip internal/system events ──────────────────────────────────
    if getattr(event, "internal", False):
        return None

    text = (getattr(event, "text", None) or "").strip()

    # ── OCR: if no text but images present, extract text via vision ──
    if not text:
        media_urls = getattr(event, "media_urls", None) or []
        # Also check for attachments with image URLs
        if not media_urls:
            attachments = getattr(event, "attachments", None) or []
            for att in attachments:
                if isinstance(att, dict):
                    url = att.get("url", "")
                    if url and any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
                        media_urls.append(url)

        if media_urls:
            logger.info("[Secretary-Gateway] No text but %d image(s) found, attempting OCR...", len(media_urls))
            ocr_text = _ocr_extract_text(media_urls)
            if ocr_text:
                text = ocr_text
                logger.info("[Secretary-Gateway] OCR extracted %d chars", len(ocr_text))
            else:
                logger.info("[Secretary-Gateway] OCR failed or returned empty, passing to agent")
                return None  # Let agent handle with vision

    if not text:
        return None

    # ── Auto-memorize user message (optional) ────────────────────────
    try:
        from secretary.memory import auto_memorize
        auto_memorize(text, source="qqbot")
    except ImportError:
        pass  # secretary package not installed — skip memory
    except Exception as e:
        logger.debug("[Secretary-Gateway] Memory extraction failed (non-fatal): %s", e)

    source = getattr(event, "source", None)
    user_id = getattr(source, "user_id", None) or "unknown"
    chat_id = getattr(source, "chat_id", None) or "unknown"
    chat_type = getattr(source, "chat_type", None) or "dm"

    # ── Call Secretary /api/inbound (sync) ───────────────────────────
    payload = {
        "text": text,
        "user_id": user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "platform": platform_name,
    }

    try:
        resp = _requests.post(
            f"{SECRETARY_URL}/api/inbound",
            json=payload,
            timeout=SECRETARY_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("Secretary /api/inbound returned %d", resp.status_code)
            return {"action": "allow"}
        decision = resp.json()
    except Exception as exc:
        logger.warning(
            "Secretary unreachable (%s) — fail-open to agent: %s",
            exc, text[:80],
        )
        return {"action": "allow"}

    if not decision:
        return {"action": "allow"}

    action = decision.get("action", "allow")

    if action == "handle":
        # Support both single reply and multiple replies
        replies = decision.get("replies")
        reply = decision.get("reply", "")

        if replies:
            # Multi-part message: send each chunk sequentially
            for i, chunk in enumerate(replies):
                if chunk:
                    _send_reply_sync(gateway, platform, chat_id, chunk)
                    logger.info(
                        "Secretary handled message from %s on %s: part %d/%d",
                        user_id, platform_name, i + 1, len(replies),
                    )
        elif reply:
            # Single message
            _send_reply_sync(gateway, platform, chat_id, reply)
            logger.info(
                "Secretary handled message from %s on %s: %s → %s",
                user_id, platform_name, text[:40], reply[:60],
            )
        return {"action": "skip"}

    # "allow" or unknown → normal agent flow
    return {"action": "allow"}


# ── Reply Sending ────────────────────────────────────────────────────────────


def _send_reply_sync(
    gateway: Any,
    platform: Any,
    chat_id: str,
    reply: str,
) -> None:
    """Send a reply through the gateway's platform adapter (sync wrapper).

    NOTE: the hook is invoked synchronously from async _handle_message, so
    this runs ON the event loop thread. ``run_coroutine_threadsafe(...).result()``
    there would deadlock (blocks the very loop that must run the coroutine),
    so we schedule the send as a fire-and-forget task instead.
    """
    try:
        adapters = getattr(gateway, "adapters", {})
        adapter = adapters.get(platform)
        if adapter is None:
            logger.warning("No adapter found for platform %s", platform)
            return
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # On the loop thread: schedule as background task, log outcome.
            task = loop.create_task(adapter.send(chat_id, reply))

            def _log_send_done(fut: "asyncio.Future") -> None:
                try:
                    result = fut.result()
                    if not getattr(result, "success", False):
                        logger.warning(
                            "Send failed: %s", getattr(result, "error", "unknown")
                        )
                except Exception as exc:
                    logger.error("Failed to send reply via adapter: %s", exc)

            task.add_done_callback(_log_send_done)
        else:
            result = loop.run_until_complete(adapter.send(chat_id, reply))
            if not getattr(result, "success", False):
                logger.warning("Send failed: %s", getattr(result, "error", "unknown"))
    except Exception as exc:
        logger.error("Failed to send reply via adapter: %s", exc)


# ── Built-in OCR (self-contained, no secretary dependency) ───────────────────


def _ocr_extract_text(image_urls: List[str]) -> Optional[str]:
    """Extract text from images using an OpenAI-compatible vision API.

    Tries each model in ``_OCR_MODELS`` in order until one succeeds.
    Returns combined text from all images, or None if all fail.
    """
    if not image_urls:
        return None

    all_texts: list[str] = []
    for url in image_urls:
        text = _ocr_single_image(url)
        if text:
            all_texts.append(text)

    if all_texts:
        return "\n\n".join(all_texts)
    return None


def _ocr_single_image(image_url: str) -> Optional[str]:
    """OCR a single image — try each model in fallback order."""
    try:
        data_url = _image_to_base64_url(image_url)
    except Exception as e:
        logger.error("[OCR] Failed to prepare image: %s", e)
        return None

    ocr_prompt = (
        "请仔细阅读这张图片中的所有文字内容，包括数字、日期、股票代码、价格等。"
        "只输出图片中的原始文字，不要添加任何解释或分析。"
        "如果有表格或结构化数据，保持原始格式。"
    )

    for model in _OCR_MODELS:
        try:
            result = _call_vision_api(model, data_url, ocr_prompt)
            if result:
                logger.info("[OCR] Success with model %s (%d chars)", model, len(result))
                return result
        except Exception as e:
            logger.warning("[OCR] Failed with model %s: %s", model, str(e)[:100])
            continue

    logger.error("[OCR] All models failed for image: %s", image_url[:80])
    return None


def _image_to_base64_url(image_path_or_url: str) -> str:
    """Convert image URL to base64 data URL for vision API."""
    if image_path_or_url.startswith(("http://", "https://")):
        resp = _requests.get(image_path_or_url, timeout=10)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        if ";" in content_type:
            content_type = content_type.split(";")[0].strip()
        b64 = base64.b64encode(resp.content).decode()
        return f"data:{content_type};base64,{b64}"
    else:
        # Local file path
        from pathlib import Path
        path = Path(image_path_or_url)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path_or_url}")
        suffix = path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
        mime = mime_map.get(suffix, "image/jpeg")
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"


def _call_vision_api(model: str, image_data_url: str, prompt: str) -> Optional[str]:
    """Call a vision model API to extract text from image."""
    url = f"{_OCR_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_OCR_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ],
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.1,
    }

    resp = _requests.post(url, json=payload, headers=headers, timeout=_OCR_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        if content and len(content.strip()) > 5:
            return content.strip()

    return None
