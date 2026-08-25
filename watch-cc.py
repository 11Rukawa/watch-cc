#!/usr/bin/env python3
"""
watch-cc — 实时查看 Claude Code 会话的完整输入输出。

Claude Code 在运行时会把每次对话、工具调用、token 用量等完整写入本地的
transcript 文件(~/.claude/projects/<项目>/*.jsonl)。本工具读取这些文件,
渲染成可读的彩色文本,支持实时跟踪、全量回放、按关键词过滤。

纯标准库实现,零第三方依赖,不联网、不调用 LLM、不需要任何 API key。

用法:
    watch-cc                     # 实时跟踪最近活跃的 session
    watch-cc --list              # 列出所有 session(只看)
    watch-cc --select            # 列出并交互选择一个 session
    watch-cc <sessionId前缀>     # 直接定位某个 session
    watch-cc <id> --all          # 全量回放整个会话历史
    watch-cc <id> --tail 50      # 只看最后 50 条
    watch-cc <id> --all --grep "关键词"
    watch-cc <id> --raw          # 打印每行原始 JSON(等价 jq .)
    watch-cc --resume <id>       # 在原会话工作目录起新 claude 进程并 resume 该会话
    watch-cc --path <id>         # 输出该会话 transcript 文件的完整路径
    watch-cc --trace <id>        # 输出该会话的"思维链条"(想法/工具/命令总结)
    watch-cc --trace <id> --think 1000   # thinking 每段最多显示 1000 字符
    watch-cc --ascii             # 纯 ASCII 模式(老终端 / 无 Unicode 时用)

也可直接:  python watch-cc.py [选项]
"""
import sys, os, json, time, glob, argparse, re

# 匹配 ANSI 颜色/样式转义码,用于 --grep 时先去掉再比对
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def _strip_ansi(s):
    return _ANSI_RE.sub("", s)

# 强制 stdout 用 UTF-8,避免 Windows 默认 GBK 编码遇到 ▶/中文/emoji 直接崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Claude Code transcript 默认目录。可用 --projects 覆盖。
DEFAULT_PROJ = os.path.expanduser("~/.claude/projects")
PROJ = DEFAULT_PROJ

# ANSI 颜色(Windows Terminal / 新版 cmd 支持;老 cmd.exe 会显示乱码,可忽略)
C = {
    "dim": "\033[2m", "r": "\033[31m", "g": "\033[32m", "y": "\033[33m",
    "b": "\033[34m", "m": "\033[35m", "c": "\033[36m", "w": "\033[97m",
    "bold": "\033[1m", "x": "\033[0m",
}

# 框线标记,默认 Unicode;--ascii 时在 main() 里改成纯 ASCII
RENDER_MARK_USER = "┌─ 你"
RENDER_MARK_ASST = "└─ Claude"

def newest_jsonl():
    cand = []
    for d in glob.glob(os.path.join(PROJ, "*")):
        if os.path.isdir(d):
            cand += glob.glob(os.path.join(d, "*.jsonl"))
    if not cand:
        sys.exit(f"找不到任何 .jsonl,请检查 {PROJ}")
    return max(cand, key=os.path.getmtime)

def _read_meta(path):
    """从 jsonl 里提取 session 标签:cwd、第一句用户输入、时间。"""
    sid = os.path.basename(path)[:-6]  # 去掉 .jsonl
    cwd = first_user = None
    n = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                n += 1
                c = d.get("cwd")
                if isinstance(c, str) and not cwd:
                    cwd = c
                if first_user is None and d.get("type") == "user" and isinstance(d.get("message"), dict):
                    cc = d["message"].get("content")
                    if isinstance(cc, str):
                        first_user = cc.strip()
                    elif isinstance(cc, list):
                        for it in cc:
                            if isinstance(it, dict) and it.get("type") == "text" and it.get("text", "").strip():
                                first_user = it["text"].strip(); break
                if cwd and first_user:
                    pass  # 继续读只是为了数行数,不提前 break 也行;但可加速
                if cwd and first_user and n > 200:
                    break
    except Exception:
        pass
    return sid, cwd, first_user, n

