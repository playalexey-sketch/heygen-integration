let phases = [];
let currentProject = null;
let projects = [];

const API = "";

async function fetchJSON(url, opts){
  const r = await fetch(url, opts);
  if(!r.ok){
    const txt = await r.text();
    throw new Error(txt);
  }
  return r.json();
}

function qs(sel){return document.querySelector(sel)}

async function init(){
  try{
    const data = await fetchJSON('/api/phases');
    phases = data.phases;
    renderPhasesNav();
    renderOverview();
    renderJourney();
  }catch(e){console.error(e)}

  await loadProjects();
  if(projects.length>0){
    selectProject(projects[0].id);
  }else{
    switchTab('phase_1');
  }

  document.getElementById('btn-new-project').addEventListener('click', openNewProjectModal);
}

async function loadProjects(){
  const data = await fetchJSON('/api/projects');
  projects = data.projects;
  document.getElementById('projects-count').textContent = projects.length;
  const list = document.getElementById('projects-list');
  list.innerHTML = "";
  projects.forEach(p=>{
    const div = document.createElement('div');
    div.className = `glass card p-3 cursor-pointer hover:border-white/20 ${currentProject && currentProject.id===p.id ? 'border-[#FF6B6B]/50 bg-[#1A2130]' : ''}`;
    div.innerHTML = `
      <div class="flex items-center justify-between">
        <div class="font-[700] text-sm truncate">${p.name}</div>
        <div class="text-[10px] mono opacity-60">${Math.round(p.completion)}%</div>
      </div>
      <div class="mono text-[11px] opacity-50 mt-1">${p.id} • ${p.input.niche || 'нет ниши'}</div>
      <div class="progress-bar mt-2"><div class="progress-fill" style="width:${p.completion}%"></div></div>
    `;
    div.onclick = ()=>selectProject(p.id);
    list.appendChild(div);
  });
}

async function selectProject(pid){
  const data = await fetchJSON(`/api/projects/${pid}`);
  currentProject = data;
  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('project-header').classList.remove('hidden');
  document.getElementById('project-name').textContent = data.name;
  document.getElementById('project-id-badge').textContent = data.id;
  document.getElementById('project-meta').textContent = `${data.input.niche || 'ниша не указана'} • ${data.input.expert_name || 'эксперт?'} • ${new Date(data.created_at).toLocaleString()} • ${Object.keys(data.agent_states).filter(k=>data.agent_states[k].status==='approved').length}/${Object.keys(data.agent_states).length} agents approved`;
  
  // fill inputs
  const map = {
    'inp-niche': data.input.niche,
    'inp-expert_name': data.input.expert_name,
    'inp-expert_current': data.input.expert_current,
    'inp-superpowers': data.input.superpowers,
    'inp-stories': data.input.stories,
    'inp-proof_existing': data.input.proof_existing,
    'inp-competitors': data.input.competitors,
    'inp-target_revenue': data.input.target_revenue,
  };
  for(const k in map){ const el=document.getElementById(k); if(el) el.value=map[k]||''; }

  updateFactoryProgress();
  renderCurrentPhase();
  renderFactoryGraph();
  loadArtifacts();
  await loadProjects(); // refresh sidebar highlight
}

function updateFactoryProgress(){
  if(!currentProject) return;
  const states = Object.values(currentProject.agent_states);
  const approved = states.filter(s=>s.status==='approved').length;
  const total = states.length;
  const pct = total? Math.round(approved/total*100):0;
  document.getElementById('factory-progress-txt').textContent = pct+'%';
  document.getElementById('factory-approved-txt').textContent = `${approved}/${total} approved`;
  document.getElementById('factory-progress-bar').style.width = pct+'%';
}

let activeTab = 'phase_1';

