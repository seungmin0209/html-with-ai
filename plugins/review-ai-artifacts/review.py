#!/usr/bin/env python3
"""review-ai-artifacts — Edit & Tell <Agent> what to do. AI 와 함께 만든 HTML 을 브라우저에서 바로 고치고 댓글을 달아 에이전트에게 돌려보낸다.
Claude Code · Codex · Gemini CLI 등 어느 에이전트와도 쓴다. 화면 문구의 에이전트 이름은 --agent 로 정하거나 환경변수로 감지한다.

    python3 review.py <문서.html | 문서.md> [--port 8901]

브라우저에서:
- 더블클릭 = 그 자리에서 글자 수정 · 바깥 클릭 = 끝 · Cmd+S / [저장] = 파일 덧쓰기(첫 저장 때 .bak)
- .md 는 보기용으로 렌더해 띄운다. 화면에서 파일을 쓰지 않고, 제출 이벤트(before/after)로 에이전트가 원문에 반영한다 (source: md)
- 우클릭 = 그 요소에 댓글. 문구를 드래그해 고른 뒤 우클릭하면 그 문구에만 댓글
- [진행중인 <Agent> Session에 제출] = 파일에 기록. Claude 는 훅·Monitor 가 이벤트 파일을 받고, Codex 는 세션 ID가 있으면 codex queue 로 알림. 저장·큐 접수·반영 완료는 별도 상태.
  변경·댓글 없이 누르면 approved=true — "이상 없음" 승인으로 전달된다

에이전트 쪽: 이 스크립트를 띄운 세션이 이벤트 파일을 지켜본다(SKILL.md / README.md).
문서에 <script id="oub-meta"> 가 있고 OPENUB_REPORT_LIB 환경변수가 있으면 저장 때 수정일·이력을 갱신한다(openub-report 연동, 선택).
ponytail: 글자 수정과 댓글만. 요소 추가·삭제·이동은 댓글로 에이전트에게 맡긴다.
"""
import sys, os, re, json, pathlib, datetime, webbrowser, http.server, argparse, shutil
import events as review_events
from html import escape as html_escape

CONFIG = pathlib.Path.home() / ".config" / "review-ai-artifacts" / "config.json"   # 사용자별 설정(mode·cases·initial·agent). SKILL.md 참조
AGENT_ENV = [("CLAUDECODE", "Claude"), ("CLAUDE_CODE_ENTRYPOINT", "Claude"), ("CODEX_THREAD_ID", "Codex"), ("CODEX_SANDBOX", "Codex"), ("CODEX_HOME", "Codex"),
             ("GEMINI_CLI", "Gemini"), ("GEMINI_API_KEY", "Gemini"), ("CURSOR_TRACE_ID", "Cursor"), ("COPILOT_AGENT", "Copilot")]
def detect_agent():
    for k, v in AGENT_ENV:
        if os.environ.get(k): return v
    return None
ap = argparse.ArgumentParser(); ap.add_argument("doc", nargs="?"); ap.add_argument("--port", type=int, default=None, help="생략하면 문서 경로로 정해지는 고정 포트(8901~8990). 같은 문서는 항상 같은 포트"); ap.add_argument("--no-open", action="store_true")
ap.add_argument("--set-mode", choices=["always", "ask", "cases", "off"], help="발동 방식 저장 후 종료")
ap.add_argument("--cases", default="", help="--set-mode cases 일 때 쉼표 목록. 예: artifact,report,dashboard")
ap.add_argument("--show-config", action="store_true")
ap.add_argument("--set-initial", help="댓글 마커에 보일 한 글자 (예: 승)")
ap.add_argument("--agent", help="화면에 표시할 에이전트 이름: Claude · Codex · Gemini … (기본: 환경변수로 감지, 없으면 설정값, 없으면 'AI')")
ap.add_argument("--set-agent", help="기본 에이전트 이름을 설정에 저장")
ap.add_argument("--thread", help="Codex 제출 대상 UUID. 기본 CODEX_THREAD_ID. --agent는 표시명일 뿐 전달 경로가 아님")
ap.add_argument("--manual", action="store_true", help="자동 전달 없이 제출 기록만 저장")
ap.add_argument("--ack", help="반영을 완료한 제출 ID")
ap.add_argument("--result", default="반영 완료", help="--ack 처리 결과")
A = ap.parse_args()
cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
INITIAL = cfg.get("initial", "나")
AGENT = A.agent or detect_agent() or cfg.get("agent") or "AI"
if A.set_mode or A.show_config or A.set_initial or A.set_agent:
    if A.set_mode:
        cfg.update(mode=A.set_mode, cases=[c.strip() for c in A.cases.split(",") if c.strip()], updated=datetime.date.today().isoformat())
    if A.set_initial: cfg["initial"] = A.set_initial[:1]
    if A.set_agent: cfg["agent"] = A.set_agent
    if A.set_mode or A.set_initial or A.set_agent:
        CONFIG.parent.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    print(json.dumps(cfg, ensure_ascii=False) if cfg else "설정 없음 — 첫 사용. SKILL.md 의 '처음 한 번 묻기' 절을 따른다"); sys.exit(0)
