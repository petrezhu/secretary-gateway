"""Gateway Interceptor Plugin — pre_gateway_dispatch hook.

Universal message interception layer for AI Agent harnesses.
Intercepts inbound IM messages, enriches them (OCR / ASR), and routes
through a conforming gateway daemon for smart dispatch.

Supported harnesses: Hermes Agent, OpenClaw, QClaw, MimoClaw, etc.
Supported daemons: Secretary, or any HTTP service implementing the
``POST /api/inbound`` contract described below.

Architecture:

    User message
        │
        ▼
    ┌──────────────────────────────────────┐
    │  Agent Harness (Hermes / OpenClaw /…) │
    │  pre_gateway_dispatch hook            │
    │  (this plugin)                        │
    │       │                               │
    │       ├─ Platform filter              │
    │       ├─ ASR (voice → text)           │
    │       ├─ OCR (image → text)           │
    │       │                               │
    │       ▼                               │
    │  POST /api/inbound ──────────────────┼──▶ Gateway Daemon
    │                                      │         │
    │       ├─ {action:"handle"} → reply   │         ├─ Intent dispatch
    │       ├─ {action:"allow"}  → agent   │         ├─ Data query
    │       └─ unreachable       → fail-open│         └─ Return decision
    └──────────────────────────────────────┘

Daemon inbound contract (POST /api/inbound):

    Request:
        {"text": str, "user_id": str, "chat_id": str,
         "chat_type": str, "platform": str}

    Response:
        {"action": "handle", "reply": "..."}        — daemon replies
        {"action": "handle", "replies": ["..", ".."]} — multi-part
        {"action": "allow"}                         — pass to agent

Self-contained — NO dependency on any daemon's Python package.
Several utility functions (utf16_len, truncate_message, silence filter)
are derived from Hermes Agent's gateway/platforms/base.py and
gateway/delivery.py by Nous Research.  See Acknowledgments in README.
Optional: secretary.memory.auto_memorize (auto-detected at runtime).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests as _requests

logger = logging.getLogger(__name__)

# ── Daemon Configuration ─────────────────────────────────────────────────────
# Primary: GATEWAY_DAEMON_*  |  Fallback: SECRETARY_* (backward compat)

DAEMON_URL = os.environ.get(
    "GATEWAY_DAEMON_URL",
    os.environ.get("SECRETARY_GATEWAY_URL", "http://127.0.0.1:8901"),
)
DAEMON_TIMEOUT = float(os.environ.get(
    "GATEWAY_DAEMON_TIMEOUT",
    os.environ.get("SECRETARY_TIMEOUT", "3"),
))
DAEMON_ENDPOINT = os.environ.get("GATEWAY_DAEMON_ENDPOINT", "/api/inbound")

# Platforms to intercept (comma-separated). Empty = all platforms.
INTERCEPT_PLATFORMS = os.environ.get(
    "GATEWAY_INTERCEPT_PLATFORMS",
    os.environ.get("SECRETARY_INTERCEPT_PLATFORMS", "qqbot"),
)

# ── OCR Configuration ────────────────────────────────────────────────────────

_OCR_API_BASE = os.environ.get(
    "NEWAPI_API_BASE",
    os.environ.get("VISION_API_BASE", "http://127.0.0.1:3300/v1"),
)
_OCR_API_KEY = os.environ.get(
    "NEWAPI_API_KEY",
    os.environ.get("VISION_API_KEY", ""),
)
_OCR_MODELS = [
    m.strip()
    for m in os.environ.get(
        "OCR_MODELS", "deepseek-v4-flash,deepseek-v4-pro"
    ).split(",")
    if m.strip()
]
_OCR_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "30"))

# ── ASR Configuration ────────────────────────────────────────────────────────

_ASR_API_BASE = os.environ.get(
    "ASR_API_BASE",
    os.environ.get("NEWAPI_API_BASE", "http://127.0.0.1:3300/v1"),
)
_ASR_API_KEY = os.environ.get(
    "ASR_API_KEY",
    os.environ.get("NEWAPI_API_KEY", ""),
)
_ASR_MODELS = [
    m.strip()
    for m in os.environ.get(
        "ASR_MODELS", "MiMo-V2.5-ASR"
    ).split(",")
    if m.strip()
]
_ASR_TIMEOUT = int(os.environ.get("ASR_TIMEOUT", "60"))
_ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "zh")

# Audio format detection: suffix → MIME type for multipart upload
_AUDIO_MIME_MAP = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".amr": "audio/amr",
    ".silk": "audio/silk",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}

# ── UTF-16 Utilities (from Hermes Agent) ────────────────────────────────────
# Telegram measures message length in UTF-16 code units, not Unicode
# codepoints.  Emoji outside the BMP (😀, CJK Extension B, …) use surrogate
# pairs and consume 2 units each.
# Source: gateway/platforms/base.py — Nous Research / Hermes Agent


def utf16_len(s: str) -> int:
    """Count UTF-16 code units in *s*."""
    return len(s.encode("utf-16-le")) // 2


def _prefix_within_utf16_limit(s: str, limit: int) -> str:
    """Return the longest prefix of *s* whose UTF-16 length ≤ *limit*."""
    if utf16_len(s) <= limit:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if utf16_len(s[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo]


def _custom_unit_to_cp(
    s: str, budget: int, len_fn: Callable[[str], int],
) -> int:
    """Largest codepoint offset *n* such that ``len_fn(s[:n]) <= budget``."""
    if len_fn(s) <= budget:
        return len(s)
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len_fn(s[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ── Silence Narration Filter (from Hermes Agent) ────────────────────────────
# Source: gateway/delivery.py — Nous Research / Hermes Agent

_SILENCE_NARRATION = re.compile(
    r'^[\s*_~`]*\(?\s*(silent|silence|no\s+response|no\s+reply)\s*\.?\)?[\s*_~`]*$'
    r'|^[\s*_~`]*[\U0001F507\.\u2026]+[\s*_~`]*$',
    re.IGNORECASE,
)


def _is_silence_narration(content: Optional[str]) -> bool:
    """True when *content* is only a silence-narration token."""
    if not content:
        return False
    stripped = content.strip()
    if not stripped or len(stripped) > 64:
        return False
    return bool(_SILENCE_NARRATION.match(stripped))


def truncate_message(
    content: str,
    max_length: int = 4096,
    len_fn: Optional[Callable[[str], int]] = None,
) -> List[str]:
    """Split a long message into chunks, preserving code block boundaries.

    Derived from Hermes Agent's ``BasePlatformAdapter.truncate_message``.
    When a split falls inside a triple-backtick code block, the fence is
    closed at the end of the current chunk and reopened at the start of
    the next.  Multi-chunk responses receive indicators like ``(1/3)``.

    Args:
        content: The full message content.
        max_length: Maximum length per chunk (default 4096 for Telegram).
        len_fn: Length function.  Defaults to ``len`` (codepoints).
                Pass ``utf16_len`` for Telegram.
    """
    _len = len_fn or len
    if _len(content) <= max_length:
        return [content]

    INDICATOR_RESERVE = 10
    FENCE_CLOSE = "\n```"

    chunks: List[str] = []
    remaining = content
    carry_lang: Optional[str] = None

    while remaining:
        prefix = f"```{carry_lang}\n" if carry_lang is not None else ""

        headroom = (
            max_length - INDICATOR_RESERVE
            - _len(prefix) - _len(FENCE_CLOSE)
        )
        if headroom < 1:
            headroom = max(1, max_length // 2)

        # Everything remaining fits
        if _len(prefix) + _len(remaining) <= max_length - INDICATOR_RESERVE:
            final_chunk = prefix + remaining
            _in_code = carry_lang is not None
            if _in_code:
                for _line in remaining.split("\n"):
                    _stripped = _line.strip()
                    if _stripped.startswith("```"):
                        if _in_code:
                            _in_code = False
                        else:
                            _in_code = True
                if _in_code:
                    final_chunk += FENCE_CLOSE
            chunks.append(final_chunk)
            break

        # Find natural split point
        if _len is not len:
            _cp_limit = _custom_unit_to_cp(remaining, headroom, _len)
        else:
            _cp_limit = headroom
        region = remaining[:_cp_limit]
        split_at = region.rfind("\n")
        if split_at < _cp_limit // 2:
            split_at = region.rfind(" ")
        if split_at < 1:
            split_at = max(1, _cp_limit)

        # Avoid splitting inside inline code spans
        candidate = remaining[:split_at]
        backtick_count = candidate.count("`") - candidate.count("\\`")
        if backtick_count % 2 == 1:
            last_bt = candidate.rfind("`")
            while last_bt > 0 and candidate[last_bt - 1] == "\\":
                last_bt = candidate.rfind("`", 0, last_bt)
            if last_bt > 0:
                safe_split = candidate.rfind(" ", 0, last_bt)
                nl_split = candidate.rfind("\n", 0, last_bt)
                safe_split = max(safe_split, nl_split)
                if safe_split > _cp_limit // 4:
                    split_at = safe_split

        chunk_body = remaining[:split_at]
        remaining = remaining[split_at:].lstrip()

        full_chunk = prefix + chunk_body

        in_code = carry_lang is not None
        lang = carry_lang or ""
        for line in chunk_body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("```"):
                if in_code:
                    in_code = False
                    lang = ""
                else:
                    in_code = True
                    tag = stripped[3:].strip()
                    lang = tag.split()[0] if tag else ""

        if in_code:
            full_chunk += FENCE_CLOSE
            carry_lang = lang
        else:
            carry_lang = None

        chunks.append(full_chunk)

    if len(chunks) > 1:
        total = len(chunks)
        chunks = [
            f"{chunk} ({i + 1}/{total})" for i, chunk in enumerate(chunks)
        ]

    return chunks


# ── Plugin Entry Point ───────────────────────────────────────────────────────


def register(ctx: Any) -> None:
    """Called by the harness plugin loader at startup.

    Registers the ``pre_gateway_dispatch`` hook.  This hook name is the
    Hermes convention; other harnesses may use a different name — adapt
    the ``register_hook`` call as needed for your harness.
    """
    hook_name = "pre_gateway_dispatch"
    logger.info(
        "[Gateway-Interceptor] registering %s hook...", hook_name,
    )
    try:
        ctx.register_hook(hook_name, _on_pre_gateway_dispatch)
        logger.info("[Gateway-Interceptor] ✅ Hook registered")
    except Exception as e:
        logger.error("[Gateway-Interceptor] ❌ Hook registration FAILED: %s", e)
    logger.info(
        "[Gateway-Interceptor] daemon=%s, platforms=%s",
        DAEMON_URL,
        INTERCEPT_PLATFORMS or "all",
    )


# ── Hook Implementation ──────────────────────────────────────────────────────


def _on_pre_gateway_dispatch(
    event: Any,
    gateway: Any,
    session_store: Any = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Pre-dispatch hook — enrich message, then ask daemon to handle it.

    MUST be synchronous (hook dispatcher calls cb(**kwargs) directly).

    Returns:
        {"action": "skip"}   — daemon handled it (already replied)
        {"action": "allow"}  — let normal agent flow proceed
        None                 — same as allow
    """
    # ── Platform filter ──────────────────────────────────────────────
    platform = getattr(getattr(event, "source", None), "platform", None)
    platform_name = platform.value if platform else "unknown"

    if INTERCEPT_PLATFORMS:
        allowed = {p.strip() for p in INTERCEPT_PLATFORMS.split(",")}
        if platform_name not in allowed:
            return None

    # ── Skip internal/system events ──────────────────────────────────
    if getattr(event, "internal", False):
        return None

    text = (getattr(event, "text", None) or "").strip()

    # ── ASR: if no text but voice present, transcribe ────────────────
    if not text:
        voice_urls = _extract_voice_urls(event)
        if voice_urls:
            logger.info(
                "[Gateway-Interceptor] %d voice(s) found, ASR...",
                len(voice_urls),
            )
            asr_text = _asr_transcribe(voice_urls)
            if asr_text:
                text = asr_text
                logger.info(
                    "[Gateway-Interceptor] ASR → %d chars", len(asr_text),
                )
            else:
                logger.info(
                    "[Gateway-Interceptor] ASR failed, passing to agent",
                )
                return None

    # ── OCR: if still no text but images present, extract ────────────
    if not text:
        image_urls = _extract_image_urls(event)
        if image_urls:
            logger.info(
                "[Gateway-Interceptor] %d image(s), OCR...",
                len(image_urls),
            )
            ocr_text = _ocr_extract_text(image_urls)
            if ocr_text:
                text = ocr_text
                logger.info(
                    "[Gateway-Interceptor] OCR → %d chars", len(ocr_text),
                )
            else:
                logger.info(
                    "[Gateway-Interceptor] OCR failed, passing to agent",
                )
                return None

    if not text:
        return None

    # ── Auto-memorize (optional, secretary-specific) ──────────────────
    try:
        from secretary.memory import auto_memorize
        auto_memorize(text, source="qqbot")
    except ImportError:
        pass
    except Exception as e:
        logger.debug("[Gateway-Interceptor] Memory skip: %s", e)

    source = getattr(event, "source", None)
    user_id = getattr(source, "user_id", None) or "unknown"
    chat_id = getattr(source, "chat_id", None) or "unknown"
    chat_type = getattr(source, "chat_type", None) or "dm"

    # ── Call daemon /api/inbound (sync) ──────────────────────────────
    payload = {
        "text": text,
        "user_id": user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "platform": platform_name,
    }

    endpoint = f"{DAEMON_URL}{DAEMON_ENDPOINT}"
    try:
        resp = _requests.post(
            endpoint, json=payload, timeout=DAEMON_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("Daemon returned %d", resp.status_code)
            return {"action": "allow"}
        decision = resp.json()
    except Exception as exc:
        logger.warning(
            "Daemon unreachable (%s) — fail-open: %s", exc, text[:80],
        )
        return {"action": "allow"}

    if not decision:
        return {"action": "allow"}

    action = decision.get("action", "allow")

    if action == "handle":
        replies = decision.get("replies")
        reply = decision.get("reply", "")

        # Filter silence narrations (from Hermes Agent delivery.py)
        if reply and _is_silence_narration(reply):
            return {"action": "allow"}
        if replies:
            replies = [r for r in replies if r and not _is_silence_narration(r)]
            if not replies:
                return {"action": "allow"}

        # Use truncate_message for single long replies (code-block aware)
        if reply and not replies:
            replies = truncate_message(reply)

        if replies:
            for i, chunk in enumerate(replies):
                if chunk:
                    _send_reply_sync(gateway, platform, chat_id, chunk)
                    logger.info(
                        "Daemon handled %s/%s: part %d/%d",
                        user_id, platform_name, i + 1, len(replies),
                    )
        elif reply:
            _send_reply_sync(gateway, platform, chat_id, reply)
            logger.info(
                "Daemon handled %s/%s: %s → %s",
                user_id, platform_name, text[:40], reply[:60],
            )
        return {"action": "skip"}

    return {"action": "allow"}


# ── Media URL Extraction ─────────────────────────────────────────────────────


def _extract_voice_urls(event: Any) -> List[str]:
    """Extract voice/audio URLs from event attachments."""
    urls: list[str] = []
    # Direct media_urls
    for url in getattr(event, "media_urls", None) or []:
        if _is_audio_url(url):
            urls.append(url)
    # Attachments
    for att in getattr(event, "attachments", None) or []:
        if isinstance(att, dict):
            url = att.get("url", "")
            if url and _is_audio_url(url):
                urls.append(url)
    return urls


def _extract_image_urls(event: Any) -> List[str]:
    """Extract image URLs from event attachments."""
    urls: list[str] = []
    for url in getattr(event, "media_urls", None) or []:
        if _is_image_url(url):
            urls.append(url)
    for att in getattr(event, "attachments", None) or []:
        if isinstance(att, dict):
            url = att.get("url", "")
            if url and _is_image_url(url):
                urls.append(url)
    return urls


def _is_audio_url(url: str) -> bool:
    lower = url.lower()
    return any(lower.endswith(ext) for ext in _AUDIO_MIME_MAP)


def _is_image_url(url: str) -> bool:
    lower = url.lower()
    return any(lower.endswith(ext) for ext in (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ))


# ── Reply Sending ────────────────────────────────────────────────────────────


def _send_reply_sync(
    gateway: Any,
    platform: Any,
    chat_id: str,
    reply: str,
) -> None:
    """Send a reply through the gateway's platform adapter (sync wrapper).

    NOTE: runs ON the event loop thread — must use fire-and-forget task,
    not run_coroutine_threadsafe (would deadlock).
    """
    try:
        adapters = getattr(gateway, "adapters", {})
        adapter = adapters.get(platform)
        if adapter is None:
            logger.warning("No adapter for platform %s", platform)
            return
        loop = asyncio.get_event_loop()
        if loop.is_running():
            task = loop.create_task(adapter.send(chat_id, reply))

            def _log_done(fut: "asyncio.Future") -> None:
                try:
                    result = fut.result()
                    if not getattr(result, "success", False):
                        logger.warning(
                            "Send failed: %s",
                            getattr(result, "error", "unknown"),
                        )
                except Exception as exc:
                    logger.error("Send error: %s", exc)

            task.add_done_callback(_log_done)
        else:
            result = loop.run_until_complete(adapter.send(chat_id, reply))
            if not getattr(result, "success", False):
                logger.warning(
                    "Send failed: %s", getattr(result, "error", "unknown"),
                )
    except Exception as exc:
        logger.error("Send error: %s", exc)


# ── Built-in ASR (self-contained) ────────────────────────────────────────────


def _asr_transcribe(audio_urls: List[str]) -> Optional[str]:
    """Transcribe voice messages to text via ASR API.

    Supports OpenAI-compatible ``POST /v1/audio/transcriptions`` endpoint.
    Tries each model in ``_ASR_MODELS`` in fallback order.

    Handles QQ voice formats (.amr, .silk) by downloading to a temp file
    and uploading as multipart form data.  If ffmpeg is available, converts
    to WAV first for better compatibility.
    """
    if not audio_urls:
        return None

    all_texts: list[str] = []
    for url in audio_urls:
        text = _asr_single(url)
        if text:
            all_texts.append(text)

    if all_texts:
        return "\n".join(all_texts)
    return None


def _asr_single(audio_url: str) -> Optional[str]:
    """ASR a single audio file — download, convert, transcribe."""
    # Download to temp file
    suffix = _suffix_from_url(audio_url)
    try:
        resp = _requests.get(audio_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error("[ASR] Download failed: %s", e)
        return None

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(resp.content)
        tmp_path = tmp.name

    try:
        # Convert to WAV if possible (better ASR compatibility)
        wav_path = _try_convert_to_wav(tmp_path)
        upload_path = wav_path or tmp_path
        upload_suffix = ".wav" if wav_path else suffix

        for model in _ASR_MODELS:
            try:
                result = _call_asr_api(upload_path, upload_suffix, model)
                if result:
                    logger.info(
                        "[ASR] Success with %s (%d chars)", model, len(result),
                    )
                    return result
            except Exception as e:
                logger.warning(
                    "[ASR] Failed with %s: %s", model, str(e)[:100],
                )
                continue

        logger.error("[ASR] All models failed for: %s", audio_url[:80])
        return None
    finally:
        # Cleanup temp files
        _safe_unlink(tmp_path)
        if wav_path:
            _safe_unlink(wav_path)


def _try_convert_to_wav(audio_path: str) -> Optional[str]:
    """Try converting audio to WAV via ffmpeg (best-effort)."""
    import subprocess

    wav_path = audio_path + ".wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", audio_path,
                "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            ],
            capture_output=True, timeout=30,
        )
        if Path(wav_path).exists() and Path(wav_path).stat().st_size > 0:
            return wav_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # ffmpeg not available — use original format
    return None


def _call_asr_api(
    audio_path: str,
    suffix: str,
    model: str,
) -> Optional[str]:
    """Call OpenAI-compatible audio transcription API."""
    url = f"{_ASR_API_BASE}/audio/transcriptions"
    mime = _AUDIO_MIME_MAP.get(suffix, "audio/wav")

    with open(audio_path, "rb") as f:
        files = {"file": (f"audio{suffix}", f, mime)}
        data: dict[str, str] = {"model": model}
        if _ASR_LANGUAGE:
            data["language"] = _ASR_LANGUAGE

        resp = _requests.post(
            url,
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {_ASR_API_KEY}"},
            timeout=_ASR_TIMEOUT,
        )

    resp.raise_for_status()
    result = resp.json()
    text = result.get("text", "").strip()
    return text if len(text) > 1 else None


def _suffix_from_url(url: str) -> str:
    """Extract file suffix from URL, defaulting to .amr."""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower()
    for ext in _AUDIO_MIME_MAP:
        if path.endswith(ext):
            return ext
    return ".amr"


def _safe_unlink(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


# ── Built-in OCR (self-contained) ────────────────────────────────────────────


def _ocr_extract_text(image_urls: List[str]) -> Optional[str]:
    """Extract text from images via OpenAI-compatible vision API.

    Tries each model in ``_OCR_MODELS`` in fallback order.
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
        "请仔细阅读这张图片中的所有文字内容，包括数字、日期、"
        "股票代码、价格等。只输出图片中的原始文字，不要添加任何"
        "解释或分析。如果有表格或结构化数据，保持原始格式。"
    )

    for model in _OCR_MODELS:
        try:
            result = _call_vision_api(model, data_url, ocr_prompt)
            if result:
                logger.info(
                    "[OCR] Success with %s (%d chars)", model, len(result),
                )
                return result
        except Exception as e:
            logger.warning("[OCR] Failed with %s: %s", model, str(e)[:100])
            continue

    logger.error("[OCR] All models failed for: %s", image_url[:80])
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
        path = Path(image_path_or_url)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path_or_url}")
        suffix = path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime = mime_map.get(suffix, "image/jpeg")
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"


def _call_vision_api(
    model: str, image_data_url: str, prompt: str,
) -> Optional[str]:
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

    resp = _requests.post(
        url, json=payload, headers=headers, timeout=_OCR_TIMEOUT,
    )
    resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        if content and len(content.strip()) > 5:
            return content.strip()

    return None