def list_sessions(active_within_s=900):
    """列出所有 session,按最近写入时间倒序。返回 [(path, sid, cwd, first_user, nlines, mtime, active)]。
    active = 文件在过去 active_within_s 秒内被写过(视为该窗口还活着)。"""
    now = time.time()
    out = []
    for d in glob.glob(os.path.join(PROJ, "*")):
        if not os.path.isdir(d):
            continue
        for p in glob.glob(os.path.join(d, "*.jsonl")):
            mtime = os.path.getmtime(p)
            sid, cwd, first_user, n = _read_meta(p)
            active = (now - mtime) < active_within_s
            out.append((p, sid, cwd, first_user, n, mtime, active))
    out.sort(key=lambda r: r[5], reverse=True)
    return out

def pick_session_interactive():
    rows = list_sessions()
    if not rows:
        sys.exit(f"找不到任何 .jsonl,请检查 {PROJ}")
    import datetime
    print(f"{C['c']}发现 {len(rows)} 个 session(按最近活动排序,★=近15分钟活跃):{C['x']}\n")
    shown = []
    for i, (p, sid, cwd, first_user, n, mtime, active) in enumerate(rows[:20], 1):
        shown.append((i, p))
        star = f"{C['y']}★{C['x']}" if active else " "
        ago = datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        cwd_short = (cwd or "?").replace("\\", "/").split("/")[-1] if cwd else "?"
        # 取第一句用户输入的前 40 字符做提示
        hint = ""
        if first_user:
            hint = first_user.replace("\n", " ")[:40]
        sid_short = sid[:8]
        print(f"  {C['bold']}[{i:>2}]{C['x']}{star} {C['dim']}{ago}{C['x']}  "
              f"{C['g']}{cwd_short:<24}{C['x']} "
              f"{C['b']}{sid_short}{C['x']}  "
              f"{C['dim']}{hint}{C['x']}")
    print()
    while True:
        try:
            raw = input(f"{C['c']}选择要跟踪的序号(回车=最近活跃的★项, q=退出): {C['x']}").strip()
        except (EOFError, KeyboardInterrupt):
            print(); sys.exit(0)
        if raw.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if raw == "":
            # 默认:第一个 active(近15分钟有写入)的;没有 active 就第 1 个
            idx = next((i for i, r in enumerate(shown, 1) if rows[i - 1][6]), 1)
        else:
            try:
                idx = int(raw)
            except ValueError:
                print(f"{C['r']}请输入数字{C['x']}"); continue
            if idx < 1 or idx > len(shown):
                print(f"{C['r']}超出范围(1-{len(shown)}){C['x']}"); continue
        chosen_i, chosen_p = shown[idx - 1]
        print(f"{C['g']}已选择 [{chosen_i}] {os.path.basename(chosen_p)}{C['x']}\n")
        return chosen_p

def shorten(s, n=2000):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n{C['dim']}…[截断,共{len(s)}字符]{C['x']}"

def content_text(content):
    """从 message.content 里抽文本/工具调用,返回可读片段列表。"""
    out = []
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                out.append(str(item)); continue
            t = item.get("type")
            if t == "text":
                out.append(item.get("text", ""))
            elif t == "thinking":
                out.append(f"{C['dim']}[thinking] {item.get('thinking','')}{C['x']}")
            elif t == "tool_use":
                inp = json.dumps(item.get("input", {}), ensure_ascii=False)
                out.append(f"{C['y']}▶ {item.get('name','?')}{C['x']} {C['dim']}{shorten(inp, 800)}{C['x']}")
            elif t == "tool_result":
                c = item.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text","") for x in c if isinstance(x, dict) and x.get("type")=="text")
                out.append(f"{C['g']}◀ result{C['x']} {C['dim']}{shorten(c, 1200)}{C['x']}")
    return "\n".join(x for x in out if x)

