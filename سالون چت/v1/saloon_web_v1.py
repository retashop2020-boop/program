#!/usr/bin/env python3
"""Saloon Web v1 — local Persian-friendly multi-agent chat UI.

Python 3.10+, standard library only.
Run: python saloon_web_v1.py
Open: http://127.0.0.1:8765
API key: OPENROUTER_API_KEY environment variable or hidden terminal prompt.
"""
from __future__ import annotations

import getpass
import json
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API_URL = "https://openrouter.ai/api/v1/chat/completions"
HOST = "127.0.0.1"
PORT = 8765
CONFIG_PATH = Path("saloon_members.json")
LOG_DIR = Path("saloon_results")
MAX_HISTORY_MESSAGES = 24


@dataclass
class Member:
    name: str
    model: str
    role: str
    enabled: bool = True
    max_tokens: int = 1200
    temperature: float = 0.7


DEFAULT_MEMBERS = [
    Member(
        name="Skeptic",
        model="openrouter/free",
        role="نقش تو: شکاک دقیق و منصف. فرض‌ها، مثال‌های نقض و عدم‌قطعیت‌ها را بررسی کن. صرفاً برای مخالفت، مخالفت نکن. به فارسی پاسخ بده مگر کاربر زبان دیگری بخواهد.",
    ),
    Member(
        name="Analyst",
        model="openrouter/free",
        role="نقش تو: تحلیل‌گر مستقل. واقعیت، فرض، استنتاج و پرسش‌های باز را از هم جدا کن. از تقلید اعضای دیگر پرهیز کن. به فارسی پاسخ بده مگر کاربر زبان دیگری بخواهد.",
    ),
]


def load_members() -> list[Member]:
    if not CONFIG_PATH.exists():
        save_members(DEFAULT_MEMBERS)
        return [Member(**asdict(m)) for m in DEFAULT_MEMBERS]
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return [Member(**item) for item in raw]


