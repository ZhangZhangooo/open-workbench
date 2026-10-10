/* 工作台内核：模块注册、侧边栏、命令面板、主题、快捷键、状态轮询 */

const $ = (s) => document.querySelector(s);
const stage = $('#stage');

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const fmtSize = (b) => {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(0) + ' KB';
  if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
  return (b / 1073741824).toFixed(2) + ' GB';
};

const fmtTime = (t) => {
  const d = new Date(t * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const day = () => new Date().toISOString().slice(0, 10);

async function api(path, opts) {
  const CS = window.CloudSync;
  if (CS && CS.active() && !CS.ready()) return { rows: [], _gated: true }; // 登录门前安全降级
  if (CS && CS.canServe(path)) {
    try { return await CS.serveApi(path); } catch (e) { console.error('[cloud api]', path, e); return { rows: [], _cloudErr: e.message }; }
  }
  if (CS && CS.active() && !CS.canServe(path)) { const lo = CS.localOnlyApi(path); if (lo) return lo; }
  const r = await fetch(path, opts);
  if (r.status === 401) {
    // 局域网访问口令失效 / 这台设备没解锁：明说，别让界面装作没事继续转圈
    if (!window.__wbNoKey) {
      window.__wbNoKey = 1;
      toast('访问口令失效了 —— 用带 ?k= 的链接重新打开一次');
    }
    return { rows: [], ok: false, unauthorized: true };
  }
  return r.json();
}

async function post(path, obj) {
  const CS = window.CloudSync;
  if (CS && CS.active() && !CS.ready()) return { ok: false, _gated: true };
  if (CS && CS.canServe(path)) {
    try { return await CS.servePost(path, obj || {}); } catch (e) { console.error('[cloud post]', path, e); return { ok: false, _cloudErr: e.message }; }
  }
  if (CS && CS.active() && !CS.canServe(path)) { const lo = await CS.localOnlyPost(path, obj); return lo; }
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(obj || {}),
  });
}

function toast(msg) {
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = msg;
  $('#toasts').appendChild(d);
  setTimeout(() => d.remove(), 2200);
}

/* ---------- 侧栏控制台尾流 ---------- */

const logLines = [];

function renderConsole() {
  const box = document.getElementById('consoleLines');
  if (!box) return;
  box.innerHTML = logLines.slice(-8).map((l) =>
    `<div class="line ${l.k || ''}"><span class="t">${l.t}</span> <span class="p">${esc(l.p)}</span> ${esc(l.m)}</div>`
  ).join('');
}

function log(kind, prefix, msg) {
  const t = new Date().toTimeString().slice(0, 5);
  logLines.push({ k: kind, p: prefix, m: msg, t });
  if (logLines.length > 60) logLines.shift();
  renderConsole();
}

/* ---------- 顶栏状态条 ---------- */

function fmtDur(sec) {
  sec = Math.max(0, sec | 0);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (x) => String(x).padStart(2, '0');
  return `${p(h)}:${p(m)}:${p(s)}`;
}

function tickClock() {
  const n = new Date();
  const p = (x) => String(x).padStart(2, '0');
  const c = document.getElementById('mClock');
  if (c) c.textContent = `${p(n.getHours())}:${p(n.getMinutes())}:${p(n.getSeconds())}`;
  const hc = document.getElementById('heroClock');
  if (hc) hc.textContent = `${p(n.getHours())}:${p(n.getMinutes())}:${p(n.getSeconds())}`;
}

async function refreshSys() {
  try {
    const s = await api('/api/sysinfo');
    const up = document.getElementById('mUptime');
    if (up) up.textContent = fmtDur(s.uptime || 0);
    const cpu = s.cpu || 0;
    const cb = document.getElementById('mCpu');
    const cbar = document.getElementById('mCpuBar');
    if (cb) cb.style.width = cpu + '%';
    if (cbar) cbar.className = 'mbar' + (cpu >= 85 ? ' err' : cpu >= 60 ? ' warn' : '');
    const mem = s.mem || {};
    const mEl = document.getElementById('mMem');
    if (mEl) mEl.textContent = mem.pct != null ? mem.pct + '%' : '--';
    const dk = (s.disks || [])[0];
    const dEl = document.getElementById('mDisk');
    if (dEl) dEl.textContent = dk && dk.total ? Math.round((dk.used / dk.total) * 100) + '%' : '--';
    // 客厅 hero 同步
    const hU = document.getElementById('hUptime');
    if (hU) hU.textContent = '运行 ' + fmtDur(s.uptime || 0);
    const hCpu = document.getElementById('heroCpu');
    if (hCpu) hCpu.textContent = (cpu || 0) + '%';
    const hMem = document.getElementById('heroMem');
    if (hMem) hMem.textContent = (mem.pct != null ? mem.pct : 0) + '%';
  } catch (e) {
    log('err', 'sys', 'sysinfo 拉取失败');
  }
}

let lastStatus = null;