function switchTab(tab){
  activeTab = tab;
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('tab-active'));

  let targetId = 'tab-generic';
  if(tab.startsWith('phase_')){
    if(tab==='phase_1'){
      targetId='tab-phase_1';
    }else{
      document.getElementById('tab-generic').classList.remove('hidden');
      renderGenericPhase(tab);
      document.querySelectorAll(`[data-tab="${tab}"]`).forEach(el=>el.classList.add('tab-active'));
      return;
    }
  }else if(['overview','factory','artifacts','journey'].includes(tab)){
    targetId = `tab-${tab}`;
  }else{
    targetId='tab-phase_1';
  }
  const target = document.getElementById(targetId);
  if(target) target.classList.remove('hidden');
  document.querySelectorAll(`[data-tab="${tab}"]`).forEach(el=>el.classList.add('tab-active'));
  if(tab==='phase_1') renderCurrentPhase();
}

function renderPhasesNav(){
  const nav = document.getElementById('phases-nav');
  nav.innerHTML="";
  phases.forEach(p=>{
    const div=document.createElement('div');
    div.className="glass card p-3 cursor-pointer hover:bg-[#1A2338]";
    div.innerHTML=`
      <div class="flex items-center gap-2">
        <span class="text-lg">${p.icon}</span>
        <div class="leading-tight">
          <div class="text-[13px] font-[700]">${p.title}</div>
          <div class="text-[11px] mono opacity-60">${p.subtitle}</div>
        </div>
      </div>
      <div class="mt-2 flex gap-1 flex-wrap">
        ${p.agents.slice(0,4).map(a=>`<span class="text-[10px] px-2 py-0.5 rounded-full bg-black/30 mono">${a.icon} ${a.id}</span>`).join('')}
        ${p.agents.length>4? `<span class="text-[10px] px-2 py-0.5 rounded-full bg-black/30 mono">+${p.agents.length-4}</span>` : ''}
      </div>
    `;
    div.onclick=()=>switchTab(p.id);
    nav.appendChild(div);
  });
}

