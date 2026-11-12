/* PanCheck 面板脚本（原来内联在 index.html 里）：不用框架、不用构建，普通 <script> 直接载入 */
/* PanCheck 前端：五页（总览 / 扫描 / 清单 / 执行 / 设置），主线：设定 → 扫描 → 决定 → 执行+ 首次设置向导。
   判定一律渲染后端 bucket / stage / cls 的白话名（/api/labels），数字一律读后端结果，前端不写死任何子类语义。 */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const u = p => new URL(p, location.origin + location.pathname).href;   // 地址栏带 user:pw@ 时 fetch 不认相对路径
const n = x => (+x || 0).toLocaleString('zh-CN');
const store = {get: k => { try { return localStorage.getItem(k) } catch (e) { return null } }, set: (k, v) => { try { localStorage.setItem(k, v) } catch (e) {} }};
function fmtGB(g) { g = +g || 0; return g >= 1024 ? (g / 1024).toFixed(g >= 102400 ? 0 : 1) + ' TB' : g.toFixed(g >= 100 ? 0 : 1) + ' GB'; }
function fmtTime(t) { return t ? new Date(t * 1000).toLocaleString('zh-CN', {hour12: false}) : '—'; }
async function api(path, opt = {}) {
  const r = await fetch(u(path), opt);
  if (!r.ok) { let m = r.status + ''; try { m = (await r.json()).detail || m } catch (e) {} throw new Error(m); }
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}
const J = body => ({method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const P = body => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
let toastT;
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 3600); }

/* ---------- 图标（Lucide 风格 SVG） ---------- */
const ICONS = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  inventory: '<path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="11.5" cy="12.5" r="3"/><path d="m13.8 14.8 2.2 2.2"/>',
  list: '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
  play: '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4z"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  chev: '<path d="m9 18 6-6-6-6"/>', down: '<path d="m6 9 6 6 6-6"/>',
  db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  gap: '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="m14 10 7-7"/><path d="m3 21 7-7"/>',
  check: '<path d="M20 6 9 17l-5-5"/>', minus: '<path d="M5 12h14"/>', folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
};
const ic = (name, cls = '') => `<svg class="ic ${cls}" viewBox="0 0 24 24">${ICONS[name] || ''}</svg>`;
function hydrate(root = document) { root.querySelectorAll('i[data-ic]').forEach(i => { i.outerHTML = ic(i.dataset.ic, i.className); }); }
const PICK = `<svg class="check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg><svg class="minus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round"><path d="M5 12h14"/></svg>`;

/* ---------- 白话名（来自 panel/labels.py） ---------- */
let LB = {buckets: {}, stages: {}, classes: {}};
const BUCKET_ORDER = ['可切', '待定', '版本型', '不动', '孤本', '缺口', '提醒', '剧集分流'];
const TONE = {'可切': 'green', '待定': 'amber', '版本型': 'sky', '不动': 'violet', '孤本': 'zinc', '缺口': 'sky', '提醒': 'zinc', '剧集分流': 'zinc'};
const bn = b => (LB.buckets[b] || {}).name || b;
const sn = s => (LB.stages[s] || {}).name || s;
const cn = (s, c) => LB.classes[s + '|' + c] || c;
const shortLb = (s, c) => (LB.short || {})[s + '|' + c] || cn(s, c);
const tierName = t => { if (!t) return '未知'; const base = {U: '4K', H: '1080p', S: '720p 及以下', '?': '未知'}[t.replace('*', '')] || t; return t.endsWith('*') ? base + '*' : base; };
const badge = b => `<span class="badge b-${TONE[b] || 'zinc'}"><i></i>${esc(bn(b))}</span>`;
const FLAG_NAME = {infer: '原盘档为体积推断', roujiang: 'BDMV 肉酱盘', whole: '整夹搬', file: '只搬单文件'};
const ZN = {yuanpan: '原盘区', heji: '合集区', remux: 'REMUX 区', pack: '整夹合集区'};
const ACT_NAME = {quarantine: '查重区', mainlib: '主库', unique: '唯一副本目录'};       // mainlib 在勾选模型下是「待入库区」，loadCfg 里改

/* ---------- 全局状态 ---------- */
let CFG = null, AUTH = false, RES = null, EXS = null, APPR = {items: {}, overlap: []}, BATCHES = [];
let execOn = false;
function uiLock() { return store.get('pc.uilock') === '1'; }
function setExecOn() {
  execOn = !!(EXS && EXS.allowed) && !uiLock();
  document.body.classList.toggle('exec-on', execOn);
  document.body.classList.toggle('exec-closed', !(EXS && EXS.allowed));
  $$('.exec-nav').forEach(a => a.title = execOn ? '' : (EXS && EXS.allowed ? '这台浏览器开了界面只读锁定' : '执行未开启'));
  const m = $('#sideMode');
  m.classList.toggle('exec', execOn);
  m.querySelector('b').textContent = execOn ? '执行已开' : '只读默认态';
  m.querySelector('span').textContent = execOn ? '只搬你批准过的 · 只改名不删除 · 可回滚' : (EXS && EXS.allowed ? '这台浏览器开了界面只读锁定' : '只出清单 · 不删不移');
  $('#approveBar').hidden = !execOn;
}
async function loadCfg() {
  const r = await api('api/config');
  CFG = r.config; AUTH = r.auth_enabled;
  ACT_NAME.mainlib = (CFG.tree_model || CFG.staging_dir) ? '待入库区' : '主库';
  const am = $('#apprMName'); if (am) am.textContent = ACT_NAME.mainlib;
  $('#sidePw').hidden = !!AUTH;
  $('#sideSrc').textContent = '数据来源：' + ({cache: 'CD2 目录缓存', scan: '遍历挂载目录', csv: 'CSV 文件'}[CFG.data_source] || '');
}
/* 版本（反馈 24）：页面头里写着这页是哪一版；服务器已经换版、这页还是旧的 → 自己刷新一次（只刷一次，防循环） */
const PAGE_VER = ((document.querySelector('meta[name="pancheck-version"]') || {}).content || '').split(' ');
function verText() { return PAGE_VER[0] ? `版本 ${PAGE_VER[0]} · 前端 ${PAGE_VER[1] || '—'}` : ''; }
async function checkVersion() {
  const el = $('#sideVer'); if (el) el.textContent = verText();
  let v; try { v = await api('api/version'); } catch (e) { return; }
  if (PAGE_VER[1] && v.static && v.static !== PAGE_VER[1]) {
    if (store.get('pc.reloadedFor') !== v.static) { store.set('pc.reloadedFor', v.static); location.reload(); return; }
    toast('面板已换版，请强制刷新页面（Ctrl+F5）');
  }
}
async function loadExec() { try { EXS = await api('api/exec/status'); } catch (e) { EXS = null; } setExecOn(); }
/* 重跑后上轮批准带过来的报数（反馈 9 进阶） */
function carryNote() {
  const c = APPR && APPR.carry;
  if (!execOn || !c || !c.prev) return '';
  const d = c.dropped || [];
  return `<div class="alert ${d.length ? 'amber' : ''}">${ic(d.length ? 'alert' : 'check')}<div>上轮批准 <b>${n(c.prev)}</b> 条：带过来 <b>${n(c.carried)}</b> 条、已失效 <b>${n(d.length)}</b> 条${c.note ? '（' + esc(c.note) + '）' : ''}。${c.carried ? '带过来的照样要先预演复核。' : ''}
    ${d.length && !c.note ? `<details style="margin-top:6px"><summary style="cursor:pointer">看失效的 ${n(d.length)} 条</summary><ul class="refused-list" style="margin-top:6px">${d.slice(0, 50).map(x => `<li><span class="mono" title="${esc(x.path)}">${esc(baseName(x.path))}</span>：${esc(x.reason)}</li>`).join('')}${d.length > 50 ? `<li>…还有 ${n(d.length - 50)} 条</li>` : ''}</ul></details>` : ''}</div></div>`;
}
async function loadAppr() { try { APPR = await api('api/approvals'); } catch (e) { APPR = {items: {}, overlap: []}; } updateApprBar(); }
async function loadResult() { try { RES = await api('api/result'); } catch (e) { RES = null; } updateNavCounts(); }
function updateNavCounts() {
  const c = RES && RES.summary && RES.summary['可切'];
  const el = $('#navListCount'); el.hidden = !c; if (c) el.textContent = n(c.count);
  const k = Object.keys(APPR.items || {}).length, e = $('#navExecCount'); e.hidden = !k; e.textContent = n(k);
}
function banners(r) {
  if (!r) return '';
  let h = '';
  if (r.engine !== 2) h += `<div class="alert amber">${ic('alert')}<div><b>这份清单是旧版生成的（按「合集 vs 原盘 / 合集内 / 小文件」分开判）。</b>重新扫描一次，同一部片的副本会归成一组再判。</div></div>`;
  if (r.stale) h += `<div class="alert amber">${ic('alert')}<div><b>设置改过，这份清单已过期。</b>重新扫描后才能导出「可清理」和批准。</div></div>`;
  if (r.rejected) h += `<div class="alert red">${ic('alert')}<div><b>整批拒绝：</b>「可清理」里有 ${n((r.protect_violations || []).length)} 条落在保护区 / 榜单包里，不能导出、不能批准。<br><span class="mono" style="font-size:11.5px">${esc((r.protect_violations || []).slice(0, 3).join('  ·  '))}</span></div></div>`;
  return h;
}