def render(line, raw=False):
    try:
        d = json.loads(line)
    except Exception:
        return None
    if raw:
        return json.dumps(d, ensure_ascii=False, indent=2)
    typ = d.get("type", "?")
    ts = (d.get("timestamp") or "")[:19].replace("T", " ")
    if typ == "user":
        msg = d.get("message") or {}
        # 跳过纯 tool_result 的 user(已被 assistant 块配对显示),除非有文本
        body = content_text(msg.get("content"))
        is_tool_only = isinstance(msg.get("content"), list) and all(
            isinstance(x, dict) and x.get("type") == "tool_result" for x in msg["content"]
        ) and msg.get("content")
        if is_tool_only:
            return None  # 避免重复,工具结果在 assistant 段已展示
        return f"\n{C['b']}{RENDER_MARK_USER} ({ts}){C['x']}\n{C['bold']}{body}{C['x']}"
    if typ == "assistant":
        msg = d.get("message") or {}
        body = content_text(msg.get("content"))
        u = msg.get("usage") or {}
        usage = ""
        if u:
            usage = f"  {C['dim']}[in {u.get('input_tokens',0)} / out {u.get('output_tokens',0)} / cache {u.get('cache_read_input_tokens',0)}]{C['x']}"
        model = msg.get("model", "?")
        return f"{C['m']}{RENDER_MARK_ASST} [{model}]{C['x']}{usage}\n{body}"
    if typ in ("summary", "ai-title", "attachment", "file-history-snapshot", "mode", "permission-mode", "last-prompt"):
        return f"{C['dim']}[{typ}]{C['x']}"
    return f"{C['dim']}[{typ}] {line[:200]}{C['x']}"

# ---------------------------------------------------------------------------
# --trace 模式:输出会话的"思维链条"
# 每轮展示:用户输入 → ◆想法(thinking) → ▶工具调用(附一句话摘要) → ◇文本回复。
# 命令行摘要是纯规则引擎,不联网:剥掉 sudo/env 前缀后按 &&/;/| 拆段,
# 每段匹配 _BASH_RULES 规则表生成一句中文描述,命不中则显示命令前 60 字符。
_BASH_RULES = [
    (r"^git\s+status",                        "查看 git 工作区状态"),
    (r"^git\s+(log|show)",                    "查看 git 提交历史/某次提交内容"),
    (r"^git\s+diff",                          "查看 git 改动差异"),
    (r"^git\s+branch",                        "查看/管理 git 分支"),
    (r"^git\s+add",                           "暂存文件到 git"),
    (r"^git\s+commit",                        "创建 git 提交"),
    (r"^git\s+push",                          "推送提交到远端仓库"),
    (r"^git\s+(pull|fetch)",                  "从远端仓库拉取更新"),
    (r"^git\s+(checkout|switch)",             "切换 git 分支/工作区文件"),
    (r"^git\s+merge",                         "合并分支"),
    (r"^git\s+rebase",                        "变基分支"),
    (r"^git\s+worktree",                      "管理 git worktree"),
    (r"^git\s+remote",                        "查看/管理 git 远端配置"),
    (r"^git\s+",                              "执行 git 操作"),
    (r"^ls\b",                                "列出目录内容"),
    (r"^cat\b",                               "查看文件内容"),
    (r"^head\b",                              "查看文件开头若干行"),
    (r"^tail\b",                              "查看文件末尾若干行"),
    (r"^(grep|rg)\b",                         "在文件/内容中搜索关键词"),
    (r"^find\b",                              "按名称/条件查找文件"),
    (r"^wc\b",                                "统计文件行数/字数"),
    (r"^mkdir\b",                             "创建目录"),
    (r"^touch\b",                             "创建空文件/更新时间戳"),
    (r"^cp\b",                                "复制文件"),
    (r"^mv\b",                                "移动/重命名文件"),
    (r"^rm\b",                                "删除文件/目录"),
    (r"^chmod\b",                             "修改文件权限"),
    (r"^(curl|wget)\b",                       "发起 HTTP 请求/下载"),
    (r"^ssh\b",                               "连接远程服务器执行命令"),
    (r"^scp\b",                               "跨机复制文件"),
    (r"^(npm|pnpm|yarn)\s+(install|i)\b",     "安装 Node 依赖包"),
    (r"^(npm|pnpm|yarn)\s+(run|test)\b",      "运行 npm 脚本/测试"),
    (r"^(npm|pnpm|yarn)\b",                   "执行 Node 包管理操作"),
    (r"^(pip|pip3)\s+install\b",              "安装 Python 依赖包"),
    (r"^(python|python3)\b.*\.py",            "运行 Python 脚本"),
    (r"^(python|python3)\b",                  "执行 Python 命令"),
    (r"^(node)\b",                            "执行 Node 命令/脚本"),
    (r"^(docker|podman)\s+(ps|images|logs)",  "查看容器/镜像/日志状态"),
    (r"^(docker|podman)\s+(run|exec)",        "启动/进入容器执行命令"),
    (r"^(docker|podman)\s+(build)",           "构建容器镜像"),
    (r"^(docker|podman)\b",                   "执行容器操作"),
    (r"^(kubectl)\b",                         "操作 Kubernetes 集群资源"),
    (r"^(cd)\b",                              "切换工作目录"),
    (r"^(echo)\b",                            "输出文本"),
    (r"^(which|where|type)\b",                "查找可执行文件位置"),
    (r"^(export|set)\b",                      "设置环境变量"),
    (r"^(tar|unzip|gzip)\b",                  "解压/打包文件"),
    (r"^(pytest|unittest)\b",                 "运行 Python 测试"),
    (r"^(make)\b",                            "执行 Makefile 构建目标"),
]

