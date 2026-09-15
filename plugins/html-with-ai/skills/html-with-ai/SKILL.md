---
name: html-with-ai
description: Edit & Tell <Agent> what to do — 에이전트(Claude · Codex · Gemini 등)가 사용자에게 보여 줄 HTML 산출물(보고서·대시보드·목업·문서 등 어떤 HTML 이든)을 만들거나 고쳐서 완성했을 때 발동한다. 산출물을 브라우저에 "이중클릭 = 수정, 우클릭 = 댓글" 화면으로 띄우고, 사용자가 [진행중인 <Agent> Session에 제출] 을 누르면 수정 내역과 댓글을 받아 반영한다. 트리거 — .html 산출물을 쓰거나 다시 생성한 직후, "편집기 열어줘", "HTML 고치고 싶어", "댓글 달게 해줘", "리뷰 모드".
---

# html-with-ai — Edit & Tell <Agent> what to do

사용자는 완성된 화면을 보면서 고치고 싶어 한다. 코드나 md 를 열어 달라고 하지 않는다.
HTML 산출물을 넘길 때는 파일 경로만 알려 주지 말고 **이 화면으로 띄워서** 넘긴다.
Claude Code · Codex · Gemini CLI 어디서 쓰든 화면과 동작은 같고, 문구의 에이전트 이름만 바뀐다.

## 설치 (폴더 하나 · Mac/Windows/Linux)

- **권장(Claude Code)**: 에이전트가 터미널에서 `claude plugin marketplace add seungmin0209/html-with-ai && claude plugin install html-with-ai@html-with-ai`. 사용자가 직접이면 입력창에 `/plugin …` 같은 두 줄. 파일 복사·권한 문제 없이 훅까지 설치된다. 아래는 그 밖의 방법이다.

```bash
# Mac / Linux
sh install.sh
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File install.ps1
```

- 설치 스크립트가 **파이썬 3가 없으면 먼저 설치한다** (Mac: Homebrew 또는 Apple 개발자 도구 · Windows: `winget install Python.Python.3.12` · Linux: apt/dnf).
  그 다음 Claude Code 스킬 위치(`~/.claude/skills/html-with-ai`, Windows 는 `%USERPROFILE%\.claude\skills\html-with-ai`)에 넣는다.
- **에이전트가 직접 해도 된다.** 사용자가 스킬 폴더만 받아 두었으면, 에이전트가 이 스크립트를 실행해 파이썬까지 깔고 진행한다.
  단 Claude Code 는 `~/.claude` 아래 쓰기를 막는 경우가 있다. 그때는 마지막 복사 한 줄만 사용자에게 넘긴다 —
  Mac: `unzip ~/Downloads/html-with-ai.zip -d ~/.claude/skills/` · Windows: `Expand-Archive "$HOME\Downloads\html-with-ai.zip" -DestinationPath "$HOME\.claude\skills\" -Force`
  `review.py` 실행이 "python3 를 찾을 수 없다" 로 실패하면 사용자에게 설치를 시키지 말고 install 스크립트를 먼저 돌린다.
- Codex 는 프로젝트 `AGENTS.md` 에, Gemini CLI 는 `GEMINI.md` 에 "HTML 산출물은 <경로>/SKILL.md 규약(html-with-ai)으로 띄운다" 한 줄.
- 실행 명령은 Mac/Linux `python3`, Windows `python`. 설정은 `~/.config/html-with-ai/config.json` 하나.

## 발동은 훅이 보장한다 — 스킬 이름을 타이핑할 필요가 없다

`install.sh` / `install.ps1` 이 `~/.claude/settings.json` 에 **PostToolUse 훅**(`hook.py`)을 등록한다. 에이전트가 `.html` 파일을 쓰거나 고칠 때마다
훅이 돌아 설정(mode)에 맞는 지시를 에이전트 문맥에 넣는다. 스킬 설명에 의존하지 않으므로 "왜 이번엔 안 떴지" 가 없다.

| 상태 | 훅이 하는 일 |
|---|---|
| 설정 없음(처음) | "발동 방식을 먼저 물어라" 를 넣는다 → 에이전트가 채팅으로 네 가지를 설명하고 저장한 뒤 띄운다 |
| `always` | 훅이 **직접** `review.py` 를 띄우고 주소·이벤트 파일 경로를 넣는다. 에이전트는 사용자에게 한 줄 알리고 감시만 건다 |
| `ask` | "띄울까요? 한 줄 물어라" 를 넣는다 |
| `cases` | "이 경우에 해당하면 띄워라" 를 넣는다 |
| `off` | 아무것도 넣지 않는다 |

훅 등록만 따로 하려면 `python3 register_hook.py`, 해제는 `--remove`. 사용자 터미널에서 실행한다(Claude Code 는 `~/.claude` 쓰기를 막는다).

## 발동 방식 — 처음 한 번 묻고, 언제든 바꿀 수 있다

`python3 review.py --show-config` 로 본다. **설정 파일이 없으면(처음 사용) 산출물을 띄우기 전에 먼저 묻는다.**
채팅으로 네 가지를 한 문장씩 설명하고 고르게 한 뒤 `--set-mode` 로 저장하고,
**"언제든 '리뷰 모드 항상/물어봐/특정 경우만/끄기' 라고 말하면 바꿀 수 있다"** 고 한 줄 덧붙인다.

| mode | 동작 |
|---|---|
| `always` | HTML 산출물이 나올 때마다 자동으로 띄운다 |
| `ask` | 산출물이 나오면 "편집·댓글 화면으로 띄울까요?" 한 줄만 묻는다 |
| `cases` | `cases` 에 적힌 경우에만 자동. 예: `artifact`(외부 배포), `report`, `dashboard`, `mockup` |
| `off` | 자동 발동 없음. "편집기 열어줘" 같은 명시 요청에만 |

