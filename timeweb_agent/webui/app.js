'use strict';

/* ===================== утилиты ===================== */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

async function api(path, opts = {}) {
  const init = { headers: { 'Content-Type': 'application/json' }, ...opts };
  if (init.body !== undefined && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  const res = await fetch(path, init);
  let j;
  try { j = await res.json(); } catch { throw new Error('HTTP ' + res.status); }
  if (!j.ok) throw new Error(j.error || ('HTTP ' + res.status));
  return j.data;
}

function toast(msg, kind = 'ok') {
  const box = $('#toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => { t.classList.add('hide'); setTimeout(() => t.remove(), 300); }, 5000);
}

function busy(btn, on) {
  if (!btn) return;
  if (on) btn.dataset.orig = btn.dataset.orig || btn.innerHTML;
  btn.disabled = on;
  btn.classList.toggle('busy', on);
  btn.innerHTML = on ? '⏳ Выполняется…' : (btn.dataset.orig || btn.innerHTML);
}

async function withBusy(btn, fn, okMsg) {
  busy(btn, true);
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, 'err'); return null; }
  finally { busy(btn, false); }
}

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); }
  catch {
    const ta = document.createElement('textarea');
    ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch {}
    ta.remove();
  }
  toast('Скопировано в буфер обмена');
}

function statusBadge(s) {
  const st = String(s || '').toLowerCase();
  let cls = 'gray';
  const label = s || '?';
  if (['on', 'active', 'started', 'running', 'ready'].includes(st)) cls = 'green';
  else if (['installing', 'starting', 'creating', 'configuring', 'booting', 'rebooting', 'stopping', 'restarting', 'queued', 'building', 'pending'].includes(st)) cls = 'amber';
  else if (['error', 'failed', 'blocked', 'locked', 'off', 'stopped'].includes(st)) cls = 'red';
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

/* ===================== навигация ===================== */
const loaders = {
  overview: loadOverview, servers: loadServers, dbs: loadDbs,
  domains: loadDomains, apps: loadApps, deploy: loadDeploy, ssh: loadSsh, settings: loadSettings,
};

function showView(name) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  const l = loaders[name];
  if (l) l().catch(e => toast(e.message, 'err'));
}

/* ===================== здоровье ===================== */
async function initHealth() {
  try {
    const h = await api('/api/health');
    const pill = $('#api-status'), txt = $('#api-status-text');
    pill.className = 'status-pill ' + (h.token_set ? 'ok' : 'bad');
    txt.textContent = h.token_set ? 'API подключено' : 'Нет токена';
    if (h.demo) $('#demo-banner').classList.remove('hidden');
  } catch {
    $('#api-status').className = 'status-pill bad';
    $('#api-status-text').textContent = 'сервер не отвечает';
  }
}

/* ===================== обзор ===================== */
async function loadOverview() {
  const d = await api('/api/doctor');
  const cards = [
    { icon: '🖥️', label: 'Серверы', value: d.servers },
    { icon: '🗄️', label: 'Базы данных', value: d.databases },
    { icon: '🌐', label: 'Домены', value: d.domains },
    { icon: '🚀', label: 'Приложения', value: d.apps },
    { icon: '🔑', label: 'SSH-ключи', value: d.ssh_keys },
    { icon: '📁', label: 'Проекты', value: d.projects },
  ];
  $('#overview-cards').innerHTML = cards.map(c => `
    <div class="stat-card">
      <div class="stat-icon">${c.icon}</div>
      <div class="stat-value">${c.value}</div>
      <div class="stat-label">${c.label}</div>
    </div>`).join('');
  const acc = d.account || {};
  const blocked = acc.is_blocked || (acc.status && acc.status.is_blocked);
  if (blocked) toast('⚠️ Аккаунт заблокирован! Проверьте оплату в панели Timeweb.', 'err');
}

async function runDoctor() {
  await withBusy($('#btn-doctor'), async () => {
    const d = await api('/api/doctor');
    const out = $('#doctor-out');
    out.hidden = false;
    out.textContent = JSON.stringify(d, null, 2);
  }, 'Подключение в порядке ✓');
}