def summarize_bash(cmd):
    """对 Bash 工具的命令给出一句'大概干了什么'的总结(纯规则,不联网)。"""
    cmd = (cmd or "").strip()
    # 去掉 sudo / 环境变量前缀,便于匹配
    m = re.match(r"^(?:sudo\s+|[\w]+=\S+\s+)*", cmd)
    body = cmd[m.end():]
    # 管道/&& 组合:总结每一段,用 → 连接
    parts = re.split(r"\s*(?:&&|\|\||;|\|)\s*", body)
    parts = [p for p in parts if p.strip()]
    if len(parts) > 4:
        parts = parts[:4] + ["…"]
    summaries = []
    for p in parts:
        s = None
        for pat, desc in _BASH_RULES:
            if re.search(pat, p.strip()):
                s = desc
                break
        if s is None:
            s = f"执行命令: {p.strip()[:60]}"
        summaries.append(s)
    return " → ".join(summaries)

def summarize_tool(name, inp):
    """非 Bash 工具的一句话摘要。"""
    inp = inp or {}
    try:
        if name == "Read":
            return f"读取文件 {inp.get('file_path','?')}"
        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            return f"{'写入' if name=='Write' else '编辑'}文件 {inp.get('file_path', inp.get('notebook_path','?'))}"
        if name in ("Glob",):
            return f"按模式查找文件 {inp.get('pattern','?')}"
        if name in ("Grep",):
            return f"搜索内容 /{inp.get('pattern','?')}/"
        if name == "Bash":
            return summarize_bash(inp.get("command", ""))
        if name == "Task" or name == "Agent":
            return f"启动子代理({inp.get('subagent_type','general')}): {(inp.get('description') or '')[:50]}"
        if name == "WebSearch":
            return f"联网搜索: {inp.get('query','?')}"
        if name == "WebFetch":
            return f"抓取网页: {inp.get('url','?')}"
        if name == "TodoWrite" or name == "TaskCreate":
            return "更新任务清单"
        # 其他工具:显示前 100 字符的入参
        s = json.dumps(inp, ensure_ascii=False)
        return f"入参: {s[:100]}"
    except Exception:
        return ""

def _clip(s, n):
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + " …"

def trace_session(path, max_think=600):
    """按轮次回放思维链条:用户输入 → ◆想法 → ▶工具(含命令总结) → ◇回复。"""
    step = 0
    print(f"{C['c']}═══ 思维链条回放: {os.path.basename(path)} ═══{C['x']}\n")
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            typ = d.get("type")
            ts = (d.get("timestamp") or "")[:19].replace("T", " ")
            if typ == "user":
                msg = d.get("message") or {}
                c = msg.get("content")
                # 只显示用户真正输入的文本,跳过 tool_result 回包
                text = ""
                if isinstance(c, str):
                    text = c
                elif isinstance(c, list):
                    texts = [x.get("text","") for x in c if isinstance(x, dict) and x.get("type")=="text"]
                    text = "\n".join(t for t in texts if t.strip())
                if text.strip():
                    step += 1
                    print(f"{C['b']}【第 {step} 轮 · 用户输入】({ts}){C['x']}")
                    print(f"{C['bold']}  {_clip(text, 300)}{C['x']}\n")
            elif typ == "assistant":
                msg = d.get("message") or {}
                c = msg.get("content")
                if not isinstance(c, list):
                    continue
                for item in c:
                    if not isinstance(item, dict):
                        continue
                    t = item.get("type")
                    if t == "thinking":
                        think = (item.get("thinking") or "").strip()
                        if think:
                            print(f"{C['c']}  ◆ 想法: {C['x']}{C['dim']}{_clip(think, max_think)}{C['x']}")
                    elif t == "text":
                        txt = (item.get("text") or "").strip()
                        if txt:
                            print(f"{C['m']}  ◇ 回复: {_clip(txt, 400)}{C['x']}")
                    elif t == "tool_use":
                        name = item.get("name", "?")
                        summary = summarize_tool(name, item.get("input", {}))
                        print(f"{C['y']}  ▶ 工具 {name}{C['x']}: {summary}")
                        if name == "Bash":
                            cmd = (item.get("input") or {}).get("command", "")
                            print(f"{C['dim']}      $ {_clip(cmd, 200)}{C['x']}")
                # 每个 assistant 块之后空一行,形成"一步"
                print()
    print(f"{C['c']}═══ 回放结束,共 {step} 轮对话 ═══{C['x']}")