```bash
python3 review.py --set-mode always            # 또는 ask / cases --cases artifact,report / off
python3 review.py --set-initial 승             # 댓글 마커에 보일 한 글자
python3 review.py --set-agent Codex            # 환경변수로 감지되지 않을 때 기본 이름
```

사용자가 나중에 "리뷰 모드 꺼", "이제 매번 띄워" 처럼 말하면 같은 명령으로 갱신하고 결과를 한 줄 알린다. 명시 요청은 mode 와 무관하게 항상 띄운다.

## 에이전트가 할 일 (발동이 결정된 산출물마다)

1. HTML 을 다 쓰고 나서 편집기를 백그라운드로 띄운다. 같은 포트에 떠 있으면 먼저 내린다. `--agent` 에는 **자기 이름**을 넣는다 (Claude / Codex / Gemini …). 환경변수로 감지되면 생략해도 된다.
   ```bash
   # Mac/Linux
   pkill -f "review.py" ; nohup python3 <이 폴더>/review.py "<산출물.html>" --agent Claude --port 8901 >/tmp/html-with-ai.log 2>&1 &
   # Windows (PowerShell)
   Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*review.py*"} | Stop-Process; Start-Process python -ArgumentList '<이 폴더>\review.py','<산출물.html>','--agent','Claude','--port','8901' -WindowStyle Hidden
   ```
2. 이벤트 파일을 지켜본다. Claude Code 는 `Monitor`(persistent), 다른 에이전트는 백그라운드 `tail -F` 또는 폴링.
   ```bash
   F="<산출물 폴더>/_review_events.jsonl"; touch "$F"; tail -n0 -F "$F" | grep --line-buffered '"status": "new"'
   ```
   Windows 는 `Get-Content -Wait -Tail 0 <파일> | Select-String '"status": "new"'`. 감시 수단이 없으면 사용자가 "제출했어" 라고 말할 때 파일을 읽어도 된다.
3. 사용자에게는 "http://localhost:8901 에 띄웠다. 이중클릭으로 고치고 우클릭으로 댓글, 끝나면 제출" 한 줄만 말한다.
4. 이벤트 한 줄 JSON 을 읽는다.
   - `edits[]` `{path, before, after}` — 사용자가 직접 고친 글자. **파일에는 이미 저장돼 있다.** 다시 쓰지 말고 요약해 "수정 N건 반영 확인" 이라고 알린다. 생성 스크립트가 있는 문서면 원본(md·json·py)에도 같은 수정을 반영한다.
   - `comments[]` `{n, path, anchor, quote, text}` — 요청. `quote` 가 있으면 그 문구만, 없으면 `anchor` 요소 전체가 대상. 파일을 고쳐 저장하고 번호별로 무엇을 어떻게 바꿨는지 답한다. 판단이 갈리면 그 번호만 물어본다.
   - 처리한 줄은 `status` 를 `done` 으로 바꾼다. 배포 대상(아티팩트 등)이 있으면 같은 링크에 갱신한다.
   - 편집기는 파일 변경을 2초마다 감지해 **자동으로 새로 고친다**. 사용자가 편집 중이면 저장 뒤에 불러온다. 파일을 고쳐 저장하는 것으로 끝이다.
5. 세션이 바뀌면 다음 세션이 `_review_events.jsonl` 의 `status: new` 줄을 먼저 처리한다.

## 사용자 조작

| 조작 | 결과 |
|---|---|
| 이중클릭 | 그 자리에서 글자 수정 (서식·링크 유지). 바깥 클릭으로 끝 |
| 우클릭 | 그 요소에 댓글. 문구를 드래그해 고른 뒤 우클릭하면 **그 문구에만** 댓글. 적기 전이면 바깥 클릭·Esc 로 닫힘 |
| Enter | 댓글 보내기 (Shift+Enter 줄바꿈). 보낸 자리에 이니셜 마커 |
| Cmd+S · [저장] | 파일 덧쓰기. 첫 저장 때 `.bak` |
| [진행중인 <Agent> Session에 제출] | 저장 + 수정 내역·댓글을 에이전트에 전달. "제출이 완료되었습니다" 표시 |

## 원칙

- 글자 수정과 댓글만 지원한다. 요소 추가·삭제·이동은 댓글로 받아 에이전트가 한다.
- 저장은 브라우저 DOM 을 그대로 직렬화한다. 클래스·인라인 CSS·SVG 가 깎이지 않는다. 브라우저 확장이 끼운 요소와 편집기 자체는 저장에서 걸러진다.
- **사용자가 저장한 HTML 이 그 시점부터 원본이다.** 재생성 전에 `.bak` 존재를 확인하고, 있으면 원본(md·json)에 먼저 수정을 반영한다.
- 서식과 무관하다. 어떤 HTML 에도 붙는다. 다른 스킬(예: openub-report)이 저장 훅이 필요하면 환경변수(`OPENUB_REPORT_LIB`)로 연동한다.

## 파일

| 파일 | 역할 |
|---|---|
| `review.py` | 편집기 서버 + 브라우저 UI |
| `hook.py` · `register_hook.py` | .html 저장마다 자동 발동하는 PostToolUse 훅과 그 등록 스크립트 |
| `install.sh` · `install.ps1` | 파이썬 3 확인·설치 + 스킬 폴더 배치 (Mac/Linux · Windows) |
| `README.md` | Codex · Gemini 등 Claude 외 에이전트용 요약 |
| `~/.config/html-with-ai/config.json` | 사용자 설정 (mode · cases · initial · agent) |
| `<문서 폴더>/_review_events.jsonl` | 제출 기록. gitignore 대상 |
