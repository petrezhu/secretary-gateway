# gateway-interceptor: Universal IM Message Interception Plugin

> Spec derived from session 2026-09-08/09.
> Status: **Implemented** — 4 commits on `main`, 841 lines core code.

## Problem Statement

个人秘书系统（Secretary）的消息拦截插件 (`secretary-gateway`) 耦合在 Secretary 项目内部，无法独立部署或被其他 Agent Harness / Daemon 复用。同时缺少语音消息转文字能力，用户发送语音时插件无法理解内容。此外，插件的消息分块策略过于简单，不处理代码块边界、Telegram UTF-16 长度限制、Agent 静默占位符等真实场景。

## Solution

将插件从 Secretary 项目中提取为独立开源仓库 `gateway-interceptor`，重新定位为**通用消息拦截层**：支持任意 Agent Harness（Hermes/OpenClaw/QClaw/MimoClaw）和任意符合 `POST /api/inbound` 契约的 Daemon。新增 ASR 语音转文字管线，并从 Hermes Agent 的 `gateway/platforms/base.py` 和 `gateway/delivery.py` 中提取经过生产验证的纯函数工具，增强核心消息管线。

## User Stories

1. 作为 **Hermes Agent 用户**，我希望插件以 Hermes `pre_gateway_dispatch` 钩子方式加载，以便自动拦截入站消息
2. 作为 **OpenClaw/QClaw/MimoClaw 用户**，我希望插件的 `register()` 函数可适配不同 Harness 的钩子机制，以便在非 Hermes 环境中复用
3. 作为 **Secretary 运维者**，我希望插件通过 symlink 引用独立仓库，以便 Secretary 项目和插件独立迭代
4. 作为 **Secretary 运维者**，我希望 Hermes 插件目录也通过 symlink 指向同一源文件，以便修改一次生效所有位置
5. 作为 **开源贡献者**，我希望插件不依赖任何 Daemon 的 Python 包，以便零配置部署
6. 作为 **QQ 用户**，我希望发送语音消息时插件自动转文字并路由到 Daemon 处理，以便免打字交互
7. 作为 **运维者**，我希望 ASR 模型可配置回退链（如 MiMo-V2.5-ASR → whisper），以便单模型故障时自动切换
8. 作为 **运维者**，我希望语音格式自动转换（amr/silk → wav），以便兼容不同 ASR 模型的输入要求
9. 作为 **QQ 用户**，我希望发送图片时插件自动 OCR 提取文字，以便图片中的信息被 Daemon 理解
10. 作为 **运维者**，我希望 OCR 模型可配置回退链，以便单模型故障时自动切换
11. 作为 **Telegram 用户**，我希望 Daemon 回复超过 4096 UTF-16 单位时自动分块，以便消息不被截断
12. 作为 **Telegram 用户**，我希望代码块内的分块自动关闭/重开围栏（```），以便每个 chunk 都是合法 Markdown
13. 作为 **多平台用户**，我希望长回复自动附加 chunk indicator（如 `(1/3)`），以便知道还有后续消息
14. 作为 **运维者**，我希望 Agent 返回的静默占位符（`silent`、`🔇`、`no reply`）被自动过滤，以便不发送无意义消息
15. 作为 **运维者**，我希望配置变量支持向后兼容（`GATEWAY_DAEMON_URL` 和 `SECRETARY_GATEWAY_URL` 都有效），以便平滑迁移
16. 作为 **运维者**，我希望通过 `GATEWAY_INTERCEPT_PLATFORMS` 控制拦截哪些平台，以便只在需要的平台上启用
17. 作为 **运维者**，我希望 Daemon 不可达时自动 fail-open（放行给 Agent），以便不丢失任何消息
18. 作为 **运维者**，我希望 ASR/OCR 失败时也 fail-open，以便 Agent 可以用自己的能力处理原始媒体
19. 作为 **开发者**，我希望 `truncate_message()` 是公开函数，以便 Daemon 侧也可调用
20. 作为 **开发者**，我希望 `utf16_len()` 是公开函数，以便其他模块计算 Telegram 消息长度
21. 作为 **开源维护者**，我希望 README 中有致谢章节标注 Hermes Agent 的代码来源，以便合规
22. 作为 **新用户**，我希望有 `install.sh` 脚本一键安装插件到 Hermes 插件目录，以便快速上手
23. 作为 **开发者**，我希望 pyproject.toml 声明 `requests>=2.28` 为唯一外部依赖，以便环境最小化
24. 作为 **Daemon 开发者**，我希望 `POST /api/inbound` 的请求/响应契约在 README 中有明确文档，以便实现兼容 Daemon

## Implementation Decisions

### 单文件架构
- 核心代码全部在 `__init__.py`（841 行），不拆分模块
- 理由：插件是钩子回调，拆分会增加加载复杂度且无收益
- 唯一外部依赖：`requests`

### Daemon 接口契约
```
POST /api/inbound
Request:  {text, user_id, chat_id, chat_type, platform}
Response: {action: "handle", reply: "..."}          — 单条回复
          {action: "handle", replies: ["..", ".."]}  — 多段回复
          {action: "allow"}                          — 放行给 Agent
