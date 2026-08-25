# watch-cc

**实时查看 Claude Code 会话的完整输入输出。**

Claude Code 在运行时会把每一轮对话、工具调用、token 用量等**完整**写入本地 transcript 文件(`~/.claude/projects/<项目>/*.jsonl`)。`watch-cc` 读取这些文件,渲染成可读的彩色文本——支持实时跟踪、全量回放、按关键词过滤。

> **为什么需要它?** Claude Code 自带的可观测性(如 langfuse hook)往往只上报裁剪后的摘要、会丢工具结果和中间过程。`watch-cc` 直接读 Claude 写的原始 transcript 文件,看到的是未经裁剪的全量内容。

## 特点

- ✅ **纯 Python 标准库**,零第三方依赖,不需要 `pip install` 任何东西
- ✅ **不联网、不调用 LLM、不需要任何 API key**
- ✅ **跨平台**:Windows / macOS / Linux 都能跑
- ✅ 单文件,拿来就用

## 它不是什么

`watch-cc` 和 Langfuse 这类监控是**两回事**:

| | watch-cc | Langfuse hook |
|---|---|---|
| 做什么 | 读取本地 transcript 文件并打印 | 把对话摘要上报到 Langfuse 服务 |
| 联网? | 否 | 是(发 HTTP) |
| 接 LLM? | 否 | 否 |
| 依赖 | 零 | `pip install langfuse` + 服务端 + key |
| 内容完整性 | 全量(读原始文件) | 摘要(裁剪+去重) |

## 安装

### 方式一:直接用 Python 跑(所有平台)

```bash
python3 watch-cc.py
```

要求 **Python 3.8+**。仅此而已,无需安装任何包。

### 方式二:配置成全局命令 `watch-cc`

**Windows (PowerShell/cmd):**

