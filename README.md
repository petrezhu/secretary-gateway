# secretary-gateway

A [Hermes Agent](https://github.com/nousresearch/hermes-agent) plugin that intercepts inbound IM messages and routes them through [Secretary](https://github.com/petrezhu/secretary) for smart dispatch.

Secretary handles simple intents directly (greetings, tasks, portfolio queries) with <50ms regex matching — no LLM needed. Complex queries pass through to the Hermes agent as usual.

## How It Works

```
User message
    │
    ▼
┌──────────────────────────────────────┐
│  Hermes Gateway                      │
│  pre_gateway_dispatch hook           │
│  (this plugin)                       │
│       │                              │
│       ├─ Platform filter             │
│       ├─ OCR (image → text)          │
│       │                              │
│       ▼                              │
│  POST /api/inbound ──────────────────┼──▶ Secretary Gateway (8901)
│                                      │         │
│                                      │         ├─ IntentRegistry (regex)
│                                      │         ├─ Data query (SQLite)
│                                      │         └─ Return decision
│                                      │
│       ├─ action: "handle" → reply    │
│       ├─ action: "allow"  → agent    │
│       └─ unreachable     → fail-open │
└──────────────────────────────────────┘
```

## Install

### Option A: Copy into Hermes plugins directory

```bash
# Global
cp __init__.py plugin.yaml ~/.hermes/plugins/secretary-gateway/

# Or per-profile
cp __init__.py plugin.yaml ~/.hermes/profiles/main/plugins/secretary-gateway/
```

### Option B: Symlink from this repo

```bash
ln -sf /path/to/secretary-gateway ~/.hermes/plugins/secretary-gateway
```

Then restart Hermes to load the plugin.

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRETARY_GATEWAY_URL` | `http://127.0.0.1:8901` | Secretary Gateway HTTP address |
| `SECRETARY_TIMEOUT` | `3` | API call timeout (seconds) |
| `SECRETARY_INTERCEPT_PLATFORMS` | `qqbot` | Platforms to intercept (comma-separated, empty = all) |
| `NEWAPI_API_BASE` | `http://127.0.0.1:3300/v1` | OpenAI-compatible API for OCR |
| `NEWAPI_API_KEY` | (empty) | API key for OCR vision models |
| `OCR_MODELS` | `deepseek-v4-flash,deepseek-v4-pro` | OCR model fallback chain (comma-separated) |
| `OCR_TIMEOUT` | `30` | OCR request timeout (seconds) |

## Requirements

- **Hermes Agent** with plugin hook support (`pre_gateway_dispatch`)
- **Python** ≥ 3.9
- **requests** library (the only external dependency)
- A running **Secretary Gateway** instance (for intent dispatch)

### Optional

- **secretary** Python package — if installed, user messages are automatically fed to its memory system (`auto_memorize`)
- Vision-capable LLM API — for OCR extraction from image messages

## Design Principles

- **Self-contained**: Zero dependency on the `secretary` Python package. All it needs is an HTTP endpoint.
- **Fail-open**: If Secretary is unreachable, times out, or returns an error, the message passes through to the Hermes agent. No message is ever lost.
- **No LLM in the hot path**: Intent matching is pure regex + keywords, <50ms, zero API cost.
- **OCR built-in**: Image messages are automatically processed via vision API before intent matching.
- **Platform-agnostic**: Works with any Hermes gateway platform (QQ, Telegram, Discord) via the `INTERCEPT_PLATFORMS` filter.

## Architecture

This plugin is the **client side** of the Secretary architecture:

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Hermes Agent       │         │  Secretary               │
│  (this plugin)      │         │  (separate project)      │
│                     │         │                          │
│  pre_gateway_dispatch│─HTTP──▶│  /api/inbound            │
│  hook               │◀────────│  Intent dispatch         │
│                     │         │  Data queries            │
│  send reply via     │         │  Proactive notifications │
│  gateway adapter    │         │  Health monitoring       │
└─────────────────────┘         └──────────────────────────┘
```

The Secretary project provides:
- Intent handler framework (regex-based, pluggable)
- Data layer (goals.db, tasks.db, portfolio.json)
- Proactive notifications (morning briefing, alerts)
- Server monitoring (health checks, deadman switch)

This plugin provides:
- Message interception hook for Hermes
- Platform filtering
- OCR for image messages
- Reply routing through Hermes gateway adapters

## Development

```bash
# Run tests (if Secretary project is available)
cd /path/to/secretary
pytest tests/unit/test_golden_set.py -v

# Lint
ruff check __init__.py
```

## License

MIT

## Related Projects

- [Secretary](https://github.com/petrezhu/secretary) — The full personal digital assistant daemon
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — The AI agent framework