window.WB = {
  api, post, toast, esc, fmtSize, fmtTime, day, log,
  go: (id, arg) => go(id, arg),
  status: () => lastStatus,
  refresh: () => refreshStatus(),
  recentLogs: () => logLines.slice(-14),
  requestNotify,
  applyModuleCfg: (cfg) => applyModuleCfg(cfg),
  readModuleCfg: () => JSON.parse(JSON.stringify(moduleCfg)),
  // i18n 切换语言后调它：侧栏 / 底栏 / 顶栏标题都是 JS 现拼的，
  // innerHTML 重建出来的是硬编码中文，得重新走一遍 apply 才译得到。
  rerender: () => {
    renderSide();
    renderMobar();
    const m = MODULES.find((x) => x.id === currentId);
    if (m) $('#topTitle').textContent = modLabel(m);
  },
  // 手机底栏那 4 个位子也让设置页能改（存 kv mobileTabs）
  readMobileTabs: () => mobileTabs.slice(),
  setMobileTabs: (arr) => {
    const ok = (Array.isArray(arr) ? arr : []).filter((id) => MODULES.some((m) => m.id === id));
    if (!ok.length) return false;
    mobileTabs = ok;
    renderMobar();
    post('/api/kv/set', { k: 'mobileTabs', v: JSON.stringify(ok) });
    return true;
  },
};

// 注：AI（问一问）和文档页都不再单独占模块位，它们是 OpenClaw 页下的子标签，
// 由 mod-claw.js 自己动态 import。别把它们加回 MODULES。
const [mHome, mTasks, mFiles, mClaw, mSkills, mCal, mMail, mProjects, mNotes, mKb, mSystem, mSettings, mLife, mRoom, mMeet,
  mPomo, mHabits, mClip, mReminders, mDaylog, mTools, mSystools, mFeatures, mTransfer, mPrinter] =
  await Promise.all([
    import('./mod-home.js'),
    import('./mod-tasks.js'),
    import('./mod-files.js'),
    import('./mod-claw.js'),
    import('./mod-skills.js'),
    import('./mod-cal.js'),
    import('./mod-mail.js'),
    import('./mod-projects.js'),
    import('./mod-notes.js'),
    import('./mod-kb.js'),
    import('./mod-system.js'),
    import('./mod-settings.js'),
    import('./mod-life.js'),
    import('./mod-room.js'),
    import('./mod-meet.js'),
    import('./mod-pomo.js'),
    import('./mod-habits.js'),
    import('./mod-clip.js'),
    import('./mod-reminders.js'),
    import('./mod-daylog.js'),
    import('./mod-tools.js'),
    import('./mod-systools.js'),
    import('./mod-features.js'),
    import('./mod-transfer.js'),
    import('./mod-printer.js'),
  ]);

const MODULES = [
  mClaw.default, mHome.default, mTasks.default, mFiles.default, mSkills.default, mCal.default, mMeet.default,
  mMail.default, mProjects.default, mNotes.default, mKb.default, mSystem.default,
  mSettings.default, mLife.default, mRoom.default,
  mPomo.default, mHabits.default, mClip.default, mReminders.default, mDaylog.default, mTools.default,
  mSystools.default,
  mFeatures.default,
  mTransfer.default,
  mPrinter.default,
];

window.WB.modules = MODULES;

/* ---------- 模块装配 ---------- */

const built = new Map();
let currentId = null;

function build(m) {
  if (built.has(m.id)) return;
  const el = document.createElement('div');
  el.className = 'mod';
  stage.appendChild(el);
  try {
    m.mount(el);
    built.set(m.id, { el, mod: m });
    log('ok', 'mount', m.id + ' ready');
  } catch (e) {
    console.error('[build] 模块挂载失败:', m.id, e);
    log('err', 'mount', m.id + ' 失败: ' + e.message);
    el.innerHTML = `<div class="panel"><h3>${esc(m.name || m.id)}</h3>`
      + `<div class="note" style="color:var(--err,#c0392b)">这个模块加载出错：${esc(e.message)}</div>`
      + `<div class="note">数据没丢，刷新或重进这个模块通常就好。</div></div>`;
    built.set(m.id, { el, mod: m, broken: true });
  }
}

/* arg 会原样交给目标模块的 onShow —— 用来跨模块带东西，
   比如 go('projects', 3) 选中 3 号项目，
   go('claw', {file:'C:\\a.py'}) 带文件去问一问，go('claw', {tab:'docs'}) 直达文档标签 */