把 `watch-cc.py` 和 `watch-cc.cmd` 放到 PATH 里的某个目录(例如 `C:\Users\你\.claude\bin\`),然后:

```powershell
watch-cc
```

**macOS / Linux:**

把 `watch-cc.py` 和 `watch-cc` 放到 PATH 里的某个目录(例如 `~/.local/bin/`),赋予可执行权限:

```bash
chmod +x watch-cc
watch-cc
```

### 方式三:用 pip 安装(可选)

```bash
pip install .
# 之后可直接:
watch-cc
```

## 使用

```bash
watch-cc                     # 实时跟踪最近活跃的 session
watch-cc --list              # 列出所有 session(只看,不跟踪)
watch-cc --select            # 列出并交互选择一个 session(开多个窗口时用)
watch-cc <sessionId前缀>     # 用 session id 前缀直接定位(非交互)

watch-cc <id> --all          # 全量回放整个会话历史后退出
watch-cc <id> --tail 50      # 只看最后 50 条
watch-cc <id> --all --grep "关键词"   # 全量回放 + 按关键词过滤
watch-cc <id> --raw          # 打印每行原始 JSON(等价 jq .)
watch-cc --resume <id>       # 在会话原工作目录起新 claude 进程并 resume 该会话
watch-cc --path <id>         # 只输出该会话 transcript 文件的完整路径
watch-cc --trace <id>        # 输出该会话的"思维链条"(想法/工具/命令总结)
watch-cc --trace <id> --think 1000   # trace 时 thinking 每段最多显示 1000 字符
watch-cc --ascii             # 纯 ASCII 模式(老终端 / 中文乱码时用)
watch-cc --projects <路径>   # 指向自定义的 transcript 目录
```

### 三种回放范围

| 命令 | 看到什么 | 适用场景 |
|---|---|---|
| `watch-cc <id>` | 只看**之后新产生**的(实时跟踪) | 盯着正在进行的窗口 |
| `watch-cc <id> --tail 50` | 最后 50 条 | 快速看刚才聊到哪 |
| `watch-cc <id> --all` | 从头到尾全部 | 回顾整个会话历史 |

### 多窗口怎么办

开多个 Claude 进程时,用 `--list` 区分:

```bash
watch-cc --list
```

输出示例:
```
共 12 个 session(★=近15分钟活跃):

  [ 1]★ 08-13 16:54  ones-ai-hub     5d81b2da  根据当前环境配置来说...
  [ 2]★ 08-13 16:50  ones-ai-hub     136ceecb  我刚刚点击了一个工单的入库...
  [ 3]  08-13 15:27  quicktron        4aa266c1  claude在一个会话中怎么跳转...
```

每行四个标签帮你区分:**★活跃** / **时间** / **目录名(你在哪个目录开的)** / **session id 前缀 + 第一句话**。选定后用前缀跟踪:`watch-cc 5d81b2da`。

> ⚠️ session id 只存在 Claude 进程的内存里,无法 100% 自动识别"当前终端窗口对应哪个 session"。靠 ★活跃标记 + 目录名 + 第一句话区分,是当前最可靠的方式。

## 常见问题

**中文 / 框线字符乱码?** 用 `--ascii` 模式,或在跑之前设置终端为 UTF-8(PowerShell: `chcp 65001`;或直接用 Windows Terminal / iTerm2)。

**提示找不到 .jsonl?** 说明该目录下还没用 Claude Code 跑过对话。transcript 默认在 `~/.claude/projects/`,可用 `--projects` 指向其它位置。

**超长会话 `--all` 刷屏?** 加 `--grep "关键词"` 只看相关消息,或 `--all | more` 翻页,或 `--all > history.txt` 存文件。

## 原理

Claude Code 每次对话都会往 `~/.claude/projects/<工作目录转义>/<sessionId>.jsonl` 追加一行 JSON,内容包含:

- `type`: `user` / `assistant` / `summary` / `attachment` 等
- `message.content`:文本、`tool_use`(工具调用入参)、`tool_result`(工具输出)、`thinking`(思考过程)
- `message.usage`:真实的 input/output/cache token 用量、模型名
- `cwd`、`timestamp`、`parentUuid`/`uuid`(可还原完整调用树,含 subagent)

`watch-cc` 就是把这些 JSON 行解析、格式化后打印。它是个纯粹的**文件查看器**,和 `tail -f` / `less` 同类。

## 开发与发布(给维护者)

### 本地测试

```bash
python watch-cc.py --help                       # 直接跑
pip install -e . && watch-cc --help             # 以可编辑模式安装后跑 entry point
python -m build                                 # 本地构建 wheel/sdist,产物在 dist/
```

### CI

仓库自带两个 GitHub Actions workflow:

- `.github/workflows/ci.yml` —— 每次 push / PR 在 Ubuntu/macOS/Windows × Python 3.8–3.13 上跑烟雾测试(`--help`、`--list`、`--all`、`--grep`、`pip install .`、entry point 校验)。
- `.github/workflows/release.yml` —— 打 `v*` tag 时触发:构建 → 发 PyPI → 创建 GitHub Release。

### 发布到 PyPI(首次配置,一次性)

发布采用 PyPI 的 **Trusted Publisher**(OIDC)方式,**不需要**在 GitHub Secrets 里存长期 API token。首次配置:

1. 在 PyPI 上注册好 `watch-cc` 这个项目(或先发布一次本地 build 占位)。
2. 进入 PyPI 项目设置页 → *Publishing* → 添加一个 GitHub trusted publisher:
   - PyPI Project Name: `watch-cc`
   - Owner: 你的 GitHub 用户名/组织名
   - Repository name: `watch-cc`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. 在 GitHub 仓库 *Settings → Environments* 新建一个名为 `pypi` 的环境(可与上一步对应;空环境即可,需要时再加 approval 等保护规则)。

### 发版步骤

版本号由 git tag 驱动(`setuptools-scm` 自动从 tag 读取),无需手动改 `pyproject.toml`。

```bash
# 1. 更新 CHANGELOG.md
# 2. 提交改动
git commit -am "release v1.1.0"
# 3. 打 tag(必须带 v 前缀,版本号即发布的版本)
git tag v1.1.0
# 4. 推送 tag,触发自动发布
git push origin v1.1.0
# 5. release.yml 自动触发:构建(tag 驱动版本号)→ 发 PyPI → 建 GitHub Release
```

打 `v1.1.0` 就发 `1.1.0`,完全不需要改 `pyproject.toml`。PyPI 不允许覆盖已发版本,所以每次发版必须用新 tag / 新版本号。

## 许可证

MIT