function renderCurrentPhase(){
  if(!currentProject || !phases.length) return;
  const phase = phases.find(p=>p.id==='phase_1');
  if(!phase) return;
  const spContainer = document.getElementById('subphases-container');
  spContainer.innerHTML="";

  phase.subphases.forEach((sp, idx)=>{
    const div=document.createElement('div');
    div.className="glass card p-5";
    div.innerHTML=`
      <div class="flex items-start gap-3">
        <div class="w-8 h-8 rounded-xl bg-[#1A2130] border border-white/10 grid place-items-center text-sm font-bold">${idx+1}</div>
        <div class="flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h4 class="font-[800] text-[14px]">${sp.title}</h4>
            <span class="text-[10px] px-2 py-0.5 rounded-full bg-[#10213A] text-[#60A5FA] mono">${sp.goal}</span>
          </div>
          <div class="grid md:grid-cols-2 gap-3 mt-3">
            <div class="bg-[#FF6B6B]/10 border border-[#FF6B6B]/20 rounded-xl p-3">
              <div class="mono text-[10px] opacity-60">ПРОБЛЕМЫ ДО (как у 90%):</div>
              <ul class="text-[12px] mt-1 leading-5 list-disc ml-4 opacity-80">${sp.problems_before.map(t=>`<li>${t}</li>`).join('')}</ul>
            </div>
            <div class="bg-[#6EE7B7]/10 border border-[#6EE7B7]/20 rounded-xl p-3">
              <div class="mono text-[10px] opacity-60">ЧТО УЛУЧШЕНО В ФАБРИКЕ:</div>
              <ul class="text-[12px] mt-1 leading-5 list-disc ml-4 opacity-80">${sp.improvements.map(t=>`<li>${t}</li>`).join('')}</ul>
            </div>
          </div>
          <div class="mt-3">
            <div class="mono text-[10px] opacity-50 mb-1">ЗАДАЧИ (чек-лист):</div>
            <div class="grid md:grid-cols-2 gap-2">
              ${sp.tasks.map(t=>`<div class="flex gap-2 text-[12px] bg-black/20 rounded-lg p-2"><span>✅</span><div><div class="font-[600]">${t.title}</div><div class="opacity-60 text-[11px]">${t.description}</div></div></div>`).join('')}
            </div>
          </div>
          <div class="mt-2 mono text-[10px] opacity-40">Агенты: ${sp.agents.join(', ')} • Артефакты: ${sp.artifacts.join(', ')}</div>
        </div>
      </div>
    `;
    spContainer.appendChild(div);
  });

  // Agents pipeline
  const pipe = document.getElementById('agents-pipeline');
  pipe.innerHTML="";
  phase.agents.forEach(agent=>{
    const state = currentProject.agent_states[agent.id];
    const status = state ? state.status : 'idle';
    const div=document.createElement('div');
    div.className=`glass card p-4 agent-card border ${status==='needs_review' ? 'border-[#FBBF24]/40' : 'border-white/10'}`;
    div.innerHTML=`
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="text-xl">${agent.icon}</span>
          <div>
            <div class="font-[700] text-[13px]">${agent.name}</div>
            <div class="mono text-[10px] opacity-60">${agent.id} • ${agent.role}</div>
          </div>
        </div>
        <span class="px-2 py-1 rounded-full text-[10px] mono font-bold status-${status}">${status}</span>
      </div>
      <div class="mt-3 text-[12px] opacity-80 leading-5">${agent.description}</div>
      <div class="mt-3 grid grid-cols-2 gap-2">
        <div class="bg-black/30 rounded-lg p-2">
          <div class="mono text-[10px] opacity-50">ВХОДЫ:</div>
          <div class="text-[11px] mono mt-1">${agent.inputs_required.map(i=>`<span class="inline-block mr-1 mb-1 px-2 py-0.5 rounded bg-[#1A2130]">${i}</span>`).join('')}</div>
        </div>
        <div class="bg-black/30 rounded-lg p-2">
          <div class="mono text-[10px] opacity-50">ВЫХОДЫ:</div>
          <div class="text-[11px] mono mt-1">${agent.outputs_produced.map(o=>`<span class="inline-block mr-1 mb-1 px-2 py-0.5 rounded bg-[#123025] text-[#6EE7B7] cursor-pointer" onclick="previewArtifact('${o}')">${o}</span>`).join('')}</div>
        </div>
      </div>
      <div class="mt-3">
        <div class="mono text-[10px] opacity-50">ЗАДАЧИ АГЕНТА:</div>
        <div class="flex flex-wrap gap-1 mt-1">${agent.tasks.map(t=>`<span class="text-[11px] px-2 py-1 rounded-full bg-[#1A2130] border border-white/5">${t}</span>`).join('')}</div>
      </div>
      ${state ? `<div class="mt-3 bg-[#0F1420] rounded-lg p-2 mono text-[11px] leading-5"><div class="opacity-60">Лог: ${state.message || '—'}</div><div class="opacity-40 mt-1">прогресс ${state.progress}% • ${state.started_at||''}</div>${state.error? `<div class="text-[#FB7185] mt-1 whitespace-pre-wrap">${state.error.slice(0,500)}</div>`:''}</div>` : ''}
      <div class="mt-3 flex gap-2">
        <button onclick="runAgent('${agent.id}')" class="px-3 py-2 rounded-xl bg-white text-black text-xs font-[800] hover:bg-zinc-200">▶️ Run</button>
        <button onclick="previewAgentOutputs('${agent.id}')" class="px-3 py-2 rounded-xl bg-[#1A2130] border border-white/10 text-xs">👁️ Preview</button>
        <button onclick="approveAgent('${agent.id}')" class="px-3 py-2 rounded-xl bg-[#4ADE80] text-black text-xs font-[800]">✅ Approve</button>
        <button onclick="rejectAgent('${agent.id}')" class="px-3 py-2 rounded-xl bg-[#1A2130] border border-white/10 text-xs">↩️ Доработать</button>
      </div>
      ${agent.human_checkpoints.length? `<div class="mt-2 mono text-[10px] opacity-60">👤 Human checkpoints: ${agent.human_checkpoints.join(' • ')}</div>` : ''}
    `;
    pipe.appendChild(div);
  });

  // preview manifest if exists
  const manifestArtifact = currentProject.artifacts.find(a=>a.filename==='07_brand_manifest.md');
  if(manifestArtifact){
    previewArtifactInline('07_brand_manifest.md', 'manifest-preview');
  }
}