assert A.doc, "HTML 파일 경로를 준다"
DOC = pathlib.Path(A.doc).resolve(); assert DOC.is_file() and DOC.suffix.lower() in (".html", ".htm", ".md", ".markdown"), "HTML 또는 md 파일 하나를 준다"

def pick_port(doc, want=None):
    """문서별 고정 포트. 이미 그 포트에 같은 문서가 떠 있으면 (port, True). 다른 문서가 쓰고 있으면 다음 빈 포트."""
    import socket, urllib.request, zlib
    start = want or 8901 + zlib.crc32(str(doc).encode()) % 90
    for p in list(range(start, 8991)) + list(range(8901, start)):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0: return p, False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/doc", timeout=0.3) as r:
                if r.read().decode() == str(doc): return p, True
        except Exception: pass
    raise SystemExit("8901~8990 포트가 모두 사용 중")
EVENTS = DOC.parent / "_review_events.jsonl"
THREAD = (A.thread or os.environ.get("CODEX_THREAD_ID")) if AGENT.lower() == "codex" and not A.manual else None
CODEX = shutil.which("codex") if THREAD else None
if THREAD:
    import uuid
    THREAD = str(uuid.UUID(THREAD))  # Exact session only; never route by display name or --last.
if A.ack:
    row = next((r for r in review_events.read(EVENTS) if r.get("id") == A.ack), None)
    if row is None or row.get("doc") != str(DOC): raise SystemExit("이 문서의 제출 ID가 아닙니다")
    review_events.update(EVENTS, A.ack, status="done", result=A.result)
    print("반영 완료 기록:", A.ack); sys.exit(0)
PORT, ALREADY = pick_port(DOC, A.port)
if ALREADY:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r: health = json.load(r)
        if health.get("thread_id") != THREAD or health.get("version") != 2:
            print("주의: 기존 서버의 전달 연결이 현재 세션과 다릅니다. /doc와 PID 확인 후 해당 서버만 재시작하세요.", flush=True)
    except Exception:
        print("주의: 기존 서버는 전달 상태를 지원하지 않습니다. /doc와 PID 확인 후 해당 서버만 재시작하세요.", flush=True)
    print(f"이미 떠 있음: http://localhost:{PORT}/  ({DOC.name})", flush=True); sys.exit(0)
IS_MD = DOC.suffix.lower() in (".md", ".markdown")
EVENTS = DOC.parent / "_review_events.jsonl"