function go(id, arg) {
  const m = MODULES.find((x) => x.id === id);
  if (!m) return;
  if (!built.has(id)) build(m);
  built.forEach((v, k) => v.el.classList.toggle('on', k === id));
  currentId = id;
  $('#topTitle').textContent = modLabel(m);
  window.__cur = id;
  document.querySelectorAll('.side-btn').forEach((b) => b.classList.toggle('on', b.dataset.id === id));
  paintMobar();
  closeNav();
  const e = built.get(id);
  if (e && e.mod && e.mod.onShow) {
    try { e.mod.onShow(arg); } catch (err) { console.error('[onShow]', id, err); }
  }
  // 地址栏跟上当前模块（#transfer 这种）。用 replaceState 不写历史，
  // 免得手机上的返回键变成"在模块之间来回跳"，那体验很怪。
  // 好处是手机上可以把某一页直接存成主屏图标：/#transfer 一开就是互传。
  try {
    if (location.hash !== '#' + id) {
      history.replaceState(null, '', location.pathname + location.search + '#' + id);
    }
  } catch (_) { /* file:// 或老浏览器不让改就算了 */ }
  post('/api/kv/set', { k: 'last_module', v: id });
}

/* ---------- 模块配置（机制内核）----------
   kv: moduleConfig 存 {order:[], disabled:[], labels:{}}。
   旧的 moduleOrder kv 在 boot 时迁移进来，不丢老布局。 */
let moduleCfg = { order: null, disabled: [], labels: {} };
let dragId = null;

const modLabel = (m) => (moduleCfg.labels && moduleCfg.labels[m.id]) || m.name;
const isEnabled = (m) => !(moduleCfg.disabled || []).includes(m.id);
const visibleModules = () => MODULES.filter(isEnabled);
const modOrder = () => (moduleCfg.order && moduleCfg.order.length)
  ? moduleCfg.order.slice() : MODULES.map((m) => m.id);

function applyModuleCfg(cfg) {
  // 设置页保存后不刷新页面也能立刻生效
  moduleCfg = {
    order: (Array.isArray(cfg.order) && cfg.order.length) ? cfg.order.slice() : null,
    disabled: (Array.isArray(cfg.disabled) ? cfg.disabled : [])
      .filter((id) => MODULES.some((m) => m.id === id)),
    labels: (cfg.labels && typeof cfg.labels === 'object') ? { ...cfg.labels } : {},
  };
  renderSide();
  renderMobar();   // 底栏 tab 跟着启用/停用和改名走
  // 当前模块被关掉时跳到第一个可见模块，别停在看不见的页上
  if (currentId && moduleCfg.disabled.includes(currentId)) {
    const first = visibleModules()[0];
    if (first) go(first.id);
  }
}

function saveModuleCfg() {
  post('/api/kv/set', { k: 'moduleConfig', v: JSON.stringify(moduleCfg) });
}

function renderSide() {
  const box = $('#mods');
  box.innerHTML = '';
  modOrder().forEach((id) => {
    const m = MODULES.find((x) => x.id === id);
    if (!m || !isEnabled(m)) return;
    const b = document.createElement('button');
    b.className = 'side-btn';
    b.dataset.id = m.id;
    b.draggable = true;
    b.title = '拖动可排序';
    b.innerHTML = `<span>${esc(modLabel(m))}</span><span class="badge" data-badge="${m.id}"></span>`;
    b.onclick = () => go(m.id);
    b.addEventListener('dragstart', (e) => { dragId = m.id; e.dataTransfer.effectAllowed = 'move'; });
    b.addEventListener('dragover', (e) => e.preventDefault());
    b.addEventListener('drop', (e) => { e.preventDefault(); reorderSide(m.id); });
    box.appendChild(b);
  });
  // 高亮当前
  box.querySelectorAll('.side-btn').forEach((b) =>
    b.classList.toggle('on', b.dataset.id === (window.__cur || '')));
}

function reorderSide(targetId) {
  if (!dragId || dragId === targetId) return;
  const base = modOrder();
  const from = base.indexOf(dragId);
  const to = base.indexOf(targetId);
  if (from < 0 || to < 0) return;
  base.splice(to, 0, base.splice(from, 1)[0]);
  moduleCfg.order = base;
  renderSide();
  saveModuleCfg();
  toast('顺序已保存');
}

/* ---------- 手机 / 平板外壳：抽屉侧栏 + 底部 tab ----------
   桌面上（>760px）这些元素都是 display:none，这段逻辑也基本不跑。
   底部那 4 个 tab 是可配的：kv mobileTabs 存 id 数组，默认「今日 / 文件 / 互传 / OpenClaw」。
   没上底栏的模块一个都没被砍 —— 全都在抽屉里，点「菜单」就出来。
   抽屉用手滑也能关：从侧栏往左划一下就收，跟原生 App 一个手感。 */

const MOB_ICON = {
  home: '🏠', tasks: '✅', files: '📁', claw: '🤖', skills: '🧩', cal: '📅',
  meet: '🎥', mail: '✉️', projects: '📌', notes: '🗒', kb: '📚', system: '📈',
  settings: '⚙️', life: '🌱', room: '🛏', pomo: '🍅', habits: '🔁', clip: '📋',
  reminders: '⏰', daylog: '📔', tools: '🧰', systools: '🖥', features: '🧪',
  transfer: '📤',
};
const DEFAULT_TABS = ['home', 'files', 'transfer', 'claw'];
let mobileTabs = DEFAULT_TABS.slice();