```

### 环境变量设计（向后兼容）
- 主变量：`GATEWAY_DAEMON_URL`, `GATEWAY_DAEMON_TIMEOUT`, `GATEWAY_INTERCEPT_PLATFORMS`
- 回退：`SECRETARY_GATEWAY_URL`, `SECRETARY_TIMEOUT`, `SECRETARY_INTERCEPT_PLATFORMS`
- ASR：`ASR_API_BASE`, `ASR_API_KEY`, `ASR_MODELS`, `ASR_TIMEOUT`, `ASR_LANGUAGE`
- OCR：`VISION_API_BASE`, `VISION_API_KEY`, `OCR_MODELS`, `OCR_TIMEOUT`

### ASR 管线
- 下载音频 → ffmpeg 转 WAV (16kHz mono) → `POST /v1/audio/transcriptions` (multipart)
- 模型回退链：按 `ASR_MODELS` 逗号分隔顺序逐个尝试
- 支持格式：wav/mp3/ogg/opus/amr/silk/flac/m4a/webm
- ffmpeg 不可用时降级到原始格式上传

### OCR 管线
- 下载图片 → base64 编码 → `POST /v1/chat/completions` (vision)
- 模型回退链：按 `OCR_MODELS` 逗号分隔顺序逐个尝试

### 从 Hermes Agent 吸纳的纯函数
来源标注：`gateway/platforms/base.py` 和 `gateway/delivery.py`，Nous Research。

| 函数 | 增强点 |
|------|--------|
| `utf16_len()` | Telegram 消息长度按 UTF-16 code unit 计算 |
| `_prefix_within_utf16_limit()` | 安全截断，不劈开 surrogate pair |
| `_custom_unit_to_cp()` | 自定义长度单位的二分查找 |
| `truncate_message()` | 代码块感知分块 + chunk indicator + UTF-16 支持 |
| `_SILENCE_NARRATION` | 静默占位符正则过滤 |

### 核心链路集成点
1. Daemon 返回 `action: "handle"` 后，先过 `_is_silence_narration()` 过滤
2. 单条 `reply` 超长时自动调用 `truncate_message()` 分块
3. 多段 `replies` 中每段也过静默过滤

### 插件命名与部署
- 插件名：`gateway-interceptor`（plugin.yaml `name` 字段）
- 仓库名：`secretary-gateway`（GitHub 仓库名不变）
- 3 个 symlink 位置指向同一源文件：
  - `~/.hermes/plugins/gateway-interceptor`
  - `~/.hermes/profiles/main/plugins/gateway-interceptor`
  - `/root/git/secretary/plugins/gateway-interceptor`

### Harness 适配
- `register(ctx)` 函数是唯一的 Harness 接触点
- 当前实现注册 `pre_gateway_dispatch` 钩子（Hermes 约定）
- 其他 Harness 在 `register()` 中适配自己的钩子名即可

## Testing Decisions

### 测试原则
- 测试外部行为，不测实现细节
- 每个纯函数独立可测（utf16_len、truncate_message、_is_silence_narration）
- 配置回退链可测（设 env → 检查模块变量）
- ASR/OCR 管线用 mock HTTP 测试

### 已有测试覆盖（在 secretary 项目中）
- `tests/unit/test_golden_set.py` — 41 条意图回归用例（测试 Daemon 侧意图匹配，不测插件本身）
- `tests/unit/test_intents.py` — 意图处理器单元测试

### 待补充测试（gateway-interceptor 仓库内）
- `utf16_len` 边界：BMP 字符、surrogate pair、空字符串
- `truncate_message` 边界：短文本不分块、代码块内分块、chunk indicator 编号
- `_is_silence_narration`：各种静默变体 + 不误杀真实文本
- 配置回退链：`GATEWAY_DAEMON_URL` 和 `SECRETARY_GATEWAY_URL` 优先级

## Out of Scope

- **Daemon 侧代码**：意图引擎、数据层、通知层属于 Secretary 项目，不在本仓库范围
- **Harness 钩子适配**：OpenClaw/QClaw/MimoClaw 的具体 `register()` 实现待各 Harness 提供插件 API 后补充
- **平台适配器**：QQ/Telegram/Discord 的平台特定逻辑由 Harness 的 gateway 负责，插件只做拦截+增强+路由
- **会话管理**：session 创建/重置/历史属于 Harness 职责
- **流式响应**：streaming 属于 Agent 推理层，插件不参与
- **LLM 意图识别**：插件不做 LLM 调用（ASR/OCR 是媒体转文字，不是意图识别）

## Further Notes

- 插件的核心价值是**轻量**：647→841 行，单文件，零框架。从 Hermes 吸纳的 200 行工具代码全部是纯函数，不引入任何新依赖或抽象层。
- 未来扩展方向：`classify_send_error()`（发送错误分类）、死信目标追踪、更多 ASR 模型适配。但都应保持纯函数级吸纳，不引入框架。
- Obsidian 笔记已同步更新：`/root/git/Obsidian-Vault/项目/Secretary秘书/消息拦截-个人秘书建立的第一步：从 SideCarAgent到secretary-gateway 插件.md`