UI = r"""
<style id="__rv_css">
[data-rv-hover]{outline:2px dashed #b45f06;outline-offset:2px;cursor:text}
[data-rv-hover]:empty,[contenteditable]:empty{min-width:24px;min-height:1em;display:inline-block}
[data-rv-target]{outline:2px solid #d97706!important;outline-offset:2px}
[contenteditable="plaintext-only"]{outline:2px solid #2f6bdc;outline-offset:2px;background:rgba(47,107,220,.06)}
[data-rv-note]{outline:2px solid rgba(120,140,170,.6);outline-offset:2px}
mark[data-rv-mark]{background:rgba(128,140,160,.35);color:inherit;border-radius:3px;padding:0 1px}
.__rv_pin{position:absolute;z-index:99998;width:30px;height:30px;border-radius:50%;background:#2b2b2b;color:#e8e8e8;border:3px solid #2f6bdc;
  display:flex;align-items:center;justify-content:center;font:600 12px/1 -apple-system,system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.35);cursor:pointer}
.__rv_pin[data-n]::after{content:attr(data-n);position:absolute;right:-6px;top:-6px;background:#c96442;color:#fff;border-radius:9px;font-size:10px;padding:1px 5px}
#__rv_pop .list{margin:0 0 10px;padding:0;list-style:none;max-height:160px;overflow:auto}#__rv_pop .list li{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid #3a3a3a;font-size:14px;color:#ddd}
#__rv_pop .list li b{color:#9aa4b2;font-weight:600;min-width:22px}#__rv_pop .list li span{flex:1}#__rv_pop .list li button{background:none;border:0;color:#8a8a8a;cursor:pointer;font-size:14px;padding:0 4px}#__rv_pop .list li button:hover{color:#f87171}
#__rv_bar{position:fixed;left:0;right:0;top:0;z-index:99999;display:flex;gap:10px;align-items:center;color-scheme:dark;
  padding:9px 18px;background:#1f1f1f;color:#d4d4d4;font:13px/1.4 -apple-system,system-ui,sans-serif;border-bottom:1px solid #333}
body{padding-top:50px!important}
#__rv_bar b{color:#fff;margin-right:6px;letter-spacing:-.2px}#__rv_bar button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid #3a3a3a;background:#2b2b2b;color:#e8e8e8;cursor:pointer}
#__rv_bar button.pri{background:#c96442;border-color:#c96442;color:#fff;font-weight:600}#__rv_bar button:disabled{opacity:.45;cursor:default}#__rv_bar .st{color:#8a8a8a}#__rv_bar .hint{margin-left:auto;color:#8a8a8a;text-align:right}
#__rv_pop{position:absolute;z-index:100000;color-scheme:dark;background:#2b2b2b;color:#ececec;border:1px solid #3d3d3d;border-radius:16px;padding:18px 22px 16px;
  box-shadow:0 12px 40px rgba(0,0,0,.45);width:560px;max-width:calc(100vw - 32px);font:15px/1.5 -apple-system,system-ui,"Apple SD Gothic Neo",sans-serif}
#__rv_pop .t{color:#8f8f8f;font-size:15px;margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#__rv_pop .a{color:#a8a8a8;font-size:14px;border-left:2px solid #6b6b6b;padding-left:10px;margin-bottom:12px;max-height:44px;overflow:hidden}
#__rv_pop textarea{width:100%;min-height:64px;font:inherit;font-size:17px;color:#fff;background:transparent;border:0;outline:0;padding:0;resize:none;box-sizing:border-box}
#__rv_pop textarea::placeholder{color:#6f6f6f}
#__rv_pop .sw{margin:-4px 0 6px}#__rv_pop .sw button{font:inherit;font-size:12.5px;color:#9aa4b2;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline dotted}#__rv_pop .sw button:disabled{text-decoration:none;cursor:default;color:#8a8a8a}
#__rv_pop .r{display:flex;align-items:center;justify-content:space-between;margin-top:14px}
#__rv_pop .lbl{color:#e8e8e8;font-size:17px}
#__rv_pop .go{width:44px;height:44px;border-radius:12px;border:0;background:#c96442;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
#__rv_pop .go:disabled{background:#4a3a34;color:#8a7a74;cursor:default}#__rv_pop .go svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
@media print{#__rv_bar,#__rv_css,#__rv_pop,.__rv_pin{display:none}body{padding-top:0!important}}
</style>
<div id="__rv_bar"><b>Edit &amp; Tell __AGENT__ what to do</b>
<button id="__rv_save" disabled>저장</button><button id="__rv_ok" class="pri">진행중인 __AGENT__ Session에 제출</button><button id="__rv_copy" hidden>전달 요청 복사</button><span class="st" id="__rv_st" role="status" aria-live="polite">__DELIVERY_LABEL__</span><span class="hint">이중클릭하여 직접 편집. 우클릭하여 현 __AGENT__ Session에게 Comment</span></div>
<script id="__rv_js">
(function(){
Array.from(document.body.children).forEach(function(x){x.setAttribute('data-rv-orig','')});
var dirty=false,submitted=false,orig=new Map(),notes=[],INITIAL=__INITIAL__,ISMD=__ISMD__,requestId=null,lastEvent=null;
if(ISMD){document.getElementById('__rv_save').style.display='none'}
var bar=document.getElementById('__rv_bar'),st=document.getElementById('__rv_st'),btn=document.getElementById('__rv_save'),ok=document.getElementById('__rv_ok');
function ours(el){return el.closest('#__rv_bar,#__rv_pop,.__rv_pin')}
var VOID={IMG:1,SVG:1,BR:1,HR:1,INPUT:1,VIDEO:1,CANVAS:1,PICTURE:1,SOURCE:1};
function hasText(el){if(Array.from(el.childNodes).some(function(n){return n.nodeType===3&&n.textContent.trim()}))return true;
  return el.children.length===0&&!VOID[el.tagName]&&(orig.has(el)||el.isContentEditable||/^(H[1-6]|P|LI|TD|TH|SPAN|B|EM|STRONG|SMALL|FIGCAPTION|SUMMARY|LABEL|A|CODE)$/.test(el.tagName))}  // 글자를 다 지운 요소도 다시 잡힌다
function mediaTarget(e){var m=e.target.closest('img,svg,video,canvas,picture,figure');return (m&&!ours(m))?m:null}
function target(e){var t=e.target;if(!(t instanceof Element)||ours(t))return null;   // 글자를 직접 품은 가장 가까운 요소 — 태그 종류를 가리지 않는다
  while(t&&t!==document.body&&t!==document.documentElement){if(hasText(t))return t;t=t.parentElement}return null}
function path(el){var p=[];while(el&&el!==document.body){var s=el.tagName.toLowerCase();if(el.id){p.unshift(s+'#'+el.id);break}
  var i=1,x=el;while((x=x.previousElementSibling))if(x.tagName===el.tagName)i++;var sib=el.parentElement?Array.from(el.parentElement.children).filter(function(c){return c.tagName===el.tagName}).length:1;
  p.unshift(sib>1?s+':nth-of-type('+i+')':s);el=el.parentElement}return p.join(' > ')}
document.addEventListener('mouseover',function(e){var t=target(e);document.querySelectorAll('[data-rv-hover]').forEach(function(x){x.removeAttribute('data-rv-hover')});if(t&&!t.isContentEditable)t.setAttribute('data-rv-hover','')});
document.addEventListener('dblclick',function(e){var t=target(e);if(!t)return;e.preventDefault();
  if(!orig.has(t))orig.set(t,t.innerText);
  if(t.tagName==='A'){t.dataset.rvHref=t.getAttribute('href');t.removeAttribute('href')}
  t.setAttribute('contenteditable','plaintext-only');t.focus();
  t.addEventListener('input',function(){dirty=true;btn.disabled=false;st.textContent=ISMD?'수정됨 — 제출하면 원문에 반영':'저장 안 됨'},{once:true});
  t.addEventListener('blur',function(){t.removeAttribute('contenteditable');brify(t);if(t.dataset.rvHref!==undefined){t.setAttribute('href',t.dataset.rvHref);delete t.dataset.rvHref}},{once:true});
},true);
document.addEventListener('mousedown',function(e){var d=document.getElementById('__rv_pop');if(d&&!d.contains(e.target)&&!d.querySelector('textarea').value.trim())closePop()},true); // 적기 전이면 바깥 클릭으로 닫힘
document.addEventListener('click',function(e){if(ours(e.target))return;var a=e.target.closest('a');if(a&&!e.target.isContentEditable&&!(a.getAttribute('href')||'').startsWith('#')&&!a.hasAttribute('download'))e.preventDefault()},true); // 편집 중 링크 이동 방지
document.addEventListener('contextmenu',function(e){var t=target(e)||mediaTarget(e);if(!t)return;e.preventDefault();
  var sel=window.getSelection(),quote='',range=null;
  if(sel&&!sel.isCollapsed&&t.contains(sel.anchorNode)&&sel.toString().trim()){quote=sel.toString().trim();range=sel.getRangeAt(0).cloneRange()}
  openPop(t,quote,range,e.pageX,e.pageY)});
function label(el){if(el.tagName==='IMG')return '[이미지] '+(el.alt||el.getAttribute('src')||'').slice(0,120);if(/^(SVG|VIDEO|CANVAS|PICTURE)$/.test(el.tagName))return '['+el.tagName.toLowerCase()+']';if(el.tagName==='FIGURE'){var c=el.querySelector('figcaption');return '[그림] '+(c?c.textContent.trim().slice(0,120):'')}return el.textContent.trim().slice(0,160)}
function openPop(t,quote,range,x,y){closePop();t.setAttribute('data-rv-target','');var d=document.createElement('div');d.id='__rv_pop';
  d.style.left=Math.max(8,Math.min(x,window.innerWidth-580+window.scrollX))+'px';d.style.top=(y+10)+'px';
  var whole=label(t).replace(/</g,'&lt;');
  var mine=notes.filter(function(x){return x.el===t});
  var list=mine.length?'<ul class="list">'+mine.map(function(x){return '<li><b>#'+x.n+'</b><span>'+(x.quote?'“'+x.quote.slice(0,40).replace(/</g,'&lt;')+'” · ':'')+x.text.replace(/</g,'&lt;')+'</span><button type="button" data-del="'+x.n+'" title="이 댓글 삭제">✕</button></li>'}).join('')+'</ul>':'';
  d.innerHTML='<div class="t">'+(document.title||location.pathname).replace(/</g,'&lt;')+'</div>'+list+'<div class="a" data-mode="'+(quote?'quote':'whole')+'">'+(quote?quote.slice(0,160).replace(/</g,'&lt;'):whole)+'</div>'
   +'<div class="sw"><button type="button" data-a="sw">'+(quote?'이 요소 전체에 달기':'문구만 고르려면 드래그 후 우클릭')+'</button></div>'
   +'<textarea rows="2" placeholder="'+(mine.length?'댓글 추가':'댓글 남기기')+'"></textarea><div class="r"><span class="lbl">Send to __AGENT__</span><button class="go" data-a="ok" disabled aria-label="보내기"><svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button></div>';
  document.body.appendChild(d);var ta=d.querySelector('textarea'),go=d.querySelector('.go');ta.focus();
  d.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
    if(b.dataset.del){var n=+b.dataset.del;notes=notes.filter(function(x){return x.n!==n});refreshPins();closePop();return}   // 댓글 삭제
    if(b.dataset.a==='sw'&&quote){quote='';range=null;d.querySelector('.a').textContent=whole;d.querySelector('.a').dataset.mode='whole';b.textContent='요소 전체에 달기로 바꿨습니다';b.disabled=true;ta.focus()}});
  ta.addEventListener('input',function(){go.disabled=!ta.value.trim();ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,240)+'px'});
  ta.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();go.click()}});
  go.addEventListener('click',function(){if(!ta.value.trim())return;
    notes.push({n:(notes.length?Math.max.apply(null,notes.map(function(x){return x.n})):0)+1,el:t,path:path(t),anchor:label(t),quote:quote||null,text:ta.value.trim()});
    if(range){try{var m=document.createElement('mark');m.setAttribute('data-rv-mark','');range.surroundContents(m)}catch(err){}}
    t.setAttribute('data-rv-note','');pin(t);closePop();st.textContent='댓글 '+notes.length+'개 (제출 전)'})}
var pins=new Map();   // 요소 → 마커
function pin(el){var p=pins.get(el);if(!p){p=document.createElement('span');p.className='__rv_pin';p.textContent=INITIAL;document.body.appendChild(p);pins.set(el,p);
    p.addEventListener('click',function(e){e.stopPropagation();openPop(el,'',null,e.pageX,e.pageY)})}
  var r=el.getBoundingClientRect(),n=notes.filter(function(x){return x.el===el}).length;
  p.style.left=(r.left+window.scrollX-36)+'px';p.style.top=(r.top+window.scrollY+r.height/2-15)+'px';
  if(n>1)p.setAttribute('data-n',n);else p.removeAttribute('data-n');p.title='댓글 '+n+'개 — 클릭하면 보기·추가·삭제'}
function refreshPins(){pins.forEach(function(p,el){if(!notes.some(function(x){return x.el===el})){p.remove();pins.delete(el);el.removeAttribute('data-rv-note');el.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))})}else pin(el)});
  st.textContent=notes.length?('댓글 '+notes.length+'개 (제출 전)'):''}
function closePop(){var d=document.getElementById('__rv_pop');if(d)d.remove();document.querySelectorAll('[data-rv-target]').forEach(function(x){x.removeAttribute('data-rv-target')});var s=window.getSelection();if(s)s.removeAllRanges()}
function brify(el){var w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),nodes=[];while(w.nextNode())if(w.currentNode.nodeValue.indexOf('\n')>=0)nodes.push(w.currentNode);
  nodes.forEach(function(n){var parts=n.nodeValue.split('\n'),f=document.createDocumentFragment();parts.forEach(function(p,i){if(i)f.appendChild(document.createElement('br'));if(p)f.appendChild(document.createTextNode(p))});n.parentNode.replaceChild(f,n)})}
function edits(){var out=[];orig.forEach(function(before,el){var after=el.innerText;if(before!==after)out.push({path:path(el),before:before.trim(),after:after.trim()})});return out}
function serialize(){orig.forEach(function(v,el){brify(el)});   // 편집한 요소의 줄바꿈을 <br> 로 (blur 를 놓친 경우 대비)
  var c=document.documentElement.cloneNode(true);
  ['__rv_css','__rv_bar','__rv_js','__rv_pop'].forEach(function(id){var x=c.querySelector('#'+id);if(x)x.remove()});
  c.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});
  c.querySelectorAll('[contenteditable]').forEach(function(x){x.removeAttribute('contenteditable')});
  c.querySelectorAll('*').forEach(function(x){Array.from(x.attributes).forEach(function(a){if(a.name.indexOf('data-rv-')===0){if(a.name==='data-rv-href')x.setAttribute('href',a.value);x.removeAttribute(a.name)}})});
  var keep=Array.from(document.body.children).filter(function(x){return x.hasAttribute('data-rv-orig')}).length; // 브라우저 확장이 끼운 요소 제거
  Array.from(c.querySelector('body').children).forEach(function(x,i){if(i>=keep)x.remove()});
  c.removeAttribute('data-theme');return '<!doctype html>'+c.outerHTML}
function post(url,body,type){return fetch(url,{method:'POST',headers:{'Content-Type':type},body:body}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.text()})}
function save(){if(document.activeElement&&document.activeElement.isContentEditable)document.activeElement.blur();
  st.textContent='저장 중…';return post('/save',serialize(),'text/html;charset=utf-8').then(function(t){dirty=false;btn.disabled=true;st.textContent=t;return fetch('/mtime').then(function(r){return r.text()}).then(function(m){MT=m;return t})}).catch(function(e){st.textContent='저장 실패: '+e;throw e})}
btn.addEventListener('click',function(){save().catch(function(){})});
ok.addEventListener('click',function(){if(ok.disabled)return;ok.disabled=true;requestId=requestId||crypto.randomUUID();var ev={id:requestId,edits:edits(),comments:notes.map(function(x){return {n:x.n,path:x.path,anchor:x.anchor,quote:x.quote,text:x.text}})};ev.approved=!ev.edits.length&&!ev.comments.length;   // 변경·댓글 없이 제출 = 이상 없음(승인)
  ((dirty&&!ISMD)?save():Promise.resolve()).then(function(){return post('/confirm',JSON.stringify(ev),'application/json')})
  .then(function(t){lastEvent=JSON.parse(t);submitted=true;showStatus(lastEvent);requestId=null;notes=[];document.querySelectorAll('[data-rv-note]').forEach(function(x){x.removeAttribute('data-rv-note')});
    document.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});pins.forEach(function(p){p.remove()});pins.clear();orig.forEach(function(v,el){orig.set(el,el.innerText)});dirty=false;btn.disabled=true}).catch(function(e){st.textContent='제출 확인 실패 · 입력 보존됨: '+e}).finally(function(){ok.disabled=false})});
document.addEventListener('keydown',function(e){if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();if(!ISMD)save().catch(function(){});else st.textContent='md 는 제출하면 에이전트가 원문에 반영합니다'}if(e.key==='Escape')closePop()});
window.addEventListener('resize',function(){pins.forEach(function(p,el){pin(el)})});
window.addEventListener('beforeunload',function(e){if(dirty||notes.length){e.preventDefault();e.returnValue=''}});
function showStatus(r){
  var copy=document.getElementById('__rv_copy'),AG='__AGENT__';
  if(r.status==='done'){st.textContent=r.result||'반영 완료';copy.hidden=true;return}
  if(AG!=='Codex'&&(r.delivery==='manual'||!r.delivery)){   // Claude 등: 훅·Monitor 가 이벤트 파일을 지켜본다
    st.textContent=r.approved?('이상 없음으로 제출되었습니다 — '+AG+' 에게 승인이 전달됩니다'):('제출이 완료되었습니다 — '+AG+' 가 반영하면 화면이 자동으로 새로 고쳐집니다');copy.hidden=true;return}
  if(r.result){st.textContent=r.result;copy.hidden=false;return}
  var labels={queued:'저장됨 · Codex 큐 접수 · 반영 대기',pending:'저장됨 · 전달 확인 중',manual:'저장됨 · 자동 전달 미연결',failed:'저장됨 · 자동 전달 실패',unknown:'저장됨 · 전달 결과 미확인'};
  st.textContent=labels[r.delivery]||'저장됨 · 반영 대기';
  copy.hidden=r.delivery==='queued'||r.delivery==='pending';
}
document.getElementById('__rv_copy').addEventListener('click',function(){
  var message='review-ai-artifacts 제출 내용을 반영해줘. 문서: '+__DOC_JSON__+' / 제출 ID: '+((lastEvent||{}).id||'기존 미처리 제출');
  navigator.clipboard.writeText(message).then(function(){st.textContent='전달 요청 복사 완료 · 현재 대화에 붙여넣기'}).catch(function(){st.textContent=message});
});
setInterval(function(){if(dirty||notes.length||ok.disabled)return;fetch('/status').then(function(r){return r.json()}).then(function(r){if(r.id||r.pending_count){lastEvent=r;showStatus(r)}}).catch(function(){})},2000);
var MT=__MTIME__;setInterval(function(){fetch('/mtime').then(function(r){return r.text()}).then(function(m){if(m===MT)return;
  if(dirty||notes.length||(document.activeElement&&document.activeElement.isContentEditable)){st.textContent='__AGENT__ 가 문서를 갱신했습니다 — '+(ISMD?'제출하면':'저장하면')+' 새 판을 불러옵니다';return}
  location.reload()}).catch(function(){})},2000);
})();
</script>
"""

