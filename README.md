# gateway-interceptor

<p align="center">
  <img src="docs/images/logo.svg" alt="gateway-interceptor" width="320"/>
</p>

> **≈0 latency · 0 tokens · all modalities · <50MB memory · all harnesses**
>
> A [hermes-agent](https://github.com/NousResearch/hermes-agent) plugin — the message gateway for [Secretary (sedimentary cold intelligence agent)](https://github.com/petrezhu/secretary). Intercepts messages before the LLM Agent, handles what rules can handle directly, only wakes the Agent when needed.

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

Agent frameworks (Hermes/OpenClaw/QClaw/MimoClaw) run: **user message → LLM reasoning → tool calls → reply**. This is correct for complex queries, but wasteful for:

[Secretary](https://github.com/petrezhu/secretary) is a **sedimentary cold intelligence agent** — no LLM reasoning, runs on rule libraries + data accumulation. Monitoring, coaching, portfolio analysis, morning briefings — all deterministic execution, zero token cost. gateway-interceptor is its message gateway, intercepting before the Agent (hot intelligence) and handling what cold intelligence can handle directly.

| Scenario | Agent main loop | gateway-interceptor |
|----------|----------------|-------------------|
| "hello" | LLM reasoning → token cost → 2-5s | Pure regex → 0 tokens → <50ms |
| Portfolio screenshot | Agent calls vision tool → multi-turn | OCR extracts text → direct routing |
| Voice message | Agent can't understand directly | ASR transcribes → intent match → reply |
| "todo list" | LLM understands intent → query DB | Regex matches → query DB → reply |

**Tokens saved over time**: high-frequency simple intents get intercepted, Agent LLM calls drop sharply. Out of 100 messages, maybe 70 get intercepted, only 30 wake the Agent.

## ✨ Core features

<table>
<tr><td><b>≈0 latency</b></td><td>Pure regex + keyword matching, no LLM reasoning, <50ms decision. User feels "instant reply".</td></tr>
<tr><td><b>0 token cost</b></td><td>Intent matching calls zero LLM APIs. ASR/OCR only trigger when needed, using the cheapest models.</td></tr>
<tr><td><b>All modalities</b></td><td>Text handled directly. Voice via ASR (MiMo-V2.5-ASR). Images via OCR (DeepSeek-V4). Unified text output for routing.</td></tr>
<tr><td><b><50MB memory</b></td><td>Single-file plugin, sole dependency <code>requests</code>. No resident memory, no state, no model loading.</td></tr>
<tr><td><b>All harnesses</b></td><td>Hermes Agent works out of the box. OpenClaw/QClaw/MimoClaw via <code>register(ctx)</code>. Daemon side only needs <code>POST /api/inbound</code>.</td></tr>
<tr><td><b>Fail-open</b></td><td>Daemon unreachable, ASR fail, OCR fail → message passes through to Agent. Nothing is ever lost.</td></tr>
<tr><td><b>Hot-pluggable</b></td><td>Symlink install, code changes take effect immediately. No Harness source modification, no fork. Harness upgrades don't break the plugin.</td></tr>
<tr><td><b>Production-grade</b></td><td>Code-block-aware splitting (no mid-<code>```</code> cuts), Telegram UTF-16 length, silence filter (🔇), chunk indicators (1/3).</td></tr>
</table>

## 🧭 Where it sits

| Category | Representative | Characteristic | Relationship with us |
|----------|---------------|----------------|---------------------|
| **Message interception** | **gateway-interceptor (us)** | Single-file plugin, cold intelligence first, 0 tokens, <50ms | — |
| LLM proxy | LiteLLM | Intercepts API requests (prompt→completion), routing/rate-limiting | Different layer, no conflict |
| Chat platforms | Botpress / Rasa | Heavyweight full-stack, built-in NLU + dialogue management | We're 841 lines, zero framework |
| Agent runtimes | OpenClaw / Hermes | Full LLM Agent execution environment | We're their plugin, not a replacement |
| Workflow platforms | Dify / n8n | Visual orchestration, multi-step workflows | We only intercept messages, no orchestration |
| Sedimentary cold agent | Secretary | Rule engine + data accumulation, 0 LLM calls | We're its message gateway |

**In one sentence:** We're the lightest message interception layer, sitting between cold intelligence (Secretary) and hot intelligence (Agent) — if rules can handle it, never wake the LLM.

---

## 🏛️ Architecture at a glance

<p align="center">
  <img src="docs/images/architecture.svg" alt="Architecture" width="840"/>
</p>

**The contract in one line:** `register(ctx)` registers a `pre_gateway_dispatch` hook; for intercepted messages the plugin enriches them (ASR/OCR), calls the daemon's `POST /api/inbound`, and either replies directly or passes through to the agent. **Harness: 0 lines changed.**

### Component map

```
secretary-gateway/
├── __init__.py                     Core: hook registration + ASR + OCR
│                                     + Hermes utils (utf16/truncate/silence)
│                                     + message routing (handle/allow/fail-open)
├── plugin.yaml                     Hermes directory-plugin manifest
├── pyproject.toml                  Python package metadata + hatchling build
├── install.sh                      Install script (copy/symlink, global/profile)
├── README.md                       English docs
├── README.zh-CN.md                 Chinese docs
├── SPEC.md                         Feature spec (24 user stories + decisions)
├── LICENSE                         MIT
├── docs/images/
│   ├── logo.svg                    3D wedge logo
│   ├── architecture.svg            Architecture diagram
│   └── pipeline.svg                Enrichment pipeline diagram
└── tests/
    ├── test_pure_functions.py      Pure functions: utf16/truncate/silence/url (69 tests)
    ├── test_config.py              Config fallback chain: env priority + defaults (16 tests)
    └── test_hook.py                Hook behavior: handle/allow/fail-open (13 tests)
```

<details>
<summary><b>Deep dive — the dispatch contract (for developers taking over this repo)</b></summary>

1. **Entry point, no Harness patches.** `register(ctx)` registers a `pre_gateway_dispatch` hook. For messages on intercepted platforms, the hook owns enrichment and routing.

2. **Media enrichment is a pipeline.** Raw message → has text? → use directly. Has voice? → ASR (download → ffmpeg convert → `POST /v1/audio/transcriptions`). Has image? → OCR (download → base64 → `POST /v1/chat/completions`). Each stage is fail-open.

3. **Daemon contract is HTTP.** `POST /api/inbound` with `{text, user_id, chat_id, chat_type, platform}`. Response: `{action: "handle", reply: "..."}` or `{action: "allow"}`.

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
# Daemon connection (required if not default)
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

### Daemon Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_DAEMON_URL` | `http://127.0.0.1:8901` | Gateway daemon HTTP address |
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
- A running **gateway daemon** implementing `POST /api/inbound`
- **ffmpeg** (optional, for voice format conversion)
- Vision API (optional, for OCR)
- ASR API (optional, for voice transcription)

---

## 🙏 Acknowledgments

See [CONTRIBUTING.md](CONTRIBUTING.md#acknowledgments).

---

## 📄 License

MIT

## 🔗 Related Projects

- [Secretary](https://github.com/petrezhu/secretary) — Sedimentary cold intelligence agent (rule engine + data accumulation, 0 LLM calls)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — LLM hot intelligence agent (reasoning engine)