/* ---------- 路由（hash：#/view?参数，刷新不丢） ---------- */
const VIEWS = ['overview', 'list', 'execute', 'settings', 'wizard'];
function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const i = h.indexOf('?');
  const v = (i < 0 ? h : h.slice(0, i)) || 'overview';
  return {view: VIEWS.includes(v) ? v : 'overview', params: new URLSearchParams(i < 0 ? '' : h.slice(i + 1))};
}
/* 主线：设定 → 扫描 → 决定 → 执行。标出现在在哪一步、下一步该去哪 */
function renderSteps() {
  const el = $('#steps'); if (!el) return;
  const nAppr = Object.keys((APPR && APPR.items) || {}).length;
  const done = {setup: !!(CFG && CFG.setup_done), scan: !!(RES && !RES.stale), decide: nAppr > 0, exec: false};
  const cur = {settings: 'setup', wizard: 'setup', overview: 'scan', list: 'decide', execute: 'exec'}[VIEW] || '';
  const order = ['setup', 'scan', 'decide', 'exec'];
  const next = order.find(k => !done[k] && (k !== 'exec' || execOn)) || '';
  const S = [['setup', '设定', CFG && !CFG.setup_done ? '#/wizard' : '#/settings'], ['scan', '扫描', '#/overview'],
             ['decide', '决定', '#/list'], ['exec', '执行', '#/execute']];
  el.innerHTML = S.map(([k, label, href], i) => `${i ? '<span class="sep">›</span>' : ''}<a href="${href}" class="${done[k] ? 'done' : ''} ${cur === k ? 'cur' : ''}" ${cur === k ? 'aria-current="step"' : ''}>`
    + `<span class="sn">${done[k] ? '✓' : i + 1}</span>${label}${next === k && cur !== k ? '<span class="nx">下一步</span>' : ''}</a>`).join('');
}
function go(view, params) { const qs = params ? params.toString() : ''; location.hash = '#/' + view + (qs ? '?' + qs : ''); }
let VIEW = '';
async function route() {
  let {view, params} = parseHash();
  if (view === 'inventory') view = 'overview';               // 扫描页并进了首页（老链接照样能用）
  if (view === 'settings' && CFG && !CFG.setup_done) view = 'wizard';
  if (view === 'execute' && !execOn) { /* 入口隐藏时直接输地址也只显示说明 */ }
  VIEW = view;
  $$('[data-view]').forEach(s => s.hidden = s.dataset.view !== view);
  $$('[data-nav]').forEach(a => { const on = a.dataset.nav === (view === 'wizard' ? 'settings' : view); a.classList.toggle('active', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  window.scrollTo(0, 0);
  renderSteps();
  try {
    if (view === 'overview') await renderOverview();
    else if (view === 'list') await renderList(params);
    else if (view === 'execute') await renderExecute();
    else if (view === 'settings') await renderSettings();
    else if (view === 'wizard') renderWizard();
  } catch (e) { toast(e.message); }
  renderSteps();
}
window.addEventListener('hashchange', route);

/* ---------- 任务（扫描 / 执行 / 回滚） ---------- */
let JOB = {running: false}, polling = false;
const JOB_NAME = {inventory: '盘点', full: '扫描', run: '执行', rollback: '回滚'};
function renderJobBar() {
  const j = JOB, bar = $('#jobBar');
  $$('[data-run]').forEach(b => b.disabled = !!j.running);
  if (!j.running) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.innerHTML = `<b>${esc(JOB_NAME[j.mode] || '任务')}中</b><span class="muted">${esc(j.msg || '')}</span><div class="progress"><i style="width:${j.pct || 0}%"></i></div><b>${j.pct || 0}%</b>
    ${j.mode === 'inventory' || j.mode === 'full' ? '<button class="btn sm" type="button" id="btnStop">停止</button>' : ''}`;
  const s = $('#btnStop'); if (s) s.onclick = stopJob;
}
async function runJob(mode) {
  if (mode === 'full') {
    let k = 0; try { k = (await api('api/exec/status')).approvals || 0; } catch (e) {}
    if (k && !confirm(`当前有 ${n(k)} 条已批准。重新扫描后，判定没变的批准会自动带到新结果，判定变了或已不在的会作废（扫完会报数）。确定重新扫描？`)) return;
  }
  try { await api('api/run/' + mode, {method: 'POST'}); poll(); } catch (e) { toast(e.message); }
}
async function stopJob() {
  if (!confirm('停止当前任务？这次不会产出结果，之前的结果不受影响。')) return;
  try { JOB = await api('api/job/cancel', {method: 'POST'}); renderJobBar(); } catch (e) { toast(e.message); }
}
async function poll() {
  if (polling) return; polling = true;
  let watched = false;
  try {
    while (true) {
      JOB = await api('api/job'); renderJobBar();
      if (JOB.running) watched = true;
      if (!JOB.running) {
        if (JOB.run_id && JOB.finished && Date.now() / 1000 - JOB.finished < 15) toast(JOB.msg || '完成');
        await Promise.all([loadResult(), loadAppr(), loadExec()]);
        LIST.paths = null;
        if (JOB.mode === 'run' || JOB.mode === 'rollback') EXSEL = JOB.run_id || EXSEL;
        // 扫描跑完（这次看着它跑的、且成功出了结果）→ 直接落到清单，下一步就是做决定
        if (watched && JOB.mode === 'full' && !JOB.exit && !JOB.cancelled && RES && RES.run_id === JOB.run_id
            && !['settings', 'wizard', 'execute'].includes(VIEW) && VIEW !== 'list') { location.hash = '#/list'; break; }
        route();
        break;
      }
      await new Promise(r => setTimeout(r, 1200));
    }
  } finally { polling = false; }
}
document.addEventListener('click', e => { const b = e.target.closest('[data-run]'); if (b) { e.preventDefault(); runJob(b.dataset.run); } });

/* ============================== 首页（原总览 + 扫描） ============================== */
let INV = null, PROBE = null;
/* 下一步：没扫过 → 扫描；扫完 → 去清单做决定；设置改过 → 重新扫描 */
function nextStepHtml() {
  const r = RES, sm = (r && r.summary) || {};
  const card = (t, sub, btn) => `<div class="next-card" role="status"><div class="nc-text"><b>${t}</b><span>${sub}</span></div>${btn}</div>`;
  const scanBtn = label => `<button class="btn primary" type="button" data-run="full">${ic('refresh', 'sm')}${label}</button>`;
  if (r && r.run_id && r.stale) return card('设置改过，这份结果过期了', '重新扫描一次，再去清单做决定。', scanBtn('重新扫描'));
  if (r && r.run_id) {
    const cut = (sm['可切'] || {}).count || 0, tbd = (sm['待定'] || {}).count || 0;
    return card('扫描完成', `${fmtTime(r.finished)}。下一步：到清单里看每部片留哪份、清哪份`,
      `<a class="btn primary" href="#/list">去清单做决定（可清理 ${n(cut)} · 需人工确认 ${n(tbd)}）${ic('chev', 'sm')}</a>`);
  }
  return card('还没扫描', '点「扫描」：读一遍勾上的目录和 Emby 片库，把同一部片的副本归成一组。只出清单，不动任何文件。', scanBtn('扫描'));
}
async function renderOverview() {
  const [inv] = await Promise.all([api('api/inventory').catch(() => null), loadResult(), loadExec()]);
  INV = inv;
  const r = RES, fresh = CFG && !CFG.setup_done;
  $('#ovBanners').innerHTML = banners(r);
  $('#ovActions').hidden = fresh;                    // 还没设定：只给「开始设置」，不给扫描
  $('#ovMain').hidden = fresh;
  $('#ovEmpty').hidden = !fresh;
  if (fresh) {
    $('#ovEmptyTitle').textContent = '还没连上数据源';
    $('#ovEmptyText').textContent = '只要告诉面板两个目录：CD2 配置目录、Emby 数据目录。其余自动识别，你只负责确认。';
    $('#ovEmptyBtns').innerHTML = '<a class="btn primary" href="#/wizard">开始设置</a>';
    $('#ovSub').textContent = '首次使用';
    return;
  }
  $('#invNext').innerHTML = nextStepHtml();
  $('#invScope').innerHTML = scopeHtml();
  const S = b => ((r && r.summary) || {})[b] || {count: 0, gb: 0};
  const st = (r && r.stats) || (inv && inv.stats) || {}, src = (r && r.source) || st.source || {};
  $('#ovSub').innerHTML = r ? `上次扫描 ${fmtTime(r.finished)}${r.stale ? '<span class="dot-sep">·</span><span class="t-amber">设置改过，建议重新扫描</span>' : ''}` : '还没有扫描结果';
  const kpi = (label, icon, num, sub, tone = '') => `<div class="card stat"><div class="stat-top"><span class="stat-label">${label}</span>${ic(icon)}</div><div class="stat-num ${tone}">${num}</div><div class="stat-sub">${sub}</div></div>`;
  $('#ovKpis').innerHTML = !r ? '' : kpi(esc(bn('可切')), 'trash', n(S('可切').count), '约 ' + fmtGB(S('可切').gb), 't-green')
    + kpi(esc(bn('待定')), 'alert', n(S('待定').count), fmtGB(S('待定').gb) + ((r.kept_hidden || {}).count ? ` · 另有 ${n(r.kept_hidden.count)} 条已确认保留` : ''), 't-amber')
    + kpi(esc(bn('缺口')), 'gap', n(S('缺口').count), fmtGB(S('缺口').gb))
    + kpi(esc(bn('孤本')), 'db', n(S('孤本').count), fmtGB(S('孤本').gb));
  $('#ovKpis').hidden = !r;
  // 判定分布
  if (r) {
    $('#ovRunMeta').innerHTML = `${esc({cache: 'CD2 目录缓存', scan: '遍历挂载目录', csv: 'CSV'}[src.kind] || '')}<span class="dot-sep">·</span>结果以缓存时刻为准`;
    const total = BUCKET_ORDER.reduce((a, b) => a + S(b).count, 0) || 1;
    $('#ovDistHead').textContent = `判定分布 · ${n(total)} 条`;
    $('#distRows').innerHTML = BUCKET_ORDER.filter(b => S(b).count).map(b => {
      const c = S(b).count, pct = c / total * 100;
      return `<button class="dist-row" type="button" data-bucket="${esc(b)}"><span class="dist-dot dot-${TONE[b]}"></span><span class="dist-label">${esc(bn(b))}</span><span class="dist-count">${n(c)}</span><span class="dist-bar"><i class="bar-${TONE[b]}" style="width:${Math.max(pct, .5)}%"></i></span><span class="dist-pct">${pct.toFixed(1)}%</span>${ic('chev', 'sm chev')}</button>`;
    }).join('');
    $$('#distRows .dist-row').forEach(b => b.onclick = () => go('list', new URLSearchParams({bucket: b.dataset.bucket})));
    const gst = r.groups || {};
    $('#ovHeld').innerHTML = r.engine === 2 && gst.held_groups ? `<div class="unmatched"><span class="u-label">暂不判定</span><span class="u-count">${n(gst.held_groups)}</span><span class="u-note">组像剧集（同一个夹里好几份或带集号），共 ${n(gst.held_copies || 0)} 份，没判；归成重复组的共 ${n(gst.groups || 0)} 组。</span></div>` : '';
  } else {
    $('#ovDistHead').textContent = '判定分布'; $('#ovRunMeta').textContent = '扫描后出现';
    $('#distRows').innerHTML = '<div class="muted" style="padding:10px 0">还没有扫描结果。</div>'; $('#ovHeld').innerHTML = '';
  }
  // 缓存覆盖（只在不全量时提醒）
  const unl = src.unlisted || {}, cov = Object.entries(unl).filter(([, x]) => x && x.count);
  $('#invCoverage').innerHTML = src.kind === 'cache' && cov.length ? '<div class="warn-box">' + cov.map(([z, x]) => `${n(x.count)} 个目录 CD2 没打开过${x.in_disc ? `（碟内 ${n(x.in_disc)}）` : ''}，那部分不在比对里`
      + (x.samples || []).slice(0, 5).map(p => `<div class="mono" style="font-size:11.5px">${esc(p)}</div>`).join('')).join('<br>') + '<br>要全量就先在 CD2 里把它们点开，再扫描。</div>' : '';
  // 扫描细节（原「库存与数据源」+「引擎与基线」）
  const kv = (k, v, dot) => `<div class="kv-row"><span class="k">${k}</span>${dot ? `<span class="status-dot dot-${dot}"></span>` : ''}<span class="v">${v}</span></div>`;
  const em = st.emby || {}, ex = EXS || {};
  let h = '';
  if (r) h += kv('结果', esc(r.run_id) + ' · ' + fmtTime(r.finished)) + kv('配置', r.stale ? '改过，需重新扫描' : '与结果一致', r.stale ? 'amber' : 'green')
    + kv('保护守卫', r.rejected ? '整批拒绝' : '通过', r.rejected ? 'amber' : 'green');
  h += kv('来源', {cache: 'CD2 目录缓存', scan: '遍历挂载目录', csv: '现成 CSV'}[src.kind] || '—')
    + (src.kind === 'cache' && src.time_max ? kv('缓存时刻', esc(fmtTime(src.time_min) + ' ~ ' + fmtTime(src.time_max))) : '');
  for (const z in ZN) if ((st[z] || {}).count) h += kv(ZN[z] + '（按名字归类）', `${n(st[z].count)} 条 · ${fmtGB(st[z].gb)}`);
  const skipped = Object.values(st.protected_skipped || {}).reduce((a, x) => a + x, 0);
  if (skipped) h += kv('没勾 / 保护剔除', `${n(skipped)} 条${st.protected_gb ? ' · ' + fmtGB(st.protected_gb) : ''}`);
  if (st.quarantine_skipped) h += kv('查重区跳过', n(st.quarantine_skipped) + ' 条');
  if (st.heji_episodes) h += kv('分出的剧集', `${n(st.heji_episodes.count)} 个文件 · ${fmtGB(st.heji_episodes.gb)}`);
  const dh = (st.dropped || {}).heji || {};
  if (Object.keys(dh).length) h += kv('没计入', Object.entries(dh).map(([k, v]) => (k === 'small' ? '小于体积门槛' : k.slice(3) + ' 格式') + ' ' + n(v)).join('，'));
  h += kv('Emby 电影', em.movies !== undefined ? `${n(em.movies)} 部 · ${esc(em.movie_rule || '')}` : '没连上', em.movies ? 'green' : 'amber');
  // 反馈 29.2：哈希门（同一个文件、Sha1 一致）这一轮的账
  const hg = st.hash_gate || (r && r.hidden && r.hidden.on !== undefined ? r.hidden : null);
  if (hg) h += kv('同文件哈希', hg.on
    ? `${n(hg.groups || 0)} 组 · 多出 ${n(hg.dup || 0)} 份 ${fmtGB(hg.dup_gb || 0)} · 标可清理 ${n(hg.cut || 0)} 份 ${fmtGB(hg.cut_gb || 0)}`
      + (hg.pointed ? ` · ${n(hg.pointed)} 份 Emby 也指着、待定` : '')
    : esc(hg.why || '没开'), hg.on ? '' : 'amber');
  h += kv('执行态', execOn ? '执行已开 · ' + (ex.backend === 'cd2' ? 'CD2 直连' : '挂载改名') : (ex.allowed ? '界面已锁定' : '只读默认态'), execOn ? 'amber' : 'zinc');
  h += '<p class="kv-note">画质档：4K / 1080p / 720p 及以下 / 未知 · 带 * 为按体积推断，非实测</p>';
  const errs = (r && r.errors) || (inv && inv.errors) || [], ne = (r && r.error_count) || (inv && inv.error_count) || 0;
  if (ne) h += `<div class="warn-box">${n(ne)} 条提示：<br>${errs.slice(0, 12).map(esc).join('<br>')}</div>`;
  $('#invInfo').innerHTML = h;
  // 最近批次（执行态才显示，只看结果）
  $('#ovBatch').hidden = true;
  if (execOn) {
    try { BATCHES = await api('api/exec/batches'); } catch (e) { BATCHES = []; }
    const b = BATCHES.find(x => x.reconcile);
    if (b) {
      const rc = b.reconcile;
      $('#ovBatch').hidden = false;
      $('#ovBatchKv').innerHTML = kv('批次', `<span class="mono">${esc(b.batch_id)}</span> · 去向：${esc(actName(b.action))}`)
        + kv('结果', `${n(rc.rows)} 条：搬成 ${n(rc.moved_rows)}${rc.failed_rows ? ' · 失败 ' + n(rc.failed_rows) : ''}${rc.refused_rows ? ' · 拒绝 ' + n(rc.refused_rows) : ''}`)
        + kv('状态', rc.ok ? '对账通过' : '对账不平', rc.ok ? 'green' : 'amber');
    }
  }
}
const actName = a => (a || '').split(',').map(x => ACT_NAME[x] || x).join(' / ') || '—';
function scopeHtml() {
  const kv = (k, v, tone) => `<div class="kv-row"><span class="k">${k}</span><span class="v${tone ? ' t-' + tone : ''}">${v}</span></div>`;
  const roots = Object.values(CFG.zones || {}).flat(), skip = CFG.skip_dirs || [];
  const path = v => v ? `<span class="mono">${esc(v)}</span>` : '';
  let h = kv('主媒体库', path(CFG.main_lib_dir) || '未指定', CFG.main_lib_dir ? '' : 'amber')
    + kv('查重区', CFG.quarantine_dir ? path(CFG.quarantine_dir) + ' · 不扫' : '未指定 · 可清理的没地方搬', CFG.quarantine_dir ? '' : 'amber')
    + kv('待入库区', CFG.staging_on === false ? '关：留下的片留在原地' : (path(CFG.staging_dir) || '未指定') + ' · 开', CFG.staging_on === false || CFG.staging_dir ? '' : 'amber')
    + kv('筛查的目录', roots.length ? roots.length + ' 个' : '还没勾，不进筛查', roots.length ? '' : 'amber');
  // 反馈 27：只显示末段目录名（全路径悬停看），左对齐、行首带序号；其中不筛默认收起，点开按父目录分组
  const last = p => String(p).replace(/\/+$/, '').split('/').pop() || p;
  const parent = p => String(p).replace(/\/+$/, '').split('/').slice(0, -1).join('/') || '/';
  const items = (list, from) => list.map((p, i) => `<li><span class="sl-n">${from + i}</span><span class="sl-name" title="${esc(p)}">${esc(last(p))}</span></li>`).join('');
  if (roots.length) h += `<ol class="scope-list">${items(roots, 1)}</ol>`;
  if (skip.length) {
    const byParent = {};
    skip.forEach(p => (byParent[parent(p)] = byParent[parent(p)] || []).push(p));
    let i = 1, body = '';
    for (const [par, list] of Object.entries(byParent)) {
      body += `<div class="sl-group" title="${esc(par)}">${esc(last(par))}</div><ol class="scope-list">${items(list, i)}</ol>`;
      i += list.length;
    }
    h += `<details class="scope-skip"><summary>其中不筛 ${skip.length} 个目录 <span class="sl-arrow">▸</span></summary>${body}</details>`;
  }
  if (!CFG.tree_model && ((CFG.protect_names || []).length || (CFG.listpack_names || []).length))
    h += kv('旧设置', '还在按名字保护：' + esc([...(CFG.protect_names || []), ...(CFG.listpack_names || [])].join('、')) + '。点「改筛查范围」换成勾选，没勾 = 不筛');
  return h;
}
async function putCfg(c, confirmRm) {
  const body = JSON.parse(JSON.stringify(c)); delete body._rmProtect;
  body.confirm_remove_protect = !!confirmRm;
  await api('api/config', J(body));
  await loadCfg();
}

/* ============================== 清单 ============================== */
const LIST = {more: false, cards: [], f: {bucket: new Set(), stage: new Set(), tag: new Set(), cls: new Set(), flag: new Set()}, q: '', sort: 'gb', page: 0, rows: [], total: 0, all: 0, gb: 0, facets: {}, sel: new Set(), paths: null, pathsKey: '', open: null};
const PAGE = 50;                                   // 一页 50 张卡（一张卡 = 一部片）
const FACET_GROUPS = [['bucket', '判定'], ['stage', '类别'], ['tag', '标签'], ['cls', '子类'], ['flag', '标记']];
function facetLabel(g, k) {
  if (g === 'bucket') return bn(k);
  if (g === 'stage') return sn(k);
  if (g === 'tag') return k;
  if (g === 'cls') { const [s, c] = k.split('|'); return sn(s) + ' · ' + cn(s, c); }
  return FLAG_NAME[k] || k;
}
function filterParams() {
  const p = new URLSearchParams();
  for (const g in LIST.f) if (LIST.f[g].size) p.set(g, [...LIST.f[g]].join(','));
  if (LIST.q) p.set('q', LIST.q);
  return p;
}
function syncUrl() {
  const p = filterParams();
  if (LIST.sort !== 'gb') p.set('sort', LIST.sort);
  if (LIST.page) p.set('page', LIST.page + 1);
  const h = '#/list' + (p.toString() ? '?' + p : '');
  if (location.hash !== h) history.replaceState(null, '', h);
}
async function renderList(params) {
  if (params) {
    for (const g in LIST.f) LIST.f[g] = new Set((params.get(g) || '').split(',').filter(Boolean));
    if (![...params.keys()].length) LIST.f.bucket = new Set(['可切']);
    LIST.q = params.get('q') || ''; LIST.sort = params.get('sort') || 'gb'; LIST.page = Math.max(0, (+params.get('page') || 1) - 1);
  }
  $('#q').value = LIST.q; $('#sortSel').value = LIST.sort;
  await Promise.all([loadResult(), loadExec(), loadAppr()]);
  const r = RES;
  $('#listBanners').innerHTML = banners(r) + carryNote() + (r ? `<div class="alert">${ic('info')}<div>结果以 CD2 缓存时刻为准${execOn ? ' · 勾选后「批准，送入执行」，到执行页预演、执行' : ' · 现在是只读模式：可以筛选和导出清单。开启执行后，这里会出现批准按钮。'}</div></div>` : '');
  $('#listSub').innerHTML = r ? `${esc(r.run_id)}<span class="dot-sep">·</span>${fmtTime(r.finished)}<span class="dot-sep">·</span>一张卡是一部片：左边是留下的，右边是同片的其他份` : '还没有扫描结果';
  const nA = Object.keys(APPR.items || {}).length, ge = $('#btnGoExec');
  if (ge) { ge.hidden = !(execOn && nA); ge.innerHTML = `${ic('play', 'sm')}去执行（已批准 ${n(nA)} 条）`; }
  await loadRows();
}
async function loadRows() {
  syncUrl();
  const p = filterParams(); p.set('sort', LIST.sort); p.set('offset', LIST.page * PAGE); p.set('limit', PAGE); p.set('facets', 1);
  const r = await api('api/cards?' + p);
  if (r.total && LIST.page * PAGE >= r.total) { LIST.page = 0; return loadRows(); }
  // 详情抽屉、勾选都还按「行」走：把这一页卡里的行摊平，卡记住自己的行号
  const rows = [];
  r.cards.forEach(c => { c.idx = c.rows.map(x => rows.push(x) - 1); });
  Object.assign(LIST, {cards: r.cards, rows, total: r.total, rowsTotal: r.rows_total, all: r.all || 0, gb: r.gb, facets: r.facets || {}, kept: r.kept_hidden || {count: 0}});
  $('#keptNote').innerHTML = LIST.kept.count ? `<div class="alert">${ic('check')}<div>另有 <b>${n(LIST.kept.count)}</b> 条「${esc(bn('待定'))}」已确认保留，已隐藏（${fmtGB(LIST.kept.gb)}）· <a href="#/settings">在设置页查看 / 撤销</a></div></div>` : '';
  renderTabs(); renderFacets(); renderChips(); renderTable(); renderListStats();
  await refreshPickAll();
}
function renderListStats() {
  const S = b => (RES && RES.summary || {})[b] || {count: 0, gb: 0};
  const kpi = (label, icon, num, sub, tone = '') => `<div class="card stat"><div class="stat-top"><span class="stat-label">${label}</span>${ic(icon)}</div><div class="stat-num ${tone}">${num}</div><div class="stat-sub">${sub}</div></div>`;
  $('#listStats').innerHTML = kpi('入清单条目', 'db', n(LIST.all), '全部类别')
    + kpi('当前筛选', 'search', n(LIST.total) + '<small> 部</small>', n(LIST.rowsTotal || 0) + ' 条 · ' + fmtGB(LIST.gb))
    + kpi(esc(bn('可切')), 'trash', n(S('可切').count), '约 ' + fmtGB(S('可切').gb), 't-green')
    + kpi('已勾选', 'check', n(LIST.sel.size), LIST.sel.size ? '跨页保留' : '勾选后可导出' + (execOn ? '或批准' : ''));
}
let OPEN_FACET = '';
const TABS = ['可切', '待定', '缺口', '孤本'];
function renderTabs() {
  const S = b => ((RES && RES.summary) || {})[b] || {count: 0};
  const sel = LIST.f.bucket, only = sel.size === 1 ? [...sel][0] : '';
  const other = ['stage', 'tag', 'cls', 'flag'].some(g => LIST.f[g].size);
  $('#listTabs').innerHTML = TABS.map(b => `<button type="button" role="tab" aria-selected="${only === b}" class="${only === b ? 'on' : ''}" data-tab="${b}">${esc(bn(b))}<span class="n">${n(S(b).count)}</span></button>`).join('')
    + `<button type="button" role="tab" aria-selected="${!sel.size}" class="${!sel.size ? 'on' : ''}" data-tab="">全部</button>`;
  $$('#listTabs [data-tab]').forEach(b => b.onclick = () => { LIST.f.bucket = new Set(b.dataset.tab ? [b.dataset.tab] : []); LIST.page = 0; LIST.sel.clear(); loadRows(); });
  const show = LIST.more || other || (sel.size && !TABS.includes(only));
  $('#facets').hidden = !show;
  $('#btnMore').setAttribute('aria-expanded', show);
  $('#btnMore').textContent = show ? '收起筛选' : '更多筛选';
}
$('#btnMore').onclick = () => { LIST.more = $('#facets').hidden; renderTabs(); };
function renderFacets() {
  $('#facets').innerHTML = FACET_GROUPS.map(([g, name]) => {
    const counts = LIST.facets[g] || {}, sel = LIST.f[g];
    let keys = Object.keys(counts);
    for (const k of sel) if (!keys.includes(k)) keys.push(k);
    if (g === 'bucket') keys.sort((a, b) => BUCKET_ORDER.indexOf(a) - BUCKET_ORDER.indexOf(b));
    else keys.sort((a, b) => (counts[b] || 0) - (counts[a] || 0));
    const opts = keys.map(k => `<button type="button" class="facet-opt ${sel.has(k) ? 'on' : ''}" data-g="${g}" data-k="${esc(k)}"><span class="box">${ic('check')}</span>${g === 'bucket' ? `<span class="dot dot-${TONE[k] || 'zinc'}"></span>` : ''}<span>${esc(facetLabel(g, k))}</span><span class="n">${n(counts[k] || 0)}</span></button>`).join('')
      || '<div class="facet-pop-head">没有可选项</div>';
    return `<div class="facet"><button type="button" class="facet-btn ${sel.size ? 'has' : ''}" data-fg="${g}"><span class="plus">${ic('plus', 'sm')}</span>${name}${sel.size ? `<span class="fcount">${sel.size}</span>` : ''}${ic('down', 'sm chev')}</button>
      <div class="facet-pop ${OPEN_FACET === g ? 'open' : ''}" data-pop="${g}"><div class="facet-pop-head">${name}（计数随其他条件联动）</div><div style="max-height:320px;overflow:auto">${opts}</div>${sel.size ? `<div class="facet-pop-foot"><button class="facet-clear" type="button" data-clear="${g}">清除这一组</button></div>` : ''}</div></div>`;
  }).join('');
  $$('#facets [data-fg]').forEach(b => b.onclick = e => { e.stopPropagation(); OPEN_FACET = OPEN_FACET === b.dataset.fg ? '' : b.dataset.fg; renderFacets(); });
  $$('#facets .facet-opt').forEach(b => b.onclick = e => { e.stopPropagation(); const s = LIST.f[b.dataset.g]; s.has(b.dataset.k) ? s.delete(b.dataset.k) : s.add(b.dataset.k); LIST.page = 0; loadRows(); });
  $$('#facets [data-clear]').forEach(b => b.onclick = e => { e.stopPropagation(); LIST.f[b.dataset.clear].clear(); LIST.page = 0; loadRows(); });
  $$('#facets .facet-pop').forEach(p => p.onclick = e => e.stopPropagation());
}
document.addEventListener('click', () => { if (OPEN_FACET) { OPEN_FACET = ''; renderFacets(); } });
function renderChips() {
  const chips = [];
  for (const [g, name] of FACET_GROUPS) for (const k of LIST.f[g]) chips.push(`<span class="fchip"><span class="k">${name}</span>${g === 'bucket' ? `<span class="dot dot-${TONE[k] || 'zinc'}"></span>` : ''}${esc(facetLabel(g, k))}<button type="button" data-rm="${g}" data-k="${esc(k)}" aria-label="移除">${ic('x')}</button></span>`);
  if (LIST.q) chips.push(`<span class="fchip"><span class="k">搜索</span>${esc(LIST.q)}<button type="button" data-rmq aria-label="移除">${ic('x')}</button></span>`);
  $('#activeBar').hidden = !chips.length;
  $('#activeChips').innerHTML = chips.join('');
  $('#activeCount').innerHTML = `显示 <b>${n(LIST.total)}</b> / ${n(LIST.all)}`;
  $('#propFill').style.width = (LIST.all ? LIST.total / LIST.all * 100 : 0) + '%';
  $$('#activeChips [data-rm]').forEach(b => b.onclick = () => { LIST.f[b.dataset.rm].delete(b.dataset.k); LIST.page = 0; loadRows(); });
  const q = $('#activeChips [data-rmq]'); if (q) q.onclick = () => { LIST.q = ''; $('#q').value = ''; LIST.page = 0; loadRows(); };
}
function zoneOfPath(p) {
  let best = '', bz = '';
  for (const z in ZN) for (const r of (CFG.zones[z] || [])) if ((p === r || p.startsWith(r + '/')) && r.length > best.length) { best = r; bz = z; }
  return bz ? ZN[bz] : '—';
}
const baseName = p => (p || '').split('/').pop();
const parentOf = p => { const i = (p || '').lastIndexOf('/'); return i > 0 ? p.slice(0, i) : '/'; };
const stripExt = s => s.replace(/\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$/i, '');
function rowChips(x) {
  const c = [];
  const ap = APPR.items[x.path];
  if (ap) c.push(`<span class="chip hot">已批准 → ${esc(ACT_NAME[ap.action] || '')}</span>`);
  if (x.move) c.push(`<span class="chip">${x.move === '整夹' ? '整夹' : '单文件'}</span>`);
  if (x.flag) c.push(`<span class="chip">${esc(x.flag)}</span>`);
  if (x.subfx && !(x.ntags || []).includes('特效字幕')) c.push(`<span class="chip" title="${esc(x.subfx)}">特效字幕版</span>`);
  if ((x.basis || '').includes('按体积推断')) c.push('<span class="chip">体积推断*</span>');
  return c.join('');
}
const ROLE_SHORT = {keep: '保留', '版本型': '也留（版本对）', '可切': '可清理', '待定': '需人工确认', locked: '不碰'};
function memberLine(m) {
  return `${esc(ZONE_SHORT[m.zone] || m.zone)} · ${esc(KIND_SHORT[m.kind] || m.kind)} · ${esc(RES_SHORT[m.res] || m.res)}${m.res_src === '体积推断' ? '*' : ''}`;
}
/* 长名字从中间截：尾巴（DISC 1、-HDHome、@CHDBits）往往是同组几行唯一的不同点，不能切掉（反馈 25） */
function midTrunc(t, max = 46) { return t.length <= max ? t : t.slice(0, max - 21) + '…' + t.slice(-20); }
/* 碟号：新结果有 disc_no；老结果从依据里「多碟装第 n / N 张」读 */
function discOf(x) {
  if (x.disc_no && x.disc_set) return `第 ${x.disc_no}/${x.disc_set} 张`;
  const m = /多碟装第 (\d+) \/ (\d+) 张/.exec(x.basis || '');
  return m ? `第 ${m[1]}/${m[2]} 张` : '';
}
/* 名字里的标签（制作组 / 版本 / 语言字幕）：一行最多 5 个，其余收进「+N」（悬停看全）；特效字幕组名单上的组名淡紫色（反馈 26） */
function tagChips(list, fxList) {
  const fx = new Set(fxList || []);
  const t = [...new Set(list.filter(Boolean))];
  if (!t.length) return '';
  const show = t.slice(0, 5), rest = t.slice(5);
  return `<div class="chips">${show.map(x => `<span class="chip${x.startsWith('第 ') ? ' hot' : fx.has(x) ? ' fx' : ''}">${esc(x)}</span>`).join('')}`
    + (rest.length ? `<span class="chip more" title="${esc(rest.join(' · '))}">+${rest.length}</span>` : '') + '</div>';
}
function fitem(path, cls, meta, extra, tags, fx) {
  const nm = stripExt(baseName(path));
  return `<div class="fitem ${cls || ''}"><div class="fn" title="${esc(nm)}">${esc(midTrunc(nm))}</div><div class="fp mono" title="${esc(path)}">${esc(parentOf(path))}</div>`
    + `<div class="fm">${meta || ''}</div>${tagChips(tags || [], fx)}${extra || ''}</div>`;
}
function cardActions(c) {
  const rs = c.idx.map(i => LIST.rows[i]);
  const can = rs.filter(x => x.bucket === '可切' || x.bucket === '缺口'), tbd = rs.filter(x => x.bucket === '待定');
  let h = '';
  if (execOn && can.length) {
    const ap = can.filter(x => APPR.items[x.path]);
    if (ap.length === can.length) h += `<span class="t-green">已批准 → ${esc(actName([...new Set(ap.map(x => APPR.items[x.path].action))].join(',')))}</span><button class="btn sm" type="button" data-unappr="${c.key}">撤销</button>`;
    else if (!(can.some(x => x.bucket === '缺口') && CFG.tree_model && CFG.staging_on === false))
      h += `<button class="btn sm primary" type="button" data-appr="${c.key}">批准这部片${can.length > 1 ? `（${can.length} 份）` : ''}</button>`;
  }
  if (tbd.length) h += `<button class="btn sm" type="button" data-keepc="${c.key}">确认保留${tbd.length > 1 ? `（${tbd.length} 份）` : ''}</button>`;
  return h + `<button class="btn sm ghost" type="button" data-open="${c.idx[0]}">详情</button>`;
}
function renderTable() {
  const box = $('#cards');
  $('#empty').hidden = !!LIST.cards.length;
  if (!RES) { $('#emptyTitle').textContent = '还没有扫描结果'; $('#emptyText').textContent = '先到首页点「扫描」。'; }
  else { $('#emptyTitle').textContent = '没有符合条件的结果'; $('#emptyText').textContent = '换个页签或关键词，或清除筛选条件试试。'; }
  box.innerHTML = LIST.cards.map(c => {
    const rs = c.idx.map(i => LIST.rows[i]), first = rs[0];
    const picked = rs.every(x => LIST.sel.has(x.path)), some = !picked && rs.some(x => LIST.sel.has(x.path));
    const title = c.title || stripExt(baseName(first.path));
    const mine = new Set(rs.flatMap(x => [x.path]));
    const isMine = m => mine.has(m.path) || (m.parts || []).some(pp => mine.has(pp));
    let left = '', right = '', more = '';
    if (c.members) {
      const keeps = c.members.filter(m => m.role === 'keep' || m.role === '版本型');
      left = keeps.map(m => fitem(m.path, 'keep', `<b>${esc(ROLE_SHORT[m.role])}</b> · ${memberLine(m)} · <span translate="no">${fmtGB(m.gb)}</span>${m.subfx ? ' · 特效字幕版' : ''}`,
        '', [(m.parts || []).length ? `多碟装 ${m.parts.length} 张` : '', ...(m.ntags || [])], m.nfx)).join('');
      const rest = c.members.filter(m => !keeps.includes(m) && !isMine(m));
      if (rest.length) more = `<div class="fmore">同组另有 ${n(rest.length)} 份：${[...new Set(rest.map(m => ROLE_SHORT[m.role] || m.role))].map(esc).join('、')}（点详情看全）</div>`;
    } else {
      const k = first.keep || '';
      left = k ? (k.startsWith('/') ? fitem(k, 'keep', `<b>参照</b>${first.keep_gb ? ' · <span translate="no">' + fmtGB(first.keep_gb) + '</span>' : ''}`) : `<div class="fitem keep"><div class="fn">${esc(k)}</div></div>`)
        : `<div class="fitem"><div class="fm">${esc({孤本: '全库只有这一份', 缺口: 'Emby 片库里没有这部片'}[first.bucket] || '—')}</div></div>`;
    }
    right = rs.map(x => {
      const m = (c.members || []).find(mm => mm.path === x.path || (mm.parts || []).includes(x.path));
      const ap = APPR.items[x.path];
      const rc = rowChips(x);
      return fitem(x.path, '', `${badge(x.bucket)}${m ? ' ' + memberLine(m) : ''} · <span translate="no">${fmtGB(x.gb)}</span>${ap ? ` · <span class="t-green">已批准</span>` : ''}`,
        rc ? `<div class="chips">${rc}</div>` : '', [discOf(x), ...(x.ntags || [])], x.nfx);
    }).join('');
    const lh = c.members ? '留' : (first.bucket === '缺口' ? '主库里' : '参照');
    const rh = first.bucket === '可切' ? '可清理' : first.bucket === '缺口' ? '这份等着入库' : first.bucket === '待定' ? (rs.length > 1 ? '同片其他几份' : '同片另一份') : '这一份';
    const tags = [...new Set(rs.flatMap(x => x.tags || []))];
    return `<article class="fcard ${picked ? 'picked' : ''}" data-key="${esc(c.key)}">
      <div class="fcard-head"><button type="button" class="pick ${picked ? 'on' : some ? 'some' : ''}" data-pickc="${esc(c.key)}" role="checkbox" aria-checked="${picked ? 'true' : some ? 'mixed' : 'false'}" aria-label="勾选这部片">${PICK}</button>
        <span class="fcard-title" data-open="${c.idx[0]}" title="${esc(title)}">${esc(title)}</span>${tags.slice(0, 3).map(t => `<span class="chip">${esc(t)}</span>`).join('')}<span class="sp"></span>
        <span class="fcard-gb">${rs.length > 1 ? n(rs.length) + ' 份 · ' : ''}<span translate="no">${fmtGB(c.gb)}</span></span></div>
      <div class="fcard-body"><div class="fcol"><h4>${lh}</h4>${left}</div><div class="fcol"><h4>${rh}</h4>${right}${more}</div></div>
      <div class="fcard-foot"><span class="basis">${esc(first.basis || '')}</span>${cardActions(c)}</div></article>`;
  }).join('');
  const byKey = k => LIST.cards.find(c => c.key === k);
  $$('#cards [data-open]').forEach(b => b.onclick = () => openDlg(+b.dataset.open));
  $$('#cards [data-pickc]').forEach(b => b.onclick = () => {
    const rs = byKey(b.dataset.pickc).idx.map(i => LIST.rows[i]), all = rs.every(x => LIST.sel.has(x.path));
    rs.forEach(x => all ? LIST.sel.delete(x.path) : LIST.sel.add(x.path));
    renderTable(); refreshPickAll();
  });
  $$('#cards [data-appr]').forEach(b => b.onclick = () => cardApprove(byKey(b.dataset.appr)));
  $$('#cards [data-unappr]').forEach(b => b.onclick = async () => {
    const ps = byKey(b.dataset.unappr).idx.map(i => LIST.rows[i].path).filter(p => APPR.items[p]);
    try { await api('api/approvals', J({remove: ps})); await loadAppr(); renderTable(); } catch (e) { toast(e.message); }
  });
  $$('#cards [data-keepc]').forEach(b => b.onclick = async () => {
    const ps = byKey(b.dataset.keepc).idx.map(i => LIST.rows[i]).filter(x => x.bucket === '待定').map(x => x.path);
    try { const r = await keepPaths(ps); toast(`已确认保留 ${n(r.added)} 份：以后不再提醒（设置页可撤销）`); } catch (e) { toast(e.message); }
  });
  const a = LIST.page * PAGE;
  $('#footInfo').textContent = LIST.total ? `第 ${n(a + 1)}–${n(a + LIST.cards.length)} 部 · 共 ${n(LIST.total)} 部（${n(LIST.rowsTotal || 0)} 条）· ${fmtGB(LIST.gb)}` : '0 部';
  const pages = Math.max(1, Math.ceil(LIST.total / PAGE));
  $('#pgInfo').textContent = `${LIST.page + 1} / ${pages}`;
  $('#pgPrev').disabled = LIST.page <= 0; $('#pgNext').disabled = LIST.page >= pages - 1;
  updateSel();
}
async function cardApprove(c) {
  const rs = c.idx.map(i => LIST.rows[i]).filter(x => (x.bucket === '可切' || x.bucket === '缺口') && !APPR.items[x.path]);
  let r;
  try { r = await api('api/approvals', J({add: rs.map(x => ({path: x.path}))})); } catch (e) { toast(e.message); return; }
  await loadAppr(); renderTable();
  const errs = r.errors || [];
  toast(errs.length ? `批准了 ${n(rs.length - errs.length)} 份；${n(errs.length)} 份没批：${errs[0].reason}` : `已批准这部片的 ${n(rs.length)} 份`);
}
function togglePick(i) {
  const p = LIST.rows[i].path;
  LIST.sel.has(p) ? LIST.sel.delete(p) : LIST.sel.add(p);
  renderTable(); refreshPickAll();
  if (LIST.open === i) renderDlg();
}
function updateSel() {
  const k = LIST.sel.size;
  $('#selCount').innerHTML = `已勾选 <b>${n(k)}</b> 份`;
  $('#btnClearSel').disabled = !k;
  $('#btnKeepSel').hidden = !k;
  $('#btnApprove').disabled = !k;
  $('#btnExport').innerHTML = ic('download', 'sm') + (k ? `导出已勾选（${n(k)}）` : '导出 CSV');
  renderListStats();
}
async function filterPaths() {
  const key = filterParams().toString();
  if (LIST.paths && LIST.pathsKey === key) return LIST.paths;
  const r = await api('api/rows/paths?' + key);
  LIST.paths = r.paths; LIST.pathsKey = key;
  return LIST.paths;
}
async function refreshPickAll() {
  let state = 'none';
  if (LIST.sel.size && LIST.total) {
    const ps = await filterPaths();
    const c = ps.filter(p => LIST.sel.has(p)).length;
    state = c === 0 ? 'none' : c >= ps.length ? 'all' : 'some';
  }
  for (const el of [$('#selAllBox')]) { el.classList.toggle('on', state === 'all'); el.classList.toggle('some', state === 'some'); }
  return state;
}
async function toggleAll() {
  const ps = await filterPaths();
  const all = ps.length && ps.every(p => LIST.sel.has(p));
  ps.forEach(p => all ? LIST.sel.delete(p) : LIST.sel.add(p));
  renderTable(); refreshPickAll();
  toast(all ? `已取消当前筛选的 ${n(ps.length)} 条` : `已勾选当前筛选的全部 ${n(ps.length)} 条（跨页）`);
}
$('#btnSelectAll').onclick = toggleAll;
$('#btnClearSel').onclick = () => { LIST.sel.clear(); renderTable(); refreshPickAll(); };
$('#btnClearFilters').onclick = $('#btnEmptyClear').onclick = () => { for (const g in LIST.f) LIST.f[g].clear(); LIST.q = ''; $('#q').value = ''; LIST.page = 0; loadRows(); };
$('#pgPrev').onclick = () => { LIST.page--; loadRows().then(() => window.scrollTo(0, $('.table-card').offsetTop - 20)); };
$('#pgNext').onclick = () => { LIST.page++; loadRows().then(() => window.scrollTo(0, $('.table-card').offsetTop - 20)); };
$('#sortSel').onchange = () => { LIST.sort = $('#sortSel').value; LIST.page = 0; loadRows(); };
let qT; $('#q').oninput = () => { clearTimeout(qT); qT = setTimeout(() => { LIST.q = $('#q').value.trim(); LIST.page = 0; loadRows(); }, 300); };
async function download(r, fallback) {
  if (!r.ok) { let m = r.status; try { m = (await r.json()).detail } catch (e) {} toast(m); return; }
  const cd = r.headers.get('content-disposition') || '', m = cd.match(/filename\*=UTF-8''([^;]+)/);
  const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = m ? decodeURIComponent(m[1]) : fallback; a.click();
}
$('#btnExport').onclick = async () => {
  if (LIST.sel.size) await download(await fetch(u('api/export/selected'), P({paths: [...LIST.sel]})), 'pancheck_selected.csv');
  else await download(await fetch(u('api/export?' + filterParams())), 'pancheck.csv');
};
// 批准，送入执行（清单页唯一出口动作）
function updateApprBar() {
  const items = Object.values(APPR.items || {}), cnt = a => items.filter(x => x.action === a).length;
  $('#apprTotal').textContent = n(items.length); $('#apprQ').textContent = n(cnt('quarantine')); $('#apprM').textContent = n(cnt('mainlib'));
  $('#apprU').innerHTML = cnt('unique') ? ` · → 唯一副本目录 <b>${n(cnt('unique'))}</b>` : '';
  $('#apprTrial').hidden = !(EXS && !EXS.trial_ok);
  updateNavCounts();
}
$('#btnApprove').onclick = async () => {
  if (!LIST.sel.size) return;
  let r;
  try { r = await api('api/approvals', J({add: [...LIST.sel].map(p => ({path: p}))})); } catch (e) { toast(e.message); return; }
  const errs = r.errors || [], need = errs.filter(e => e.reason.includes('选去处')), bad = errs.length - need.length;
  const okN = LIST.sel.size - errs.length;
  const bad_set = new Set(errs.map(e => e.path));
  [...LIST.sel].forEach(p => { if (!bad_set.has(p)) LIST.sel.delete(p); });
  await loadAppr(); renderTable(); refreshPickAll();
  toast(`已批准 ${n(okN)} 条` + (bad ? `；${n(bad)} 条不能批准（只限可清理 / 主库缺口）` : '') + (need.length ? `；${n(need.length)} 条同时是唯一副本，请在详情里选去处` : ''));
};

/* 详情弹窗（居中） */
function openDlg(i) { LIST.open = i; renderDlg(); $('#dlg').classList.add('open'); $('#scrim').classList.add('open'); $('#dlg').setAttribute('aria-hidden', 'false'); }
function closeDlg() { LIST.open = null; $('#dlg').classList.remove('open'); $('#scrim').classList.remove('open'); $('#dlg').setAttribute('aria-hidden', 'true'); }
$('#dClose').onclick = closeDlg; $('#scrim').onclick = closeDlg;
const ROLE = {keep: ['保留', 't-green'], '版本型': ['也留（版本对）', 't-green'], '可切': ['可清理', ''], '待定': ['需人工确认', 't-amber'], locked: ['不碰（榜单 / 排除 / 多片合装）', 'muted']};
const ZONE_SHORT = {heji: '合集区', yuanpan: '原盘区', remux: 'REMUX 区', pack: '整夹合集区'};
const KIND_SHORT = {T: '特效字幕版', I: '原盘', D: 'DIY', R: 'REMUX', O: '压制'};
const RES_SHORT = {U: '4K', H: '1080p', S: '720p 及以下', '?': '画质未知'};
async function renderGroup(x) {
  const w = $('#dGroupWrap');
  w.hidden = !x.grp;
  if (!x.grp) return;
  $('#dGroup').innerHTML = '<div class="muted">读取中…</div>';
  let g; try { g = await api('api/group/' + encodeURIComponent(x.grp) + (RES ? '?run_id=' + encodeURIComponent(RES.run_id) : '')); }
  catch (e) { $('#dGroup').innerHTML = `<div class="muted">${esc(e.message)}</div>`; return; }
  if (LIST.rows[LIST.open] !== x) return;
  $('#dGroupHead').textContent = `这部片的全部副本（${g.members.length} 份 · ${g.title}）`;
  const order = ['keep', '版本型', '可切', '待定', 'locked'];
  const ms = [...g.members].sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role) || b.gb - a.gb);
  $('#dGroup').innerHTML = `<table class="grp-table"><tbody>${ms.map(m => {
    const [rn, tone] = ROLE[m.role] || [m.role, ''];
    const me = m.path === x.path || (m.parts || []).includes(x.path);
    return `<tr class="${me ? 'me' : ''}"><td class="role ${tone}">${esc(rn)}${me ? '<br><span class="muted">（这一条）</span>' : ''}</td>
      <td>${esc(ZONE_SHORT[m.zone] || m.zone)} · ${esc(KIND_SHORT[m.kind] || m.kind)} · ${esc(RES_SHORT[m.res] || m.res)}${m.res_src === '体积推断' ? '*' : ''} · <span translate="no">${fmtGB(m.gb)}</span>${m.subfx ? `<div class="muted">认作特效字幕版：${esc(m.subfx)}</div>` : ''}${(m.parts || []).length ? `<div class="muted">多碟装 ${m.parts.length} 张一套，算一份</div>` + m.parts.map(pp => `<div class="mono">${esc(pp)}</div>`).join('') : `<div class="mono">${esc(m.path)}</div>`}</td></tr>`;
  }).join('')}</tbody></table><div class="muted" style="font-size:11.5px;margin-top:6px">先比分辨率，同分辨率再比来源（特效字幕版 > 原盘 > DIY > REMUX > 压制），再比所在区和命名。* = 按体积推断。特效字幕组名单在设置里改。</div>`;
}
function renderDlg() {
  const x = LIST.rows[LIST.open]; if (!x) return;
  $('#dTitle').textContent = stripExt(baseName(x.path));
  $('#dSub').innerHTML = `${badge(x.bucket)} <span class="muted" style="margin-left:6px">${esc(sn(x.stage))} · ${esc(cn(x.stage, x.cls))}</span>`;
  $('#dDropTag').textContent = x.bucket === '可切' ? '待清理' : x.bucket === '缺口' ? '主库缺口' : '这一份';
  $('#dDropFile').textContent = baseName(x.path);
  const li = (k, v) => `<li><span>${k}</span><b>${v}</b></li>`;
  $('#dDropSpecs').innerHTML = li('大小', '<span translate="no">' + fmtGB(x.gb) + '</span>') + li('分区', esc(zoneOfPath(x.path))) + (x.move ? li('搬运方式', x.move === '整夹' ? '整夹搬' : '只搬这个文件') : '') + (x.flag ? li('标记', esc(x.flag)) : '');
  $('#dDropPath').textContent = x.path;
  const keep = x.keep || '';
  $('#dKeepFile').textContent = keep ? (keep.startsWith('/') ? baseName(keep) : keep) : '—';
  $('#dKeepSpecs').innerHTML = keep.startsWith('/') ? li('分区', esc(zoneOfPath(keep))) + (x.keep_gb ? li('大小', '<span translate="no">' + fmtGB(x.keep_gb) + '</span>') : '') : '';
  $('#dKeepPath').textContent = keep.startsWith('/') ? keep : '';
  $('#dReason').textContent = x.basis || '—';
  renderGroup(x);
  const B = LB.buckets[x.bucket] || {};
  $('#dAction').innerHTML = `${esc(B.desc || '')}<br><b>${esc(B.action || '')}</b>`;
  const can = x.bucket === '可切' || x.bucket === '缺口';
  $('#dKeepWrap').hidden = x.bucket !== '待定';
  if (x.bucket === '待定') $('#dKeep').innerHTML = `判断这份就留着？记下后以后重跑不再出现在「${esc(bn('待定'))}」里（设置页可撤销）。<br><button class="btn sm" type="button" style="margin-top:8px" onclick='dKeep(${esc(JSON.stringify(x.path))})'>${ic('check', 'sm')}确认保留，以后不再提醒</button>`;
  $('#dExecWrap').hidden = !(execOn && can);
  if (execOn && can) {
    const ap = APPR.items[x.path], pe = esc(JSON.stringify(x.path));
    let h;
    if (ap) h = `<span class="t-green">已批准 → ${esc(ACT_NAME[ap.action] || '')}</span> <button class="btn sm" type="button" onclick='dUnapprove(${pe})'>撤销批准</button>`;
    else if (x.bucket === '可切') h = `<button class="btn sm primary" type="button" onclick='dApprove(${pe})'>批准：搬到查重区</button>`;
    else if (CFG.tree_model && CFG.staging_on === false) h = '<span class="muted">待入库区的开关关着：留下的片留在原地，不搬</span>';
    else if ((APPR.overlap || []).includes(x.path) && ((EXS || {}).dirs || {}).unique) h = `同时是「唯一副本」，选去处：<button class="btn sm primary" type="button" onclick='dApprove(${pe}, "mainlib")'>挪入${ACT_NAME.mainlib}</button> <button class="btn sm" type="button" onclick='dApprove(${pe}, "unique")'>移到唯一副本目录</button>`;
    else h = `<button class="btn sm primary" type="button" onclick='dApprove(${pe}, "mainlib")'>批准：挪入${ACT_NAME.mainlib}</button>`;
    $('#dExec').innerHTML = h;
  }
  const picked = LIST.sel.has(x.path);
  $('#dToggle').textContent = picked ? '取消勾选' : '勾选';
  $('#dPrev').disabled = LIST.open <= 0; $('#dNext').disabled = LIST.open >= LIST.rows.length - 1;
}
async function keepPaths(paths) {
  const r = await api('api/keeps', P({paths}));
  LIST.sel.forEach(p => { if (paths.includes(p)) LIST.sel.delete(p); });
  LIST.paths = null;
  await Promise.all([loadResult(), loadRows()]);
  return r;
}
async function dKeep(path) {
  try {
    const r = await keepPaths([path]);
    if (!r.added) { toast((r.skipped[0] || {}).reason || '没记下'); return; }
    toast('已记下：以后不再提醒（设置页可撤销）');
    if (!LIST.rows.length) closeDlg();
    else { LIST.open = Math.min(LIST.open, LIST.rows.length - 1); renderDlg(); }
  } catch (e) { toast(e.message); }
}
$('#btnKeepSel').onclick = async () => {
  const k = LIST.sel.size; if (!k) return;
  if (!confirm(`把勾选的 ${n(k)} 条里属于「${bn('待定')}」的记为「已确认保留」？\n以后重跑不再提醒；设置页能看名单、逐条撤销。其他分类的条目不受影响。`)) return;
  try {
    const r = await keepPaths([...LIST.sel]);
    toast(`已确认保留 ${n(r.added)} 条` + (r.skipped.length ? `；${n(r.skipped.length)} 条不是「${bn('待定')}」，没记` : ''));
  } catch (e) { toast(e.message); }
};
async function dApprove(path, dest) { try { const r = await api('api/approvals', J({add: [{path, dest}]})); if (r.errors.length) toast(r.errors[0].reason); await loadAppr(); renderTable(); renderDlg(); } catch (e) { toast(e.message); } }
async function dUnapprove(path) { try { await api('api/approvals', J({remove: [path]})); await loadAppr(); renderTable(); renderDlg(); } catch (e) { toast(e.message); } }
$('#dToggle').onclick = () => togglePick(LIST.open);
$('#dPrev').onclick = () => { if (LIST.open > 0) { LIST.open--; renderDlg(); } };
$('#dNext').onclick = () => { if (LIST.open < LIST.rows.length - 1) { LIST.open++; renderDlg(); } };
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#kOverlay').hidden = false; $('#kInput').value = LIST.q; $('#kInput').focus(); $('#kInput').select(); return; }
  if (e.key === 'Escape') { $('#kOverlay').hidden = true; if (LIST.open != null) closeDlg(); if (OPEN_FACET) { OPEN_FACET = ''; renderFacets(); } }
  if (LIST.open != null && !$('#dlg').hidden) { if (e.key === 'ArrowLeft') $('#dPrev').click(); if (e.key === 'ArrowRight') $('#dNext').click(); }
});
$('#kOverlay').onclick = e => { if (e.target.id === 'kOverlay') $('#kOverlay').hidden = true; };
$('#kInput').onkeydown = e => { if (e.key === 'Enter') { $('#kOverlay').hidden = true; LIST.q = e.target.value.trim(); LIST.page = 0; const p = filterParams(); go('list', p); } };

