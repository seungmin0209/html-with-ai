#!/bin/sh
# review-ai-artifacts 설치 (Mac/Linux). 파이썬 3가 없으면 설치까지 한다. Windows 는 install.ps1.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)

# 1) 파이썬 3 확인 → 없으면 설치
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
  echo "python3 : $(python3 --version)"
else
  echo "python3 없음 → 설치합니다"
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then brew install python@3 >/dev/null && echo "python3 : Homebrew 로 설치";
      else echo "Apple 개발자 도구 설치 창이 뜹니다. 확인을 누르고 끝나면 이 스크립트를 다시 실행하세요."; xcode-select --install 2>/dev/null || true; exit 1; fi ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y python3 >/dev/null;
      elif command -v dnf >/dev/null 2>&1; then sudo dnf install -y python3 >/dev/null;
      else echo "패키지 관리자를 찾지 못했습니다. python3 를 설치한 뒤 다시 실행하세요."; exit 1; fi
      echo "python3 : $(python3 --version)" ;;
  esac
fi

# 2) 에이전트별 스킬 위치에 링크
mkdir -p "$HOME/.claude/skills" "$HOME/.config/review-ai-artifacts"
[ "$HERE" = "$HOME/.claude/skills/review-ai-artifacts" ] || ln -sfn "$HERE" "$HOME/.claude/skills/review-ai-artifacts"
echo "Claude Code : ~/.claude/skills/review-ai-artifacts"
python3 "$HERE/register_hook.py" || true   # .html 저장마다 자동 발동하는 훅
echo "Codex       : 프로젝트 AGENTS.md 에 한 줄 —  'HTML 산출물은 $HERE/SKILL.md 규약(review-ai-artifacts)으로 띄운다'"
echo "Gemini CLI  : GEMINI.md 에 같은 한 줄. review.py 실행 시 --agent Gemini"
[ -f "$HOME/.config/review-ai-artifacts/config.json" ] || { printf '{"mode": "ask", "cases": [], "first_run": true}\n' > "$HOME/.config/review-ai-artifacts/config.json"; echo "기본 설정 mode=ask 생성. 첫 HTML 때 에이전트가 발동 방식을 묻습니다."; }