/* ===================== серверы ===================== */
async function loadServers() {
  const servers = await api('/api/servers');
  const tb = $('#servers-table');
  if (!servers.length) { tb.innerHTML = '<tr><td class="muted">Серверов пока нет — создайте первый выше.</td></tr>'; return; }
  tb.innerHTML = `<thead><tr><th>Имя</th><th>Статус</th><th>IP</th><th>Конфигурация</th><th>Действия</th></tr></thead><tbody>` +
    servers.map(s => {
      const conf = [s.cpu ? s.cpu + ' vCPU' : null, s.ram ? Math.round(s.ram / 1024) + ' ГБ RAM' : null, s.disk ? s.disk + ' ГБ' : null]
        .filter(Boolean).join(' · ') || ('тариф #' + (s.preset_id ?? '?'));
      const on = String(s.status || '').toLowerCase() === 'on';
      const off = ['off', 'stopped'].includes(String(s.status || '').toLowerCase());
      return `<tr>
        <td><b>${esc(s.name)}</b><div class="muted small">id ${esc(s.id)} · ${esc(s.location || '')}</div></td>
        <td>${statusBadge(s.status)}</td>
        <td class="mono">${esc(s.ip || '—')}</td>
        <td>${esc(conf)}</td>
        <td class="actions">
          ${on ? `<button class="btn sm" data-srv="${s.id}" data-act="reboot">Перезагрузить</button>
                  <button class="btn sm" data-srv="${s.id}" data-act="shutdown">Выключить</button>` : ''}
          ${off ? `<button class="btn sm" data-srv="${s.id}" data-act="start">Запустить</button>` : ''}
          <button class="btn sm" data-srv="${s.id}" data-act="reset-password">Пароль root</button>
          <button class="btn sm danger" data-srv="${s.id}" data-act="delete">Удалить</button>
        </td></tr>`;
    }).join('') + '</tbody>';
  $$('#servers-table [data-act]').forEach(b => b.addEventListener('click', onServerAction));
}

async function onServerAction(e) {
  const b = e.currentTarget;
  const id = b.dataset.srv, act = b.dataset.act;
  const names = {
    reboot: 'перезагрузить', shutdown: 'выключить', start: 'запустить',
    'reset-password': 'сбросить root-пароль', delete: 'УДАЛИТЬ БЕЗВОЗВРАТНО',
  };
  if (!confirm(`Сервер #${id}: ${names[act]}?`)) return;
  if (act === 'delete') {
    await withBusy(b, () => api('/api/servers/' + id, { method: 'DELETE' }), 'Сервер удалён');
  } else {
    const r = await withBusy(b, () => api(`/api/servers/${id}/action`, { method: 'POST', body: { action: act } }), 'Готово');
    if (r && act === 'reset-password' && r.root_password) {
      toast('Новый root-пароль: ' + r.root_password);
    }
  }
  loadServers().catch(() => {});
}

function bindCreateServer() {
  $('#server-create-form').addEventListener('submit', async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      name: f.get('name'), os: f.get('os'), preset: f.get('preset'), ssh_key: f.get('ssh_key'),
      ddos: f.get('ddos') === 'on', wait: f.get('wait') === 'on', comment: f.get('comment') || null,
    };
    if (!confirm(`Создать сервер «${body.name}»? Это платная операция.`)) return;
    const srv = await withBusy($('#btn-server-create'), () => api('/api/servers/create', { method: 'POST', body }), 'Сервер создан');
    if (srv) { toast('IP: ' + (srv.ip || 'скоро появится')); loadServers().catch(() => {}); }
  });
}

/* ===================== базы данных ===================== */
async function loadDbs() {
  const dbs = await api('/api/dbs');
  const tb = $('#dbs-table');
  if (!dbs.length) { tb.innerHTML = '<tr><td class="muted">Кластеров нет — создайте первый выше.</td></tr>'; return; }
  tb.innerHTML = `<thead><tr><th>Имя</th><th>Тип</th><th>Статус</th><th>Подключение</th><th>Действия</th></tr></thead><tbody>` +
    dbs.map(d => {
      const c = d.connection || {};
      const host = c.host ? `${c.host}:${c.port || ''}` : (d.host || '—');
      return `<tr>
        <td><b>${esc(d.name)}</b><div class="muted small">id ${esc(d.id)}</div></td>
        <td>${esc((d.type || d.hash_type || '—'))}</td>
        <td>${statusBadge(d.status)}</td>
        <td class="mono">${esc(host)}</td>
        <td class="actions"><button class="btn sm danger" data-db="${d.id}">Удалить</button></td>
      </tr>`;
    }).join('') + '</tbody>';
  $$('#dbs-table [data-db]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Удалить кластер БД #' + b.dataset.db + ' БЕЗВОЗВРАТНО?')) return;
    await withBusy(b, () => api('/api/dbs/' + b.dataset.db, { method: 'DELETE' }), 'Кластер удалён');
    loadDbs().catch(() => {});
  }));
}

