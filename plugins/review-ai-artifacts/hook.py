#!/usr/bin/env python3
"""review-ai-artifacts 훅 — 에이전트가 HTML·md 산출물을 만들면 어떤 도구로 만들었든 편집 화면이 뜨게 한다.

PostToolUse (Write|Edit|MultiEdit|NotebookEdit|Bash)
  - Write/Edit: tool_input.file_path 가 .html 이면 대상.
  - Bash: tool_input.command 에서 .html/.htm 경로를 뽑아, 실제로 존재하고 최근 60초 안에 바뀐 것만 대상(가장 최근 1개).
    cat > x.html <<EOF, tee, sed -i, cp, python 스크립트 등 어떤 경로든 잡힌다.
Stop (턴 종료)
  - 훅이 놓친 경우의 안전망. cwd 아래에서 이 세션 시작 이후 바뀐 .html 중 아직 처리하지 않은 것이 있으면 그때 발동한다.
    stop_hook_active 면 재발동하지 않는다(무한 루프 방지).

설정(mode)에 따라: always → review.py 를 직접 띄우고 알린다 · ask → "띄울까요?" 물어라 · cases → 해당하면 띄워라 · off → 침묵.
설정 파일이 없으면 mode=ask 로 만들고 first_run 을 표시해 "발동 방식을 먼저 물어라" 를 한 번 넣는다.
처리한 문서는 ~/.config/review-ai-artifacts/state.json 에 세션별로 기록해 같은 문서를 두 번 띄우지 않는다.
"""
import sys, os, re, json, pathlib, subprocess, socket, time, urllib.request
HERE = pathlib.Path(__file__).resolve().parent
CFG_DIR = pathlib.Path.home() / ".config" / "review-ai-artifacts"
CONFIG, STATE = CFG_DIR / "config.json", CFG_DIR / "state.json"
PY = sys.executable or "python3"
RECENT = 60          # Bash 경로 후보의 mtime 허용(초)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache", ".agents", ".claude", ".codex", "memory", "handoffs"}
SKIP_MD = {"claude.md", "agents.md", "gemini.md", "readme.md", "skill.md", "changelog.md", "license.md", "contributing.md", "memory.md", "todo.md"}   # 규약·설정 성격의 md 는 산출물이 아니다
ART_EXT = (".html", ".htm", ".md", ".markdown")
def is_artifact(p):
    n = p.name.lower()
    if not n.endswith(ART_EXT) or n.endswith(".bak") or "_review_" in n: return False
    if n.endswith((".md", ".markdown")) and (n in SKIP_MD or n.startswith(("status", "handoff", "_"))): return False
    return not any(part in SKIP_DIRS for part in p.parts)

def emit(event, ctx):
    if event == "Stop":
        print(json.dumps({"decision": "block", "reason": ctx}, ensure_ascii=False))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False))
    sys.exit(0)

def load_json(p, default):
    try: return json.loads(p.read_text())
    except Exception: return default

def config():
    cfg = load_json(CONFIG, None)
    if cfg is None:                                   # [4] 기본 설정을 만들어 두고 첫 사용을 표시
        cfg = {"mode": "ask", "cases": [], "first_run": True, "created": time.strftime("%Y-%m-%d")}
        CFG_DIR.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    return cfg

def state(): return load_json(STATE, {})
def mark(sid, doc):
    st = state(); s = st.setdefault(sid, {"started": time.time(), "handled": []})
    if str(doc) not in s["handled"]: s["handled"].append(str(doc))
    CFG_DIR.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, ensure_ascii=False))
def session_start(sid):
    st = state(); s = st.setdefault(sid, {"started": time.time(), "handled": []})
    if len(st) > 50:                                  # 오래된 세션 정리
        for k in sorted(st, key=lambda k: st[k]["started"])[:-30]: st.pop(k, None)
    STATE.write_text(json.dumps(st, ensure_ascii=False)); return s

def launch(doc, agent):
    """review.py 가 문서별 고정 포트를 고른다. 이미 떠 있으면 그 주소를 돌려준다."""
    CFG_DIR.mkdir(parents=True, exist_ok=True); log = open(CFG_DIR / "server.log", "a")
    kw = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen([PY, str(HERE / "review.py"), str(doc), "--agent", agent, "--no-open"], stdout=subprocess.PIPE, stderr=log, text=True, **kw)
    url = None
    for _ in range(40):                      # 첫 줄(들)에서 URL 을 읽는다 — 최대 2초
        line = p.stdout.readline()
        if not line: break
        m = re.search(r"http://localhost:(\d+)/", line)
        if m: url = int(m.group(1)); break
    return url or 8901
def serving(doc):
    for p in range(8901, 8991):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/doc", timeout=0.2) as r:
                if r.read().decode() == str(doc): return p
        except Exception: pass
    return None

