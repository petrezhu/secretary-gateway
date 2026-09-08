"""Unit tests for pure functions in the gateway-interceptor plugin.

Tests cover: utf16_len, _prefix_within_utf16_limit, _custom_unit_to_cp,
truncate_message, _is_silence_narration, _is_audio_url, _is_image_url.
"""

import sys
from pathlib import Path

import pytest

# Ensure the plugin package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from __init__ import (
    _custom_unit_to_cp,
    _is_audio_url,
    _is_image_url,
    _is_silence_narration,
    _prefix_within_utf16_limit,
    truncate_message,
    utf16_len,
)


# ── utf16_len ────────────────────────────────────────────────────────────────


class TestUtf16Len:
    def test_ascii(self):
        assert utf16_len("hi") == 2

    def test_cjk(self):
        # Each CJK char is 1 BMP codepoint = 1 UTF-16 code unit
        assert utf16_len("你好") == 2

    def test_emoji_surrogate_pair(self):
        # 😀 is outside BMP → surrogate pair → 2 UTF-16 code units
        assert utf16_len("😀") == 2

    def test_empty(self):
        assert utf16_len("") == 0

    def test_mixed(self):
        # 'hello' (5) + '😀' (2) + 'world' (5) = 12
        assert utf16_len("hello😀world") == 12

    def test_single_ascii_char(self):
        assert utf16_len("a") == 1

    def test_multiple_emoji(self):
        assert utf16_len("😀😀") == 4


# ── _prefix_within_utf16_limit ──────────────────────────────────────────────


class TestPrefixWithinUtf16Limit:
    def test_ascii_partial(self):
        assert _prefix_within_utf16_limit("hello", 3) == "hel"

    def test_emoji_boundary(self):
        # Each emoji = 2 UTF-16 units; limit=2 → first emoji only
        assert _prefix_within_utf16_limit("😀😀", 2) == "😀"

    def test_passthrough_when_within_limit(self):
        assert _prefix_within_utf16_limit("hello", 100) == "hello"

    def test_empty_string(self):
        assert _prefix_within_utf16_limit("", 5) == ""

    def test_limit_zero(self):
        assert _prefix_within_utf16_limit("hello", 0) == ""

    def test_exact_fit(self):
        assert _prefix_within_utf16_limit("hi", 2) == "hi"

    def test_cjk_partial(self):
        assert _prefix_within_utf16_limit("你好世界", 2) == "你好"


# ── _custom_unit_to_cp ──────────────────────────────────────────────────────


class TestCustomUnitToCp:
    def test_utf16_fn_with_emoji(self):
        # '😀😀' has utf16_len 4; budget=2 → can fit 1 codepoint (s[:1]='😀', len=2)
        assert _custom_unit_to_cp("😀😀", 2, utf16_len) == 1

    def test_builtin_len_fn(self):
        assert _custom_unit_to_cp("hello", 3, len) == 3

    def test_fits_entirely(self):
        assert _custom_unit_to_cp("hi", 10, len) == 2

    def test_budget_zero(self):
        assert _custom_unit_to_cp("hello", 0, len) == 0

    def test_exact_budget(self):
        assert _custom_unit_to_cp("hello", 5, len) == 5


# ── truncate_message ─────────────────────────────────────────────────────────


