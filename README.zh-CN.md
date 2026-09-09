# gateway-interceptor

<p align="center">
  <img src="docs/images/logo.svg" alt="gateway-interceptor" width="320"/>
</p>

通用 IM 消息拦截插件，适用于各类 AI Agent 框架。

拦截入站消息，通过 ASR（语音转文字）和 OCR（图片转文字）进行增强，然后路由到符合契约的 Gateway Daemon 进行智能分发——简单意图直接回复，复杂查询放行给 Agent。

> [English Version](README.md)

## 架构

<p align="center">
  <img src="docs/images/architecture.svg" alt="Architecture" width="840"/>
</p>

## 两层抽象

### Harness 侧（加载此插件的框架）

插件注册 `pre_gateway_dispatch` 钩子——这是 Hermes 的约定，其他框架在 `register()` 中适配自己的钩子名：

| 框架 | 钩子机制 | 适配方式 |
|------|---------|---------|
| **Hermes Agent** | `ctx.register_hook("pre_gateway_dispatch", cb)` | 开箱即用 |
| **OpenClaw** | 插件加载器待定 | 实现 `register(ctx)` |
| **QClaw** | 插件加载器待定 | 同上 |
| **MimoClaw** | 插件加载器待定 | 同上 |

钩子契约与框架无关：

```python
def hook(event, gateway, **kwargs) -> {"action": "skip"} | {"action": "allow"} | None
```

### Daemon 侧（插件调用的目标）

任何实现了 `POST /api/inbound` 的 HTTP 服务：

```
请求:
{
    "text": "用户消息（经 ASR/OCR 增强后）",
    "user_id": "12345",
    "chat_id": "channel-789",
    "chat_type": "dm | group",
    "platform": "qqbot | telegram | discord | ..."
}

响应:
{"action": "handle", "reply": "daemon 的回答"}        → 插件回复，Agent 跳过
{"action": "handle", "replies": ["part1", "part2"]}   → 多段回复
{"action": "allow"}                                    → 放行给 Agent
```

实现这个契约就够了。Secretary 是参考实现，你也可以用任何技术栈构建自己的 Daemon。

## 消息增强管线

<p align="center">
  <img src="docs/images/pipeline.svg" alt="Pipeline" width="840"/>
</p>

消息在到达 Daemon 之前经过三级增强：

```
原始消息
    │
    ├─ 有文字？→ 直接使用
    │
    ├─ 有语音？→ ASR（语音转文字）
    │   └─ 下载音频 → ffmpeg 转码 → POST /v1/audio/transcriptions
    │      模型: MiMo-V2.5-ASR（可配置回退链）
    │
    ├─ 有图片？→ OCR（图片转文字）
    │   └─ 下载图片 → base64 编码 → POST /v1/chat/completions（视觉）
    │      模型: deepseek-v4-flash（可配置回退链）
    │
    └─ 都没有？→ 放行给 Agent（让 Agent 原生处理）
```

每一级都是 fail-open：如果 ASR/OCR 失败，消息原样传递给 Agent。

## 安装

### 复制到插件目录

```bash
# 全局（所有 profile）
cp __init__.py plugin.yaml ~/.hermes/plugins/gateway-interceptor/

# 指定 profile
cp __init__.py plugin.yaml ~/.hermes/profiles/main/plugins/gateway-interceptor/
```

### 符号链接（开发模式）

```bash
ln -sf /path/to/secretary-gateway ~/.hermes/plugins/gateway-interceptor
```

### 安装脚本

```bash
./install.sh                    # 全局复制
./install.sh --profile main     # 指定 profile
./install.sh --symlink          # 符号链接模式
```

重启 Harness 加载插件。

## 配置

### Daemon 连接

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GATEWAY_DAEMON_URL` | `http://127.0.0.1:8901` | Gateway daemon HTTP 地址 |
| `GATEWAY_DAEMON_TIMEOUT` | `3` | API 调用超时（秒） |
| `GATEWAY_DAEMON_ENDPOINT` | `/api/inbound` | 入站消息端点路径 |
| `GATEWAY_INTERCEPT_PLATFORMS` | `qqbot` | 拦截的平台（逗号分隔，空=all） |

> 向后兼容：`SECRETARY_GATEWAY_URL`、`SECRETARY_TIMEOUT`、`SECRETARY_INTERCEPT_PLATFORMS` 仍然有效。

### ASR（语音转文字）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASR_API_BASE` | `$NEWAPI_API_BASE` | OpenAI 兼容的音频转录 API |
| `ASR_API_KEY` | `$NEWAPI_API_KEY` | API 密钥 |
| `ASR_MODELS` | `MiMo-V2.5-ASR` | 模型回退链（逗号分隔） |
| `ASR_TIMEOUT` | `60` | 转录超时（秒） |
| `ASR_LANGUAGE` | `zh` | ASR 语言提示 |

语音管线：下载音频 → ffmpeg 转 WAV（16kHz 单声道）→ `POST /v1/audio/transcriptions`（multipart）。ffmpeg 不可用时降级到原始格式。

支持的音频格式：`.wav`、`.mp3`、`.ogg`、`.opus`、`.amr`、`.silk`、`.flac`、`.m4a`、`.webm`

### OCR（图片转文字）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VISION_API_BASE` | `$NEWAPI_API_BASE` | OpenAI 兼容的视觉 API |
| `VISION_API_KEY` | `$NEWAPI_API_KEY` | API 密钥 |
| `OCR_MODELS` | `deepseek-v4-flash,deepseek-v4-pro` | 模型回退链 |
| `OCR_TIMEOUT` | `30` | OCR 超时（秒） |

## 依赖

- **Python** ≥ 3.9
- **requests**（唯一外部依赖）
- 运行中的 **Gateway Daemon**（实现 `POST /api/inbound`）
- **ffmpeg**（可选，用于语音格式转换）
- 视觉 API（可选，用于 OCR）
- ASR API（可选，用于语音转录）

## 设计原则

- **通用**：适用于任何 Agent 框架和任何符合契约的 Daemon。
- **自包含**：不依赖 Daemon 的 Python 包。
- **Fail-open**：Daemon 不可达、ASR 失败、OCR 失败 → 消息放行给 Agent。绝不丢消息。
- **热路径无 LLM**：插件只做增强，意图分发由 Daemon 负责。
- **回退链**：ASR 和 OCR 都按顺序尝试多个模型。

## 致谢

本项目吸纳了 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（Nous Research）的代码和设计模式。

| 函数 | 来源 | 用途 |
|------|------|------|
| `utf16_len()` | `gateway/platforms/base.py` | Telegram 消息按 UTF-16 code unit 计长 |
| `_prefix_within_utf16_limit()` | `gateway/platforms/base.py` | 安全 UTF-16 截断（surrogate-pair 感知） |
| `_custom_unit_to_cp()` | `gateway/platforms/base.py` | 自定义长度单位的二分查找 |
| `truncate_message()` | `gateway/platforms/base.py` | 代码块感知分块 + chunk indicator |
| `_SILENCE_NARRATION` | `gateway/delivery.py` | 静默占位符过滤（`silent`、`🔇` 等） |

这些函数是纯函数、零依赖，原样提取或最小改动适配，不增加运行时开销。

## 许可证

MIT

## 相关项目

- [Secretary](https://github.com/petrezhu/secretary) — 参考 Daemon 实现
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — 参考 Harness
