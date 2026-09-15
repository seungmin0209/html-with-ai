# review-ai-artifacts 설치 (Windows PowerShell). 파이썬 3가 없으면 winget 으로 설치까지 한다.
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1) 파이썬 3 확인 → 없으면 설치
$py = Get-Command python -ErrorAction SilentlyContinue
$ok = $false
if ($py) { try { $v = & python -c "import sys; print(sys.version_info >= (3, 8))" 2>$null; $ok = ($v -eq "True") } catch {} }
if ($ok) { Write-Host "python : $(& python --version)" }
else {
  Write-Host "python 3 없음 → winget 으로 설치합니다 (Microsoft Store 없이, PATH 자동 등록)"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
    Write-Host "설치 완료. 새 터미널을 열고 이 스크립트를 다시 실행하세요 (PATH 반영)."
  } else {
    Write-Host "winget 이 없습니다. https://www.python.org/downloads/windows/ 에서 설치 때 'Add python.exe to PATH' 를 체크한 뒤 다시 실행하세요."
  }
  exit 1
}

# 2) Claude Code 스킬 위치에 복사(Windows 는 링크 대신 복사)
$Dest = Join-Path $env:USERPROFILE ".claude\skills\review-ai-artifacts"
if ((Resolve-Path $Here).Path -ne $Dest) {
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  Copy-Item -Path (Join-Path $Here "*") -Destination $Dest -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $env:USERPROFILE ".config\review-ai-artifacts") | Out-Null
Write-Host "Claude Code : $Dest"
& python (Join-Path $Dest "register_hook.py")   # .html 저장마다 자동 발동하는 훅
Write-Host "Codex       : 프로젝트 AGENTS.md 에 한 줄 — 'HTML 산출물은 $Dest\SKILL.md 규약(review-ai-artifacts)으로 띄운다'"
Write-Host "Gemini CLI  : GEMINI.md 에 같은 한 줄. review.py 실행 시 --agent Gemini"
$Cfg = Join-Path $env:USERPROFILE ".config\review-ai-artifacts\config.json"
if (-not (Test-Path $Cfg)) { '{"mode": "ask", "cases": [], "first_run": true}' | Set-Content -Encoding UTF8 $Cfg; Write-Host "기본 설정 mode=ask 생성. 첫 HTML 때 에이전트가 발동 방식을 묻습니다." }