// 手机上才认；桌面窗口拉很窄时也能预览到手机布局，方便调样式
const isNarrow = () => window.matchMedia('(max-width: 760px)').matches;
const iconOfMod = (m) => MOB_ICON[m.id] || (modLabel(m) || '·').slice(0, 1);

function tabModules() {
  const out = [];
  mobileTabs.forEach((id) => {
    const m = MODULES.find((x) => x.id === id);
    if (m && isEnabled(m) && !out.includes(m)) out.push(m);
  });
  return out;
}

function renderMobar() {
  const bar = $('#mobar');
  if (!bar) return;
  const tabs = tabModules();
  bar.innerHTML = tabs.map((m) => `<button class="mo-btn" data-id="${esc(m.id)}">
      <i class="mo-ic">${iconOfMod(m)}</i>
      <span class="mo-tx">${esc(modLabel(m))}</span>
      <em class="mo-badge" data-badge="${esc(m.id)}"></em>
    </button>`).join('')
    + `<button class="mo-btn" id="moMore"><i class="mo-ic">☰</i><span class="mo-tx">菜单</span></button>`;

  tabs.forEach((m) => {
    const b = bar.querySelector(`[data-id="${m.id}"]`);
    if (b) b.onclick = () => go(m.id);
  });
  const more = bar.querySelector('#moMore');
  if (more) more.onclick = () => openNav();
  paintMobar();
}

function paintMobar() {
  const bar = $('#mobar');
  if (!bar) return;
  bar.querySelectorAll('.mo-btn[data-id]').forEach((b) =>
    b.classList.toggle('on', b.dataset.id === (window.__cur || '')));
}

function openNav() { document.body.classList.add('nav-open'); }
function closeNav() { document.body.classList.remove('nav-open'); }

