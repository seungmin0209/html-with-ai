#!/usr/bin/env python3
"""~/.claude/settings.json 에 html-with-ai PostToolUse 훅을 등록한다(있으면 갱신). 사용자 터미널에서 실행 — Claude Code 는 ~/.claude 쓰기를 막는다.
    python3 register_hook.py          # 등록
    python3 register_hook.py --remove # 해제
"""
import json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
S = pathlib.Path.home() / ".claude" / "settings.json"
cfg = json.loads(S.read_text()) if S.exists() else {}
hooks = cfg.setdefault("hooks", {}); post = hooks.setdefault("PostToolUse", [])
post[:] = [g for g in post if not any("html-with-ai/hook.py" in (h.get("command") or "") for h in g.get("hooks", []))]
if "--remove" not in sys.argv:
    hook = str(HERE / "hook.py").replace("\\", "/")
    post.append({"matcher": "Write|Edit|MultiEdit|NotebookEdit",
                 "hooks": [{"type": "command", "timeout": 10,
                            "command": f'python3 "{hook}" 2>/dev/null || python "{hook}"'}]})
S.parent.mkdir(exist_ok=True); S.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
print(("해제" if "--remove" in sys.argv else "등록") + f": {S}  (PostToolUse → hook.py). Claude Code 를 새로 열면 적용된다.")