class TestTruncateMessage:
    def test_short_text_passthrough(self):
        """Short text returns a single chunk unchanged."""
        result = truncate_message("hello world", max_length=100)
        assert result == ["hello world"]

    def test_multiple_chunks(self):
        """Long text is split into multiple chunks."""
        content = "x" * 5000
        result = truncate_message(content, max_length=100)
        assert len(result) > 1
        for chunk in result:
            # Each chunk should be at most max_length + indicator overhead
            assert len(chunk) <= 100 + 20  # generous margin for (1/N)

    def test_code_block_fence_handling(self):
        """Code blocks get proper fence close/reopen across chunks."""
        content = "```python\n" + "x" * 5000 + "\n```"
        result = truncate_message(content, max_length=200)
        assert len(result) > 1
        # First chunk should close the fence if split mid-code-block
        assert result[0].count("```") >= 2  # open + close at minimum

    def test_multi_chunk_indicators(self):
        """Multi-chunk results get (1/N) indicators."""
        content = "x" * 5000
        result = truncate_message(content, max_length=100)
        assert len(result) > 1
        for i, chunk in enumerate(result):
            assert f"({i + 1}/{len(result)})" in chunk

    def test_no_indicator_for_single_chunk(self):
        """Single chunk should not have (1/1) indicator."""
        result = truncate_message("short", max_length=100)
        assert len(result) == 1
        assert "(1/1)" not in result[0]

    def test_custom_len_fn(self):
        """Works with utf16_len as the length function."""
        content = "a" * 100
        result = truncate_message(content, max_length=50, len_fn=utf16_len)
        assert len(result) > 1

    def test_empty_string(self):
        result = truncate_message("", max_length=100)
        assert result == [""]

    def test_max_length_respected_approximately(self):
        """Each chunk roughly respects max_length (with indicator reserve)."""
        content = "word " * 2000  # ~10000 chars
        result = truncate_message(content, max_length=500)
        for chunk in result:
            # Remove indicator for length check
            base = chunk
            if base.endswith(")") and " (" in base:
                base = base[:base.rfind(" (")]
            assert len(base) <= 500


# ── _is_silence_narration ────────────────────────────────────────────────────


class TestIsSilenceNarration:
    @pytest.mark.parametrize("text", [
        "silent",
        "silence",
        "no response",
        "no reply",
        "🔇",
        "*(silent)*",
        "_silent_",
        "Silent",
        "SILENCE",
        "no  response",   # multiple spaces in \s+
    ])
    def test_true_cases(self, text):
        assert _is_silence_narration(text) is True

    @pytest.mark.parametrize("text", [
        "The deployment ran silently",
        "",
        "hello",
        "I was silent for a moment",
        "no response was given by the server",
    ])
    def test_false_cases(self, text):
        assert _is_silence_narration(text) is False

    def test_none(self):
        assert _is_silence_narration(None) is False

    def test_whitespace_only(self):
        assert _is_silence_narration("   ") is False

    def test_long_string(self):
        # Strings > 64 chars are never silence narrations
        assert _is_silence_narration("silent " * 20) is False


# ── _is_audio_url / _is_image_url ────────────────────────────────────────────


class TestIsAudioUrl:
    @pytest.mark.parametrize("url", [
        "https://example.com/voice.wav",
        "https://example.com/song.mp3",
        "https://example.com/audio.ogg",
        "https://example.com/recording.silk",
        "https://example.com/file.opus",
        "https://example.com/file.amr",
        "https://example.com/file.flac",
        "https://example.com/file.m4a",
        "https://example.com/file.webm",
    ])
    def test_audio_urls(self, url):
        assert _is_audio_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://example.com/doc.txt",
        "https://example.com/report.pdf",
        "https://example.com/photo.jpg",
        "https://example.com/image.png",
    ])
    def test_non_audio_urls(self, url):
        assert _is_audio_url(url) is False

    def test_case_insensitive(self):
        assert _is_audio_url("https://example.com/AUDIO.WAV") is True


class TestIsImageUrl:
    @pytest.mark.parametrize("url", [
        "https://example.com/photo.jpg",
        "https://example.com/image.png",
        "https://example.com/anim.gif",
        "https://example.com/pic.jpeg",
        "https://example.com/pic.webp",
        "https://example.com/pic.bmp",
    ])
    def test_image_urls(self, url):
        assert _is_image_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://example.com/doc.txt",
        "https://example.com/report.pdf",
        "https://example.com/audio.wav",
    ])
    def test_non_image_urls(self, url):
        assert _is_image_url(url) is False

    def test_case_insensitive(self):
        assert _is_image_url("https://example.com/PHOTO.PNG") is True