function renderGenericPhase(phaseId){
  const phase = phases.find(p=>p.id===phaseId);
  const container = document.getElementById('generic-content');
  if(!phase){ container.innerHTML="Phase not found"; return; }
  container.innerHTML=`
    <div class="glass card p-6 mb-5" style="border-left:4px solid ${phase.color}">
      <div class="flex items-center gap-3"><span class="text-2xl">${phase.icon}</span><h2 class="font-[800] text-xl">${phase.title}</h2></div>
      <div class="mono text-xs opacity-60 mt-1">${phase.subtitle}</div>
      <div class="mt-3 text-sm opacity-80">${phase.goal} → <b>${phase.outcome}</b></div>
    </div>
    <div class="grid md:grid-cols-2 gap-4">
      ${phase.agents.map(agent=>{
        const state = currentProject ? currentProject.agent_states[agent.id] : null;
        const status = state ? state.status : 'idle';
        return `<div class="glass card p-4">
          <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span>${agent.icon}</span><span class="font-bold text-sm">${agent.name}</span></div><span class="px-2 py-1 rounded-full text-[10px] mono status-${status}">${status}</span></div>
          <div class="text-xs opacity-70 mt-2">${agent.description}</div>
          <div class="mt-2 mono text-[10px]">Входы: ${agent.inputs_required.join(', ')}</div>
          <div class="mt-1 mono text-[10px]">Выходы: ${agent.outputs_produced.join(', ')}</div>
          <div class="mt-3 flex gap-2">
            <button onclick="runAgent('${agent.id}')" class="px-3 py-1.5 rounded-lg bg-white text-black text-xs font-bold">Run</button>
            <button onclick="approveAgent('${agent.id}')" class="px-3 py-1.5 rounded-lg bg-[#4ADE80] text-black text-xs font-bold">Approve</button>
          </div>
        </div>`;
      }).join('')}
    </div>
    <div class="mt-6">
      <h3 class="font-bold mb-2">Подфазы</h3>
      <div class="flex flex-col gap-3">
        ${phase.subphases.map(sp=>`<div class="glass card p-4"><div class="font-bold text-sm">${sp.title}</div><div class="text-xs opacity-60">${sp.goal}</div></div>`).join('')}
      </div>
    </div>
  `;
  document.getElementById('tab-generic').classList.remove('hidden');
}

function renderOverview(){
  const el=document.getElementById('overview-phases');
  if(!el) return;
  el.innerHTML="";
  phases.forEach(p=>{
    const div=document.createElement('div');
    div.className="glass card p-4 flex gap-3";
    div.innerHTML=`<div class="w-10 h-10 rounded-xl grid place-items-center text-lg" style="background:${p.color}20; border:1px solid ${p.color}40">${p.icon}</div>
      <div class="flex-1"><div class="font-bold text-sm">${p.title}</div><div class="text-xs opacity-60">${p.goal}</div><div class="mt-2 flex flex-wrap gap-1">${p.agents.map(a=>`<span class="text-[10px] px-2 py-0.5 rounded-full bg-[#1A2130] mono">${a.name}</span>`).join('')}</div></div>
      <div class="text-right"><div class="mono text-[11px] opacity-50">${p.agents.length} agents</div><div class="text-xs mt-1 opacity-70">${p.subphases.length} подфаз</div></div>
    `;
    el.appendChild(div);
  });
}