function bindMobileShell() {
  const burger = $('#btnMenu');
  const scrim = $('#scrim');
  if (burger) burger.onclick = () => {
    document.body.classList.contains('nav-open') ? closeNav() : openNav();
  };
  if (scrim) scrim.onclick = closeNav;

  // 抽屉里往左划 = 关掉
  const aside = document.querySelector('aside');
  if (aside) {
    let x0 = null, y0 = null;
    aside.addEventListener('touchstart', (e) => {
      if (!isNarrow() || !e.touches.length) return;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    aside.addEventListener('touchend', (e) => {
      if (x0 === null || !e.changedTouches.length) return;
      const t = e.changedTouches[0];
      const dx = t.clientX - x0, dy = t.clientY - y0;
      // 横向位移够大、并且明显比纵向大，才算「划」而不是「滚」
      if (dx < -52 && Math.abs(dx) > Math.abs(dy) * 1.5) closeNav();
      x0 = null; y0 = null;
    }, { passive: true });
  }

  // 屏幕转回宽屏（比如平板横过来）时把抽屉状态清掉，免得留在「半开」
  window.addEventListener('resize', () => { if (!isNarrow()) closeNav(); });
}

/* ---------- 极简 hash 路由：/#transfer 直达互传 ----------
   只认「模块 id」，认不出来就当没有，不做真路由、不接管浏览器历史。
   另外 /#nav 直接把抽屉拉开（手机上收藏这一条，进来就是模块总表）。 */
const rawHash = () => (location.hash || '').replace(/^#\/?/, '').trim();

function hashModule() {
  const h = rawHash();
  if (!h) return '';
  return MODULES.some((m) => m.id === h) ? h : '';
}

window.addEventListener('hashchange', () => {
  const h = hashModule();
  if (h && h !== window.__cur) go(h);
});

/* ---------- 命令面板 ---------- */

let cmdItems = [];
let cmdSel = 0;

function renderCmd() {
  const list = $('#cmdList');
  list.innerHTML = cmdItems
    .map(
      (it, i) =>
        `<div class="cmdk-item${i === cmdSel ? ' sel' : ''}" data-i="${i}">
          <span>${esc(it.title)}</span><span class="g">${esc(it.hint || '')}</span>
        </div>`
    )
    .join('');
  list.querySelectorAll('.cmdk-item').forEach((el) => {
    el.onclick = () => runCmd(+el.dataset.i);
    el.onmouseenter = () => { cmdSel = +el.dataset.i; paintSel(); };
  });
}

function paintSel() {
  $('#cmdList').querySelectorAll('.cmdk-item').forEach((el, i) => {
    el.classList.toggle('sel', i === cmdSel);
  });
}

function runCmd(i) {
  const it = cmdItems[i];
  if (!it) return;
  closeCmd();
  Promise.resolve(it.run()).catch((e) => toast('执行失败：' + e.message));
}

function openCmd() {
  $('#cmdk').classList.add('on');
  $('#cmdInput').value = '';
  cmdSel = 0;
  updateCmd('');
  setTimeout(() => $('#cmdInput').focus(), 20);
}

function closeCmd() {
  $('#cmdk').classList.remove('on');
}

let cmdTimer = null;

async function updateCmd(q) {
  const items = [];

  // 语言切换永远排在最前（命令面板默认空查询，这里就是全部）
  items.push({
    title: window.WBi18n && window.WBi18n.lang === 'zh' ? '切换到 English（Ctrl/⌘ L）' : '切换到中文（Ctrl/⌘ L）',
    hint: '界面语言',
    run: () => {
      const i = i18nApi();
      if (!i) { toast('语言包还在加载，刷新一下再来'); return; }
      return setLang(i.lang === 'zh' ? 'en' : 'zh');
    },
  });
  items.push({
    title: '界面语言设置',
    hint: '设置',
    run: () => go('settings'),
  });

  visibleModules().forEach((m) => {
    const label = modLabel(m);
    if (!q || label.includes(q) || (m.name && m.name.includes(q))) {
      items.push({ title: '前往 ' + label, hint: '模块', run: () => go(m.id) });
    }
    (typeof m.commands === 'function' ? m.commands() : []).forEach((c) => {
      if (!q || c.title.includes(q)) items.push(c);
    });
  });

  if (q.length >= 2) {
    try {
      const d = await api(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
      d.rows.forEach((r) => {
        items.push({
          title: r.name,
          hint: r.path,
          run: () => post('/api/open', { path: r.path }),
        });
      });
    } catch (_) { /* 索引没跑完时不报错 */ }
  }

  if (q.trim()) {
    items.push({
      title: '记下：' + q.trim(),
      hint: '快速捕捉',
      run: async () => {
        await post('/api/inbox/add', { text: q.trim() });
        toast('已记下');
        const e = built.get('home');
        if (e && e.mod.refresh) e.mod.refresh();
      },
    });
  }

  cmdItems = items;
  cmdSel = 0;
  renderCmd();
}

$('#cmdInput').addEventListener('input', () => {
  const v = $('#cmdInput').value;
  clearTimeout(cmdTimer);
  cmdTimer = setTimeout(() => updateCmd(v), 220);
});

$('#cmdInput').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { e.preventDefault(); cmdSel = Math.min(cmdSel + 1, cmdItems.length - 1); paintSel(); }
  if (e.key === 'ArrowUp') { e.preventDefault(); cmdSel = Math.max(cmdSel - 1, 0); paintSel(); }
  if (e.key === 'Enter') { e.preventDefault(); runCmd(cmdSel); }
});

$('#cmdk').addEventListener('click', (e) => { if (e.target.id === 'cmdk') closeCmd(); });

/* ---------- 快捷键 ---------- */

/* ---------- 快捷启动器（Alt + Space）----------
   跟 Ctrl+K 命令面板的区别：这个只干两件事——启动程序、打开文件，
   所以匹配更狠：输入「chr」就该跳出 Chrome。 */

let apps = null;          // 启动项缓存
let lcItems = [];
let lcSel = 0;

async function ensureApps() {
  if (apps) return apps;
  try {
    const d = await api('/api/launch/list');
    apps = d.rows || [];
  } catch (_) {
    apps = [];
  }
  return apps;
}

function openLaunch() {
  $('#launch').classList.add('on');
  $('#lcInput').value = '';
  lcSel = 0;
  updateLaunch('');
  setTimeout(() => $('#lcInput').focus(), 20);
}

function closeLaunch() {
  $('#launch').classList.remove('on');
}

async function updateLaunch(q) {
  const items = [];
  const qq = q.trim().toLowerCase();

  const list = await ensureApps();
  // 前缀匹配排前面，包含匹配排后面
  const pre = [];
  const inc = [];
  for (const a of list) {
    const n = a.name.toLowerCase();
    if (!qq || n === qq) {
      pre.push(a);
    } else if (n.startsWith(qq)) {
      pre.push(a);
    } else if (n.includes(qq)) {
      inc.push(a);
    }
    if (pre.length + inc.length > 400) break;
  }
  [...pre, ...inc].slice(0, 12).forEach((a) => {
    items.push({
      title: a.name,
      hint: a.dir || '程序',
      run: () => post('/api/open', { path: a.path }),
    });
  });

  if (qq.length >= 2) {
    try {
      const d = await api(`/api/search?q=${encodeURIComponent(qq)}&limit=8`);
      d.rows.forEach((r) => {
        items.push({
          title: r.name,
          hint: r.path,
          run: () => post('/api/open', { path: r.path }),
        });
      });
    } catch (_) { /* 索引没跑完就算了 */ }
  }

  lcItems = items;
  lcSel = 0;
  renderLaunch(qq);
}

function renderLaunch(qq) {
  const list = $('#lcList');
  if (!lcItems.length) {
    list.innerHTML = `<div class="cmdk-item"><span>${qq ? '没匹配到' : '装的程序还在扫，稍等'}</span></div>`;
    return;
  }
  list.innerHTML = lcItems
    .map((it, i) => `<div class="cmdk-item${i === lcSel ? ' sel' : ''}" data-i="${i}">
        <span>${esc(it.title)}</span><span class="g">${esc(it.hint || '')}</span>
      </div>`)
    .join('');
  list.querySelectorAll('.cmdk-item').forEach((el) => {
    el.onclick = () => runLaunch(+el.dataset.i);
    el.onmouseenter = () => {
      lcSel = +el.dataset.i;
      list.querySelectorAll('.cmdk-item').forEach((x, j) => x.classList.toggle('sel', j === lcSel));
    };
  });
}

function runLaunch(i) {
  const it = lcItems[i];
  if (!it) return;
  closeLaunch();
  Promise.resolve(it.run()).catch((e) => toast('启动失败：' + e.message));
}

$('#lcInput').addEventListener('input', () => updateLaunch($('#lcInput').value));
$('#lcInput').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { e.preventDefault(); lcSel = Math.min(lcSel + 1, lcItems.length - 1); renderLaunch(''); }
  if (e.key === 'ArrowUp') { e.preventDefault(); lcSel = Math.max(lcSel - 1, 0); renderLaunch(''); }
  if (e.key === 'Enter') { e.preventDefault(); runLaunch(lcSel); }
});
$('#launch').addEventListener('click', (e) => { if (e.target.id === 'launch') closeLaunch(); });