MD_CSS = """<style>:root{color-scheme:light dark}body{max-width:860px;margin:40px auto;padding:0 24px 80px;font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Pretendard,"Segoe UI",sans-serif;color:#1c2431;background:#fff;word-break:keep-all}
@media(prefers-color-scheme:dark){body{color:#e6edf7;background:#141b26}a{color:#a9c5ff}code,pre{background:#233043}th{background:#233043}td,th{border-color:#38475c}blockquote{border-color:#38475c;color:#a8b8cb}}
h1{font-size:32px;line-height:1.3;margin:0 0 20px}h2{font-size:24px;margin:36px 0 12px}h3{font-size:18px;margin:26px 0 8px}p{margin:0 0 14px}ul,ol{padding-left:24px;margin:0 0 14px}li+li{margin-top:4px}
code{font:13.5px ui-monospace,Menlo,monospace;background:#eef2f7;padding:1px 5px;border-radius:4px}pre{background:#eef2f7;padding:14px 16px;border-radius:8px;overflow:auto}pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:0 0 16px;font-size:14.5px}th,td{border:1px solid #dce3ed;padding:8px 12px;text-align:left;vertical-align:top}th{background:#eaf0f8}
blockquote{border-left:3px solid #dce3ed;margin:0 0 14px;padding:4px 16px;color:#57677c}hr{border:0;border-top:1px solid #dce3ed;margin:24px 0}img{max-width:100%}
.mdnote{font-size:12.5px;color:#8a97a8;border-top:1px solid #dce3ed;margin-top:40px;padding-top:12px}</style>"""