function renderJourney(){
  const el=document.getElementById('journey-content');
  if(!el) return;
  let html = `<p>Полный путь эксперта от нуля до автопродаж, улучшенный фабрикой агентов. Каждый этап решает конкретную проблему и передает артефакты дальше.</p>`;
  phases.forEach((p,i)=>{
    html+=`<h2>${i+1}. ${p.icon} ${p.title} — ${p.subtitle}</h2><p><b>Цель:</b> ${p.goal}<br><b>Результат:</b> ${p.outcome}</p>`;
    html+=`<h3>Подфазы и задачи:</h3><ul>`;
    p.subphases.forEach(sp=>{
      html+=`<li><b>${sp.title}</b>: ${sp.goal}<ul><li>Проблемы ДО: ${sp.problems_before.join('; ')}</li><li>Улучшения: ${sp.improvements.join('; ')}</li><li>Задачи: ${sp.tasks.map(t=>t.title).join(', ')}</li></ul></li>`;
    });
    html+=`</ul><h3>Агенты этой фазы:</h3><table><tr><th>Агент</th><th>Входы</th><th>Выходы</th><th>Задачи</th></tr>`;
    p.agents.forEach(a=>{
      html+=`<tr><td>${a.icon} ${a.name} (${a.id})</td><td>${a.inputs_required.join(', ')}</td><td>${a.outputs_produced.join(', ')}</td><td>${a.tasks.join(', ')}</td></tr>`;
    });
    html+=`</table>`;
  });
  html+=`<h2>Что улучшено vs классический путь</h2><ul>
    <li><b>Было:</b> 3 месяца распаковки и стратегии в Notion. <b>Стало:</b> 1 день, 7 агентов Phase1, единый манифест md+json.</li>
    <li><b>Было:</b> Контент рандомно, выгорание. <b>Стало:</b> Content Factory 30 сценариев + HeyGen фото→видео, план 30 дней.</li>
    <li><b>Было:</b> Лиды теряются в директ. <b>Стало:</b> DM триггеры по слову, квиз-магнит, CRM n8n.</li>
    <li><b>Было:</b> Продажи вручную. <b>Стало:</b> Автопрогрев 7 дней, скрипты, автовеб, KPI дашборд.</li>
    <li><b>Было:</b> Разные сервисы, хаос. <b>Стало:</b> Одно приложение, все агенты с единым интерфейсом, человек утверждает каждый этап.</li>
  </ul>`;
  el.innerHTML=html;
}

function renderFactoryGraph(){
  const el=document.getElementById('factory-graph');
  if(!el || !currentProject) return;
  let html=`<div class="mono text-[11px] opacity-60 mb-4">Граф строится по dependencies из манифестов. Стрелка = передача артефактов (md, json, image, HeyGen video).</div><div class="flex flex-col gap-2">`;
  phases.forEach(p=>{
    html+=`<div class="font-bold text-sm mt-4" style="color:${p.color}">${p.icon} ${p.title}</div><div class="flex flex-wrap gap-2">`;
    p.agents.forEach(a=>{
      const s=currentProject.agent_states[a.id];
      const st=s? s.status: 'idle';
      html+=`<div class="px-3 py-2 rounded-xl bg-[#1A2130] border ${st==='approved'?'border-[#4ADE80]/50': st==='needs_review'?'border-[#FBBF24]/50':'border-white/10'}">
        <div class="text-xs font-bold">${a.icon} ${a.id}</div>
        <div class="text-[10px] mono opacity-60">${st}</div>
        ${a.dependencies.length? `<div class="text-[9px] opacity-40 mt-1">← ${a.dependencies.join(', ')}</div>`:''}
      </div>`;
    });
    html+=`</div>`;
  });
  html+=`</div>`;
  el.innerHTML=html;
}

