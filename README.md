# gateway-interceptor

<p align="center">
  <img src="docs/images/logo.svg" alt="gateway-interceptor" width="320"/>
</p>

> **≈0 latency · 0 tokens · all modalities · <50MB memory · all harnesses**
>
> The message gateway for [Secretary](https://github.com/petrezhu/secretary) — a **sedimentary cold intelligence agent**. Intercepts messages before the LLM Agent, handles what rules can handle directly, only wakes the Agent when needed. Cold intelligence first, hot intelligence fallback.

<p>
<a href="#-quick-start"><img src="https://img.shields.io/badge/latency-≈0ms-22C55E?style=for-the-badge" alt="≈0ms"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/tokens-0-22C55E?style=for-the-badge" alt="0 tokens"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/modality-text·voice·image-2563EB?style=for-the-badge" alt="all modalities"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/memory-<50MB-22C55E?style=for-the-badge" alt="<50MB"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/harness-all-2563EB?style=for-the-badge" alt="all harnesses"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=for-the-badge" alt="MIT"></a>
</p>

**English** | [简体中文](README.zh-CN.md)

---

## 🎯 Problem it solves

AI Agents are **hot intelligence** — every conversation burns tokens on LLM reasoning. This is correct for complex queries, but wasteful for "hello", "todo list", "how's my portfolio".

[Secretary](https://github.com/petrezhu/secretary) is a **sedimentary cold intelligence agent** — no reasoning, runs on rule libraries + data accumulation. Monitoring, coaching, portfolio analysis, morning briefings — all deterministic execution, zero token cost.

**gateway-interceptor is the boundary between cold and hot intelligence:**

```
User message
    │
    ▼
gateway-interceptor (message interception)
    │
    ├─ Cold intelligence can handle? → Secretary rule engine → direct reply (0 tokens, <50ms)
    │
    └─ Cold intelligence can't? → Wake hot intelligence → Agent LLM reasoning → reply (burns tokens)
```

| Scenario | Hot intelligence (Agent) | Cold intelligence (Secretary) |
|----------|------------------------|------------------------------|
| "hello" | LLM reasoning → burn tokens → 2-5s | Regex match → 0 tokens → <50ms |
| Portfolio screenshot | Agent calls vision tool → multi-turn | OCR extract → intent route → direct reply |
| Voice message | Agent can't understand audio | ASR transcribe → regex match → reply |
| "todo list" | LLM understands intent → query DB | Regex hits → query DB → direct reply |
| "server status" | LLM + tool call → 2-3s | Direct psutil read → <50ms |

**Tokens saved over time**: high-frequency simple intents get intercepted by cold intelligence, Agent LLM calls drop sharply. Out of 100 messages, maybe 70 handled by cold intelligence, only 30 wake the Agent.

## ✨ Core features

<table>
<tr><td><b>≈0 latency</b></td><td>Pure regex + keyword matching, no LLM reasoning, <50ms decision. User feels "instant reply".</td></tr>
<tr><td><b>0 token cost</b></td><td>Intent matching calls zero LLM APIs. ASR/OCR only trigger when needed, using the cheapest models.</td></tr>
<tr><td><b>All modalities</b></td><td>Text handled directly. Voice via ASR (MiMo-V2.5-ASR). Images via OCR (DeepSeek-V4). Unified text output for routing.</td></tr>
<tr><td><b><50MB memory</b></td><td>Single-file plugin, sole dependency <code>requests</code>. No resident memory, no state, no model loading.</td></tr>
<tr><td><b>All harnesses</b></td><td>Hermes Agent works out of the box. OpenClaw/QClaw/MimoClaw via <code>register(ctx)</code>. Daemon side only needs <code>POST /api/inbound</code>.</td></tr>
<tr><td><b>Fail-open</b></td><td>Cold intelligence unreachable, ASR fail, OCR fail → message passes through to hot intelligence. Nothing is ever lost.</td></tr>
<tr><td><b>Hot-pluggable</b></td><td>Symlink install, code changes take effect immediately. No Harness source modification, no fork. Harness upgrades don't break the plugin.</td></tr>
<tr><td><b>Production-grade</b></td><td>Code-block-aware splitting (no mid-<code>```</code> cuts), Telegram UTF-16 length, silence filter (🔇), chunk indicators (1/3).</td></tr>
</table>

## 🧭 Cold vs Hot Intelligence

| Dimension | Sedimentary cold intelligence (Secretary) | LLM hot intelligence (Agent) |
|-----------|------------------------------------------|------------------------------|
| Decision method | Rule library + keyword matching | LLM reasoning |
| Cost per call | 0 tokens | Hundreds to thousands of tokens |
| Response latency | <50ms | 2-5 seconds |
| Determinism | Fully predictable | Hallucination risk |
| Capability boundary | Rule coverage | General reasoning |
| Intelligence source | Data accumulation + rule sedimentation | Model parameters |
| Best for | High-frequency, deterministic, data-backed intents | Complex, open-ended, reasoning-required queries |

**Cold intelligence's "cold" doesn't mean "low capability" — it means "low cost".** It substitutes accumulation for reasoning, rules for guessing. The more it's used, the more precise it becomes, the more tokens it saves.

gateway-interceptor's value: **if cold intelligence can handle it, never wake hot intelligence.**

---

## 🏛️ Architecture at a glance

<p align="center">
  <img src="docs/images/architecture.svg" alt="Architecture" width="840"/>
</p>

**The contract in one line:** `register(ctx)` registers a `pre_gateway_dispatch` hook; for intercepted messages the plugin enriches them (ASR/OCR), calls cold intelligence's `POST /api/inbound`, and either replies directly or passes through to hot intelligence. **Harness: 0 lines changed.**

### Component map

```
secretary-gateway/
├── __init__.py                     Core: hook registration + ASR + OCR
│                                     + Hermes utils (utf16/truncate/silence)
│                                     + message routing (handle/allow/fail-open)
├── plugin.yaml                     Hermes directory-plugin manifest
├── pyproject.toml                  Python package metadata + hatchling build
├── install.sh                      Install script (copy/symlink, global/profile)
├── README.md                       English docs (this file)
├── README.zh-CN.md                 Chinese docs
├── SPEC.md                         Feature spec (24 user stories + decisions)
├── LICENSE                         MIT
├── docs/images/
│   ├── logo.svg                    3D wedge logo
│   ├── architecture.svg            Architecture diagram
│   ├── architecture.zh-CN.svg      Architecture diagram (Chinese)
│   ├── pipeline.svg                Enrichment pipeline diagram
│   └── pipeline.zh-CN.svg          Enrichment pipeline diagram (Chinese)
└── tests/
    ├── test_pure_functions.py      Pure functions: utf16/truncate/silence/url (69 tests)
    ├── test_config.py              Config fallback chain: env priority + defaults (16 tests)
    └── test_hook.py                Hook behavior: handle/allow/fail-open (13 tests)
```

<details>
<summary><b>Deep dive — the dispatch contract (for developers taking over this repo)</b></summary>

1. **Entry point, no Harness patches.** `register(ctx)` registers a `pre_gateway_dispatch` hook. For messages on intercepted platforms, the hook owns enrichment and routing.

2. **Media enrichment is a pipeline.** Raw message → has text? → use directly. Has voice? → ASR (download → ffmpeg convert → `POST /v1/audio/transcriptions`). Has image? → OCR (download → base64 → `POST /v1/chat/completions`). Each stage is fail-open.

3. **Cold intelligence contract is HTTP.** `POST /api/inbound` with `{text, user_id, chat_id, chat_type, platform}`. Response: `{action: "handle", reply: "..."}` or `{action: "allow"}`.

4. **Reply handling is multi-stage.** Silence filter removes `silent`/`🔇`/`no reply`. `truncate_message()` splits long replies at code-block boundaries with chunk indicators `(1/3)`. Replies sent via gateway adapter (fire-and-forget on event loop thread).

5. **Config uses fallback chains.** `GATEWAY_DAEMON_URL` → `SECRETARY_GATEWAY_URL` → default. All env vars have backward-compatible aliases. Module-level constants read at import time.

6. **Hermes utilities are pure functions.** `utf16_len()`, `_prefix_within_utf16_limit()`, `_custom_unit_to_cp()`, `truncate_message()` — all derived from Hermes Agent's `gateway/platforms/base.py`. Zero dependency, zero side effects.

</details>

---

## 🚀 Quick Start

### 1. Install the plugin

```bash
# Option A: Symlink (recommended for development)
ln -sf /path/to/secretary-gateway ~/.hermes/plugins/gateway-interceptor

# Option B: Copy
cp __init__.py plugin.yaml ~/.hermes/plugins/gateway-interceptor/

# Option C: Install script
./install.sh                    # global copy
./install.sh --profile main     # per-profile
./install.sh --symlink          # symlink mode
```

Restart the harness to load the plugin.

### 2. Configure environment variables

```bash
# Cold intelligence connection (required if not default)
export GATEWAY_DAEMON_URL="http://127.0.0.1:8901"

# ASR (optional — for voice messages)
export ASR_API_BASE="http://127.0.0.1:3300/v1"
export ASR_MODELS="MiMo-V2.5-ASR"

# OCR (optional — for image messages)
export OCR_MODELS="deepseek-v4-flash,deepseek-v4-pro"

# Platform filter
export GATEWAY_INTERCEPT_PLATFORMS="qqbot"  # or empty for all
```

### 3. Verify

```bash
# Run tests
python3 -m pytest tests/ -v

# Check plugin loads
python3 -c "from __init__ import register; print('✅ Plugin loads')"
```

---

## ⚙️ Configuration

### Cold Intelligence Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_DAEMON_URL` | `http://127.0.0.1:8901` | Cold intelligence HTTP address |
| `GATEWAY_DAEMON_TIMEOUT` | `3` | API call timeout (seconds) |
| `GATEWAY_DAEMON_ENDPOINT` | `/api/inbound` | Inbound message endpoint path |
| `GATEWAY_INTERCEPT_PLATFORMS` | `qqbot` | Platforms to intercept (comma-separated, empty=all) |

> Backward compat: `SECRETARY_GATEWAY_URL`, `SECRETARY_TIMEOUT`, `SECRETARY_INTERCEPT_PLATFORMS` still work.

### ASR (Voice → Text)

| Variable | Default | Description |
|----------|---------|-------------|
| `ASR_API_BASE` | `$NEWAPI_API_BASE` | OpenAI-compatible audio transcription API |
| `ASR_API_KEY` | `$NEWAPI_API_KEY` | API key |
| `ASR_MODELS` | `MiMo-V2.5-ASR` | Model fallback chain (comma-separated) |
| `ASR_TIMEOUT` | `60` | Transcription timeout (seconds) |
| `ASR_LANGUAGE` | `zh` | Language hint for ASR |

Voice pipeline: download audio → ffmpeg convert to WAV (16kHz mono) → `POST /v1/audio/transcriptions` (multipart). Falls back to original format if ffmpeg unavailable.

Supported audio formats: `.wav`, `.mp3`, `.ogg`, `.opus`, `.amr`, `.silk`, `.flac`, `.m4a`, `.webm`

### OCR (Image → Text)

| Variable | Default | Description |
|----------|---------|-------------|
| `VISION_API_BASE` | `$NEWAPI_API_BASE` | OpenAI-compatible vision API |
| `VISION_API_KEY` | `$NEWAPI_API_KEY` | API key |
| `OCR_MODELS` | `deepseek-v4-flash,deepseek-v4-pro` | Model fallback chain |
| `OCR_TIMEOUT` | `30` | OCR timeout (seconds) |

---

## 🧪 Testing

```bash
# All tests
python3 -m pytest tests/ -v

# Specific test file
python3 -m pytest tests/test_pure_functions.py -v   # 69 tests
python3 -m pytest tests/test_config.py -v           # 16 tests
python3 -m pytest tests/test_hook.py -v             # 13 tests

# Lint
ruff check __init__.py --select E,F,W,I
```

**Total: 98 tests, 0.27s runtime.**

---

## 📦 Requirements

- **Python** ≥ 3.9
- **requests** (only external dependency)
- A running [cold intelligence agent](https://github.com/petrezhu/secretary) implementing `POST /api/inbound`
- **ffmpeg** (optional, for voice format conversion)
- Vision API (optional, for OCR)
- ASR API (optional, for voice transcription)

---

## 🙏 Acknowledgments

This project incorporates code and design patterns derived from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.

| Function | Source | Purpose |
|----------|--------|---------|
| `utf16_len()` | `gateway/platforms/base.py` | Telegram message length in UTF-16 code units |
| `_prefix_within_utf16_limit()` | `gateway/platforms/base.py` | Safe UTF-16 truncation (surrogate-pair aware) |
| `_custom_unit_to_cp()` | `gateway/platforms/base.py` | Binary search for custom length unit boundaries |
| `truncate_message()` | `gateway/platforms/base.py` | Code-block-aware message splitting with chunk indicators |
| `_SILENCE_NARRATION` | `gateway/delivery.py` | Silence narration filter (suppresses `silent`, `🔇`, etc.) |

These functions are pure, zero-dependency, and extracted verbatim or adapted with minimal changes.

---

## 📄 License

MIT

## 🔗 Related Projects

- [Secretary](https://github.com/petrezhu/secretary) — Sedimentary cold intelligence agent (rule engine + data accumulation)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — LLM hot intelligence agent (reasoning engine)