window.addEventListener('keydown', (e) => {
  if (e.altKey && e.code === 'Space') {
    e.preventDefault();
    $('#launch').classList.contains('on') ? closeLaunch() : openLaunch();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    $('#cmdk').classList.contains('on') ? closeCmd() : openCmd();
    return;
  }
  // Ctrl/⌘+L 切界面语言（浏览器地址栏那个 Ctrl+L 要 preventDefault 才抢得到）
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'l') {
    e.preventDefault();
    const i = i18nApi();
    if (!i) { toast('语言包还在加载，刷新一下再来'); return; }
    setLang(i.lang === 'zh' ? 'en' : 'zh');
    return;
  }
  if (e.key === 'Escape' && $('#cmdk').classList.contains('on')) {
    closeCmd();
    return;
  }
  if (e.key === 'Escape' && $('#launch').classList.contains('on')) {
    closeLaunch();
    return;
  }
  // Alt+1..9 前九个可见模块，Alt+0 第十个，- 和 = 接第十一、十二个
  if (e.altKey && /^[0-9\-=]$/.test(e.key)) {
    const map = { '0': 9, '-': 10, '=': 11 };
    const i = map[e.key] !== undefined ? map[e.key] : +e.key - 1;
    const m = visibleModules()[i];
    if (m) { e.preventDefault(); go(m.id); }
  }
});

$('#btnCmd').onclick = openCmd;
$('#btnCmd2').onclick = openCmd;

/* ---------- 主题（默认暗色，切到 light 才存 light） ---------- */

$('#btnTheme').onclick = async () => {
  const light = document.body.classList.toggle('light');
  await post('/api/kv/set', { k: 'theme', v: light ? 'light' : 'dark' });
};

/* ---------- 语言切换 ----------
   i18n.js 是异步 module，加载完才把 window.WBi18n 挂上，所以这里不能直接引用。
   点击时才取，取不到就提示「语言包还在加载」而不是静默失败。 */

function i18nApi() {
  return window.WBi18n || null;
}

async function setLang(lang) {
  const i = i18nApi();
  if (!i) { toast('语言包还在加载，刷新一下再来'); return; }
  if (lang) i.apply(lang);
  else i.follow();
  i.paintSwitchers();
  // 当前模块的内容得重画一次，否则新语言只作用在已渲染的节点上
  const e = currentId ? built.get(currentId) : null;
  if (e && e.mod && e.mod.onShow) {
    try { e.mod.onShow(); } catch (err) { console.error('[lang] 重画失败', err); }
  }
  toast('界面语言：' + ((i.LABELS && i.LABELS[i.lang]) || i.lang));
}

const btnLang = $('#btnLang');
const btnLang2 = $('#btnLang2');
[btnLang, btnLang2].forEach((b) => {
  if (!b) return;
  b.onclick = () => {
    const i = i18nApi();
    if (!i) { toast('语言包还在加载，刷新一下再来'); return; }
    setLang(i.lang === 'zh' ? 'en' : 'zh');
  };
});
if (btnLang || btnLang2) {
  // i18n 加载完会自己 paint 一次；这里再兜一次底（加载失败时至少按钮还在）
  const wait = setInterval(() => {
    if (!i18nApi()) return;
    clearInterval(wait);
    i18nApi().paintSwitchers();
  }, 200);
  setTimeout(() => clearInterval(wait), 8000);
}

/* ---------- 状态轮询 ---------- */

