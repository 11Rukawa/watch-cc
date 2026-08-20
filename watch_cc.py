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

def main():
    ap = argparse.ArgumentParser(description="实时跟踪 Claude Code session 的完整输入输出")
    ap.add_argument("path", nargs="?", help="jsonl 路径或 session id(前缀即可);不填则 --select 或自动选最新")
    ap.add_argument("--select", action="store_true", help="交互式从所有 session 里选一个(多窗口时用)")
    ap.add_argument("--list", action="store_true", help="只列出最近 session,不跟踪")
    ap.add_argument("--raw", action="store_true", help="打印完整 JSON(等价 jq .)")
    ap.add_argument("--all", action="store_true", help="从头到尾全量回放整个会话历史后退出")
    ap.add_argument("--tail", type=int, default=0, help="回放最后 N 行后退出(0=实时跟踪新模式)")
    ap.add_argument("--grep", default=None, help="只显示包含该关键词的消息(忽略大小写)")
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