/* ============================== 执行 ============================== */
/* 开执行还差哪一步：设置页和执行页共用 */
function readyRows(s, withTrial) {
  const kv = (k, v, dot) => `<div class="kv-row"><span class="k">${k}</span>${dot ? `<span class="status-dot dot-${dot}"></span>` : ''}<span class="v">${v}</span></div>`;
  const direct = s.direct || {}, dirs = s.dirs || {};
  let h = kv('执行开关', s.allowed ? '已开' : '没开：docker-compose.yml 里加 PANEL_ALLOW_MOVE=1，重启面板', s.allowed ? 'green' : 'amber');
  if (s.backend === 'cd2') h += kv('执行方式', 'CD2 直连（面板直接跟 CloudDrive 说话搬文件，快）')
    + kv('直连', direct.ok ? `可用 · 令牌「${esc(direct.name || '未命名')}」` : esc(direct.error || '不可用') + '（检查设置页「执行」卡片里的 CD2 接口地址和令牌权限）', direct.ok ? 'green' : 'amber');
  else h += kv('执行方式', s.exec_mode === 'mount' ? '挂载改名（经过系统文件夹改名，慢）' : '挂载改名（没找到 CloudDrive 令牌，兜底；慢）', s.exec_mode === 'mount' ? '' : 'amber')
    + kv('挂载', s.mount_writable ? '可写' : '只读或没挂：compose 里挂载那行 :ro 改成 :rw', s.mount_writable ? 'green' : 'amber');
  const nm = s.dir_names || {quarantine: '查重区', mainlib: '主库目录'};
  h += kv(nm.quarantine, dirs.quarantine ? esc(dirs.quarantine) : '没填（点「改筛查范围」在顶部设）', dirs.quarantine ? 'green' : 'amber');
  if (s.tree_model && s.staging_on === false) h += kv(nm.mainlib, '开关关着：留下的片留在原地，不搬', 'green');
  else h += kv(nm.mainlib, dirs.mainlib ? esc(dirs.mainlib) : '没填（点「改筛查范围」在顶部设）', dirs.mainlib ? 'green' : 'amber');
  if (withTrial) h += kv('试跑', s.trial_ok ? '小批量试跑已对账无误，放开批量' : `第一次只许 ≤${s.trial_max || 10} 条`, s.trial_ok ? 'green' : 'amber');
  return h;
}
let EXSEL = '', PREVIEW = {};
async function renderExecute() {
  await Promise.all([loadExec(), loadAppr()]);
  const s = EXS || {};
  const off = !s.allowed ? '执行未开启。开启方法见 README『执行』一节，设置页可查看当前还差哪一步。'
    : uiLock() ? '这台浏览器开了「界面只读锁定」（设置里关），执行入口已隐藏。' : '';
  $('#exOff').hidden = !off; $('#exOffText').textContent = off;
  if (!s.allowed) return;
  $('#exCarry').innerHTML = carryNote();
  $('#exStatus').innerHTML = readyRows(s, true);
  const dr = s.direct || {}, dd = s.dirs || {};
  const ready = s.allowed && (s.backend === 'cd2' ? dr.ok : s.mount_writable) && dd.quarantine;
  $('#exReadySum').innerHTML = ready ? '<span class="t-green">全部就绪</span>' + (s.trial_ok ? '' : ` · 第一次只许 ≤${s.trial_max || 10} 条`) : '<span class="t-amber">还差几项，展开看</span>';
  $('#exReadyFold').open = !ready;
  const items = APPR.items || {}, byAct = {};
  Object.entries(items).forEach(([p, a]) => (byAct[a.action] = byAct[a.action] || []).push(p));
  try { BATCHES = await api('api/exec/batches'); } catch (e) { BATCHES = []; }
  const acts = ['quarantine', 'mainlib', 'unique'].filter(a => (byAct[a] || []).length || PREVIEW[a]);
  const dirs = s.dirs || {};
  $('#exCards').innerHTML = acts.map(a => {
    const cnt = (byAct[a] || []).length, pv = PREVIEW[a], last = BATCHES.find(b => b.action === a);
    const state = JOB.running && (JOB.mode === 'run') ? '执行中' : pv && pv.count === cnt && cnt ? '已预演' : cnt ? '待预演' : '没有批准';
    return `<section class="card batch-card"><div class="batch-top"><span class="batch-id">去向：${ACT_NAME[a]}</span><span class="tag ${state === '已预演' ? 'ok' : ''}">${state}</span></div>
      <p class="batch-meta">已批准待搬移 <b>${n(cnt)}</b> 项${pv ? ` · 预演 <b>${n(pv.ops.length)}</b> 处 · <b>${fmtGB(pv.gb)}</b>` : ''}</p>
      <div class="batch-target mono">目标：${esc(dirs[a] || '（设置里还没填）')}</div>
      <div class="batch-btns"><button class="btn sm" type="button" data-prev="${a}" ${cnt && execOn ? '' : 'disabled'}>先预演</button>
        <button class="btn sm primary" type="button" data-runb="${a}" ${pv && pv.count === cnt && cnt && pv.ops.length && execOn ? '' : 'disabled'} title="先预演才能执行">执行本批</button>
        ${last && execOn ? `<button class="btn sm" type="button" data-rb="${esc(last.batch_id)}">回滚上一批</button>` : ''}</div>
      ${pv ? previewBox(pv) : ''}</section>`;
  }).join('') || `<section class="card batch-card"><p class="batch-meta">还没有批准任何条目。到清单里一部片一部片看，点「批准这部片」。</p><div class="batch-btns"><a class="btn sm primary" href="#/list">去清单</a></div></section>`;
  $$('#exCards [data-prev]').forEach(b => b.onclick = () => doPreview(b.dataset.prev));
  $$('#exCards [data-runb]').forEach(b => b.onclick = () => doRun(b.dataset.runb));
  $$('#exCards [data-rb]').forEach(b => b.onclick = () => batchAct('rollback', b.dataset.rb));
  if (!EXSEL && BATCHES.length) EXSEL = BATCHES[0].batch_id;
  $('#exLogFold').hidden = BATCHES.length < 2;
  renderBatchLog(); await renderBatch(EXSEL);
}
function previewBox(pv) {
  const folders = pv.ops.filter(o => o.kind === 'folder').length;
  return `<div class="preview-box">预演：<b>${n(pv.ops.length)}</b> 处搬运（整夹 ${n(folders)} · 单文件 ${n(pv.ops.length - folders)}）· <b>${fmtGB(pv.gb)}</b> · 方式 ${pv.backend === 'cd2' ? 'CD2 直连' : '挂载改名'}${pv.refused.length ? ` · <span class="t-amber">拒绝 ${n(pv.refused.length)} 条</span>` : ''}
    ${pv.refused.length ? `<details><summary style="cursor:pointer">看拒绝的原因</summary><ul class="refused-list">${pv.refused.slice(0, 6).map(r => `<li><span class="mono">${esc(baseName(r.path))}</span>：${esc(r.reason)}</li>`).join('')}${pv.refused.length > 6 ? `<li>…还有 ${n(pv.refused.length - 6)} 条</li>` : ''}</ul></details>` : ''}</div>`;
}
async function doPreview(a) {
  const b = $(`#exCards [data-prev="${a}"]`); if (b) { b.disabled = true; b.textContent = '预演中…'; }
  try {
    const p = await api('api/exec/plan?action=' + a, {method: 'POST'});
    p.count = Object.values(APPR.items).filter(x => x.action === a).length;
    PREVIEW[a] = p;
  } catch (e) { toast(e.message); }
  renderExecute();
}
async function doRun(a) {
  const pv = PREVIEW[a]; if (!pv) return;
  const k = pv.ops.length;
  const typed = prompt(`将把 ${k} 处（${fmtGB(pv.gb)}）搬到「${ACT_NAME[a]}」，只改名、不删除；每处先写日志，可回滚。\n\n确认请输入搬运处数 ${k}：`);
  if (typed === null) return;
  if (String(typed).trim() !== String(k)) { toast('输入的数字不对，没有执行'); return; }
  try { await api('api/exec/run?action=' + a, {method: 'POST'}); delete PREVIEW[a]; poll(); } catch (e) { toast(e.message); }
}
const ST_NAME = {done: ['搬成', 'green'], skip: ['跳过', 'zinc'], fail: ['失败', 'red'], unknown: ['结果未知', 'amber'], rolled_back: ['已回滚', 'sky'], intent: ['未完成', 'amber'], pending: ['未执行', 'zinc']};
async function renderBatch(id) {
  const reset = () => { $('#exLast').hidden = true; };
  $('#exLast').hidden = false;
  if (!id) return reset();
  let b; try { b = await api('api/exec/batch/' + encodeURIComponent(id)); } catch (e) { return reset(); }
  const pl = b.plan, rc = b.reconcile, meta = `当前查看批次：${id} · 去向 ${actName(pl.action || [...new Set(pl.ops.map(o => o.action))].join(','))} · ${pl.backend === 'cd2' ? 'CD2 直连' : '挂载改名'} · ${fmtTime(pl.created)}`;
  $('#reconMeta').textContent = meta.replace('当前查看批次：', '');
  $('#detailMeta').textContent = '';
  const running = JOB.running && (JOB.mode === 'run' || JOB.mode === 'rollback');
  const rb = (BATCHES.find(x => x.batch_id === id) || {}).rollback;
  const problem = (rc ? !rc.ok || rc.failed_rows || rc.refused_rows : !running) || !!(rb && rb.problems.length);
  $('#exLastSum').innerHTML = running ? `<b>${esc(JOB_NAME[JOB.mode])}中</b> · ${esc(JOB.msg || '')} · ${JOB.pct || 0}%`
    : rc ? (rc.ok ? `<span class="t-green">对账通过</span> · ${n(rc.rows)} 条，搬成 <b>${n(rc.moved_rows)}</b>${rc.skipped_rows ? ' · 跳过 ' + n(rc.skipped_rows) : ''}${rc.refused_rows ? ` · <span class="t-amber">拒绝 ${n(rc.refused_rows)}</span>` : ''}`
      : `<span class="t-amber">${rc.balanced ? '有失败' : '对账不平'}</span> · 搬成 ${n(rc.moved_rows)} · 失败 ${n(rc.failed_rows)}${rc.refused_rows ? ' · 拒绝 ' + n(rc.refused_rows) : ''}；明细在下面，可在「历史批次」里续跑或回滚`)
    : '<span class="t-amber">没跑完</span>：明细在下面，可在「历史批次」里续跑或回滚';
  if (rb && !running) $('#exLastSum').innerHTML += ` · <b>已回滚 ${n(rb.rolled_back)} 处</b>${rb.problems.length ? ` · <span class="t-amber">${n(rb.problems.length)} 处没回（${esc(rb.problems[0].reason || '')}）</span>` : ''}`;
  $('#exDetailFold').open = !!problem;
  if (rc) {
    $('#rcTotal').textContent = n(rc.rows); $('#rcMoved').textContent = n(rc.moved_rows); $('#rcSkipped').textContent = n(rc.skipped_rows);
    $('#rcFailed').textContent = n(rc.failed_rows); $('#rcRefused').textContent = n(rc.refused_rows);
    $('#reconBadge').className = 'recon-badge ' + (rc.ok ? 'ok' : 'bad'); $('#reconBadge').textContent = rc.ok ? '对账平齐' : rc.balanced ? '有失败' : '对账不平';
    $('#reconNote').innerHTML = rc.ok ? '搬成的逐条实地核对过：源没了、目标在。' : `<span class="recon-mismatch">${esc((rc.failures || []).slice(0, 2).map(f => baseName(f.src) + '：' + f.reason).join('；'))}</span>`;
  } else { $('#reconBadge').className = 'recon-badge wait'; $('#reconBadge').textContent = '未完成'; }
  const st = b.states || {};
  const rows = pl.ops.map(o => {
    const s = st[o.id] || {state: 'pending'}, [nm, tone] = ST_NAME[s.state] || [s.state, 'zinc'];
    return `<tr><td><div class="t-title" title="${esc(o.src)}">${esc(stripExt(baseName(o.src)))}</div></td>
      <td><div class="t-path mono" title="${esc(o.src)}">${esc(o.src)}</div><div class="t-arrow">→</div><div class="t-path mono" title="${esc(o.dst)}">${esc(o.dst)}</div></td>
      <td>${o.kind === 'folder' ? `整夹（${o.videos}）` : '单文件'}</td>
      <td><span class="badge b-${tone}"><i></i>${nm}</span>${s.reason ? `<div class="t-path" title="${esc(s.reason)}">${esc(s.reason)}</div>` : ''}${s.secs != null ? `<div class="t-path">${s.secs}s</div>` : ''}</td></tr>`;
  }).concat(pl.refused.map(r => `<tr><td><div class="t-title">${esc(stripExt(baseName(r.path)))}</div></td><td><div class="t-path mono">${esc(r.path)}</div></td><td>—</td>
      <td><span class="badge b-${r.skip ? 'zinc' : 'amber'}"><i></i>${r.skip ? '跳过' : '拒绝'}</span><div class="t-path" title="${esc(r.reason)}">${esc(r.reason)}</div></td></tr>`));
  $('#exDetail').innerHTML = rows.join('') || '<tr><td colspan="4" class="muted">这个批次没有条目。</td></tr>';
}
function renderBatchLog() {
  if (!BATCHES.length) { $('#batchLog').innerHTML = '<div class="muted" style="padding:10px 4px">还没有批次。</div>'; return; }
  $('#batchLog').innerHTML = BATCHES.map(b => {
    const rc = b.reconcile, rb = b.rollback, id = esc(b.batch_id);
    const stt = rb ? `已回滚 ${n(rb.rolled_back)} 处${rb.problems.length ? ' · 问题 ' + rb.problems.length : ''}` : !rc ? '未完成' : rc.ok ? '对账平齐' : '对账不平';
    return `<div class="blog-row ${b.batch_id === EXSEL ? 'sel' : ''}"><span class="blog-id mono">${id}</span>
      <span class="blog-meta">${fmtTime(b.created)} · 去向 ${esc(actName(b.action))} · ${b.backend === 'cd2' ? '直连' : '挂载'} · 批准 ${n(b.rows)} · ${n(b.ops)} 处 · ${fmtGB(b.gb)}</span>
      <span class="tag ${rc && rc.ok && !rb ? 'ok' : rc && !rc.ok ? 'bad' : ''}">${stt}</span><span class="sp"></span>
      <button class="btn sm" type="button" data-see="${id}">查看</button>
      ${execOn && rc && !rc.ok ? `<button class="btn sm" type="button" data-resume="${id}">续跑</button>${b.backend === 'cd2' ? `<button class="btn sm" type="button" data-resume-mount="${id}">改用挂载续跑</button>` : ''}` : ''}
      ${execOn ? `<button class="btn sm" type="button" data-roll="${id}">回滚</button>` : ''}</div>`;
  }).join('');
  $$('#batchLog [data-see]').forEach(b => b.onclick = () => { EXSEL = b.dataset.see; renderBatchLog(); renderBatch(EXSEL); });
  $$('#batchLog [data-resume]').forEach(b => b.onclick = () => batchAct('resume', b.dataset.resume));
  $$('#batchLog [data-resume-mount]').forEach(b => b.onclick = () => batchAct('resume', b.dataset.resumeMount, 'mount'));
  $$('#batchLog [data-roll]').forEach(b => b.onclick = () => batchAct('rollback', b.dataset.roll));
}
async function batchAct(kind, id, be) {
  if (!id) return;
  const msg = kind === 'rollback' ? `把批次 ${id} 搬走的按日志搬回原位？（体积对不上的不覆盖、报出来）`
    : be === 'mount' ? `改用「挂载改名」续跑批次 ${id}？挂载改名慢（1–2 分钟一部），只适合剩下不多的时候。` : `按日志续跑批次 ${id}？`;
  if (!confirm(msg)) return;
  EXSEL = id;
  try { await api(`api/exec/${kind}/${encodeURIComponent(id)}` + (be ? '?backend=' + be : ''), {method: 'POST'}); poll(); } catch (e) { toast(e.message); }
}