async function refreshStatus() {
  let d = {};
  try { d = await api('/api/status') || {}; } catch (_) { /* 云模式下 status 不可用 */ }
  lastStatus = d;
  const p = d.progress || {};
  const dot = $('#dot');
  dot.classList.toggle('busy', !!p.running);
  const cnt = d.count != null ? d.count : 0;
  const scanned = p.scanned != null ? p.scanned : 0;
  dot.textContent = p.running ? `${scanned.toLocaleString()} 个` : `${cnt.toLocaleString()} 个`;
  $('#topState').textContent = p.running ? '索引中' : '';

  MODULES.forEach((m) => {
    if (typeof m.badge !== 'function') return;
    // 侧栏和手机底栏可能同时挂着同一个模块的角标，所以是 All 不是单选
    document.querySelectorAll(`[data-badge="${m.id}"]`).forEach((el) => {
      el.textContent = m.badge(d) || '';
    });
  });
}

setInterval(refreshStatus, 2000);

/* ---------- 提醒桌面通知 ---------- */

let notifiedSet = new Set();

async function loadNotified() {
  try {
    const d = await api('/api/kv?k=notifiedReminders');
    const arr = JSON.parse(d.v || '[]');
    if (Array.isArray(arr)) notifiedSet = new Set(arr);
  } catch (_) { /* 忽略 */ }
}
function saveNotified() {
  const arr = [...notifiedSet];
  post('/api/kv/set', { k: 'notifiedReminders', v: JSON.stringify(arr) }).catch(() => {});
}

function fireNotify(title, body) {
  if ('Notification' in window && Notification.permission === 'granted') {
    try { new Notification(title, { body, tag: 'wb-reminder' }); } catch (_) {}
  }
  toast(body ? `${title}：${body}` : title);
}

async function notifyPoll() {
  let data;
  try { data = await api('/api/reminders'); } catch (_) { return; }
  const now = Date.now() / 1000;
  let changed = false;
  (data.rows || []).forEach((r) => {
    if ((r.done || 0) > 0) return;
    if ((r.at || 0) > now) return;
    if (notifiedSet.has(r.id)) return;
    notifiedSet.add(r.id);
    changed = true;
    fireNotify('提醒', r.text || '时间到了');
  });
  if (changed) saveNotified();
}

// 在用户手势里请求权限（浏览器要求）；非手势调用可能被拒，但站内 toast 仍兜底
function requestNotify() {
  if (!('Notification' in window)) { toast('这个浏览器不支持桌面通知，会用站内提示兜底'); return; }
  if (Notification.permission === 'granted') { toast('桌面通知已开启'); return; }
  if (Notification.permission === 'denied') { toast('桌面通知被浏览器禁用，去站点设置里打开；站内提示仍生效'); return; }
  Notification.requestPermission().then((p) => {
    toast(p === 'granted' ? '桌面通知已开启' : '没开桌面通知，站内提示仍生效');
  });
}

setInterval(notifyPoll, 15000);

/* ---------- 启动 ---------- */

async function boot() {
  // 云同步必须在「任何 api 调用之前」初始化：
  // 发布域名下没有 Flask 后端，/api/* 会返回 404，若先调用 api() 会让 boot() 抛错、
  // 整个启动流程中断（侧栏空、模块不挂、登录门也不弹）。所以先 init 再读数据。
  if (window.CloudSync) {
    let published = false;
    try { published = await window.CloudSync.init(); } catch (e) { console.error('[boot] cloud init', e); }
    if (published && !window.CloudSync.ready()) {
      if (typeof window.WorkBuddyCloud === 'undefined') {
        // SDK 没加载（弱网）：降级跑，模块显示空壳，不弹登录门
        toast('云同步组件未加载（检查网络），跨设备同步暂不可用');
      } else {
        window.CloudSync.showLogin();
        let done = false;
        window.CloudSync.onSyncChange((s) => {
          if (s.ready && !done) { done = true; bootRest(); }
        });
        return;
      }
    }
  }
  bootRest();
}

async function bootRest() {
  let theme = {}, last = {}, ord = {}, mc = {}, tabs = {};
  try {
    [theme, last, ord, mc, tabs] = await Promise.all([
      api('/api/kv?k=theme'),
      api('/api/kv?k=last_module'),
      api('/api/kv?k=moduleOrder'),
      api('/api/kv?k=moduleConfig'),
      api('/api/kv?k=mobileTabs'),
    ]);
  } catch (e) { console.error('[boot] kv 读取失败', e); }
  if (theme && theme.v === 'light') document.body.classList.add('light');
  // 手机底栏放哪几个模块：没配过就用默认那四个
  try {
    const t = JSON.parse((tabs && tabs.v) || 'null');
    if (Array.isArray(t) && t.length) {
      const ok = t.filter((id) => MODULES.some((m) => m.id === id));
      if (ok.length) mobileTabs = ok;
    }
  } catch (e) { /* 坏了就用默认 */ }
  try {
    const c = JSON.parse((mc && mc.v) || 'null');
    if (c && (Array.isArray(c.order) || Array.isArray(c.disabled) || c.labels)) {
      moduleCfg = {
        order: (Array.isArray(c.order) && c.order.length) ? c.order : null,
        disabled: Array.isArray(c.disabled) ? c.disabled : [],
        labels: (c.labels && typeof c.labels === 'object') ? c.labels : {},
      };
    }
  } catch (e) { /* 配置坏了就当没配 */ }
  if (!moduleCfg.order) {
    // 老布局迁移：旧 moduleOrder kv 并入新配置，拖过的顺序不丢
    try {
      const o = JSON.parse((ord && ord.v) || 'null');
      if (Array.isArray(o) && o.length) moduleCfg.order = o;
    } catch (e) { /* ignore */ }
  }
  // 升级后新注册的模块补到末尾，保证可见
  const base = modOrder();
  for (const m of MODULES) if (!base.includes(m.id)) base.push(m.id);
  moduleCfg.order = base;
  await loadNotified();
  finishBoot(last && last.v);
}