async function loadArtifacts(){
  if(!currentProject) return;
  const data = await fetchJSON(`/api/projects/${currentProject.id}/artifacts`);
  const list=document.getElementById('artifacts-list');
  if(!list) return;
  list.innerHTML="";
  data.artifacts.sort((a,b)=>a.filename.localeCompare(b.filename)).forEach(art=>{
    const div=document.createElement('div');
    div.className="glass card p-4";
    const typeIcon = art.type==='image'?'🖼️': art.type==='video'?'🎥': art.type==='json'?'📋':'📄';
    div.innerHTML=`
      <div class="flex items-start justify-between"><div class="flex items-center gap-2"><span>${typeIcon}</span><div class="font-bold text-[13px]">${art.filename}</div></div><span class="text-[10px] mono opacity-50">${art.type}</span></div>
      <div class="text-[11px] opacity-60 mt-1">${art.description} • by ${art.created_by} • ${Math.round(art.size/1024)}KB</div>
      <div class="mt-3 flex gap-2"><button onclick="previewArtifact('${art.filename}')" class="px-3 py-1.5 rounded-lg bg-white text-black text-xs font-bold">Открыть</button>
      <a href="/api/projects/${currentProject.id}/artifacts/${art.filename}" target="_blank" class="px-3 py-1.5 rounded-lg bg-[#1A2130] text-xs">Скачать</a></div>
    `;
    list.appendChild(div);
  });
}

