# Changelog

本项目所有重要变更记录于此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

## [1.0.3] - 2026-08-13
### Fixed
- 修复 v1.0.3 tag 与 v1.0.2 指向同一 commit 导致 setuptools-scm 解析为 1.0.2 的问题,
  PyPI 自动发布 1.0.3 失败。本次 tag 基于独立 commit,版本号正确解析为 1.0.3。

## [1.0.0] - 2026-08-13

### Added
- 实时跟踪 Claude Code 当前会话的完整输入输出(等价 `tail -f`)。
- `--list` 列出所有 session,带 ★活跃标记 / 时间 / 工作目录 / session id 前缀 / 第一句话。
- `--select` 交互式从多个 session 中选择一个(多窗口场景)。
- `<sessionId 前缀>` 直接定位 session,非交互。
- `--all` 全量回放整个会话历史。
- `--tail N` 回放最后 N 条。
- `--grep` 按关键词过滤(忽略大小写)。
- `--raw` 打印每行原始 JSON(等价 `jq .`)。
- `--ascii` 纯 ASCII 模式,兼容老终端 / 无 Unicode 环境。
- `--projects` 指向自定义的 transcript 目录。
- 跨平台支持:Windows / macOS / Linux。
- 纯 Python 标准库实现,零第三方依赖,不联网、不调用 LLM。
- GitHub Actions:CI(多平台多版本烟雾测试)与 Release(自动发 PyPI + GitHub Release)。
