# Changelog

## [0.3.0] - 2026-09-09

### Added
- ASR voice-to-text support (MiMo-V2.5-ASR, configurable fallback chain)
- OCR image-to-text support (DeepSeek-V4, configurable fallback chain)
- Voice format auto-conversion via ffmpeg (amr/silk → wav)
- Silence narration filter (from Hermes Agent)
- Code-block-aware message splitting with chunk indicators
- UTF-16 message length calculation (from Hermes Agent)
- Env variable fallback chains (GATEWAY_DAEMON_* + SECRETARY_* backward compat)
- Forgejo Actions CI pipeline
- PyPI publish workflow
- SVG diagrams (logo, architecture, pipeline)
- Chinese README (README.zh-CN.md)
- SPEC.md with 24 user stories
- 98 pytest tests (69 pure + 16 config + 13 hook)

### Changed
- Plugin renamed: secretary-gateway → gateway-interceptor
- Repositioned as universal plugin for any Agent Harness + any conforming Daemon
- Secretary repositioned as "sedimentary cold intelligence agent"

## [0.2.0] - 2026-09-08

### Added
- Standalone repository extracted from secretary project
- Universal harness support (Hermes/OpenClaw/QClaw/MimoClaw)
- Daemon interface contract (POST /api/inbound)
- Platform filter (INTERCEPT_PLATFORMS)
- Multi-part reply support
- install.sh script

## [0.1.0] - 2026-09-03

### Added
- Initial plugin as part of secretary project
- pre_gateway_dispatch hook for Hermes Agent
- Basic intent routing via Secretary Gateway
