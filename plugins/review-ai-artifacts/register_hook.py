#!/usr/bin/env python3
"""~/.claude/settings.json 에 review-ai-artifacts PostToolUse 훅을 등록한다(있으면 갱신). 사용자 터미널에서 실행 — Claude Code 는 ~/.claude 쓰기를 막는다.
    python3 register_hook.py          # 등록
    python3 register_hook.py --remove # 해제
"""
import os, json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
S = pathlib.Path.home() / ".claude" / "settings.json"
cfg = json.loads(S.read_text(encoding="utf-8")) if S.exists() else {}
hooks = cfg.setdefault("hooks", {})
def clean(lst): return [g for g in lst if not any(any(n in (h.get("command") or "") for n in ("review-ai-artifacts/hook.py","html-with-ai/hook.py")) for h in g.get("hooks", []))]
post = hooks["PostToolUse"] = clean(hooks.get("PostToolUse", [])); stop = hooks["Stop"] = clean(hooks.get("Stop", []))
if "--remove" not in sys.argv:
    hook = str(HERE / "hook.py").replace("\\", "/")
    # Windows 는 python3 가 Store 별칭이고 2>/dev/null 은 cmd·PowerShell 에서 뜻이 다르다 — install.ps1 이 보장한 python 하나만 부른다
    cmd = {"type": "command", "timeout": 10, "command": f'python "{hook}"' if os.name == "nt" else f'python3 "{hook}" 2>/dev/null || python "{hook}"'}
    post.append({"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [cmd]})   # 저장·Bash 직후
    stop.append({"hooks": [cmd]})                                                       # 턴 종료 안전망
S.parent.mkdir(exist_ok=True); S.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(("해제" if "--remove" in sys.argv else "등록") + f": {S}  (PostToolUse[Write·Edit·Bash] + Stop → hook.py). Claude Code 를 새로 열면 적용된다.")
