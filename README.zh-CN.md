# gateway-interceptor

<p align="center">
  <img src="docs/images/logo.svg" alt="gateway-interceptor" width="320"/>
</p>

> **≈0 延迟 · 0 tokens · 全模态 · <50MB 内存 · 全 Harness**
>
> 一个 [hermes-agent](https://github.com/NousResearch/hermes-agent) 插件，把"简单意图 + 媒体增强"从 Agent 主链路中剥离出来。用户发语音/图片/文字，插件在 Agent 之前拦截，用 ASR/OCR 转文字，用纯正则匹配意图，直接回复——**Agent 根本不被唤醒**。

<p>
<a href="#-quick-start"><img src="https://img.shields.io/badge/latency-≈0ms-22C55E?style=for-the-badge" alt="≈0ms"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/tokens-0-22C55E?style=for-the-badge" alt="0 tokens"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/modality-text·voice·image-2563EB?style=for-the-badge" alt="all modalities"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/memory-<50MB-22C55E?style=for-the-badge" alt="<50MB"></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/harness-all-2563EB?style=for-the-badge" alt="all harnesses"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=for-the-badge" alt="MIT"></a>
</p>

> [English](README.md) | **简体中文**

---

## 🎯 Problem it solves

Agent 框架（Hermes/OpenClaw/QClaw/MimoClaw）的主链路是：**用户消息 → LLM 推理 → 工具调用 → 回复**。这对复杂问题是对的，但对以下场景是浪费：

| 场景 | Agent 主链路 | gateway-interceptor |
|------|-------------|-------------------|
| "你好" | LLM 推理 → token 消耗 → 2-5s | 纯正则 → 0 token → <50ms |
| 发一张持仓截图 | Agent 要调 vision 工具 → 多轮 | OCR 提取文字 → 直接路由 |
| 发一段语音 | Agent 无法直接理解 | ASR 转文字 → 意图匹配 → 回复 |
| "待办" | LLM 理解意图 → 查数据库 | 正则命中 → 直接查 → 直接回 |

**越用越省 tokens**：高频简单意图被拦截后，Agent 的 LLM 调用次数直线下降。100 条消息里，可能 70 条被拦截，只有 30 条唤醒 Agent。

## ✨ Core features

<table>
<tr><td><b>≈0 延迟响应</b></td><td>纯正则 + 关键词匹配，无 LLM 推理，<50ms 决策。用户感知"秒回"。</td></tr>
<tr><td><b>0 token 消耗</b></td><td>意图匹配不调用任何 LLM API。ASR/OCR 只在需要时触发，且用最便宜的模型。</td></tr>
<tr><td><b>全模态输入</b></td><td>文字直接处理。语音通过 ASR（MiMo-V2.5-ASR）转文字。图片通过 OCR（DeepSeek-V4）提取文字。统一输出为文本后路由。</td></tr>
<tr><td><b><50MB 内存</b></td><td>单文件插件，唯一依赖 requests。不常驻内存，不持有状态，不加载模型。</td></tr>
<tr><td><b>全 Harness 支持</b></td><td>Hermes Agent 开箱即用。OpenClaw/QClaw/MimoClaw 通过 <code>register(ctx)</code> 适配。Daemon 侧只需实现 <code>POST /api/inbound</code>。</td></tr>
<tr><td><b>Fail-open 设计</b></td><td>Daemon 不可达、ASR 失败、OCR 失败 → 消息原样放行给 Agent。绝不丢消息。</td></tr>
<tr><td><b>热插拔中间件</b></td><td>Symlink 安装，改代码即生效。不修改 Harness 源码，不 fork 任何项目。升级 Harness 不影响插件。</td></tr>
<tr><td><b>生产级消息处理</b></td><td>代码块感知分块（不劈开 <code>```</code>）、Telegram UTF-16 长度计算、静默占位符过滤（🔇）、chunk indicator（1/3）。</td></tr>
</table>

## 🧭 Where it sits

- **vs 直接用 Agent 处理所有消息：** Agent 的 LLM 推理对"你好"、"待办"是过度工程化。gateway-interceptor 用纯正则 <50ms 拦截，省 token 省延迟。Agent 只处理真正需要推理的复杂查询。
- **vs LiteLLM 等 LLM 网关：** LiteLLM 拦截的是 API 请求（prompt → completion），gateway-interceptor 拦截的是 IM 消息（用户消息 → 意图分发）。层级不同，不冲突。
- **vs Botpress/Rasa 等对话平台：** 那些是重量级全栈平台。gateway-interceptor 是一个 841 行的单文件插件，不引入任何框架。

```
                  轻量 ←──────────────────→ 重量
                    │
  消息拦截 ──────── ● gateway-interceptor (我们)
                    │
  LLM 代理 ──────── │ ──── LiteLLM
                    │
  对话平台 ──────── │ ──────────── Botpress / Rasa
                    │
  Agent 运行时 ──── │ ────────────────── OpenClaw / Hermes
                    │
  工作流平台 ────── │ ──────────────────────── Dify / n8n
```

---

## 🏛️ Architecture at a glance

<p align="center">
  <img src="docs/images/architecture.svg" alt="Architecture" width="840"/>
</p>

**The contract in one line:** `register(ctx)` registers a `pre_gateway_dispatch` hook; for intercepted messages the plugin enriches them (ASR/OCR), calls the daemon's `POST /api/inbound`, and either replies directly or passes through to the agent. **Harness: 0 lines changed.**

### Component map

```
secretary-gateway/
├── __init__.py                     核心：hook 注册 + ASR 管线 + OCR 管线
│                                     + Hermes utils (utf16/truncate/silence)
│                                     + 消息路由 (handle/allow/fail-open)
├── plugin.yaml                     Hermes 目录插件清单 (name, version, hooks)
├── pyproject.toml                  Python 包元数据 + hatchling 构建配置
├── install.sh                      安装脚本 (copy/symlink, global/profile)
├── README.md                       英文文档
├── README.zh-CN.md                 中文文档
├── SPEC.md                         功能规格 (24 条用户故事 + 实现决策)
├── LICENSE                         MIT
├── docs/images/
│   ├── logo.svg                    3D 楔形 Logo
│   ├── architecture.svg            架构图 (Harness → Plugin → Daemon)
│   └── pipeline.svg                增强管线图 (text → ASR → OCR → filter)
└── tests/
    ├── test_pure_functions.py      纯函数测试：utf16/truncate/silence/url (69 tests)
    ├── test_config.py              配置回退链测试：env 优先级 + 默认值 (16 tests)
    └── test_hook.py                钩子行为测试：handle/allow/fail-open (13 tests)
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

- [Secretary](https://github.com/petrezhu/secretary) — Reference daemon implementation
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — Reference harness