function bindCreateDb() {
  $('#db-create-form').addEventListener('submit', async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      name: f.get('name'), type: f.get('type'), admin_login: f.get('admin_login'),
      admin_password: f.get('admin_password') || null, preset: f.get('preset'),
      instance_name: f.get('instance_name') || null, wait: f.get('wait') === 'on',
    };
    if (!confirm(`Создать кластер БД «${body.name}» (${body.type})? Это платная операция.`)) return;
    const db = await withBusy($('#db-create-form button[type=submit]'), () => api('/api/dbs/create', { method: 'POST', body }), 'Кластер создан');
    if (db && db.admin_password) toast('Пароль админа: ' + db.admin_password);
    loadDbs().catch(() => {});
  });
}

/* ===================== домены и DNS ===================== */
let CURRENT_FQDN = null;

async function loadDomains() {
  const domains = await api('/api/domains');
  const chips = $('#domain-chips');
  chips.innerHTML = domains.length
    ? domains.map(d => `<button class="chip domain-chip" data-fqdn="${esc(d.fqdn)}">🌐 ${esc(d.fqdn)}</button>`).join('')
    : '<p class="muted">Доменов на аккаунте нет.</p>';
  $$('.domain-chip').forEach(c => c.addEventListener('click', () => selectDomain(c.dataset.fqdn)));
  if (CURRENT_FQDN && domains.some(d => d.fqdn === CURRENT_FQDN)) selectDomain(CURRENT_FQDN);
  else { $('#dns-table').innerHTML = ''; $('#dns-domain-name').textContent = '—'; }
}

async function selectDomain(fqdn) {
  CURRENT_FQDN = fqdn;
  $$('.domain-chip').forEach(c => c.classList.toggle('active', c.dataset.fqdn === fqdn));
  $('#dns-domain-name').textContent = fqdn;
  const recs = await api('/api/dns/' + encodeURIComponent(fqdn));
  const tb = $('#dns-table');
  tb.innerHTML = recs.length
    ? `<thead><tr><th>Тип</th><th>Значение</th><th>TTL</th><th></th></tr></thead><tbody>` +
      recs.map(r => `<tr>
        <td><span class="badge blue">${esc(r.type)}</span></td>
        <td class="mono">${esc(r.value)}</td>
        <td>${esc(r.ttl ?? '—')}</td>
        <td class="actions"><button class="btn sm danger" data-rid="${r.id}">Удалить</button></td>
      </tr>`).join('') + '</tbody>'
    : '<tr><td class="muted">Записей нет.</td></tr>';
  $$('#dns-table [data-rid]').forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Удалить DNS-запись #' + b.dataset.rid + '?')) return;
    await withBusy(b, () => api(`/api/dns/${encodeURIComponent(fqdn)}/${b.dataset.rid}`, { method: 'DELETE' }), 'Запись удалена');
    selectDomain(fqdn).catch(() => {});
  }));
}

function bindDnsAdd() {
  $('#dns-add-form').addEventListener('submit', async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const fqdn = f.get('fqdn');
    const body = { type: f.get('type'), value: f.get('value'), ttl: parseInt(f.get('ttl') || '3600', 10) };
    await withBusy($('#dns-add-form button[type=submit]'), () => api('/api/dns/' + encodeURIComponent(fqdn), { method: 'POST', body }), 'Запись добавлена');
    e.target.reset();
    if (CURRENT_FQDN === fqdn) selectDomain(fqdn).catch(() => {});
  });
}

