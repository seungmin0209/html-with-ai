# html-with-ai — Edit & Tell <Agent> what to do

AI 와 함께 만든 HTML 을 브라우저에서 바로 고치고(이중클릭), 문구에 댓글을 달아(우클릭) 작업 중인 에이전트 세션에 돌려보내는 도구.
Claude Code · Codex · Gemini CLI 어디서든 같은 화면. 파이썬 3 표준 라이브러리만 쓴다 (Mac/Windows/Linux).

```bash
sh install.sh                                          # Mac/Linux — 파이썬 3 없으면 설치까지
powershell -ExecutionPolicy Bypass -File install.ps1   # Windows  — winget 으로 파이썬 3 설치까지
python3 review.py <문서.html> --agent Codex            # Windows 는 python. http://localhost:8901
```

파이썬 3 외 의존성은 없다. 에이전트가 설치 스크립트를 대신 실행해도 된다. `~/.claude` 쓰기가 막힌 환경이면 zip 을 풀어 넣는 한 줄만 직접 실행한다
(Mac `unzip ~/Downloads/html-with-ai.zip -d ~/.claude/skills/` · Windows `Expand-Archive "$HOME\Downloads\html-with-ai.zip" -DestinationPath "$HOME\.claude\skills\" -Force`).

설치 스크립트가 PostToolUse 훅을 등록해, 에이전트가 .html 을 저장할 때마다 스킬 이름을 부르지 않아도 자동으로 발동한다.

에이전트 규약(무엇을 언제 띄우고, 제출 이벤트를 어떻게 처리하는지)은 `SKILL.md` 에 있다. Claude Code 는 스킬로 자동 로드되고,
Codex 는 `AGENTS.md` 에, Gemini 는 `GEMINI.md` 에 "HTML 산출물은 html-with-ai 규약(SKILL.md)으로 띄운다" 한 줄을 넣으면 같은 규약을 따른다.

제출 이벤트는 `<문서 폴더>/_review_events.jsonl` 에 한 줄 JSON 으로 쌓인다:
`{"edits":[{path,before,after}], "comments":[{n,path,anchor,quote,text}], "doc", "agent", "ts", "status":"new"}`
