# Contributing to gateway-interceptor

感谢你对本项目的兴趣！

## 开发环境

```bash
git clone https://github.com/petrezhu/secretary-gateway
cd secretary-gateway
pip install requests pytest ruff
```

## 提交规范

```
<type>: <description>

类型：
  feat     新功能
  fix      修复
  docs     文档
  test     测试
  refactor 重构
  ci       CI/CD
```

## 代码质量

提交前必须通过：

```bash
ruff check __init__.py --select E,F,W,I
python3 -m pytest tests/ -v
```

## 致谢

本项目吸纳了 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（Nous Research）的代码和设计模式：

| 函数 | 来源 | 用途 |
|------|------|------|
| `utf16_len()` | `gateway/platforms/base.py` | Telegram 消息按 UTF-16 code unit 计长 |
| `_prefix_within_utf16_limit()` | `gateway/platforms/base.py` | 安全 UTF-16 截断（surrogate-pair 感知） |
| `_custom_unit_to_cp()` | `gateway/platforms/base.py` | 自定义长度单位的二分查找 |
| `truncate_message()` | `gateway/platforms/base.py` | 代码块感知分块 + 分段标记 |
| `_SILENCE_NARRATION` | `gateway/delivery.py` | 静默占位符过滤（`silent`、`🔇` 等） |

这些函数是纯函数、零依赖，原样提取或最小改动适配，不增加运行时开销。

## 许可证

提交代码即表示你同意以 MIT 许可证发布。