def save_members(members: list[Member]) -> None:
    CONFIG_PATH.write_text(
        json.dumps([asdict(m) for m in members], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def call_model(api_key: str, member: Member, transcript: list[dict[str, Any]]) -> tuple[str, bool]:
    messages: list[dict[str, str]] = []
    for item in transcript[-MAX_HISTORY_MESSAGES:]:
        if item["kind"] == "user":
            messages.append({"role": "user", "content": item["text"]})
        elif item["kind"] == "reply":
            messages.append({
                "role": "assistant",
                "content": "[" + item["member"] + "]: " + item["text"],
            })
        elif item["kind"] == "error":
            messages.append({
                "role": "user",
                "content": "[اطلاع فنی: پاسخ عضو " + item.get("member", "نامشخص")
                + " ناموفق بود: " + item["text"] + "]",
            })
    messages.append({
        "role": "user",
        "content": (
            "تو عضو «" + member.name + "» در یک گفت‌وگوی گروهی هستی. "
            "به آخرین پیام کاربر یا ادعای مرتبط پاسخ بده. "
            "اگر با عضوی اختلاف داری، ادعای مشخص او را منصفانه بازگو کن. "
            "اختلاف موجه را حفظ کن و کل گفتگو را از ابتدا تکرار نکن."
        ),
    })
    payload = {
        "model": member.model,
        "messages": [{"role": "system", "content": member.role + "\n\nزبان پیش‌فرض گفتگو فارسی است. به فارسی روان و طبیعی پاسخ بده، مگر اینکه کاربر صریحاً زبان دیگری بخواهد. متن‌های انگلیسی، نام مدل‌ها و کدها را در صورت نیاز به شکل اصلی نگه دار."}, *messages],
        "temperature": member.temperature,
        "max_tokens": member.max_tokens,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json; charset=utf-8",
            "HTTP-Referer": "http://localhost/saloon-chat",
            "X-Title": "Saloon Web v1",
        },
        method="POST",
    )
    http_status = None
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            http_status = response.status
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError("HTTP " + str(exc.code) + ": " + detail) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("خطای ارتباط با سرویس: " + str(exc)) from exc

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("سرویس پاسخی برنگرداند: " + json.dumps(data, ensure_ascii=False)[:700])
    choice = choices[0]
    message = choice.get("message") or {}
    value = message.get("content")
    if isinstance(value, list):
        value = "\n".join(str(part.get("text", "")) for part in value if isinstance(part, dict))
    answer = str(value or "").strip()
    finish_reason = choice.get("finish_reason", "unknown")
    truncated = finish_reason == "length"

    # Diagnostic logging for empty/truncated responses. Never log request headers or API key.
    if not answer or truncated:
        print("\n[diagnostic] OpenRouter response for member: " + member.name)
        print("[diagnostic] HTTP status: " + str(http_status))
        print("[diagnostic] requested model: " + member.model)
        print("[diagnostic] returned model: " + str(data.get("model", "unknown")))
        print("[diagnostic] usage: " + json.dumps(data.get("usage"), ensure_ascii=False))
        print("[diagnostic] finish_reason: " + str(finish_reason))
        print("[diagnostic] raw choice (max 4000 chars): " + json.dumps(choice, ensure_ascii=False)[:4000])

    if not answer:
        raise RuntimeError("پاسخ خالی بود (finish_reason=" + str(finish_reason) + "). جزئیات تشخیصی در پنجرهٔ PowerShell ثبت شد.")
    return answer, truncated


def save_transcript(transcript: list[dict[str, Any]]) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / ("saloon_web_" + stamp + ".json")
    # Avoid overwriting if two saves occur in the same second.
    suffix = 1
    while path.exists():
        path = LOG_DIR / ("saloon_web_" + stamp + "_" + str(suffix) + ".json")
        suffix += 1
    path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def page_html() -> str:
    return r'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>سالوون | گفت‌وگوی چندمدلی</title>
<style>
:root{color-scheme:dark;--bg:#11151b;--panel:#1b222c;--panel2:#222b37;--line:#303b49;--text:#edf2f7;--muted:#a8b5c4;--accent:#7cc4b6;--user:#263f54;--error:#542f35}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:Tahoma,"Segoe UI",sans-serif;font-size:15px;line-height:1.8}
button,input,textarea,select{font:inherit}
button{cursor:pointer;border:1px solid var(--line);border-radius:10px;background:var(--panel2);color:var(--text);padding:8px 13px}
button:hover{border-color:var(--accent)}button.primary{background:#28685f;border-color:#347d72}button.danger{background:#492c32}
.app{display:grid;grid-template-columns:280px minmax(0,1fr);height:100vh;max-width:1600px;margin:auto}
aside{background:var(--panel);border-left:1px solid var(--line);padding:18px;overflow:auto}
.brand{font-size:23px;font-weight:bold;margin-bottom:2px}.sub{font-size:12px;color:var(--muted);margin-bottom:20px}
.section-title{display:flex;justify-content:space-between;align-items:center;font-weight:bold;margin:16px 0 8px}
.member{border:1px solid var(--line);border-radius:12px;padding:10px;margin-bottom:9px;background:#171d25}
.member.off{opacity:.55}.member-top{display:flex;align-items:center;gap:7px}.dot{width:9px;height:9px;border-radius:50%;background:var(--accent);flex:none}.off .dot{background:#66717e}
.member-name{font-weight:bold;flex:1;overflow-wrap:anywhere}.model{font-size:11px;color:var(--muted);direction:ltr;text-align:left;overflow-wrap:anywhere}
.member-actions{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}.member-actions button{font-size:12px;padding:4px 8px}
main{display:flex;flex-direction:column;min-width:0;min-height:0}
.topbar{padding:14px 22px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--panel)}
.topbar h1{font-size:17px;margin:0}.status{color:var(--muted);font-size:12px}
#messages{flex:1;overflow:auto;padding:24px max(16px,calc((100% - 900px)/2));scroll-behavior:smooth}
.welcome{text-align:center;color:var(--muted);margin:12vh auto 0;max-width:520px}.welcome h2{color:var(--text);font-size:25px}
.msg{max-width:900px;margin:0 auto 18px;border:1px solid var(--line);border-radius:15px;padding:13px 16px;background:var(--panel);box-shadow:0 4px 18px #00000012}
.msg.user{background:var(--user);border-color:#34556d}.msg.error{background:var(--error)}
.msg-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px;font-size:12px;color:var(--muted)}
.msg-head strong{color:var(--text);font-size:14px}.msg-body{white-space:pre-wrap;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:start;direction:auto}
.msg-body[dir="auto"]{unicode-bidi:plaintext}
.meta{font-size:11px;color:var(--muted);direction:ltr;text-align:left}
.composer-wrap{border-top:1px solid var(--line);padding:14px 20px 18px;background:var(--panel)}
.composer{max-width:900px;margin:auto;display:flex;gap:10px;align-items:flex-end}
textarea{resize:vertical;min-height:54px;max-height:220px;flex:1;background:#11171e;color:var(--text);border:1px solid var(--line);border-radius:13px;padding:12px 14px;outline:none;direction:auto;text-align:start}
textarea:focus,input:focus,select:focus{border-color:var(--accent);outline:1px solid #7cc4b633}
.hint{max-width:900px;margin:5px auto 0;color:var(--muted);font-size:11px}
.overlay{position:fixed;inset:0;background:#0009;display:none;align-items:center;justify-content:center;padding:16px;z-index:5}.dialog{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;width:min(600px,100%);max-height:90vh;overflow:auto}
.dialog h2{margin-top:0}.field{display:block;margin:12px 0}.field span{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}
.field input,.field textarea,.field select{width:100%;background:#11171e;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px;direction:auto;text-align:start}
.field textarea{min-height:100px}.checkline{display:flex;align-items:center;gap:8px}.dialog-actions{display:flex;gap:8px;justify-content:flex-start;margin-top:18px}
.busy{display:inline-flex;gap:8px;align-items:center;color:var(--muted);font-size:13px}.spinner{width:14px;height:14px;border:2px solid #5d6b78;border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:760px){.app{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr)}aside{border-left:0;border-bottom:1px solid var(--line);max-height:210px;padding:10px 14px}.brand{font-size:18px}.sub{margin-bottom:4px}.section-title{margin:7px 0}.member-list{display:flex;gap:8px;overflow-x:auto}.member{min-width:190px;margin:0}.topbar{padding:10px 14px}#messages{padding:16px 10px}.composer-wrap{padding:10px}.composer{gap:6px}button{padding:8px 10px}}
</style>
</head>
<body>
<div class="app">
<aside>
  <div class="brand">سالوون <span style="color:var(--accent)">●</span></div>
  <div class="sub">محیط گفت‌وگوی چند هوش مصنوعی</div>
  <div class="section-title"><span>اعضای گفتگو</span><button id="addMember">+ عضو</button></div>
  <div id="memberList" class="member-list"></div>
  <div style="font-size:11px;color:var(--muted);margin-top:14px">نام و نقش اعضا قابل ویرایش است. تغییرات در فایل محلی saloon_members.json ذخیره می‌شوند.</div>
  <button id="newChat" style="width:100%;margin-top:18px">گفت‌وگوی تازه</button>
</aside>
<main>
  <div class="topbar"><div><h1 id="chatTitle">گفت‌وگوی تازه</h1><div class="status" id="status">آمادهٔ گفتگو</div></div><button id="saveChat">ذخیره گفتگو</button></div>
  <div id="messages"><div class="welcome" id="welcome"><h2>از کجا شروع کنیم؟</h2><p>موضوعت را به فارسی بنویس. هر عضو فعال پاسخ خودش را می‌دهد؛ ادامهٔ بحث با پیام بعدی تو پیش می‌رود.</p></div></div>
  <div class="composer-wrap"><div class="composer"><textarea id="input" rows="2" placeholder="پیامت را بنویس… (Enter برای ارسال، Shift+Enter برای خط جدید)"></textarea><button id="send" class="primary">ارسال</button></div><div class="hint">این محیط فقط روی همین رایانه باز می‌شود. پاسخ مدل‌ها به سرویس OpenRouter فرستاده می‌شود.</div></div>
</main>
</div>
<div class="overlay" id="overlay"><div class="dialog"><h2 id="dialogTitle">افزودن عضو</h2><form id="memberForm">
<label class="field"><span>نام نمایشی</span><input id="mName" required></label>
<label class="field"><span>شناسهٔ مدل در OpenRouter</span><input id="mModel" required placeholder="openrouter/free"></label>
<label class="field"><span>نقش و دستورالعمل (می‌توانی فارسی بنویسی)</span><textarea id="mRole" required></textarea></label>
<label class="field"><span>حداکثر توکن پاسخ</span><input id="mTokens" type="number" min="100" max="8000" value="1200"></label>
<label class="field"><span>Temperature (۰ تا ۲)</span><input id="mTemp" type="number" min="0" max="2" step="0.1" value="0.7"></label>
<label class="checkline"><input id="mEnabled" type="checkbox" checked> عضو فعال باشد</label>
<div class="dialog-actions"><button class="primary" type="submit">ذخیره عضو</button><button type="button" id="cancelDialog">انصراف</button></div>
</form></div></div>
<script>
const $ = id => document.getElementById(id);
let members = [], editingIndex = null, busy = false, transcript = [], title = "";
function el(tag, cls, txt){const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;}
async function api(path, data){const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});const j=await r.json();if(!r.ok||j.error)throw new Error(j.error||'خطای نامشخص');return j;}
function renderMembers(){const box=$('memberList');box.replaceChildren();members.forEach((m,i)=>{const card=el('div','member'+(m.enabled?'':' off'));const top=el('div','member-top');top.append(el('span','dot'),el('span','member-name',m.name));card.append(top,el('div','model',m.model));const acts=el('div','member-actions');const toggle=el('button','',m.enabled?'غیرفعال‌کردن':'فعال‌کردن');toggle.onclick=()=>changeMember(i,{...m,enabled:!m.enabled});const edit=el('button','','ویرایش');edit.onclick=()=>openDialog(i);const remove=el('button','danger','حذف');remove.onclick=async()=>{if(!confirm('عضو «'+m.name+'» حذف شود؟'))return;const next=members.filter((_,j)=>j!==i);await saveMembers(next);};acts.append(toggle,edit,remove);card.append(acts);box.append(card);});}
async function saveMembers(next){try{const r=await api('/api/members',{members:next});members=r.members;renderMembers();}catch(e){alert(e.message);}}
async function changeMember(i,m){const next=members.slice();next[i]=m;await saveMembers(next);}
function openDialog(i=null){editingIndex=i;const m=i===null?{name:'',model:'openrouter/free',role:'به فارسی پاسخ بده. واقعیت‌ها، فرض‌ها و استنتاج‌ها را از هم جدا کن.',enabled:true,max_tokens:1200,temperature:.7}:members[i];$('dialogTitle').textContent=i===null?'افزودن عضو':'ویرایش عضو';$('mName').value=m.name;$('mModel').value=m.model;$('mRole').value=m.role;$('mTokens').value=m.max_tokens||1200;$('mTemp').value=m.temperature??.7;$('mEnabled').checked=!!m.enabled;$('overlay').style.display='flex';$('mName').focus();}
function closeDialog(){$('overlay').style.display='none';}
$('cancelDialog').onclick=closeDialog;$('addMember').onclick=()=>openDialog();$('overlay').addEventListener('click',e=>{if(e.target===$('overlay'))closeDialog();});
$('memberForm').onsubmit=async e=>{e.preventDefault();const m={name:$('mName').value.trim(),model:$('mModel').value.trim(),role:$('mRole').value.trim(),enabled:$('mEnabled').checked,max_tokens:Number($('mTokens').value)||1200,temperature:Number($('mTemp').value)||0};if(!m.name||!m.model||!m.role)return;const next=members.slice();if(editingIndex===null)next.push(m);else next[editingIndex]=m;await saveMembers(next);closeDialog();};
function addMessage(kind,name,text,meta=''){const welcome=$('welcome');if(welcome)welcome.remove();const box=el('article','msg '+kind);const head=el('div','msg-head');head.append(el('strong','',name),el('span','meta',meta));const body=el('div','msg-body',text);body.dir='auto';box.append(head,body);$('messages').append(box);$('messages').scrollTop=$('messages').scrollHeight;return box;}
function setBusy(v,label='در حال دریافت پاسخ…'){busy=v;$('send').disabled=v;$('input').disabled=v;$('status').textContent=v?label:'آمادهٔ گفتگو';if(v){$('send').textContent='منتظر…';}else{$('send').textContent='ارسال';}}
async function sendMessage(){if(busy)return;const text=$('input').value.trim();if(!text)return;$('input').value='';if(!title){title=text.slice(0,55);$('chatTitle').textContent=title;}transcript.push({kind:'user',text,at:new Date().toISOString()});addMessage('user','تو',text);setBusy(true);const pending=addMessage('','سالوون','اعضا در حال پاسخ‌گویی هستند…');try{const r=await api('/api/chat',{text,transcript});pending.remove();for(const item of r.events){transcript.push(item);if(item.kind==='reply')addMessage('',''+item.member,item.text,item.model);else if(item.kind==='error')addMessage('error','خطا: '+item.member,item.text);}if(r.saved)$('status').textContent='ذخیره شد: '+r.saved.split(/[\\/]/).pop();}catch(e){pending.remove();addMessage('error','خطای سالوون',e.message);}finally{setBusy(false);$('input').focus();}}
$('send').onclick=sendMessage;$('input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}});
$('newChat').onclick=()=>{if(busy)return;if(transcript.length&&!confirm('گفتگوی فعلی پاک شود؟ فایل ذخیره‌شده باقی می‌ماند.'))return;transcript=[];title='';$('chatTitle').textContent='گفت‌وگوی تازه';$('messages').replaceChildren();const w=el('div','welcome');w.id='welcome';w.append(el('h2','', 'از کجا شروع کنیم؟'),el('p','','موضوعت را به فارسی بنویس.'));$('messages').append(w);$('status').textContent='گفت‌وگوی تازه';};
$('saveChat').onclick=async()=>{try{const r=await api('/api/save',{transcript,title});$('status').textContent='ذخیره شد: '+r.saved.split(/[\\/]/).pop();}catch(e){alert(e.message);}};
(async()=>{try{const r=await api('/api/state');members=r.members;renderMembers();}catch(e){alert('خطا در بارگذاری: '+e.message);}})();
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "SaloonWeb/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[web] " + (fmt % args))

    def send_json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("درخواست بیش از حد بزرگ است.")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            body = page_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self.send_json(200, {"members": [asdict(m) for m in self.server.members]})
        else:
            self.send_json(404, {"error": "مسیر پیدا نشد."})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/members":
                raw_members = data.get("members")
                if not isinstance(raw_members, list):
                    raise ValueError("فهرست اعضا معتبر نیست.")
                cleaned: list[Member] = []
                for item in raw_members:
                    m = Member(
                        name=str(item.get("name", "")).strip(),
                        model=str(item.get("model", "")).strip(),
                        role=str(item.get("role", "")).strip(),
                        enabled=bool(item.get("enabled", True)),
                        max_tokens=max(100, min(8000, int(item.get("max_tokens", 1200)))),
                        temperature=max(0.0, min(2.0, float(item.get("temperature", 0.7)))),
                    )
                    if not m.name or not m.model or not m.role:
                        raise ValueError("نام، شناسهٔ مدل و نقش همهٔ اعضا الزامی است.")
                    cleaned.append(m)
                if not cleaned:
                    raise ValueError("حداقل یک عضو باید در فهرست باقی بماند.")
                self.server.members = cleaned
                save_members(cleaned)
                self.send_json(200, {"members": [asdict(m) for m in cleaned]})
            elif path == "/api/chat":
                text = str(data.get("text", "")).strip()
                transcript = data.get("transcript", [])
                if not text:
                    raise ValueError("پیام خالی است.")
                active = [m for m in self.server.members if m.enabled]
                if not active:
                    raise ValueError("هیچ عضو فعالی وجود ندارد. از پنل اعضا یکی را فعال کن.")
                context = list(transcript)
                events: list[dict[str, Any]] = []
                for member in active:
                    try:
                        answer, truncated = call_model(self.server.api_key, member, context)
                        if truncated:
                            answer += "\n\n[هشدار: احتمال دارد پاسخ به‌دلیل رسیدن به سقف توکن ناقص باشد.]"
                        event = {"kind": "reply", "member": member.name, "model": member.model,
                                 "text": answer, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                        events.append(event)
                        context.append(event)
                    except RuntimeError as exc:
                        event = {"kind": "error", "member": member.name, "text": str(exc),
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                        events.append(event)
                        context.append(event)
                all_events = transcript + events
                saved = save_transcript(all_events)
                self.send_json(200, {"events": events, "saved": saved})
            elif path == "/api/save":
                transcript = data.get("transcript", [])
                if not isinstance(transcript, list):
                    raise ValueError("تاریخچه معتبر نیست.")
                self.send_json(200, {"saved": save_transcript(transcript)})
            else:
                self.send_json(404, {"error": "مسیر پیدا نشد."})
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "خطای داخلی: " + str(exc)})


def main() -> None:
    if not CONFIG_PATH.exists():
        save_members(DEFAULT_MEMBERS)
        print("فایل تنظیمات اولیه ساخته شد: " + str(CONFIG_PATH))
    try:
        members = load_members()
    except Exception as exc:
        print("خطا در خواندن تنظیمات اعضا: " + str(exc))
        return
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("OpenRouter API key (input hidden): ").strip()
    if not api_key:
        print("کلید API وارد نشد؛ برنامه اجرا نمی‌شود.")
        return
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.members = members
    server.api_key = api_key
    url = "http://" + HOST + ":" + str(PORT)
    print("\nسالوون آماده است: " + url)
    print("برای توقف برنامه، در این پنجره Ctrl+C بزن.")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nسالوون متوقف شد.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