def md_to_html(md):
    """md → 보기용 HTML. 원문 복원용이 아니다 — 수정은 제출 이벤트(before/after)로 에이전트가 원문에 반영한다."""
    import html as H
    def inl(s):
        s = H.escape(s, quote=False)
        s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s); s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<i>\1</i>", s)
        return s
    lines = md.splitlines()
    if sum(1 for l in lines if l.strip()) <= 3 and len(md) > 1500:   # 블록 구분 없이 한 줄로 쓰인 md — 표식 앞에서 나눈다
        md = re.sub(r"\s(?=#{1,6}\s)", "\n\n", md); md = re.sub(r"\s-\s(?=\S)", "\n- ", md); md = re.sub(r"\s(?=\|[^|]+\|)", "\n", md, count=1)
        lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if l.startswith("```"):
            j = i + 1; buf = []
            while j < len(lines) and not lines[j].startswith("```"): buf.append(lines[j]); j += 1
            out.append("<pre><code>" + H.escape("\n".join(buf)) + "</code></pre>"); i = j + 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)", l)
        if m: out.append(f"<h{len(m.group(1))}>{inl(m.group(2))}</h{len(m.group(1))}>"); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,})\s*$", l): out.append("<hr>"); i += 1; continue
        if l.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|\s*$", lines[i]): rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if rows:
                th = "".join(f"<th>{inl(c)}</th>" for c in rows[0]); body = "".join("<tr>" + "".join(f"<td>{inl(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", l):
            ordered = bool(re.match(r"^\s*\d+\.", l)); items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*+]|\d+\.)\s+", "", lines[i])); i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]): items[-1] += " " + lines[i].strip(); i += 1
            tag = "ol" if ordered else "ul"; out.append(f"<{tag}>" + "".join(f"<li>{inl(x)}</li>" for x in items) + f"</{tag}>"); continue
        if l.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"): buf.append(lines[i].lstrip("> ").strip()); i += 1
            out.append("<blockquote>" + inl(" ".join(buf)) + "</blockquote>"); continue
        if not l.strip(): i += 1; continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|\||>|\s*([-*+]|\d+\.)\s|-{3,}\s*$)", lines[i]): buf.append(lines[i].strip()); i += 1
        out.append("<p>" + inl(" ".join(buf)) + "</p>")
    title = next((re.sub(r"^#\s+", "", x) for x in lines if x.startswith("# ")), DOC.name)
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{H.escape(title)}</title>{MD_CSS}</head>'
            f'<body>{"".join(out)}<p class="mdnote">원문 {H.escape(DOC.name)} · 마크다운을 보기용으로 렌더한 화면이다. 이중클릭 수정과 댓글은 제출 시 에이전트가 원문에 반영한다.</p></body></html>')