/* ===================== приложения ===================== */
async function loadApps() {
  const apps = await api('/api/apps');
  const tb = $('#apps-table');
  if (!apps.length) { tb.innerHTML = '<tr><td class="muted">Приложений нет.</td></tr>'; return; }
  tb.innerHTML = `<thead><tr><th>Имя</th><th>Тип</th><th>Статус</th><th>Фреймворк</th><th>Домены</th></tr></thead><tbody>` +
    apps.map(a => `<tr>
      <td><b>${esc(a.name)}</b><div class="muted small">id ${esc(a.id)}</div></td>
      <td>${esc(a.type || '—')}</td>
      <td>${statusBadge(a.status)}</td>
      <td>${esc((a.framework && a.framework.language) || a.language || '—')}</td>
      <td>${esc((a.domains || []).join(', ') || '—')}</td>
    </tr>`).join('') + '</tbody>';
}

/* ===================== деплой ===================== */
async function loadDeploy() {
  const servers = await api('/api/servers');
  const sel = $('#deploy-server-select');
  const cur = sel.value;
  sel.innerHTML = '<option value="">— выбрать сервер из панели —</option>' +
    servers.map(s => `<option value="${esc(s.name)}">${esc(s.name)} (${esc(s.ip || '?')})</option>`).join('');
  if (cur) sel.value = cur;
}

function deployParams(extra = {}) {
  const p = { ...extra };
  const sel = $('#deploy-server-select').value;
  const host = $('#deploy-host').value.trim();
  const user = $('#deploy-user').value.trim();
  const port = $('#deploy-port').value.trim();
  const pass = $('#deploy-password').value;
  if (sel) p.server = sel;
  if (host) p.host = host;
  if (user) p.ssh_user = user;
  if (port) p.ssh_port = parseInt(port, 10);
  if (pass) p.ssh_password = pass;
  return p;
}

async function runDeploy(kind, extra, btn) {
  const out = $('#deploy-out');
  out.hidden = true;
  await withBusy(btn, async () => {
    const r = await api('/api/deploy/' + kind, { method: 'POST', body: deployParams(extra) });
    out.hidden = false;
    out.textContent = JSON.stringify(r, null, 2);
  }, 'Готово');
}

function bindDeployForms() {
  $('#btn-provision').addEventListener('click', () => runDeploy('provision', {}, $('#btn-provision')));
  $('#deploy-website-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = new FormData(e.target);
    runDeploy('website', { path: f.get('path'), domain: f.get('domain'), ssl: f.get('ssl') === 'on', ssl_email: f.get('ssl_email') || null }, $('#deploy-website-form button[type=submit]'));
  });
  $('#deploy-docker-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = new FormData(e.target);
    runDeploy('docker', { path: f.get('path'), domain: f.get('domain'), port: parseInt(f.get('port') || '8000', 10), ssl: f.get('ssl') === 'on' }, $('#deploy-docker-form button[type=submit]'));
  });
  $('#deploy-git-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = new FormData(e.target);
    runDeploy('git', { repo: f.get('repo'), branch: f.get('branch'), domain: f.get('domain') || null, port: parseInt(f.get('port') || '8000', 10) }, $('#deploy-git-form button[type=submit]'));
  });
  $('#deploy-mysql-form').addEventListener('submit', e => {
    e.preventDefault();
    const f = new FormData(e.target);
    runDeploy('mysql', { name: f.get('name'), user: f.get('user'), password: f.get('password') || null, port: parseInt(f.get('port') || '3306', 10) }, $('#deploy-mysql-form button[type=submit]'));
  });
}

/* ===================== SSH и диагностика ===================== */
let LAST_DIAG = null;

function resolveSshTarget(inp) {
  const body = {};
  if (inp) body.targetGuess = inp;
  return body;
}

async function targetPayload(inp) {
  const body = {};
  if (!inp) return body;
  try {
    const servers = await api('/api/servers');
    const byName = servers.find(s => s.name === inp);
    if (byName) body.server = byName.name; else body.host = inp;
  } catch { body.host = inp; }
  return body;
}

async function runDiag() {
  const inp = $('#diag-server').value.trim();
  const payload = await targetPayload(inp);
  const r = await withBusy($('#btn-diag'), () => api('/api/diag', { method: 'POST', body: payload }), 'Диагностика завершена');
  if (!r) return;
  LAST_DIAG = r;
  renderDiag(r);
}

