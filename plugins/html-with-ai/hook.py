#!/usr/bin/env python3
"""html-with-ai PostToolUse 훅 — 에이전트가 .html 파일을 쓰거나 고칠 때마다 자동으로 돈다.

stdin 으로 Claude Code 훅 JSON 을 받고, 파일이 .html 이면 설정(mode)에 따라
  always → review.py 를 띄우고 "띄웠다" 를 에이전트 문맥에 넣는다
  ask    → "사용자에게 띄울지 물어라" 를 문맥에 넣는다
  cases  → "이 경우가 cases 에 해당하면 띄워라" 를 문맥에 넣는다
  off    → 아무 말도 하지 않는다
  (설정 없음) → "처음이니 발동 방식을 먼저 물어라" 를 문맥에 넣는다
스킬 이름을 타이핑하지 않아도 이 훅이 있으면 매번 같은 자리에서 발동한다.
"""
import sys, os, json, pathlib, subprocess, socket, time
HERE = pathlib.Path(__file__).resolve().parent
CONFIG = pathlib.Path.home() / ".config" / "html-with-ai" / "config.json"
PY = sys.executable or "python3"

def out(ctx):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}, ensure_ascii=False)); sys.exit(0)

def free_port(start=8901):
    for p in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0: return p
    return start

def already(doc):
    """같은 문서를 띄운 서버가 있으면 그 포트를 돌려준다 (서버가 /doc 로 경로를 알려 준다)."""
    for p in range(8901, 8921):
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/doc", timeout=0.3) as r:
                if r.read().decode() == str(doc): return p
        except Exception: pass
    return None

try: ev = json.load(sys.stdin)
except Exception: sys.exit(0)
fp = (ev.get("tool_input") or {}).get("file_path") or ""
if not fp.lower().endswith((".html", ".htm")): sys.exit(0)
doc = pathlib.Path(fp).resolve()
if not doc.exists() or "/_review_" in str(doc): sys.exit(0)
cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else None
agent = os.environ.get("HTML_WITH_AI_AGENT") or (cfg or {}).get("agent") or "Claude"
skill = HERE / "SKILL.md"

if cfg is None:
    out(f"[html-with-ai] 이 스킬은 설치돼 있지만 발동 방식이 아직 정해지지 않았다(처음 사용). 산출물 '{doc.name}' 을 편집 화면으로 띄우기 전에, "
        "사용자에게 채팅으로 네 가지를 한 문장씩 설명하고 하나를 고르게 하라: always(HTML 만들 때마다 자동) · ask(매번 물어보기) · cases(아티팩트·보고서 등 특정 경우만) · off(명시 요청에만). "
        f"고르면 `{PY} \"{HERE/'review.py'}\" --set-mode <mode> [--cases a,b]` 로 저장하고, \"언제든 '리뷰 모드 항상/물어봐/특정 경우만/끄기' 라고 말하면 바꿀 수 있다\" 고 덧붙여라. "
        f"always/ask(예)/cases(해당) 이면 이어서 이 파일을 review.py 로 띄워라. 규약: {skill}")
mode = cfg.get("mode", "ask")
if mode == "off": sys.exit(0)
if mode == "ask":
    out(f"[html-with-ai] 발동 방식이 ask 다. 사용자에게 \"'{doc.name}' 을 편집·댓글 화면으로 띄울까요?\" 한 줄만 물어라. 예라고 하면 `{PY} \"{HERE/'review.py'}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 규약: {skill}")
if mode == "cases":
    out(f"[html-with-ai] 발동 방식이 cases={cfg.get('cases')} 다. 이 산출물 '{doc.name}' 이 그 경우(예: 아티팩트 배포, 보고서, 대시보드)에 해당하면 `{PY} \"{HERE/'review.py'}\" \"{doc}\" --agent {agent}` 를 백그라운드로 띄우고 이벤트 파일을 지켜본다. 해당하지 않으면 띄우지 않는다. 규약: {skill}")

# always — 훅이 직접 띄운다
port = already(doc)
if port is None:
    port = free_port()
    log = open(pathlib.Path.home() / ".config" / "html-with-ai" / "server.log", "a")
    kw = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}   # Windows DETACHED_PROCESS
    subprocess.Popen([PY, str(HERE / "review.py"), str(doc), "--agent", agent, "--port", str(port), "--no-open"], stdout=log, stderr=log, **kw)
    time.sleep(0.6)
events = doc.parent / "_review_events.jsonl"
out(f"[html-with-ai] '{doc.name}' 을 편집·댓글 화면으로 띄웠다: http://localhost:{port}/ . 사용자에게 이 주소와 \"이중클릭으로 고치고 우클릭으로 댓글, 끝나면 [진행중인 {agent} Session에 제출]\" 을 한 줄로 알려라. "
    f"그리고 제출 이벤트 파일을 지켜봐라(Claude Code 는 Monitor persistent): {events} — 새 줄에 status \"new\" 가 오면 edits 는 반영 확인, comments 는 파일을 고쳐 저장하고 status 를 done 으로 바꾼다. 규약: {skill}")