/* ============================== 设置 ============================== */
const SCALARS = ['cd2_mount', 'cd2_config', 'cd2_api_name', 'cd2_api_user', 'emby_data', 'emby_prefix', 'csv_dir', 'min_video_mb', 'exec_mode', 'cd2_api_addr'];
const LISTS = ['subfx_groups'];            // 其余名单（保护 / 榜单包 / 排除词…）不再在界面上改：没勾 = 不筛
const SRC_DESC = {cache: '读 CD2 自己的目录缓存（推荐）：快，不向网盘发请求；结果以缓存时刻为准。', scan: '遍历 CD2 挂载目录（兜底）：慢，每个目录都会经 CD2 向网盘发请求。', csv: '读现成的五张 CSV（对账用）。'};
let SRC = 'cache';
async function renderSettings() {
  await loadExec();
  SCALARS.forEach(k => { const el = $('#c-' + k); if (el) el.value = CFG[k] ?? ''; });
  LISTS.forEach(k => $('#c-' + k).value = (CFG[k] || []).join('\n'));
  $('#setScope').innerHTML = scopeHtml();
  SRC = CFG.data_source; renderSeg();
  const s = EXS || {};
  $('#setExecSwitch').innerHTML = readyRows(s, false);
  $('#swLock').setAttribute('aria-checked', uiLock());
  $('#setSecurity').innerHTML = AUTH ? '<div class="recog"><div class="r-row"><b>已设访问口令</b>（浏览器弹窗用户名随便填）</div></div>'
    : `<div class="alert red" style="margin-top:0">${ic('alert')}<div><b>当前未设访问口令：</b>局域网里谁都能打开。在 .env 里设 PANEL_PASSWORD，然后 docker compose up -d。</div></div>`;
  probeCards(); renderKeeps();
}
async function renderKeeps() {
  let r; try { r = await api('api/keeps'); } catch (e) { $('#keepList').innerHTML = `<div class="keep-empty">${esc(e.message)}</div>`; return; }
  const items = r.items || [];
  $('#keepList').innerHTML = items.length ? items.map(x => `<div class="keep-item"><div class="ki-main"><div class="ki-path mono" title="${esc(x.path)}">${esc(x.path)}</div>
      <div class="ki-meta">${esc(x.at || '')} · ${esc(x.stage_name || '')} · ${esc(x.cls_name || '')} · ${fmtGB(x.gb || 0)}${x.hit ? '' : ' · <span class="t-amber">最新结果里已不在「' + esc(bn('待定')) + '」里（可能已搬走或改判）</span>'}</div></div>
      <button class="btn sm" type="button" data-unkeep="${esc(x.path)}">撤销</button></div>`).join('')
    : '<div class="keep-empty">还没有。在清单里打开一条「需人工确认」，点「确认保留，以后不再提醒」。</div>';
  $$('#keepList [data-unkeep]').forEach(b => b.onclick = async () => {
    try { await api('api/keeps/remove', P({paths: [b.dataset.unkeep]})); toast('已撤销：这条会重新出现在清单里'); LIST.paths = null; await loadResult(); renderKeeps(); } catch (e) { toast(e.message); }
  });
}
function renderSeg() { $$('#segSource button').forEach(b => b.classList.toggle('active', b.dataset.v === SRC)); $('#segDesc').textContent = SRC_DESC[SRC] || ''; }
$$('#segSource button').forEach(b => b.onclick = () => { SRC = b.dataset.v; renderSeg(); });
$('#swLock').onclick = () => { store.set('pc.uilock', uiLock() ? '0' : '1'); $('#swLock').setAttribute('aria-checked', uiLock()); setExecOn(); toast(uiLock() ? '已锁定：这台浏览器隐藏批准与执行入口' : '已解除界面锁定'); };
async function probeCards() {
  $('#setCd2').innerHTML = $('#setEmby').innerHTML = '识别中…';
  try { PROBE = await api('api/probe', {method: 'POST'}); } catch (e) { PROBE = {error: e.message}; }
  const k = (PROBE.cd2 || {}).cache || {}, e = PROBE.emby || {};
  $('#setCd2').innerHTML = k.ok ? `<div class="r-row"><span class="tag ok">已识别</span></div><div class="mono" style="font-size:11.5px;word-break:break-all">${esc(CFG.cd2_config)}</div>缓存 ${fmtTime(k.time_min)} ~ ${fmtTime(k.time_max)} · 网盘文件 <b>${n(k.matched_files)}</b>`
    : `<span class="t-amber">${esc(k.error || PROBE.error || '没连上')}</span>`;
  $('#setEmby').innerHTML = e.ok ? `<div class="r-row"><span class="tag ok">已识别</span></div><div class="mono" style="font-size:11.5px;word-break:break-all">${esc(CFG.emby_data)}</div>电影 <b>${n(e.movies)}</b> 部 · ${esc(e.movie_rule || '')}`
    : `<span class="t-amber">${esc(e.error || '没连上')}：不连也能用，只是少了「对比 Emby」和「主库缺口」</span>`;
}
function readForm() {
  const c = JSON.parse(JSON.stringify(CFG));
  SCALARS.forEach(k => { const el = $('#c-' + k); if (el) c[k] = el.value.trim(); });
  c.min_video_mb = parseInt(c.min_video_mb || '0', 10);
  LISTS.forEach(k => c[k] = $('#c-' + k).value.split('\n').map(s => s.trim()).filter(Boolean));
  c.data_source = SRC;
  return c;
}
async function saveSettings(probe) {
  try { await putCfg(readForm(), false); $('#saveMsg').textContent = '已保存'; toast('已保存'); await loadExec(); if (probe) probeCards(); }
  catch (e) { $('#saveMsg').innerHTML = `<span class="t-amber">${esc(e.message)}</span>`; toast(e.message); }
}
$('#btnSave').onclick = () => saveSettings(false);
$('#btnSaveProbe').onclick = () => saveSettings(true);
document.addEventListener('click', e => { const b = e.target.closest('[data-wizard]'); if (b) { WZ = {step: +b.dataset.wizard, mode: 'edit'}; go('wizard'); } });