function finishBoot(lastModule) {
  renderSide();
  renderMobar();
  bindMobileShell();
  mountSyncBadge();
  log('ok', 'boot', 'workbench online');
  let start = (lastModule && MODULES.some((m) => m.id === lastModule)) ? lastModule : 'home';
  if (moduleCfg.disabled.includes(start)) start = (visibleModules()[0] || {}).id || start;
  const h = hashModule();
  go(h || start);
  if (rawHash() === 'nav') openNav();
  refreshStatus();
  MODULES.forEach((m) => { if (m.boot) m.boot(); });
  notifyPoll();
  log('info', 'sys', MODULES.length + ' 模块已注册');
  // 云站是纯前端、没有本机后端：问一问(Ollama)/OpenClaw/文件/终端/系统这些本机功能在此不可用，
  // 一次性提示用户，避免他以为出了 bug。
  if (window.CloudSync && window.CloudSync.active()) {
    setTimeout(() => toast('云站是纯前端：问一问(Ollama)、OpenClaw、文件、终端、系统等本机功能需在桌面版(本机地址)使用。'), 600);
  }
}

// 专属欢迎提示：用指定邮箱登录时弹「您好！尊敬的开发者！」
// 不把个人邮箱硬编码进开源仓库：想给自己开这个「开发者问候」小灶，
// 就在浏览器控制台执行 localStorage.setItem('wb_dev_email','你的邮箱')。默认为空 = 不触发。
const DEV_EMAIL = localStorage.getItem('wb_dev_email') || '';
let greeted = false;
function greetIfDev(s) {
  if (greeted) return;
  if (s && s.ready && s.user && s.user.email === DEV_EMAIL) {
    greeted = true;
    toast('您好！尊敬的开发者！');
  }
}

function mountSyncBadge() {
  const cs = document.getElementById('cloudStat');
  if (!cs) return;
  const render = (s) => {
    if (!s.published) { cs.style.display = 'none'; return; }
    cs.style.display = '';
    if (!s.ready) {
      cs.textContent = '未登录·点此同步';
      cs.className = 'm cloud-off';
      cs.onclick = () => window.CloudSync && window.CloudSync.showLogin();
    } else {
      const name = s.user && s.user.email ? s.user.email.split('@')[0] : '已同步';
      cs.textContent = '已同步·' + name;
      cs.className = 'm cloud-on';
      cs.onclick = () => window.CloudSync && window.CloudSync.showLogin();
    }
    greetIfDev(s);
  };
  if (window.CloudSync) window.CloudSync.onSyncChange(render);
  render(window.CloudSync ? window.CloudSync.state() : { published: false });
}

/* ---------- PWA：装到主屏 ----------
   Service Worker 只在「安全上下文」里能注册 —— https，或 localhost / 127.0.0.1。
   手机连 http://192.168.x.x:8777 这种局域网明文地址是**注册不上**的，
   所以这里必须先判断，否则控制台天天多一条没用的报错，还容易被误会成 bug。
   想真的全屏无地址栏：用设置页里那条 https 隧道地址打开，再加到主屏。 */
function registerSW() {
  if (!('serviceWorker' in navigator)) return;
  const secure = location.protocol === 'https:'
    || ['localhost', '127.0.0.1', '::1'].indexOf(location.hostname) >= 0;
  if (!secure) {
    console.info('[pwa] 明文局域网地址不注册 Service Worker（浏览器规定）。'
      + '想装成 App 请改用 https 隧道地址。');
    return;
  }
  navigator.serviceWorker.register('/sw.js').catch((e) => {
    console.warn('[pwa] Service Worker 注册失败：', e && e.message);
  });
}

tickClock();
setInterval(tickClock, 1000);
// 先 boot（内部先做云初始化，发布域名下会弹登录门），再开始 sysinfo 轮询，
// 否则发布域名下 refreshSys 会抢在云初始化前打 /api/sysinfo 拿 404。
boot().catch((e) => { console.error('[boot]', e); log('err', 'boot', (e && e.message) || String(e)); });
registerSW();
setInterval(refreshSys, 2000);