HTML_RE = re.compile(r"""(?<![\w./-])((?:~|\.{1,2})?/?[^\s'"`;|&<>()]*?\.(?:html?|md|markdown))(?=$|[\s'"`;|&<>)])""", re.I)
def candidates_from_command(cmd, cwd):
    out = []
    for m in HTML_RE.findall(cmd or ""):
        p = pathlib.Path(os.path.expanduser(m)); p = p if p.is_absolute() else pathlib.Path(cwd or ".") / p
        try:
            if p.is_file() and time.time() - p.stat().st_mtime <= RECENT: out.append(p.resolve())
        except OSError: pass
    return sorted(set(out), key=lambda p: p.stat().st_mtime, reverse=True)

def recent_htmls(cwd, since, handled):
    found = []
    for root, dirs, files in os.walk(cwd or "."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = pathlib.Path(root, f).resolve()
            if is_artifact(p):
                try:
                    if p.stat().st_mtime >= since and str(p) not in handled: found.append(p)
                except OSError: pass
        if len(found) > 200: break
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

def instruct(event, doc, cfg, agent, sid):
    skill = HERE / "SKILL.md"; rv = HERE / "review.py"
    lead = "[review-ai-artifacts]" + (" (턴 종료 안전망 — 저장 훅이 놓친 HTML)" if event == "Stop" else "")
    if cfg.get("first_run"):
        cfg["first_run"] = False; CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1)); mark(sid, doc)
        emit(event, f"{lead} 이 스킬을 처음 쓴다. 산출물 '{doc.name}' 을 편집 화면으로 띄우기 전에, 사용자에게 채팅으로 네 가지를 한 문장씩 설명하고 하나를 고르게 하라: "
             "always(HTML 만들 때마다 자동) · ask(매번 물어보기) · cases(아티팩트·보고서 등 특정 경우만) · off(명시 요청에만). 기본은 ask 로 저장돼 있다. "
             f"고르면 `{PY} \"{rv}\" --set-mode <mode> [--cases a,b]` 로 저장하고, \"언제든 '리뷰 모드 항상/물어봐/특정 경우만/끄기' 라고 말하면 바꿀 수 있다\" 고 덧붙여라. "
             f"always/ask(예)/cases(해당) 이면 이어서 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일 `{doc.parent/'_review_events.jsonl'}` 을 지켜본다. 규약: {skill}")
    mode = cfg.get("mode", "ask")
    if mode == "off": sys.exit(0)
    mark(sid, doc)
    if mode == "ask":
        emit(event, f"{lead} 발동 방식이 ask 다. 사용자에게 \"'{doc.name}' 을 편집·댓글 화면으로 띄울까요?\" 한 줄만 물어라. 예라고 하면 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 규약: {skill}")
    if mode == "cases":
        emit(event, f"{lead} 발동 방식이 cases={cfg.get('cases')} 다. '{doc.name}' 이 그 경우에 해당하면 `{PY} \"{rv}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 아니면 띄우지 않는다. 규약: {skill}")
    port = serving(doc) or launch(doc, agent)
    emit(event, f"{lead} '{doc.name}' 을 편집·댓글 화면으로 띄웠다: http://localhost:{port}/ . 사용자에게 이 주소와 \"이중클릭으로 고치고 우클릭으로 댓글, 끝나면 [진행중인 {agent} Session에 제출]\" 을 한 줄로 알려라. "
         f"제출 이벤트 파일을 지켜봐라(Claude Code 는 Monitor persistent): {doc.parent/'_review_events.jsonl'} — status \"new\" 줄이 오면 edits 는 반영 확인, comments 는 파일을 고쳐 저장하고 status 를 done 으로. 규약: {skill}")

def main():
    try: ev = json.load(sys.stdin)
    except Exception: sys.exit(0)
    event = ev.get("hook_event_name") or ("Stop" if "stop_hook_active" in ev else "PostToolUse")
    sid = ev.get("session_id") or "nosession"; cwd = ev.get("cwd") or os.getcwd()
    cfg = config(); agent = os.environ.get("HTML_WITH_AI_AGENT") or cfg.get("agent") or "Claude"
    sess = session_start(sid)
    if event == "Stop":
        if ev.get("stop_hook_active"): sys.exit(0)
        docs = recent_htmls(cwd, sess["started"] - 5, set(sess["handled"]))
        if not docs: sys.exit(0)
        instruct("Stop", docs[0], cfg, agent, sid)
    tool = ev.get("tool_name") or ""; ti = ev.get("tool_input") or {}
    if tool == "Bash":
        docs = candidates_from_command(ti.get("command", ""), cwd)
        if not docs: sys.exit(0)
        doc = docs[0]
    else:
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if not fp.lower().endswith(ART_EXT): sys.exit(0)
        doc = pathlib.Path(fp).resolve()
    if not doc.exists() or not is_artifact(doc): sys.exit(0)
    if str(doc) in sess["handled"] and serving(doc): sys.exit(0)   # 이미 띄운 문서를 다시 고친 것 — 화면이 자동 새로고침한다
    instruct("PostToolUse", doc, cfg, agent, sid)

if __name__ == "__main__": main()