/* ============================== 首次设置向导 ============================== */
let WZ = {step: 0};
const WZ_STEPS = ['连 CD2', '连 Emby', '确认筛查范围'];
function renderWizard() {
  if (!WZ.step) WZ = {step: 1, mode: 'first'};
  const st = WZ.step;
  $('#wzTitle').textContent = WZ.mode === 'edit' ? (st === 1 ? '更换 CD2 配置目录' : st === 2 ? '更换 Emby 数据目录' : '改筛查范围') : '首次设置';
  $('#wzLead').hidden = WZ.mode === 'edit';
  $('#wzTitle').insertAdjacentHTML('beforeend', verText() ? ` <span class="wz-ver">${esc(verText())}</span>` : '');
  $('#wzSteps').innerHTML = WZ.mode === 'edit' ? '' : WZ_STEPS.map((t, i) => `<span class="${i + 1 === st ? 'on' : i + 1 < st ? 'done' : ''}">${i + 1 < st ? '✓ ' : (i + 1) + ' · '}${t}</span>`).join('');
  const b = $('#wzBody');
  if (st === 1) b.innerHTML = `<h2>${ic('db')}连 CD2</h2><p class="sec-sub">只填 CD2 的配置目录（装 CD2 时指定的数据目录）。Docker 部署时就是 compose 里挂进来的 /cd2-config，一般不用改。</p>
      <div class="wz-in"><input type="text" id="wzPath" class="mono" value="${esc(CFG.cd2_config)}" placeholder="/cd2-config"><button class="btn" type="button" id="wzCheck">识别</button></div><div id="wzRes"></div><div class="sec-foot" id="wzNav"></div>`;
  else if (st === 2) b.innerHTML = `<h2>${ic('db')}连 Emby</h2><p class="sec-sub">只填 Emby 的数据目录（Emby 后台「关于」页能看到原样路径）。Docker 部署时就是 compose 里挂进来的 /emby-data。</p>
      <div class="wz-in"><input type="text" id="wzPath" class="mono" value="${esc(CFG.emby_data)}" placeholder="/emby-data"><button class="btn" type="button" id="wzCheck">识别</button></div><div id="wzRes"></div><div class="sec-foot" id="wzNav"></div>`;
  else b.innerHTML = `<h2>${ic('folder')}确认筛查范围</h2><p class="sec-sub">上面定三个位置，下面勾要筛查的目录。都按名字预选好了，扫一眼没问题就点完成。</p><div id="wzRes" class="muted">读取目录…</div><div class="sec-foot" id="wzNav"></div>`;
  const c = $('#wzCheck'); if (c) c.onclick = wzCheck;
  wzCheck();
}
async function wzCheck() {
  const st = WZ.step, res = $('#wzRes'), nav = $('#wzNav');
  const back = st > 1 && WZ.mode !== 'edit' ? '<button class="btn" type="button" id="wzBack">上一步</button>' : '';
  const cancel = WZ.mode === 'edit' ? '<button class="btn" type="button" id="wzCancel">取消</button>' : '';
  const bind = () => { const a = $('#wzBack'); if (a) a.onclick = () => { WZ.step--; renderWizard(); }; const x = $('#wzCancel'); if (x) x.onclick = () => { WZ = {step: 0}; go('settings'); }; };
  if (st < 3 && !$('#wzPath').value.trim()) { res.innerHTML = '<p class="muted">填好目录后点「识别」。</p>'; nav.innerHTML = back + cancel; bind(); return; }
  res.innerHTML = '<p class="muted">识别中…</p>'; nav.innerHTML = back + cancel; bind();
  let r;
  try {
    if (st === 1) r = await api('api/setup/cd2', P({cd2_config: $('#wzPath').value.trim(), cd2_api_name: WZ.api}));
    else if (st === 2) r = await api('api/setup/emby', P({emby_data: $('#wzPath').value.trim()}));
    else r = await api('api/setup/zones', {method: 'POST'});
  } catch (e) { r = {ok: false, error: '识别时出错了。', hint: '刷新页面再试；一直这样就看容器日志。'}; }
  WZ.r = r;
  const nextLbl = WZ.mode === 'edit' ? '保存' : st === 3 ? '完成，去扫描' : '下一步';
  if (!r.ok) {
    res.innerHTML = `<div class="err-box"><b>${esc(r.error)}</b>${r.hint ? '<br>' + esc(r.hint) : ''}</div>`;
    nav.innerHTML = back + cancel + (st === 2 ? '<button class="btn" type="button" id="wzSkip">暂不连 Emby</button><span class="hint">不连也能用，只是少了「对比 Emby」和「主库缺口」</span>' : '');
    bind(); const s = $('#wzSkip'); if (s) s.onclick = () => { WZ.step = 3; renderWizard(); };
    return;
  }
  const kv = (k, v) => `<div class="kv-row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  let h = '';
  if (st === 1) {
    WZ.api = r.api_name;
    h = `<div class="kv">${kv('目录缓存', '<span class="t-green">找到</span> <span class="mono" style="font-size:11px">' + esc(r.db) + '</span>')}${kv('缓存时间', fmtTime(r.time_min) + ' ~ ' + fmtTime(r.time_max))}${kv('网盘文件', n(r.files) + ' 个')}</div>`;
    if (r.need_choice) h += `<div class="opt-box">缓存里有好几个网盘，选影视所在的那个：${r.api_names.map(a => `<label class="path-row"><input type="radio" name="wzApi" value="${esc(a.api_name)}" ${a.api_name === r.api_name ? 'checked' : ''}>${esc(a.api_name)}（${n(a.files)} 个文件）</label>`).join('')}</div>`;
    h += `<div class="chipset">${(r.top_dirs.length ? r.top_dirs : r.tops).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div><p class="muted" style="font-size:12.5px">和你在 CD2 里看到的对得上，就点下一步。</p>`;
  } else if (st === 2) {
    const pf = r.prefix || {};
    if (WZ.prefix === undefined || WZ.prefixFor !== pf.prefix) { WZ.prefix = pf.ok ? pf.prefix : null; WZ.prefixFor = pf.prefix; }
    h = `<div class="kv">${kv('片库', '<span class="t-green">找到</span> <span class="mono" style="font-size:11px">' + esc(r.db) + '</span>')}${kv('电影', n(r.movies) + ' 部（带 TMDB ' + n(r.movies_tmdb) + '）')}`
      + (pf.ok ? kv('路径抽查', `抽查 ${n(pf.checked)} 部，<b class="t-green">${n(pf.hits)}</b> 部对得上（${Math.round(pf.hits / Math.max(1, pf.checked) * 100)}%）`) : '') + '</div>';
    if (pf.ok) {
      const ex = pf.example || (pf.sample || [])[0] || '';
      const rest = ex.startsWith(pf.prefix) ? ex.slice(pf.prefix.length) : ex;
      h += `<div class="pf-card"><div class="pf-label">Emby 路径前缀</div><div class="pf-main mono">${esc(pf.prefix || '（无）')}</div>
        <div class="pf-sample mono" title="${esc(ex)}"><b>${esc(pf.prefix)}</b><span>${esc(shortPath(rest))}</span></div></div>
        <p class="muted" style="font-size:12.5px;margin:8px 0 0">去掉这段前缀，就是网盘里的路径；对不上的多半是网盘外的片。</p>
        <div class="choice-cards" role="radiogroup" aria-label="前缀对不对">
          <button type="button" class="choice-card${WZ.prefix != null ? ' on' : ''}" role="radio" aria-checked="${WZ.prefix != null}" data-pf="1"><b>对，用这个</b><span>按路径给原盘配实测分辨率</span></button>
          <button type="button" class="choice-card${WZ.prefix == null ? ' on' : ''}" role="radio" aria-checked="${WZ.prefix == null}" data-pf="0"><b>不对，先不管</b><span>之后在高级设置里再填</span></button>
        </div>`;
    } else {
      const ex = (pf.sample || [])[0] || '';
      h += `<div class="warn-box"><b>Emby 路径对不上网盘目录，像是 strm 镜像库。</b><div class="pf-sample mono" title="${esc(ex)}" style="color:inherit">${esc(shortPath(ex))}</div>这一项不用设：原盘的实测分辨率改按 TMDB 编号配对。</div>`;
    }
    h += '<p class="muted" style="font-size:12.5px">电影数和 Emby 后台对得上，就点下一步。</p>';
  } else {
    const keep = WZ.refresh && WZ.places; WZ.refresh = false;
    if (!keep) { WZ.nodes = {}; WZ.byPath = {}; }
    wzInit3(r, keep);
    h = '<div class="wz-sec" style="margin-top:4px"><h3>三个位置（设一次）</h3><div id="wzPlaces"></div></div>'
      + '<div class="wz-sec"><h3>勾选要筛查的目录</h3><p>勾上的参与筛查；勾父目录整枝生效，枝里不想筛的单独取消。没勾 = 不筛（系列合集、出品公司、榜单包这类已帮你预先取消）。灰字只是提示，不挡勾选。</p><div class="ztree tree23" id="wzTree"></div></div>';
  }
  res.innerHTML = h;
  if (st === 3) wzRender();
  $$('[name="wzApi"]').forEach(i => i.onchange = () => { WZ.api = i.value; wzCheck(); });
  $$('#wzRes [data-pf]').forEach(b => b.onclick = () => {
    WZ.prefix = b.dataset.pf === '1' ? WZ.r.prefix.prefix : null;
    $$('#wzRes [data-pf]').forEach(x => { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-checked', on); });
  });
  nav.innerHTML = back + cancel + (st === 3 ? '<button class="btn" type="button" id="wzRefresh">刷新</button>' : '')
    + `<button class="btn primary" type="button" id="wzNext">${nextLbl}</button>` + (st === 3 ? '<span class="hint" id="wzNavHint"></span>' : '');
  bind(); $('#wzNext').onclick = wzNext;
  const rf = $('#wzRefresh'); if (rf) rf.onclick = () => { WZ.refresh = true; wzCheck(); };
  if (st === 3) wzNavHint();
}
/* 路径一行放下：中间目录省略、长文件名中间截断 */
function shortPath(p) {
  const segs = (p || '').split('/').filter(Boolean);
  if (!segs.length) return p || '';
  let name = segs[segs.length - 1];
  if (name.length > 34) name = name.slice(0, 22) + '…' + name.slice(-8);
  return '/' + (segs.length > 3 ? [segs[0], segs[1], '…', name] : [...segs.slice(0, -1), name]).join('/');
}
const ZDESC = {yuanpan: '高画质参照库，同档时优先留这里的', heji: '散放的合集，同一部片有更好的就可清理', remux: 'REMUX 单元，和其他区的副本一起比', pack: '整夹存放的合集（如 10-合集），按单元一起比'};
const ZORDER = ['yuanpan', 'heji', 'remux', 'pack'];
/* ===== 第 3 步「确认筛查范围」（反馈 23）：顶部三个位置 + 下面一棵只管勾选的目录树 =====
   勾上的目录参与筛查（分区类型由面板按名字自动定，界面上不出现）；勾了父目录整枝生效，枝里不想筛的单独取消。
   没勾 = 不筛：保护目录、榜单包都不再单独设。置灰只是提示，不挡勾选；查重区本身不能勾（它不进扫描）。 */
const PLACES = [['mainlib', '主媒体库', '最终收藏所在；同档时最优先留这里的'],
  ['quarantine', '查重区', '筛出的重复份搬到这里，等你过目再删；它和下面都不扫'],
  ['staging', '待入库区', '排重后留下、主库还没有的片挪到这里，等你放进主媒体库']];
const PLACE_LBL = Object.fromEntries(PLACES.map(([k, t]) => [k, t]));
function wzInit3(r, keep) {
  WZ.r = r;
  (WZ.byPath = WZ.byPath || {}); WZ.nodes = WZ.nodes || {};
  Object.entries(r.nodes || {}).forEach(([p, nd]) => { WZ.nodes[p] = nd; nd.dirs.forEach(e => { WZ.byPath[e.path] = e; }); });
  if (keep) return;
  WZ.places = Object.assign({mainlib: '', quarantine: '', staging: ''}, r.places || {});
  WZ.guessed = new Set(r.guessed || []);
  WZ.stagingOn = r.staging_on !== false;
  WZ.inc = new Set(r.include || []);
  WZ.skip = new Map((r.skip || []).map(s => [s.path, s.why || '']));
  WZ.auto = Object.assign({}, r.auto || {});
  WZ.more = null;
  WZ.open = new Set(Object.keys(r.nodes || {}).filter(p => p !== '/'));
}
const under = (p, d) => !!d && (p === d || p.startsWith(d + '/'));
/* 一个目录现在算不算勾上：从自己往上找最近的「勾」或「不勾」标记 */
function wzOn(p) {
  if (under(p, WZ.places.quarantine)) return false;
  let q = p;
  while (q) {
    if (WZ.skip.has(q)) return false;
    if (WZ.inc.has(q)) return true;
    q = q.slice(0, q.lastIndexOf('/'));
  }
  return false;
}
const strictlyUnder = (p, d) => p.startsWith(d + '/');
function wzToggle(p) {
  const drop = set => { for (const x of [...(set.keys ? set.keys() : set)]) if (strictlyUnder(x, p)) set.delete(x); };
  if (wzOn(p)) {
    if (WZ.inc.has(p)) WZ.inc.delete(p); else WZ.skip.set(p, '');
    drop(WZ.inc); drop(WZ.skip);
    if (wzOn(p)) WZ.skip.set(p, '');
  } else {
    if (WZ.skip.has(p)) WZ.skip.delete(p);
    if (!wzOn(p)) { WZ.inc.add(p); drop(WZ.inc); }
    const e = WZ.byPath[p]; if (e) WZ.auto[p] = e.auto;
  }
  wzRender();
}
function wzSetPlace(k, p) {
  for (const x in WZ.places) if (WZ.places[x] === p) WZ.places[x] = '';
  WZ.places[k] = p; WZ.guessed.delete(k);
  if (k === 'quarantine') {                        // 查重区和下面不进扫描：勾也去掉
    for (const x of [...WZ.inc]) if (under(x, p)) WZ.inc.delete(x);
    for (const x of [...WZ.skip.keys()]) if (under(x, p)) WZ.skip.delete(x);
  }
  WZ.more = null; wzRender();
}
async function wzExpand(p) {
  if (WZ.open.has(p)) { WZ.open.delete(p); wzRender(); return; }
  WZ.open.add(p);
  if (!WZ.nodes[p]) {
    try {
      const nd = await api('api/setup/children', P({path: p}));
      WZ.nodes[p] = nd; nd.dirs.forEach(e => { WZ.byPath[e.path] = e; });
    } catch (e) { toast(e.message); WZ.open.delete(p); }
  }
  wzRender();
}
function wzRender() { renderWzPlaces(); renderWzTree(); wzNavHint(); }
function renderWzPlaces() {
  const el = $('#wzPlaces'); if (!el) return;
  let h = '<div class="place-grid">' + PLACES.map(([k, t, d]) => {
    const v = WZ.places[k];
    return `<div class="place${v ? '' : ' empty'}"><div class="place-head"><b>${t}</b>${WZ.guessed.has(k) ? '<span class="ztag">按名字猜的</span>' : ''}</div>
      <div class="place-path mono" title="${esc(v)}">${v ? esc(v) : '未指定'}</div><div class="zmeta">${d}</div>
      ${k === 'staging' ? `<div class="choice-cards slim" role="radiogroup" aria-label="待入库区开关">
        <button type="button" class="choice-card${WZ.stagingOn ? ' on' : ''}" role="radio" aria-checked="${WZ.stagingOn}" data-son="1"><b>开</b><span>留下的统一挪进来</span></button>
        <button type="button" class="choice-card${WZ.stagingOn ? '' : ' on'}" role="radio" aria-checked="${!WZ.stagingOn}" data-son="0"><b>关</b><span>留在原地，不搬</span></button></div>` : ''}
      ${v ? `<button type="button" class="zmove" data-unplace="${k}">清除</button>` : ''}</div>`;
  }).join('') + '</div><p class="muted" style="font-size:12px;margin:6px 0 0">要换位置：在下面目录树里点那一行的「⋯」。</p>';
  if (!WZ.places.quarantine) h += '<div class="warn-box">还没指定查重区：可清理的没地方搬；它要是在勾上的目录里，第一次扫描还会把待删的那份扫进来。</div>';
  const lg = (WZ.r.legacy || {}).protect_names || [];
  if (lg.length) h += `<p class="muted" style="font-size:12px;margin:8px 0 0">原来按名字设的保护（${lg.map(esc).join('、')}）和榜单包，换成了下面具体目录的「没勾」；点完成后按名字的保护不再单独生效。</p>`;
  el.innerHTML = h;
  $$('#wzPlaces [data-unplace]').forEach(b => b.onclick = () => { WZ.places[b.dataset.unplace] = ''; WZ.guessed.delete(b.dataset.unplace); wzRender(); });
  $$('#wzPlaces [data-son]').forEach(b => b.onclick = () => { WZ.stagingOn = b.dataset.son === '1'; wzRender(); });
}
function renderWzTree() {
  const el = $('#wzTree'); if (!el) return;
  const placeOf = p => Object.keys(WZ.places).filter(k => WZ.places[k] === p);
  const count = (set, p) => [...(set.keys ? set.keys() : set)].filter(x => strictlyUnder(x, p)).length;
  const row = (e, depth) => {
    const p = e.path, on = wzOn(p), qz = under(p, WZ.places.quarantine), open = WZ.open.has(p);
    const pls = placeOf(p), skipWhy = WZ.skip.get(p);
    let meta = [];
    if (e.units != null && !e.off) meta.push('约 ' + n(e.units) + ' 部片');
    if (qz) meta.push(WZ.places.quarantine === p ? '查重区：它和下面都不扫' : '在查重区里，不扫');
    else {
      if (on && count(WZ.skip, p)) meta.push(`下面 ${n(count(WZ.skip, p))} 处没勾`);
      if (!on && count(WZ.inc, p)) meta.push(`下面勾了 ${n(count(WZ.inc, p))} 处`);
      if (skipWhy) meta.push('预选没勾：' + skipWhy);
    }
    const why = e.off && !qz ? `<div class="zwhy">${e.off === 'few' && e.units ? '约 ' + n(e.units) + ' 部片 · ' : ''}${esc(e.why)}</div>` : '';
    const tog = e.kids ? `<button type="button" class="ttog" data-ztog="${esc(p)}" aria-expanded="${open}" aria-label="${open ? '收起' : '展开'}">${open ? '▾' : '▸'}</button>` : '<span class="ttog"></span>';
    const acts = WZ.more === p ? `<div class="tacts">${PLACES.map(([k, t]) => `<button type="button" data-place="${k}" data-p="${esc(p)}">设为${t}</button>`).join('')}</div>` : '';
    const cls = (e.off ? ' off' + (e.off === 'unknown' ? ' unknown' : '') : '') + (on ? ' chk' : '');
    let h = `<div class="tnode${cls}" style="padding-left:${8 + depth * 18}px">${tog}
      <input type="checkbox" class="tchk" data-chk="${esc(p)}" ${on ? 'checked' : ''} ${qz ? 'disabled' : ''} aria-label="筛查 ${esc(e.name)}">
      <div class="zmain"><div class="tname" title="${esc(p)}">${ic('folder', 'sm')}${esc(e.name)}${pls.map(k => `<span class="ztag">${PLACE_LBL[k]}</span>`).join('')}</div>
      ${meta.length ? `<div class="zmeta">${meta.map(esc).join(' · ')}</div>` : ''}${why}${acts}</div>
      <button type="button" class="tmore" data-tmore="${esc(p)}" aria-expanded="${WZ.more === p}" title="设为主媒体库 / 查重区 / 待入库区">⋯</button></div>`;
    if (open) {
      const nd = WZ.nodes[p];
      if (!nd) h += `<div class="zempty" style="padding-left:${30 + depth * 18}px">读取中…</div>`;
      else {
        h += nd.dirs.map(c => row(c, depth + 1)).join('');
        if (nd.more) h += `<div class="zempty" style="padding-left:${30 + depth * 18}px">还有 ${n(nd.more)} 个目录没列出</div>`;
      }
    }
    return h;
  };
  // 网盘根（/115）下面才是用户的目录；网盘根自己不给勾
  const roots = (WZ.nodes['/'] || {dirs: []}).dirs;
  let h = '';
  roots.forEach(t => { const nd = WZ.nodes[t.path]; h += nd ? nd.dirs.map(e => row(e, 0)).join('') : row(t, 0); });
  el.innerHTML = h || '<div class="zempty">缓存里没有网盘目录。</div>';
  $$('#wzTree [data-chk]').forEach(i => i.onchange = () => wzToggle(i.dataset.chk));
  $$('#wzTree [data-ztog]').forEach(b => b.onclick = () => wzExpand(b.dataset.ztog));
  $$('#wzTree [data-tmore]').forEach(b => b.onclick = () => { WZ.more = WZ.more === b.dataset.tmore ? null : b.dataset.tmore; renderWzTree(); });
  $$('#wzTree [data-place]').forEach(b => b.onclick = () => wzSetPlace(b.dataset.place, b.dataset.p));
}
/* 存的时候：skip 只留落在某个勾上的根下面的；查重区和下面的勾去掉 */
function wzScope() {
  const q = WZ.places.quarantine;
  const inc = [...WZ.inc].filter(p => !under(p, q));
  const skip = [...WZ.skip.keys()].filter(p => !under(p, q) && inc.some(r => strictlyUnder(p, r)));
  return {inc, skip};
}
function wzNavHint() {
  const b = $('#wzNext'); if (!b || WZ.step !== 3 || !WZ.places) return;
  const {inc, skip} = wzScope();
  const miss = PLACES.filter(([k]) => !WZ.places[k] && !(k === 'staging' && !WZ.stagingOn)).map(([, t]) => t);
  b.textContent = `${WZ.mode === 'edit' ? '保存' : '完成'}：筛查 ${inc.length} 个目录、排除 ${skip.length} 处、${miss.length ? '还差' + miss.join('、') : '三位置已定'}${WZ.mode === 'edit' ? '' : ' → 去扫描'}`;
  b.disabled = !inc.length;
  const el = $('#wzNavHint'); if (el) el.innerHTML = inc.length ? '' : '<span class="t-amber">至少勾一个目录</span>';
}
async function wzNext() {
  const st = WZ.step, c = JSON.parse(JSON.stringify(CFG));
  try {
    if (st === 1) { c.cd2_config = $('#wzPath').value.trim(); c.cd2_api_name = WZ.api || c.cd2_api_name; c.cd2_api_user = ''; }
    if (st === 2) { c.emby_data = $('#wzPath').value.trim(); if (WZ.prefix != null) c.emby_prefix = WZ.prefix; WZ.prefix = undefined; }
    if (st === 3) {
      // 反馈 23：勾上的目录 = 筛查范围（分区类型按名字自动定）；根下面没勾的记 skip_dirs；保护名 / 榜单包换成「没勾」
      const {inc, skip} = wzScope();
      const z = {heji: [], yuanpan: [], remux: [], pack: []};
      inc.forEach(p => z[WZ.auto[p] || (WZ.byPath[p] || {}).auto || 'heji'].push(p));
      c.zones = z; c.skip_dirs = skip; c.tree_model = true; c.confirm_tree_model = true;
      c.protect_names = []; c.listpack_names = []; c.listpack_off = [];
      c.main_lib_dir = WZ.places.mainlib; c.quarantine_dir = WZ.places.quarantine; c.staging_dir = WZ.places.staging;
      c.staging_on = WZ.stagingOn;
      c.setup_done = true;
    }
    await putCfg(c, false);
  } catch (e) { $('#wzRes').insertAdjacentHTML('afterbegin', `<div class="err-box">保存没成功：${esc(e.message)}</div>`); return; }
  if (WZ.mode === 'edit') { const back = st === 3 ? 'overview' : 'settings'; WZ = {step: 0}; go(back); return; }
  if (st < 3) { WZ.step++; renderWizard(); return; }
  WZ = {step: 0};
  go('overview'); runJob('full');
}

/* ---------- 启动 ---------- */
(async () => {
  hydrate();
  try { LB = await api('api/labels'); } catch (e) {}
  await loadCfg(); checkVersion();
  await Promise.all([loadExec(), loadAppr()]);
  if (!location.hash) location.replace('#/overview');
  await route();
  JOB = await api('api/job'); renderJobBar(); if (JOB.running) poll();
})();