// Actions
async function openNewProjectModal(){
  document.getElementById('modal-new-project').classList.remove('hidden');
  document.getElementById('modal-new-project').classList.add('grid');
}
function closeNewProjectModal(){
  document.getElementById('modal-new-project').classList.add('hidden');
  document.getElementById('modal-new-project').classList.remove('grid');
}
async function createProject(){
  const name=document.getElementById('new-proj-name').value.trim();
  const niche=document.getElementById('new-proj-niche').value.trim();
  const expert=document.getElementById('new-proj-expert').value.trim();
  if(!name){alert('Название обязательно'); return;}
  const payload={name, input:{niche, expert_name:expert, expert_current:"", big_goal:"", target_revenue:"", socials:{}, superpowers:"", stories:"", proof_existing:"", competitors:"", tone_of_voice:""}};
  const proj=await fetchJSON('/api/projects',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  closeNewProjectModal();
  await loadProjects();
  selectProject(proj.id);
  switchTab('phase_1');
}

async function savePhase1Input(){
  if(!currentProject){alert('Сначала создай проект'); return;}
  const input={
    niche: document.getElementById('inp-niche').value,
    expert_name: document.getElementById('inp-expert_name').value,
    expert_current: document.getElementById('inp-expert_current').value,
    superpowers: document.getElementById('inp-superpowers').value,
    stories: document.getElementById('inp-stories').value,
    proof_existing: document.getElementById('inp-proof_existing').value,
    competitors: document.getElementById('inp-competitors').value,
    target_revenue: document.getElementById('inp-target_revenue').value,
    big_goal: "",
    socials: {},
    tone_of_voice: "",
  };
  const res=await fetchJSON(`/api/projects/${currentProject.id}/input`,{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(input)});
  currentProject=res;
  alert('Сохранено! Агенты фазы 1 разблокированы если есть ниша.');
  updateFactoryProgress();
  renderCurrentPhase();
}

async function runAgent(agentId){
  if(!currentProject) return;
  const btn=event?.target;
  if(btn) btn.textContent='⏳ Running...';
  try{
    const res=await fetchJSON(`/api/projects/${currentProject.id}/agents/${agentId}/run`,{method:'POST'});
    currentProject=res.project;
    renderCurrentPhase();
    updateFactoryProgress();
    loadArtifacts();
    if(res.ok) {
      // auto preview if needs_review
      const st=currentProject.agent_states[agentId];
      if(st && st.outputs.length>0){
        previewArtifact(st.outputs[0]);
      }
    }
  }catch(e){
    alert('Ошибка: '+e.message);
  }
}

async function approveAgent(agentId){
  if(!currentProject) return;
  const notes=prompt('Заметки к Approve (опц):','');
  const res=await fetchJSON(`/api/projects/${currentProject.id}/agents/${agentId}/approve`,{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({notes})});
  currentProject=res.project;
  renderCurrentPhase();
  updateFactoryProgress();
  renderFactoryGraph();
}

async function rejectAgent(agentId){
  if(!currentProject) return;
  const notes=prompt('Что доработать?','');
  const res=await fetchJSON(`/api/projects/${currentProject.id}/agents/${agentId}/reject`,{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({notes})});
  currentProject=res.project;
  renderCurrentPhase();
}

async function previewArtifact(filename){
  if(!currentProject) return;
  try{
    const res=await fetch(`/api/projects/${currentProject.id}/artifacts/${filename}`);
    if(!res.ok){ alert('Файл не найден'); return; }
    const ct=res.headers.get('content-type')||'';
    let contentHtml="";
    if(ct.includes('image')){
      contentHtml=`<img src="/api/projects/${currentProject.id}/artifacts/${filename}" class="max-w-full rounded-xl" />`;
    }else{
      const json=await res.json().catch(()=>null);
      if(json && json.content){
        contentHtml=`<div class="whitespace-pre-wrap mono text-[13px] leading-6">${escapeHtml(json.content)}</div>`;
        // try render as md-ish
        contentHtml = `<div class="md-content">${markdownToHtml(json.content)}</div>`;
      }else if(json){
        contentHtml=`<pre class="mono text-xs whitespace-pre-wrap bg-[#0F1420] p-4 rounded-xl">${escapeHtml(JSON.stringify(json,null,2))}</pre>`;
      }else{
        const txt=await res.text();
        contentHtml=`<div class="whitespace-pre-wrap">${escapeHtml(txt.slice(0,20000))}</div>`;
      }
    }
    document.getElementById('artifact-modal-title').textContent=filename;
    document.getElementById('artifact-modal-content').innerHTML=contentHtml;
    document.getElementById('modal-artifact').classList.remove('hidden');
    document.getElementById('modal-artifact').classList.add('grid');
  }catch(e){alert(e.message)}
}

async function previewArtifactInline(filename, targetId){
  if(!currentProject) return;
  try{
    const res=await fetch(`/api/projects/${currentProject.id}/artifacts/${filename}`);
    const data=await res.json();
    const el=document.getElementById(targetId);
    if(el && data.content){
      el.innerHTML=`<div class="md-content">${markdownToHtml(data.content.slice(0,6000))}</div>`;
    }
  }catch(e){}
}

function previewAgentOutputs(agentId){
  if(!currentProject) return;
  const state=currentProject.agent_states[agentId];
  if(!state || !state.outputs.length){ alert('Нет выходов еще, запусти агента'); return; }
  previewArtifact(state.outputs[0]);
}

function closeArtifactModal(){
  document.getElementById('modal-artifact').classList.add('hidden');
  document.getElementById('modal-artifact').classList.remove('grid');
}

async function uploadFile(file){
  if(!file || !currentProject){ alert('Выбери проект'); return; }
  const fd=new FormData();
  fd.append('file', file);
  const res=await fetch(`/api/projects/${currentProject.id}/upload`,{method:'POST', body:fd});
  const data=await res.json();
  alert('Загружено: '+data.filename);
  loadArtifacts();
}

// helpers
function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function markdownToHtml(md){
  // very lightweight
  return escapeHtml(md)
    .replace(/^### (.*)$/gm,'<h3>$1</h3>')
    .replace(/^## (.*)$/gm,'<h2>$1</h2>')
    .replace(/^# (.*)$/gm,'<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/g,'<b>$1</b>')
    .replace(/\*(.*?)\*/g,'<i>$1</i>')
    .replace(/\n\n/g,'</p><p>')
    .replace(/\n/g,'<br>');
}

init();