function renderDiag(r) {
  const results = r.results || [];
  $('#diag-results').innerHTML = results.map(res => `
    <div class="diag-block">
      <div class="diag-head">
        <code>$ ${esc(res.command)}</code>
        <span class="muted small">${esc(res.description)}${res.demo ? ' · <b>ДЕМО</b>' : ''}${res.exit_code ? ' · exit ' + res.exit_code : ''}</span>
        <button class="btn sm ghost copy-btn" data-cmd="${esc(res.command)}">📋 Копировать</button>
      </div>
      ${res.error ? `<pre class="terminal err">${esc(res.error)}</pre>` : ''}
      <pre class="terminal">${esc(res.output || '(пусто)')}</pre>
    </div>`).join('');
  $$('#diag-results .copy-btn').forEach(b => b.addEventListener('click', () => {
    const res = results.find(x => x.command === b.dataset.cmd);
    if (res) copyText('$ ' + res.command + '\n' + res.output + (res.error ? '\n' + res.error : ''));
  }));
  $('#btn-diag-copy').disabled = !results.length;
}

function buildReport() {
  if (!LAST_DIAG) return '';
  const r = LAST_DIAG;
  const header = `Диагностика сервера${r.demo ? ' (ДЕМО)' : ''}: ${r.target || ''}\nДата: ${new Date().toLocaleString('ru-RU')}\n`;
  return header + r.results.map(res => `\n$ ${res.command}\n${res.output}${res.error ? '\n' + res.error : ''}`).join('\n');
}

async function sshExec() {
  const inp = $('#ssh-server').value.trim();
  const cmd = $('#ssh-command').value.trim();
  if (!cmd) { toast('Введите команду', 'err'); return; }
  const payload = await targetPayload(inp);
  payload.command = cmd;
  const r = await withBusy($('#btn-ssh-exec'), () => api('/api/ssh/exec', { method: 'POST', body: payload }), 'Готово');
  if (!r) return;
  $('#ssh-out').textContent = r.stdout + (r.stderr ? '\n' + r.stderr : '') + (r.exit_code ? `\n[exit ${r.exit_code}]` : '');
}

async function loadSsh() { /* по запросу */ }

/* ===================== настройки ===================== */
async function loadSettings() {
  const e = await api('/api/env');
  $('#env-files').innerHTML = e.files.map(f =>
    `<li>${esc(f.path)} ${f.exists ? '✅' : '— не создан'}</li>`).join('');
  $('#env-table').innerHTML = `<thead><tr><th>Переменная</th><th>Задана</th><th>Значение</th><th>Зачем</th></tr></thead><tbody>` +
    Object.entries(e.values).map(([k, v]) => `<tr>
      <td class="mono">${esc(k)}</td>
      <td>${v.set ? '✅' : '❌'}</td>
      <td class="mono">${esc(v.value ?? '—')}</td>
      <td class="muted small">${esc(v.hint || '')}</td>
    </tr>`).join('') + '</tbody>';
}

/* ===================== старт ===================== */
function init() {
  initHealth();
  bindCreateServer();
  bindCreateDb();
  bindDnsAdd();
  bindDeployForms();

  $('#btn-overview-refresh').addEventListener('click', () => loadOverview().catch(e => toast(e.message, 'err')));
  $('#btn-servers-refresh').addEventListener('click', () => loadServers().catch(e => toast(e.message, 'err')));
  $('#btn-dbs-refresh').addEventListener('click', () => loadDbs().catch(e => toast(e.message, 'err')));
  $('#btn-domains-refresh').addEventListener('click', () => loadDomains().catch(e => toast(e.message, 'err')));
  $('#btn-apps-refresh').addEventListener('click', () => loadApps().catch(e => toast(e.message, 'err')));
  $('#btn-doctor').addEventListener('click', runDoctor);
  $('#btn-diag').addEventListener('click', runDiag);
  $('#btn-diag-copy').addEventListener('click', () => copyText(buildReport()));
  $('#btn-ssh-exec').addEventListener('click', sshExec);
  $('#ssh-command').addEventListener('keydown', e => { if (e.key === 'Enter') sshExec(); });

  $$('.quick .chip[data-cmd]').forEach(c => c.addEventListener('click', () => {
    $('#ssh-command').value = c.dataset.cmd;
    sshExec();
  }));

  $$('.nav-item').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
  showView('overview');
}

document.addEventListener('DOMContentLoaded', init);
