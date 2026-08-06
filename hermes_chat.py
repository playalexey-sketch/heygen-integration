# -*- coding: utf-8 -*-
"""
=====================================================================
  Локальный чат с Hermes / Qwen — ОДНИМ ФАЙЛОМ, без установки проекта
=====================================================================

Что делает:
  - подключается к вашей Ollama (модель Hermes или Qwen уже в ней),
  - даёт веб-интерфейс чата "как чатник" (стриминг, выбор модели,
    установка новых моделей прямо из интерфейса).

Запуск (Windows PowerShell):
    python hermes_chat.py
  или
    python C:\\Users\\User\\hermes_chat.py

Потом откройте в браузере:  http://localhost:8002

Требуется:
  - установленный Python 3.9+ (https://www.python.org)
  - установленная Ollama (https://ollama.com) и модель, например:
        ollama pull hermes3:8b        (или ollama pull qwen3:8b)
  - зависимости (один раз):  pip install fastapi uvicorn requests python-multipart

Адрес Ollama можно поменять переменной OLLAMA_URL.
=====================================================================
"""

import json
import os
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
PORT = int(os.getenv("PORT", "8002"))
HOST = os.getenv("HOST", "127.0.0.1")

MODEL_CATALOG = [
    "hermes3:8b", "hermes3:3b", "hermes3:70b",
    "qwen3:8b", "qwen3:4b", "qwen3:1.7b",
    "llama3.1:8b", "gemma2:9b", "mistral:7b", "phi3:mini",
]

HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Локальный чат Hermes / Qwen</title>
<style>
  :root{--bg:#0f1420;--panel:#1a2130;--panel2:#222c40;--line:#2e3a52;--text:#e8ecf4;--muted:#8b96ab;--accent:#4f8cff;--accent2:#6ee7b7;}
  *{box-sizing:border-box;}
  body{margin:0;height:100vh;display:flex;flex-direction:column;background:var(--bg);color:var(--text);font-family:"Segoe UI",system-ui,sans-serif;}
  header{padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
  header .logo{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,var(--accent),#7c5cff);font-size:20px;}
  header h1{margin:0;font-size:18px;}
  header .status{margin-left:auto;font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;}
  header .dot{width:9px;height:9px;border-radius:50%;background:#f87171;}
  header .dot.ok{background:var(--accent2);}
  select{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px;outline:none;}
  input[type=text]{width:170px;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px;outline:none;}
  #chat{flex:1;overflow-y:auto;padding:20px;}
  .msg{max-width:760px;margin:0 auto 16px;display:flex;gap:12px;}
  .msg .avatar{width:34px;height:34px;border-radius:8px;flex-shrink:0;display:grid;place-items:center;font-size:17px;}
  .msg.user{flex-direction:row-reverse;}
  .msg.user .avatar{background:var(--accent);}
  .msg.assistant .avatar{background:#2a3350;}
  .bubble{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:11px 14px;line-height:1.55;white-space:pre-wrap;word-wrap:break-word;font-size:14.5px;}
  .msg.user .bubble{background:#26314a;border-color:var(--accent);}
  .msg .name{font-size:11px;color:var(--muted);margin-bottom:4px;}
  .cursor::after{content:"\\u258b";color:var(--accent2);animation:blink 1s step-start infinite;}
  @keyframes blink{50%{opacity:0;}}
  .hintbar{display:none;padding:10px 20px;background:var(--panel);border-top:1px solid var(--line);font-size:13px;color:var(--muted);}
  .hintbar.show{display:block;}
  form{display:flex;gap:10px;padding:14px 20px;background:var(--panel);border-top:1px solid var(--line);}
  textarea{flex:1;resize:none;background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:11px 14px;font-size:14px;outline:none;font-family:inherit;}
  textarea:focus{border-color:var(--accent);}
  button{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#0b1020;border:none;border-radius:10px;padding:0 22px;font-size:15px;font-weight:600;cursor:pointer;}
  button:disabled{opacity:.5;cursor:not-allowed;}
  button.small{padding:6px 12px;font-size:13px;}
</style></head><body>
<header>
  <div class="logo">\\U0001f9e0</div>
  <h1>Локальный чат (Hermes / Qwen)</h1>
  <select id="model"></select>
  <button id="install-btn" type="button" class="small">\\u2b07 Установить</button>
  <input type="text" id="custom-model" placeholder="или своё имя модели">
  <div class="status"><span class="dot" id="dot"></span><span id="status">проверка…</span></div>
</header>
<div id="chat"></div>
<form id="form">
  <textarea id="input" rows="1" placeholder="Спросите что-нибудь…"></textarea>
  <button id="send" type="submit">\\u27a4</button>
</form>
<div class="hintbar" id="hintbar"></div>
<script>
const chatEl=document.getElementById('chat'),formEl=document.getElementById('form'),inputEl=document.getElementById('input');
const sendBtn=document.getElementById('send'),modelEl=document.getElementById('model'),dotEl=document.getElementById('dot');
const statusEl=document.getElementById('status'),installBtn=document.getElementById('install-btn'),hintbarEl=document.getElementById('hintbar');
const customModelEl=document.getElementById('custom-model');
let history=[];
const API_BASE=location.pathname.startsWith('/hermes')?'/hermes/api':'/api';
function addMsg(role,text,streaming=false){const m=document.createElement('div');m.className='msg '+role;
 m.innerHTML='<div class="avatar">'+(role==='user'?'\\uD83D\\uDE42':'\\U0001f9e0')+'</div><div><div class="name">'+(role==='user'?'Вы':'Модель')+'</div><div class="bubble">'+esc(text)+'</div></div>';
 chatEl.appendChild(m);if(streaming)m.querySelector('.bubble').classList.add('cursor');chatEl.scrollTop=chatEl.scrollHeight;return m;}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function showHint(m){hintbarEl.textContent=m;hintbarEl.classList.add('show');}
function addOption(v,s){const o=document.createElement('option');o.value=v;o.textContent=v+s;modelEl.appendChild(o);}
async function refreshModels(){try{const r=await fetch(API_BASE+'/models');const d=await r.json();modelEl.innerHTML='';
  if(d.ollama_up){dotEl.classList.add('ok');statusEl.textContent='Ollama работает';}
  else{dotEl.classList.remove('ok');statusEl.textContent='Ollama не запущен';showHint('Ollama не отвечает. Запустите Ollama (ollama serve).');return;}
  const inst=d.installed||[];inst.forEach(m=>addOption(m,' ✓ установлена'));
  (d.catalog||[]).forEach(m=>{if(!inst.includes(m))addOption(m,' (не установлена)');});
  if(!inst.length)showHint('Нет моделей. Выберите в списке и нажмите «Установить».');
  else{hintbarEl.classList.remove('show');}
 }catch(e){statusEl.textContent='нет связи с сервером';}}
installBtn.addEventListener('click',async()=>{const custom=customModelEl.value.trim();const model=custom||modelEl.value;if(!model)return;
 installBtn.disabled=true;showHint('⏳ Устанавливаю '+model+'… это может занять несколько минут.');
 try{const r=await fetch(API_BASE+'/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model})});
  const d=await r.json();if(d.ok){showHint('✅ '+model+' установлена. Можете отправлять сообщения.');customModelEl.value='';await refreshModels();modelEl.value=model;}
  else showHint('❌ '+d.error);}catch(e){showHint('❌ '+e);}
 installBtn.disabled=false;});
customModelEl.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();installBtn.click();}});
(async function init(){await refreshModels();})();
formEl.addEventListener('submit',async(e)=>{e.preventDefault();const text=inputEl.value.trim();if(!text||sendBtn.disabled)return;
 history.push({role:'user',content:text});addMsg('user',text);inputEl.value='';sendBtn.disabled=true;
 const m=addMsg('assistant','',true);const bubble=m.querySelector('.bubble');let acc='';
 try{const resp=await fetch(API_BASE+'/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:modelEl.value,messages:history})});
  const reader=resp.body.getReader();const decoder=new TextDecoder();let buf='';
  while(true){const {done,value}=await reader.read();if(done)break;buf+=decoder.decode(value,{stream:true});
   let idx;while((idx=buf.indexOf('\\n\\n'))!==-1){const line=buf.slice(0,idx).replace(/^data: /,'');buf=buf.slice(idx+2);if(!line)continue;
    let j;try{j=JSON.parse(line);}catch(_){continue;}
    if(j.error)acc+='\\n[ошибка] '+j.error;else if(j.delta)acc+=j.delta;
    bubble.textContent=acc;chatEl.scrollTop=chatEl.scrollHeight;if(j.done)break;}}}
 catch(err){acc='[нет связи с сервером] '+err;}
 bubble.textContent=acc;bubble.classList.remove('cursor');history.push({role:'assistant',content:acc});sendBtn.disabled=false;inputEl.focus();});
inputEl.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();formEl.requestSubmit();}});
</script></body></html>"""

app = FastAPI(title="Hermes Local Chat", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _installed() -> list:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.get("/api/models")
def models():
    inst = _installed()
    return {"installed": inst, "catalog": MODEL_CATALOG, "ollama_up": bool(inst) or _alive()}


def _alive() -> bool:
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


@app.post("/api/pull")
def pull(req: dict):
    model = (req.get("model") or "").strip()
    if not model:
        return JSONResponse({"error": "Модель не указана"}, status_code=400)
    try:
        r = requests.post(f"{OLLAMA_URL}/api/pull", json={"name": model, "stream": False}, timeout=1800)
        if r.status_code != 200:
            return JSONResponse({"error": f"Ollama pull: {r.status_code} {r.text[:300]}"}, status_code=502)
        return {"ok": True, "model": model}
    except Exception as exc:
        return JSONResponse({"error": f"Нет связи с Ollama: {exc}"}, status_code=502)


@app.post("/api/chat")
def chat(req: dict):
    model = req.get("model", "hermes3:8b")
    messages = req.get("messages", [])
    payload = {"model": model, "messages": messages, "stream": True}

    def gen():
        try:
            with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=120) as resp:
                if resp.status_code != 200:
                    yield f'data: {json.dumps({"error": f"Ollama: {resp.status_code} {resp.text[:300]}"})}\n\n'
                    return
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield f'data: {json.dumps({"delta": content})}\n\n'
                    if chunk.get("done"):
                        yield f'data: {json.dumps({"done": True})}\n\n'
        except Exception as exc:
            yield f'data: {json.dumps({"error": f"Нет связи с Ollama: {exc}"})}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print(f"\n  Локальный чат:  http://localhost:{PORT}")
    print(f"  Ollama:          {OLLAMA_URL}")
    print("  Выберите модель в браузере и общайтесь.\n")
    uvicorn.run(app, host=HOST, port=PORT)
