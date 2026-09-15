#!/usr/bin/env python3
"""html-with-ai — Edit & Tell <Agent> what to do. AI 와 함께 만든 HTML 을 브라우저에서 바로 고치고 댓글을 달아 에이전트에게 돌려보낸다.
Claude Code · Codex · Gemini CLI 등 어느 에이전트와도 쓴다. 화면 문구의 에이전트 이름은 --agent 로 정하거나 환경변수로 감지한다.

    python3 review.py <문서.html> [--port 8901]

브라우저에서:
- 더블클릭 = 그 자리에서 글자 수정 · 바깥 클릭 = 끝 · Cmd+S / [저장] = 파일 덧쓰기(첫 저장 때 .bak)
- 우클릭 = 그 요소에 댓글. 문구를 드래그해 고른 뒤 우클릭하면 그 문구에만 댓글
- [진행중인 __AGENT__ Session에 제출] = 저장 + 바뀐 글자 목록·댓글을 <폴더>/_review_events.jsonl 에 한 줄 기록 → 에이전트가 받아 반영.
  변경·댓글 없이 누르면 approved=true — "이상 없음" 승인으로 전달된다

에이전트 쪽: 이 스크립트를 띄운 세션이 이벤트 파일을 지켜본다(SKILL.md / README.md).
문서에 <script id="oub-meta"> 가 있고 OPENUB_REPORT_LIB 환경변수가 있으면 저장 때 수정일·이력을 갱신한다(openub-report 연동, 선택).
ponytail: 글자 수정과 댓글만. 요소 추가·삭제·이동은 댓글로 에이전트에게 맡긴다.
"""
import sys, os, re, json, pathlib, datetime, webbrowser, http.server, argparse
from html import escape as html_escape

CONFIG = pathlib.Path.home() / ".config" / "html-with-ai" / "config.json"   # 사용자별 설정(mode·cases·initial·agent). SKILL.md 참조
AGENT_ENV = [("CLAUDECODE", "Claude"), ("CLAUDE_CODE_ENTRYPOINT", "Claude"), ("CODEX_SANDBOX", "Codex"), ("CODEX_HOME", "Codex"),
             ("GEMINI_CLI", "Gemini"), ("GEMINI_API_KEY", "Gemini"), ("CURSOR_TRACE_ID", "Cursor"), ("COPILOT_AGENT", "Copilot")]
def detect_agent():
    for k, v in AGENT_ENV:
        if os.environ.get(k): return v
    return None
ap = argparse.ArgumentParser(); ap.add_argument("doc", nargs="?"); ap.add_argument("--port", type=int, default=8901); ap.add_argument("--no-open", action="store_true")
ap.add_argument("--set-mode", choices=["always", "ask", "cases", "off"], help="발동 방식 저장 후 종료")
ap.add_argument("--cases", default="", help="--set-mode cases 일 때 쉼표 목록. 예: artifact,report,dashboard")
ap.add_argument("--show-config", action="store_true")
ap.add_argument("--set-initial", help="댓글 마커에 보일 한 글자 (예: 승)")
ap.add_argument("--agent", help="화면에 표시할 에이전트 이름: Claude · Codex · Gemini … (기본: 환경변수로 감지, 없으면 설정값, 없으면 'AI')")
ap.add_argument("--set-agent", help="기본 에이전트 이름을 설정에 저장")
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
DOC = pathlib.Path(A.doc).resolve(); assert DOC.is_file() and DOC.suffix == ".html", "HTML 파일 하나를 준다"
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
<button id="__rv_save" disabled>저장</button><button id="__rv_ok" class="pri">진행중인 __AGENT__ Session에 제출</button><span class="st" id="__rv_st"></span><span class="hint">이중클릭하여 직접 편집. 우클릭하여 현 __AGENT__ Session에게 Comment</span></div>
<script id="__rv_js">
(function(){
Array.from(document.body.children).forEach(function(x){x.setAttribute('data-rv-orig','')});
var dirty=false,submitted=false,orig=new Map(),notes=[],INITIAL=__INITIAL__;
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
  t.addEventListener('input',function(){dirty=true;btn.disabled=false;st.textContent='저장 안 됨'},{once:true});
  t.addEventListener('blur',function(){t.removeAttribute('contenteditable');brify(t);if(t.dataset.rvHref!==undefined){t.setAttribute('href',t.dataset.rvHref);delete t.dataset.rvHref}},{once:true});
},true);
document.addEventListener('mousedown',function(e){var d=document.getElementById('__rv_pop');if(d&&!d.contains(e.target)&&!d.querySelector('textarea').value.trim())closePop()},true); // 적기 전이면 바깥 클릭으로 닫힘
document.addEventListener('click',function(e){if(ours(e.target))return;if(e.target.closest('a')&&!e.target.isContentEditable)e.preventDefault()},true); // 편집 중 링크 이동 방지
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
  d.innerHTML='<div class="t">'+(document.title||location.pathname).replace(/</g,'&lt;')+'</div>'+list+'<div class="a" data-mode="'+(quote?'quote':'whole')+'">'+(quote||t.textContent.trim()).slice(0,160).replace(/</g,'&lt;')+'</div>'
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
function serialize(){var c=document.documentElement.cloneNode(true);
  ['__rv_css','__rv_bar','__rv_js','__rv_pop'].forEach(function(id){var x=c.querySelector('#'+id);if(x)x.remove()});
  c.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});
  c.querySelectorAll('[contenteditable]').forEach(function(x){x.removeAttribute('contenteditable')});
  c.querySelectorAll('*').forEach(function(x){Array.from(x.attributes).forEach(function(a){if(a.name.indexOf('data-rv-')===0){if(a.name==='data-rv-href')x.setAttribute('href',a.value);x.removeAttribute(a.name)}})});
  var keep=Array.from(document.body.children).filter(function(x){return x.hasAttribute('data-rv-orig')}).length; // 브라우저 확장이 끼운 요소 제거
  Array.from(c.querySelector('body').children).forEach(function(x,i){if(i>=keep)x.remove()});
  c.removeAttribute('data-theme');return '<!doctype html>'+c.outerHTML}