def main():
    ap = argparse.ArgumentParser(description="实时跟踪 Claude Code session 的完整输入输出")
    ap.add_argument("path", nargs="?", help="jsonl 路径或 session id(前缀即可);不填则 --select 或自动选最新")
    ap.add_argument("--select", action="store_true", help="交互式从所有 session 里选一个(多窗口时用)")
    ap.add_argument("--list", action="store_true", help="只列出最近 session,不跟踪")
    ap.add_argument("--raw", action="store_true", help="打印完整 JSON(等价 jq .)")
    ap.add_argument("--all", action="store_true", help="从头到尾全量回放整个会话历史后退出")
    ap.add_argument("--tail", type=int, default=0, help="回放最后 N 行后退出(0=实时跟踪新模式)")
    ap.add_argument("--grep", default=None, help="只显示包含该关键词的消息(忽略大小写)")
    ap.add_argument("--trace", action="store_true", help="输出会话的思维链条(想法/工具/命令总结)后退出")
    ap.add_argument("--think", type=int, default=600, help="--trace 时 thinking 每段最多显示字符数(默认600)")
    ap.add_argument("--ascii", action="store_true", help="纯 ASCII 框线,不依赖 Unicode/ANSI(老终端用)")
    ap.add_argument("--projects", default=None, help=f"Claude transcript 目录(默认 {DEFAULT_PROJ})")
    ap.add_argument("--resume", default=None, metavar="ID",
                    help="在会话原工作目录起新的 claude 进程并 resume 该会话(参数为 session id 前缀)")
    ap.add_argument("--path", dest="path_opt", default=None, metavar="ID",
                    help="只输出该会话 transcript 文件的完整路径(参数为 session id 前缀)")
    args = ap.parse_args()

    # 允许指向非默认的 projects 目录
    global PROJ
    if args.projects:
        PROJ = os.path.expanduser(args.projects)

    # ASCII 模式:把所有框线/特殊符号替换成纯 ASCII,关闭颜色
    if args.ascii:
        for k in list(C.keys()):
            C[k] = ""
        global RENDER_MARK_USER, RENDER_MARK_ASST
        RENDER_MARK_USER = ">> 你"
        RENDER_MARK_ASST = "<< Claude"

    # --path <前缀>:解析成唯一 session 后,只输出 transcript 文件完整路径
    if args.path_opt:
        prefix = args.path_opt
        rows = list_sessions()
        matches = [r[0] for r in rows if os.path.basename(r[0]).startswith(prefix)]
        if not matches:
            sys.exit(f"找不到匹配 '{prefix}' 的 session")
        if len(matches) > 1:
            sys.exit(f"session 前缀 '{prefix}' 匹配到 {len(matches)} 个,请用更长的前缀:\n  "
                     + "\n  ".join(os.path.basename(m) for m in matches))
        print(matches[0])
        return

    # --resume <前缀>:解析成唯一 session 后,在原工作目录起新 claude 进程恢复会话
    if args.resume:
        prefix = args.resume
        rows = list_sessions()
        matches = [r[0] for r in rows if os.path.basename(r[0]).startswith(prefix)]
        if not matches:
            sys.exit(f"找不到匹配 '{prefix}' 的 session")
        if len(matches) > 1:
            sys.exit(f"session 前缀 '{prefix}' 匹配到 {len(matches)} 个,请用更长的前缀:\n  "
                     + "\n  ".join(os.path.basename(m) for m in matches))
        path = matches[0]
        sid = os.path.basename(path)[:-6]
        # 会话原工作目录(从 transcript 头部 cwd 字段取,取不到退回用户目录)
        _, cwd, _, _ = _read_meta(path)
        if not cwd or not os.path.isdir(cwd):
            cwd = os.path.expanduser("~")
        import shutil
        claude_bin = shutil.which("claude")
        if not claude_bin:
            sys.exit("找不到 claude 可执行文件,请确认已安装并在 PATH 中")
        print(f"{C['c']}→ resume 会话 {sid}\n  工作目录 {cwd}{C['x']}", flush=True)
        import subprocess
        rc = subprocess.call([claude_bin, "--resume", sid], cwd=cwd)
        sys.exit(rc)

    # --trace <前缀|路径>:解析成唯一 session 后,输出思维链条回放并退出
    if args.trace:
        if not args.path:
            sys.exit("用法: watch-cc --trace <sessionId前缀>   # 前缀来自 watch-cc --list")
        if os.path.exists(args.path):
            tpath = args.path
        else:
            trows = list_sessions()
            tmatches = [r[0] for r in trows if os.path.basename(r[0]).startswith(args.path)]
            if not tmatches:
                sys.exit(f"找不到匹配 '{args.path}' 的 session")
            if len(tmatches) > 1:
                sys.exit(f"session 前缀 '{args.path}' 匹配到 {len(tmatches)} 个,请用更长的前缀:\n  "
                         + "\n  ".join(os.path.basename(m) for m in tmatches))
            tpath = tmatches[0]
        trace_session(tpath, args.think)
        return

    # --list:只列出不跟踪
    if args.list:
        rows = list_sessions()
        if not rows:
            sys.exit(f"找不到任何 .jsonl,请检查 {PROJ}")
        import datetime
        print(f"{C['c']}共 {len(rows)} 个 session(★=近15分钟活跃):{C['x']}\n")
        for i, (p, sid, cwd, first_user, n, mtime, active) in enumerate(rows[:30], 1):
            star = f"{C['y']}★{C['x']}" if active else " "
            ago = datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            cwd_short = (cwd or "?").replace("\\", "/").split("/")[-1]
            hint = (first_user or "").replace("\n", " ")[:40]
            print(f"  [{i:>2}]{star} {C['dim']}{ago}{C['x']}  "
                  f"{C['g']}{cwd_short:<24}{C['x']} "
                  f"{C['b']}{sid[:8]}{C['x']}  "
                  f"{C['dim']}{hint}{C['x']}")
        return

    # 决定要跟踪哪个文件
    if args.path:
        # path 可以是完整路径,也可以是 session id 前缀
        if os.path.exists(args.path):
            path = args.path
        else:
            # 当作 session id 前缀去匹配
            rows = list_sessions()
            matches = [r[0] for r in rows if os.path.basename(r[0]).startswith(args.path)]
            if len(matches) == 1:
                path = matches[0]
            elif len(matches) > 1:
                sys.exit(f"session 前缀 '{args.path}' 匹配到 {len(matches)} 个,请用更长的前缀:\n  "
                         + "\n  ".join(os.path.basename(m) for m in matches))
            else:
                sys.exit(f"找不到匹配 '{args.path}' 的 session")
    elif args.select:
        path = pick_session_interactive()
    else:
        path = newest_jsonl()
    print(f"{C['c']}跟踪: {path}{C['x']}\n", flush=True)

    # 启用终端的 ANSI 颜色支持
    #   Windows 10+ 需要显式调 SetConsoleMode;macOS/Linux 终端默认就支持。
    if sys.platform == "win32" and not args.ascii:
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            # STD_OUTPUT_HANDLE = -11; ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            k32.SetConsoleMode(k32.GetStdHandle(-11), 7)
        except Exception:
            pass

    def emit(line):
        """渲染一行并打印,应用 --grep 过滤。"""
        out = render(line, args.raw)
        if not out:
            return
        if args.grep and args.grep.lower() not in _strip_ansi(out).lower():
            return
        print(out, flush=True)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        if args.all:
            # 全量回放:从头到尾,打印完退出
            count = 0
            for line in f:
                emit(line)
                count += 1
            print(f"{C['dim']}— 全量回放完成,共 {count} 条记录 —{C['x']}")
            return
        if args.tail:
            # 回放最后 N 行后退出
            import collections
            buf = collections.deque(f, maxlen=args.tail)
            for line in buf:
                emit(line)
            return
        # 实时模式:跳到文件尾,只看新增
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.3); continue
            emit(line)

if __name__ == "__main__":
    main()
