/* 项目域：项目卡片 → 任务看板 → 里程碑 → 番茄钟 → 动态日志 → 全部任务 → 时间线 */

const { api, post, toast, esc, day } = window.WB;

const STATUS = ['进行中', '待启动', '摸索中', '卡住了', '已完成'];
const STATES = ['待办', '在做', '已完成'];
const COLORS = [
  { v: '', n: '默认', c: 'var(--accent)' },
  { v: 'red', n: '红', c: '#e5484d' },
  { v: 'orange', n: '橙', c: '#f0883e' },
  { v: 'amber', n: '黄', c: '#d4a72c' },
  { v: 'green', n: '绿', c: '#2f9e63' },
  { v: 'blue', n: '蓝', c: '#2f6feb' },
  { v: 'purple', n: '紫', c: '#8e5ad8' },
];
const colorOf = (v) => (COLORS.find((x) => x.v === (v || '')) || COLORS[0]).c;

const pad = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDay = (s) => {
  const [y, m, d] = (s || '').split('-').map(Number);
  return new Date(y || 2026, (m || 1) - 1, d || 1);
};
const diffDays = (a, b) => Math.round((parseDay(b) - parseDay(a)) / 86400000);

export default {
  id: 'projects',
  name: '项目',
  el: null,
  tab: 'proj',        // proj | tasks | timeline
  projs: [],
  tasks: [],
  allTasks: [],
  ms: [],             // 当前项目的里程碑
  logs: [],
  tpls: [],
  timeline: [],
  showArchived: false,
  taskFilter: '',     // 全部任务页的状态筛选
  cur: 0,
  tick: null,
  running: null,
  today: { minutes: 0, count: 0 },

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <div style="display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden">
          <button class="btn ptab" data-t="proj" style="height:30px;padding:0 12px;font-size:12px;border:0;border-radius:0">项目</button>
          <button class="btn ptab" data-t="tasks" style="height:30px;padding:0 12px;font-size:12px;border:0;border-radius:0">全部任务</button>
          <button class="btn ptab" data-t="timeline" style="height:30px;padding:0 12px;font-size:12px;border:0;border-radius:0">时间线</button>
        </div>
        <span id="pomoToday" class="tag" style="margin-left:auto"></span>
      </div>

      <div id="vProj" class="stack">
        <div class="panel">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <h3 style="margin:0">项目</h3>
            <label class="note" style="display:flex;align-items:center;gap:5px;cursor:pointer">
              <input type="checkbox" id="pArch"> 看归档
            </label>
          </div>
          <div id="projList" class="note" style="margin-top:8px">加载中…</div>
          <div class="field-row" style="margin-top:10px">
            <input id="pName" placeholder="新项目名，例如 voxelcraft" style="flex:1">
            <input id="pNext" placeholder="下一步做什么" style="flex:1">
            <input id="pDeadline" type="date" title="目标日期（给时间线用）" style="width:140px">
            <select id="pTpl" title="起手模板">${'{TPL}'}</select>
            <button class="btn primary" id="btnAddProj">添加</button>
          </div>
        </div>

        <div id="detail" style="display:none">
          <div class="panel">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <h3 id="dTitle" style="margin:0"></h3>
              <span id="dStat" class="tag" style="cursor:pointer"></span>
              <span id="dIdle" class="note"></span>
              <div id="dPomo" style="margin-left:auto;display:flex;align-items:center;gap:8px"></div>
            </div>
            <div class="bar-mini" id="dBars" style="margin-top:8px"></div>
            <div class="field-row" style="margin-top:10px">
              <input id="tTitle" placeholder="加一个任务，回车即可" style="flex:1">
              <select id="tState">${STATES.map((s) => `<option>${s}</option>`).join('')}</select>
              <input id="tDue" type="date" title="截止日，留空就是不限" style="width:140px">
              <button class="btn primary" id="btnAddTask">加任务</button>
            </div>
            <div class="field-row" style="margin-top:8px">
              <input id="mTitle" placeholder="加一个里程碑，例如「跑通主流程」" style="flex:1">
              <input id="mDay" type="date" title="目标日期" style="width:140px">
              <input id="mPct" type="number" min="0" max="100" value="50" title="完成度%" style="width:80px">
              <button class="btn" id="btnAddMs">加里程碑</button>
              <button class="btn" id="btnArch">归档这个项目</button>
              <button class="btn" id="btnDelProj">删除</button>
            </div>
          </div>

          <div class="board" id="board"></div>

          <div class="panel">
            <div style="display:flex;align-items:center;gap:10px">
              <h3 style="margin:0">里程碑</h3>
              <span class="note" id="msSum"></span>
            </div>
            <div id="msList" style="margin-top:10px"></div>
          </div>

          <div class="panel">
            <div style="display:flex;align-items:center;gap:10px">
              <h3 style="margin:0">动态日志</h3>
              <span class="note">你做的每个操作自动记一笔，也能手写一句</span>
              <label class="note" style="margin-left:auto;display:flex;gap:5px;align-items:center;cursor:pointer">
                <input type="checkbox" id="lAuto" checked> 显示自动记录
              </label>
            </div>
            <div class="field-row" style="margin-top:10px">
              <input id="lText" placeholder="今天推进了什么（回车记录）" style="flex:1">
              <button class="btn" id="btnMilestone">记为里程碑</button>
              <button class="btn primary" id="btnAddLog">记一条</button>
            </div>
            <div id="logList" style="margin-top:10px"></div>
          </div>
        </div>
      </div>

      <div id="vTasks" style="display:none">
        <div class="panel">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <h3 style="margin:0">全部任务</h3>
            <span class="note">所有项目的任务一屏看</span>
            <div style="display:flex;gap:6px;margin-left:auto" id="tfChips"></div>
          </div>
          <div id="allList" style="margin-top:10px"></div>
        </div>
      </div>

      <div id="vTimeline" style="display:none">
        <div class="panel">
          <div style="display:flex;align-items:center;gap:10px">
            <h3 style="margin:0">时间线</h3>
            <span class="note">甘特简版：项目跨度 + 任务截止 + 里程碑</span>
          </div>
          <div id="tlBox" style="margin-top:12px"></div>
        </div>
      </div>`;

    const q = (s) => el.querySelector(s);

    el.querySelectorAll('.ptab').forEach((b) => {
      b.onclick = () => this.setTab(b.dataset.t);
    });
    q('#pArch').onchange = (e) => { this.showArchived = e.target.checked; this.load(); };
    q('#btnAddProj').onclick = () => this.addProj();
    q('#pName').onkeydown = (e) => { if (e.key === 'Enter') this.addProj(); };
    q('#btnAddTask').onclick = () => this.addTask();
    q('#tTitle').onkeydown = (e) => { if (e.key === 'Enter') this.addTask(); };
    q('#btnAddMs').onclick = () => this.addMs();
    q('#mTitle').onkeydown = (e) => { if (e.key === 'Enter') this.addMs(); };
    q('#btnArch').onclick = () => this.archiveProj(this.cur, this.projs.find((x) => x.id === this.cur)?.archived ? 0 : 1);
    q('#btnDelProj').onclick = () => {
      const p = this.projs.find((x) => x.id === this.cur);
      if (!p) return;
      if (!confirm(`删掉「${p.name}」？任务、里程碑和记录一起没。`)) return;
      post('/api/projects/del', { id: this.cur }).then(() => { this.cur = 0; this.load(); });
    };
    q('#btnAddLog').onclick = () => this.addLog('log');
    q('#btnMilestone').onclick = () => this.addLog('milestone');
    q('#lText').onkeydown = (e) => { if (e.key === 'Enter') this.addLog('log'); };
    q('#lAuto').onchange = () => this.renderLogs();

    // 项目列表：选中 / 换状态 / 归档
    q('#projList').addEventListener('click', (e) => {
      const row = e.target.closest('.prow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.arch')) { this.archiveProj(id, row.dataset.archived === '1' ? 0 : 1); return; }
      if (e.target.closest('.st')) {
        const i = STATUS.indexOf(row.dataset.status);
        post('/api/projects/save', {
          id, name: row.dataset.name, status: STATUS[(i + 1) % STATUS.length],
          next_step: row.dataset.next, deadline: row.dataset.deadline || '',
          color: row.dataset.color || '',
        }).then(() => this.load());
        return;
      }
      this.select(id);
    });

    // 看板：点按 + 拖拽换列（81）
    q('#board').addEventListener('click', async (e) => {
      const t = e.target.closest('.trow');
      if (!t) return;
      const id = +t.dataset.id;
      if (e.target.closest('.del')) await post('/api/tasks/del', { id });
      else if (e.target.closest('.next')) {
        const i = STATES.indexOf(t.dataset.state);
        const to = STATES[(i + 1) % STATES.length];
        await post('/api/tasks/state', { id, state: to });
        if (to === '已完成') toast('搞定一件');
      } else if (e.target.closest('.pomo')) { this.startPomo(id, t.dataset.title); return; }
      else if (e.target.closest('.due')) {
        const v = prompt('截止日（YYYY-MM-DD，留空清除）', t.dataset.due || '');
        if (v === null) return;
        await post('/api/tasks/due', { id, due: v.trim() });
      } else return;
      this.load();
    });
    q('#board').addEventListener('dragstart', (e) => {
      const t = e.target.closest('.trow');
      if (!t) return;
      this.dragTask = +t.dataset.id;
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', String(this.dragTask)); } catch (_) { /* 忽略 */ }
      t.classList.add('dragging');
    });
    q('#board').addEventListener('dragend', (e) => {
      const t = e.target.closest('.trow');
      if (t) t.classList.remove('dragging');
      q('#board').querySelectorAll('.col').forEach((c) => c.classList.remove('drop-hint'));
    });
    q('#board').addEventListener('dragover', (e) => {
      const c = e.target.closest('.col');
      if (!c || !this.dragTask) return;
      e.preventDefault();
      c.classList.add('drop-hint');
    });
    q('#board').addEventListener('dragleave', (e) => {
      const c = e.target.closest('.col');
      if (c) c.classList.remove('drop-hint');
    });
    q('#board').addEventListener('drop', async (e) => {
      const c = e.target.closest('.col');
      if (!c) return;
      e.preventDefault();
      c.classList.remove('drop-hint');
      let id = this.dragTask;
      try { id = +e.dataTransfer.getData('text/plain') || id; } catch (_) { /* 用 this.dragTask */ }
      this.dragTask = null;
      if (!id || !c.dataset.state) return;
      await post('/api/tasks/state', { id, state: c.dataset.state });
      toast('挪到「' + c.dataset.state + '」');
      this.load();
    });

    // 里程碑
    q('#msList').addEventListener('click', async (e) => {
      const row = e.target.closest('.mrow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.del')) await post('/api/milestones/del', { id });
      else if (e.target.closest('.cb')) await post('/api/milestones/done', { id, done: row.dataset.done === '1' ? 0 : 1 });
      else if (e.target.closest('.pct')) {
        const v = prompt('完成度 %（0-100）', row.dataset.pct || '0');
        if (v === null) return;
        await post('/api/milestones/save', { id, project_id: this.cur, title: row.dataset.title, day: row.dataset.day || '', pct: +v || 0 });
      } else return;
      this.load();
    });

    q('#logList').addEventListener('click', async (e) => {
      const del = e.target.closest('.del');
      if (!del) return;
      await post('/api/plog/del', { id: +del.dataset.id });
      this.load();
    });

    q('#tfChips').addEventListener('click', (e) => {
      const c = e.target.closest('[data-f]');
      if (!c) return;
      this.taskFilter = c.dataset.f;
      this.renderAllTasks();
    });

    this.loadTemplates();
    this.load();
  },

  setTab(t) {
    this.tab = t;
    const el = this.el;
    el.querySelector('#vProj').style.display = t === 'proj' ? '' : 'none';
    el.querySelector('#vTasks').style.display = t === 'tasks' ? '' : 'none';
    el.querySelector('#vTimeline').style.display = t === 'timeline' ? '' : 'none';
    el.querySelectorAll('.ptab').forEach((b) => b.classList.toggle('active', b.dataset.t === t));
    if (t === 'tasks') this.loadAllTasks();
    if (t === 'timeline') this.loadTimeline();
  },

  async loadTemplates() {
    const d = await api('/api/projects/templates');
    this.tpls = d.rows || [];
    const sel = this.el.querySelector('#pTpl');
    if (sel) {
      sel.innerHTML = this.tpls.map((t) => `<option value="${t.key}" title="${esc(t.desc || '')}">${esc(t.name)}</option>`).join('');
    }
  },

  async load() {
    const [p, t, m] = await Promise.all([
      api('/api/projects'), api('/api/tasks?project_id=0'),
      this.cur ? api('/api/plog?project_id=' + this.cur) : Promise.resolve({ rows: [] }),
    ]);
    this.allProjs = p.rows || [];
    this.projs = this.showArchived ? this.allProjs : this.allProjs.filter((x) => !x.archived);
    this.tasks = t.rows || [];
    this.running = t.running || null;
    this.today = t.today || { minutes: 0, count: 0 };
    this.logs = m.rows || [];
    if (!this.projs.find((x) => x.id === this.cur)) this.cur = this.projs.length ? this.projs[0].id : 0;
    if (this.cur) this.ms = (await api('/api/milestones?project_id=' + this.cur)).rows || [];
    else this.ms = [];
    this.render();
  },

  select(id) {
    this.cur = id;
    this.load();
  },

  // ---- 86 日志 ----

  renderLogs() {
    const box = this.el.querySelector('#logList');
    if (!box) return;
    const onlyAuto = this.el.querySelector('#lAuto');
    const show = onlyAuto && !onlyAuto.checked
      ? this.logs.filter((l) => l.kind !== 'auto') : this.logs;
    box.innerHTML = show.length ? show.map((l) => `
      <div class="lrow ${l.kind === 'milestone' ? 'ms' : ''}" style="padding:8px 0;border-bottom:1px solid var(--line-soft)">
        <div style="display:flex;gap:8px;align-items:baseline">
          <span class="note">${this.day(l.created)}</span>
          ${l.kind === 'milestone' ? '<span class="tag on">里程碑</span>'
            : l.kind === 'auto' ? '<span class="tag">自动</span>' : '<span class="tag">手记</span>'}
          <span style="flex:1">${esc(l.text)}</span>
          <button class="del" data-id="${l.id}" style="border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
        </div>
      </div>`).join('') : '<div class="note">还没记过。做完一件事就写一句，将来回看很有用。</div>';
  },

  // ---- 渲染 ----

  render() {
    const el = this.el;
    const q = (s) => el.querySelector(s);
    q('#pomoToday').textContent = `今天专注 ${this.today.minutes} 分钟 · ${this.today.count} 个番茄`;
    q('#pArch').checked = this.showArchived;

    // 项目卡片（80 停滞标灰 / 82 归档）
    if (!this.projs.length) {
      q('#projList').innerHTML = '<div class="note">还没有项目。上面加一个，比如 voxelcraft。</div>';
    } else {
      const staleN = this.projs.filter((x) => x.stale).length;
      q('#projList').innerHTML = (staleN ? `<div class="note" style="color:var(--warn);margin-bottom:4px">有 ${staleN} 个项目好久没动了</div>` : '')
        + this.projs.map((p) => {
          const pct = p.n_task ? Math.round((p.n_done / p.n_task) * 100) : 0;
          const col = colorOf(p.color);
          return `
        <div class="prow ${p.id === this.cur ? 'on' : ''}${p.stale ? ' stale' : ''}${p.archived ? ' arch' : ''}"
             data-id="${p.id}" data-status="${esc(p.status || '')}" data-name="${esc(p.name || '')}"
             data-next="${esc(p.next_step || '')}" data-archived="${p.archived ? 1 : 0}"
             data-deadline="${esc(p.deadline || '')}" data-color="${esc(p.color || '')}"
             style="padding:10px;border-bottom:1px solid var(--line-soft);border-left:3px solid ${col}">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <b style="font-weight:500">${esc(p.name)}</b>
            <button class="st tag" style="border:0;cursor:pointer">${esc(p.status || '未设')}</button>
            ${p.archived ? '<span class="tag">已归档</span>' : ''}
            ${p.stale ? `<span class="tag warn">停滞 ${p.idle_days} 天</span>` : ''}
            ${p.deadline ? `<span class="tag">目标 ${esc(p.deadline)}</span>` : ''}
            <span class="note">${p.n_done}/${p.n_task} 任务${p.n_ms ? ` · 里程碑 ${p.ms_done}/${p.n_ms}` : ''} · ${p.mins} 分钟</span>
            <button class="arch note" style="margin-left:auto;border:0;background:transparent;cursor:pointer">${p.archived ? '放回' : '归档'}</button>
          </div>
          <div class="bar-mini"><i style="width:${pct}%"></i></div>
          <div style="font-size:12.5px;color:var(--ink-2);margin-top:4px">
            下一步：${esc(p.next_step || '还没想好')}
          </div>
        </div>`;
        }).join('');
    }

    const p = this.projs.find((x) => x.id === this.cur);
    const box = q('#detail');
    if (!p) { box.style.display = 'none'; return; }
    box.style.display = '';
    q('#dTitle').textContent = p.name;
    q('#dStat').textContent = p.status || '未设';
    q('#dIdle').textContent = p.stale ? `⚠ 已经 ${p.idle_days} 天没动静了` : (p.n_ms ? `里程碑完成度 ${p.ms_pct}%` : '');
    q('#btnArch').textContent = p.archived ? '放回项目列表' : '归档这个项目';
    q('#dBars').innerHTML =
      `<i style="width:${p.n_task ? Math.round(p.n_done / p.n_task * 100) : 0}%"></i>`;

    if (this.running) {
      q('#dPomo').innerHTML = `
        <span id="pomoClock" class="tag on">${this.fmt(this.elapsed())}</span>
        <span class="note">${esc(this.running.title || '专注中')}</span>
        <button class="btn primary" id="btnStopPomo">结束</button>`;
      q('#btnStopPomo').onclick = () => this.stopPomo();
    } else {
      q('#dPomo').innerHTML = `
        <span class="note">专注一段：</span>
        <button class="btn pomo-quick" data-m="25">25 分钟</button>
        <button class="btn pomo-quick" data-m="45">45</button>
        <button class="btn pomo-quick" data-m="15">15</button>`;
      q('#dPomo').querySelectorAll('.pomo-quick').forEach((b) => {
        b.onclick = () => this.startPomo(0, `${p.name} · ${b.dataset.m} 分钟`);
      });
    }

    // 81 看板三列
    const mine = this.tasks.filter((t) => t.project_id === this.cur);
    q('#board').innerHTML = STATES.map((st) => {
      const rows = mine.filter((t) => t.state === st);
      return `
      <div class="col" data-state="${st}">
        <div class="col-h">${st} <span class="note">${rows.length}</span></div>
        ${rows.map((t) => `
          <div class="trow" draggable="true" data-id="${t.id}" data-state="${esc(t.state)}"
               data-title="${esc(t.title)}" data-due="${esc(t.due || '')}">
            <div class="trow-t">${esc(t.title)}</div>
            ${t.due ? `<div class="trow-due${this.overdue(t.due) ? ' od' : ''}">${esc(t.due)}${this.overdue(t.due) ? ' 已过' : ''}</div>` : ''}
            <div class="trow-b">
              <button class="next" title="挪到下一栏">→</button>
              <button class="due" title="设截止日">截止</button>
              <button class="pomo" title="为它开一个番茄钟">专注</button>
              <button class="del" title="删除">×</button>
            </div>
          </div>`).join('') || '<div class="note" style="padding:8px 0">空</div>'}
      </div>`;
    }).join('');

    // 79 里程碑
    q('#msSum').textContent = this.ms.length
      ? `${this.ms.filter((m) => m.done).length}/${this.ms.length} 完成 · 加权 ${p.ms_pct}%` : '';
    q('#msList').innerHTML = this.ms.length ? this.ms.map((m) => `
      <div class="mrow" data-id="${m.id}" data-done="${m.done ? 1 : 0}"
           data-pct="${m.pct || 0}" data-title="${esc(m.title)}" data-day="${esc(m.day || '')}"
           style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line-soft)">
        <div class="cb${m.done ? ' on' : ''}" title="标完成"></div>
        <div style="flex:1;min-width:0">
          <b style="font-weight:500${m.done ? ';text-decoration:line-through;opacity:.6' : ''}">${esc(m.title)}</b>
          ${m.day ? `<span class="tag">${esc(m.day)}</span>` : ''}
          <div class="bar-mini" style="margin-top:5px"><i style="width:${m.done ? 100 : (m.pct || 0)}%"></i></div>
        </div>
        <button class="pct note" style="border:0;background:transparent;cursor:pointer">${m.done ? 100 : (m.pct || 0)}%</button>
        <button class="del" style="border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
      </div>`).join('') : '<div class="note">还没有里程碑。定几个节点，进度就看得见了。</div>';

    this.renderLogs();

    if (this.tab === 'tasks') this.renderAllTasks();
    if (this.tab === 'timeline') this.renderTimeline();
  },

  // ---- 83 全部任务 ----

  async loadAllTasks() {
    const d = await api('/api/tasks/all');
    this.allTasks = d.rows || [];
    this.renderAllTasks();
  },

  renderAllTasks() {
    const el = this.el;
    const chips = ['', ...STATES];
    el.querySelector('#tfChips').innerHTML = chips.map((s) => `
      <button class="btn tag${this.taskFilter === s ? ' on' : ''}" data-f="${s}"
              style="height:26px;font-size:12px;border:0;cursor:pointer">${s || '全部'}</button>`).join('');
    const rows = this.taskFilter ? this.allTasks.filter((t) => t.state === this.taskFilter) : this.allTasks;
    const box = el.querySelector('#allList');
    if (!rows.length) { box.innerHTML = '<div class="note">没有任务。</div>'; return; }
    box.innerHTML = rows.map((t) => `
      <div class="trow-all" data-id="${t.id}" style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line-soft)">
        <span class="tag" style="border-left:3px solid ${colorOf(t.pcolor)}">${esc(t.project)}</span>
        <span style="flex:1;min-width:0">${esc(t.title)}</span>
        ${t.due ? `<span class="tag${this.overdue(t.due) ? ' err' : ''}">${esc(t.due)}</span>` : ''}
        <span class="tag${t.state === '已完成' ? ' ok' : t.state === '在做' ? ' on' : ''}">${esc(t.state)}</span>
        <button class="btn jump" data-pid="${t.project_id}" style="height:24px;font-size:11px">去项目</button>
      </div>`).join('');
    box.querySelectorAll('.jump').forEach((b) => {
      b.onclick = () => { this.setTab('proj'); this.select(+b.dataset.pid || 0); };
    });
  },

  // ---- 85 时间线 ----

  async loadTimeline() {
    const d = await api('/api/projects/timeline');
    this.timeline = d.rows || [];
    this.renderTimeline();
  },

  renderTimeline() {
    const box = this.el.querySelector('#tlBox');
    if (!box) return;
    const rows = this.timeline;
    if (!rows.length) { box.innerHTML = '<div class="note">还没有项目。</div>'; return; }
    // 全局范围
    const starts = rows.map((r) => r.start).filter(Boolean).sort();
    const ends = rows.map((r) => r.end).filter(Boolean).sort();
    const a = starts[0];
    const b = ends[ends.length - 1];
    const span = Math.max(1, diffDays(a, b));
    box.innerHTML = `
      <div class="note" style="margin-bottom:8px">${a} → ${b}（共 ${span + 1} 天）</div>
      ${rows.map((r) => {
        const s = r.start < a ? a : r.start;
        const e = r.end > b ? b : r.end;
        const left = Math.max(0, (diffDays(a, s) / span) * 100);
        const w = Math.max(2, ((diffDays(s, e) + 1) / span) * 100);
        return `<div class="gantt-row">
          <div class="gantt-name" title="${esc(r.name)}">${esc(r.name)}${r.archived ? ' (归档)' : ''}</div>
          <div class="gantt-track">
            <div class="gantt-bar" style="left:${left}%;width:${Math.min(w, 100 - left)}%;background:${colorOf(r.color)}"></div>
            ${(r.milestones || []).map((m) => {
              const pos = Math.max(0, Math.min(100, (diffDays(a, m.day) / span) * 100));
              return `<i class="gantt-ms${m.done ? ' done' : ''}" style="left:${pos}%"
                        title="里程碑：${esc(m.title)} · ${esc(m.day)}${m.done ? '（已完成）' : ''}"></i>`;
            }).join('')}
          </div>
          <div class="gantt-note">${r.tasks ? r.tasks.length + ' 个带截止的任务' : ''}</div>
        </div>`;
      }).join('')}`;
  },

  // ---- 操作 ----

  async addProj() {
    const q = (s) => this.el.querySelector(s);
    const name = q('#pName').value.trim();
    if (!name) return;
    const tpl = q('#pTpl').value;
    const r = await post('/api/projects/save', {
      name, status: '进行中', next_step: q('#pNext').value.trim(),
      deadline: q('#pDeadline').value || '', template: tpl === 'blank' ? '' : tpl,
    });
    q('#pName').value = ''; q('#pNext').value = '';
    toast(r.template ? '已添加，并套了模板' : '已添加');
    await this.load();
    this.select(r.id || 0);
  },

  async addTask() {
    const inp = this.el.querySelector('#tTitle');
    const title = inp.value.trim();
    if (!title) return;
    await post('/api/tasks/save', {
      project_id: this.cur, title,
      state: this.el.querySelector('#tState').value,
      due: this.el.querySelector('#tDue').value || '',
    });
    inp.value = '';
    this.load();
  },

  async addMs() {
    const q = (s) => this.el.querySelector(s);
    const title = q('#mTitle').value.trim();
    if (!title) return;
    const r = await post('/api/milestones/save', {
      project_id: this.cur, title, day: q('#mDay').value || '', pct: +q('#mPct').value || 0,
    });
    if (!r.ok) { toast(r.error || '没加上'); return; }
    q('#mTitle').value = '';
    toast('里程碑已加');
    this.load();
  },

  async archiveProj(id, on) {
    await post('/api/projects/archive', { id, on });
    toast(on ? '已归档，眼不见心不烦' : '放回来了');
    if (on && this.cur === id && !this.showArchived) this.cur = 0;
    this.load();
  },

  overdue(d) {
    return !!d && d < day();
  },

  async addLog(kind) {
    const inp = this.el.querySelector('#lText');
    const text = inp.value.trim();
    if (!text) return;
    await post('/api/plog/add', { project_id: this.cur, text, kind });
    inp.value = '';
    toast(kind === 'milestone' ? '里程碑已记' : '已记录');
    this.load();
  },

  async startPomo(taskId, title) {
    if (this.running) { toast('已经有一个在跑了'); return; }
    const r = await post('/api/pomodoro/start', { project_id: this.cur, task_id: taskId, title });
    this.running = { id: r.id, started: r.started, title };
    toast('开始计时，去干活');
    this.startTick();
    this.render();
  },

  async stopPomo() {
    const r = await post('/api/pomodoro/stop', { id: this.running.id });
    this.stopTick();
    this.running = null;
    const m = r.minutes || 0;
    toast(m < 1 ? `记下了 ${Math.round(m * 60)} 秒` : `记下了 ${m} 分钟`);
    this.load();
  },

  startTick() {
    this.stopTick();
    this.tick = setInterval(() => {
      const c = this.el.querySelector('#pomoClock');
      if (!c) { this.stopTick(); return; }
      c.textContent = this.fmt(this.elapsed());
    }, 1000);
  },

  stopTick() {
    if (this.tick) { clearInterval(this.tick); this.tick = null; }
  },

  elapsed() {
    return this.running ? (Date.now() / 1000) - this.running.started : 0;
  },

  fmt(sec) {
    const s = Math.max(0, Math.floor(sec));
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  },

  day(ts) {
    const d = new Date((ts || 0) * 1000);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  },

  onShow(pid) {
    if (pid) { this.tab = 'proj'; this.cur = +pid; }
    this.load();
  },

  badge(s) {
    const n = (s.counts && s.counts.tasks) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      { title: '加一个项目', hint: '项目', run: async () => {
        const name = prompt('项目名');
        if (!name) return;
        const r = await post('/api/projects/save', { name, status: '进行中', next_step: '' });
        window.WB.go('projects');
        await this.load();
        this.select(r.id || 0);
      } },
      { title: '加任务到当前项目', hint: '项目', run: async () => {
        if (!this.cur) { toast('先选一个项目'); return; }
        const title = prompt('任务名');
        if (!title) return;
        await post('/api/tasks/save', { project_id: this.cur, title, state: '待办' });
        this.load();
      } },
      { title: '开始 25 分钟专注', hint: '番茄钟', run: () => {
        if (!this.cur) { toast('先选一个项目'); return; }
        this.startPomo(0, '25 分钟专注');
      } },
      { title: '看项目时间线', hint: '项目', run: () => {
        window.WB.go('projects');
        this.setTab('timeline');
      } },
    ];
  },
};