function post(url,body,type){return fetch(url,{method:'POST',headers:{'Content-Type':type},body:body}).then(function(r){return r.text()})}
function save(){if(document.activeElement&&document.activeElement.isContentEditable)document.activeElement.blur();
  st.textContent='저장 중…';return post('/save',serialize(),'text/html;charset=utf-8').then(function(t){dirty=false;btn.disabled=true;st.textContent=t;return fetch('/mtime').then(function(r){return r.text()}).then(function(m){MT=m;return t})}).catch(function(e){st.textContent='실패: '+e})}
btn.addEventListener('click',save);
ok.addEventListener('click',function(){var ev={edits:edits(),comments:notes.map(function(x){return {n:x.n,path:x.path,anchor:x.anchor,quote:x.quote,text:x.text}})};ev.approved=!ev.edits.length&&!ev.comments.length;   // 변경·댓글 없이 제출 = 이상 없음(승인)
  (dirty?save():Promise.resolve()).then(function(){return post('/confirm',JSON.stringify(ev),'application/json')})
  .then(function(t){submitted=true;st.textContent=t;notes=[];document.querySelectorAll('[data-rv-note]').forEach(function(x){x.removeAttribute('data-rv-note')});
    document.querySelectorAll('mark[data-rv-mark]').forEach(function(m){m.replaceWith(document.createTextNode(m.textContent))});pins.forEach(function(p){p.remove()});pins.clear();orig.forEach(function(v,el){orig.set(el,el.innerText)})})});
document.addEventListener('keydown',function(e){if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();save()}if(e.key==='Escape')closePop()});
window.addEventListener('resize',function(){pins.forEach(function(p,el){pin(el)})});
window.addEventListener('beforeunload',function(e){if(dirty){e.preventDefault();e.returnValue=''}});
var MT=__MTIME__;setInterval(function(){fetch('/mtime').then(function(r){return r.text()}).then(function(m){if(m===MT)return;
  if(dirty||(document.activeElement&&document.activeElement.isContentEditable)){st.textContent='__AGENT__ 가 문서를 갱신했습니다 — 저장하면 새 판을 불러옵니다';return}
  location.reload()}).catch(function(){})},2000);
})();
</script>
"""

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
        if self.path.startswith("/mtime"): return reply(self, 200, str(DOC.stat().st_mtime_ns))
        if self.path.startswith("/doc"): return reply(self, 200, str(DOC))
        body = DOC.read_text(encoding="utf-8")
        ui = (UI.replace("__INITIAL__", json.dumps(INITIAL, ensure_ascii=False)).replace("__MTIME__", json.dumps(str(DOC.stat().st_mtime_ns)))
                .replace("__AGENT__", html_escape(AGENT)))
        body = body.replace("</body>", ui + "</body>", 1) if "</body>" in body else body + ui
        reply(self, 200, body, "text/html;charset=utf-8")
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if self.path.startswith("/save"):
            assert "__rv_bar" not in raw, "편집기 요소가 섞여 들어왔다"
            bak = DOC.with_suffix(".html.bak")
            if not bak.exists(): bak.write_bytes(DOC.read_bytes())
            raw = bump_meta(raw); DOC.write_text(raw, encoding="utf-8")
            return reply(self, 200, f"저장됨 {len(raw.encode()):,}B")
        if self.path.startswith("/confirm"):
            ev = json.loads(raw); ev.update(ts=datetime.datetime.now().isoformat(timespec="seconds"), doc=str(DOC), agent=AGENT, status="new")
            ev["approved"] = not ev.get("edits") and not ev.get("comments")
            with EVENTS.open("a", encoding="utf-8") as f: f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            if ev["approved"]: return reply(self, 200, f"이상 없음으로 제출되었습니다 — {AGENT} 에게 승인이 전달됩니다")
            return reply(self, 200, f"제출이 완료되었습니다 — 수정 {len(ev['edits'])}건 · 댓글 {len(ev['comments'])}건. {AGENT} 가 반영하면 화면이 자동으로 새로 고쳐집니다")
        reply(self, 404, "?")

if __name__ == "__main__":
    print(f"문서: {DOC}\n이벤트: {EVENTS}\nhttp://localhost:{A.port}/   (Ctrl+C 로 종료)", flush=True)
    if not A.no_open: webbrowser.open(f"http://localhost:{A.port}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", A.port), Handler).serve_forever()