def bump_meta(html):
    """openub-report 문서면 수정일·이력 갱신. 라이브러리가 없으면 그대로 둔다."""
    lib_dir = os.environ.get("OPENUB_REPORT_LIB")
    if 'id="oub-meta"' not in html or not lib_dir: return html
    sys.path.insert(0, lib_dir); import lib
    meta = lib.meta_next(lib.meta_load(html), "편집기 저장", by="사용자")
    html = re.sub(r'<header class="topbar">.*?</header>', lambda m: lib.topbar(meta), html, count=1, flags=re.S)
    return re.sub(r'(<footer class="footer">Openub Artifacts · 작성 [^·]+ · 수정 )[^·<]+', lambda m: m.group(1) + meta["modified"], html, count=1)

def reply(h, code, text, ctype="text/plain;charset=utf-8"):
    data = text.encode(); h.send_response(code); h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data))); h.end_headers(); h.wfile.write(data)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/health": return reply(self, 200, json.dumps({"version":2,"doc":str(DOC),"thread_id":THREAD,"automatic":bool(THREAD and CODEX)}), "application/json")
        if self.path == "/status": return reply(self, 200, json.dumps(review_events.status(EVENTS, DOC, THREAD if CODEX else None), ensure_ascii=False), "application/json")
        if self.path.startswith("/mtime"): return reply(self, 200, str(DOC.stat().st_mtime_ns))
        if self.path.startswith("/doc"): return reply(self, 200, str(DOC))
        body = md_to_html(DOC.read_text(encoding="utf-8")) if IS_MD else DOC.read_text(encoding="utf-8")
        ui = (UI.replace("__INITIAL__", json.dumps(INITIAL, ensure_ascii=False)).replace("__MTIME__", json.dumps(str(DOC.stat().st_mtime_ns)))
                .replace("__AGENT__", html_escape(AGENT)).replace("__DELIVERY_LABEL__", ("Codex 자동 전달 연결" if THREAD and CODEX else "자동 전달 미연결 · 제출 저장 후 대화에서 알림 필요") if AGENT.lower() == "codex" else "").replace("__DOC_JSON__", json.dumps(str(DOC), ensure_ascii=False).replace("<", "\\u003c")).replace("__ISMD__", "true" if IS_MD else "false"))
        body = body.replace("</body>", ui + "</body>", 1) if "</body>" in body else body + ui
        reply(self, 200, body, "text/html;charset=utf-8")
    def do_POST(self):
        allowed = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
        if self.headers.get("Host") not in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"} or self.headers.get("Origin") not in allowed | {None}:
            return reply(self, 403, "다른 사이트에서 제출할 수 없습니다")
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if self.path.startswith("/save"):
            if IS_MD: return reply(self, 200, "md 는 화면에서 바로 저장하지 않습니다 — 제출하면 에이전트가 원문에 반영합니다")
            assert "__rv_bar" not in raw, "편집기 요소가 섞여 들어왔다"
            bak = DOC.with_suffix(".html.bak")
            if not bak.exists(): bak.write_bytes(DOC.read_bytes())
            raw = bump_meta(raw); DOC.write_text(raw, encoding="utf-8")
            return reply(self, 200, f"저장됨 {len(raw.encode()):,}B")
        if self.path.startswith("/confirm"):
            try:
                ev = review_events.submit(EVENTS, DOC, AGENT, "md" if IS_MD else "html", json.loads(raw), THREAD, CODEX)
                return reply(self, 200, json.dumps(ev, ensure_ascii=False), "application/json")
            except (ValueError, TypeError, TimeoutError) as error:
                return reply(self, 400, str(error))
        reply(self, 404, "?")

if __name__ == "__main__":
    print(f"문서: {DOC}\n이벤트: {EVENTS}\nhttp://localhost:{PORT}/   (Ctrl+C 로 종료)", flush=True)
    if not A.no_open: webbrowser.open(f"http://localhost:{PORT}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
