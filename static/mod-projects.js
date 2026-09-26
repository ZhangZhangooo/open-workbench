/* 项目任务域：项目卡片 → 任务看板 → 番茄钟 → 迭代记录 */

const { api, post, toast, esc } = window.WB;

const STATUS = ['进行中', '待启动', '摸索中', '卡住了', '已完成'];
const STATES = ['待办', '在做', '已完成'];

export default {
  id: 'projects',
  name: '项目',
  el: null,
  projs: [],
  tasks: [],
  logs: [],
  cur: 0,          // 当前选中的项目 id
  tick: null,
  running: null,   // 正在跑的番茄钟
  today: { minutes: 0, count: 0 },

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <h3 style="margin:0">项目</h3>
            <span id="pomoToday" class="tag" style="margin-left:auto"></span>
          </div>
          <div id="projList" class="note" style="margin-top:8px">加载中…</div>
          <div class="field-row" style="margin-top:10px">
            <input id="pName" placeholder="新项目名，例如 voxelcraft" style="flex:1">
            <input id="pNext" placeholder="下一步做什么" style="flex:1">
            <button class="btn primary" id="btnAddProj">添加</button>
          </div>
        </div>

        <div id="detail" style="display:none">
          <div class="panel">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <h3 id="dTitle" style="margin:0"></h3>
              <span id="dStat" class="tag" style="cursor:pointer"></span>
              <div id="dPomo" style="margin-left:auto;display:flex;align-items:center;gap:8px"></div>
            </div>
            <div class="field-row" style="margin-top:10px">
              <input id="tTitle" placeholder="加一个任务，回车即可" style="flex:1">
              <select id="tState">
                ${STATES.map((s) => `<option>${s}</option>`).join('')}
              </select>
              <input id="tDue" type="date" title="截止日，留空就是不限" style="width:140px">
              <button class="btn primary" id="btnAddTask">加任务</button>
            </div>
          </div>

          <div class="board" id="board"></div>

          <div class="panel">
            <div style="display:flex;align-items:center;gap:10px">
              <h3 style="margin:0">迭代记录</h3>
              <span class="note">做完什么、卡在哪、下一步，随手记一句</span>
            </div>
            <div class="field-row" style="margin-top:10px">
              <input id="lText" placeholder="今天推进了什么（回车记录）" style="flex:1">
              <button class="btn" id="btnMilestone">记为里程碑</button>
              <button class="btn primary" id="btnAddLog">记一条</button>
            </div>
            <div id="logList" style="margin-top:10px"></div>
          </div>
        </div>
      </div>`;

    const q = (s) => el.querySelector(s);

    q('#btnAddProj').onclick = async () => {
      const name = q('#pName').value.trim();
      if (!name) return;
      const r = await post('/api/projects/save', {
        name, status: '进行中', next_step: q('#pNext').value.trim(),
      });
      q('#pName').value = ''; q('#pNext').value = '';
      toast('已添加');
      await this.load();
      this.select(r.id || 0);
    };
    q('#pName').onkeydown = (e) => { if (e.key === 'Enter') q('#btnAddProj').click(); };

    q('#btnAddTask').onclick = () => this.addTask();
    q('#tTitle').onkeydown = (e) => { if (e.key === 'Enter') this.addTask(); };
    q('#btnAddLog').onclick = () => this.addLog('log');
    q('#btnMilestone').onclick = () => this.addLog('milestone');
    q('#lText').onkeydown = (e) => { if (e.key === 'Enter') this.addLog('log'); };

    q('#projList').addEventListener('click', (e) => {
      const row = e.target.closest('.prow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.del')) {
        if (!confirm(`删掉「${row.dataset.name}」？任务和记录一起没。`)) return;
        post('/api/projects/del', { id }).then(() => {
          if (this.cur === id) this.cur = 0;
          this.load();
        });
        return;
      }
      if (e.target.closest('.st')) {
        const i = STATUS.indexOf(row.dataset.status);
        post('/api/projects/save', {
          id, name: row.dataset.name,
          status: STATUS[(i + 1) % STATUS.length],
          next_step: row.dataset.next,
        }).then(() => this.load());
        return;
      }
      this.select(id);
    });

    q('#board').addEventListener('click', async (e) => {
      const t = e.target.closest('.trow');
      if (!t) return;
      const id = +t.dataset.id;
      if (e.target.closest('.del')) {
        await post('/api/tasks/del', { id });
      } else if (e.target.closest('.next')) {
        const i = STATES.indexOf(t.dataset.state);
        const to = STATES[(i + 1) % STATES.length];
        await post('/api/tasks/state', { id, state: to });
        if (to === '已完成') toast('搞定一件');
      } else if (e.target.closest('.pomo')) {
        this.startPomo(id, t.dataset.title);
        return;
      } else if (e.target.closest('.due')) {
        const v = prompt('截止日（YYYY-MM-DD，留空清除）', t.dataset.due || '');
        if (v === null) return;
        await post('/api/tasks/due', { id, due: v.trim() });
        this.load();
        return;
      } else {
        return;
      }
      this.load();
    });

    q('#logList').addEventListener('click', async (e) => {
      const del = e.target.closest('.del');
      if (!del) return;
      await post('/api/plog/del', { id: +del.dataset.id });
      this.load();
    });

    this.load();
  },

  // ---- 数据 ----

  async load() {
    const [p, t] = await Promise.all([api('/api/projects'), api('/api/tasks?project_id=0')]);
    this.projs = p.rows || [];
    this.tasks = t.rows || [];
    this.running = t.running || null;
    this.today = t.today || { minutes: 0, count: 0 };
    if (!this.cur && this.projs.length) this.cur = this.projs[0].id;
    if (this.cur) {
      const l = await api('/api/plog?project_id=' + this.cur);
      this.logs = l.rows || [];
    }
    this.render();
  },

  select(id) {
    this.cur = id;
    this.load();
  },

  // ---- 渲染 ----

  render() {
    const el = this.el;
    const q = (s) => el.querySelector(s);

    q('#pomoToday').textContent = `今天专注 ${this.today.minutes} 分钟 · ${this.today.count} 个番茄`;

    // 项目卡片
    if (!this.projs.length) {
      q('#projList').innerHTML = '<div class="note">还没有项目。上面加一个，比如 voxelcraft。</div>';
    } else {
      q('#projList').innerHTML = this.projs.map((p) => {
        const pct = p.n_task ? Math.round(p.n_done / p.n_task * 100) : 0;
        return `
        <div class="prow ${p.id === this.cur ? 'on' : ''}" data-id="${p.id}"
             data-status="${esc(p.status || '')}" data-name="${esc(p.name || '')}"
             data-next="${esc(p.next_step || '')}" style="padding:10px;border-bottom:1px solid var(--line-soft)">
          <div style="display:flex;align-items:center;gap:10px">
            <b style="font-weight:500">${esc(p.name)}</b>
            <button class="st tag" style="border:0;cursor:pointer">${esc(p.status || '未设')}</button>
            <span class="note">${p.n_done}/${p.n_task} 已完成 · ${p.mins} 分钟</span>
            <button class="del" style="margin-left:auto;border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
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

    // 番茄钟控件
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

    // 看板
    const mine = this.tasks.filter((t) => t.project_id === this.cur);
    q('#board').innerHTML = STATES.map((st) => {
      const rows = mine.filter((t) => t.state === st);
      return `
      <div class="col">
        <div class="col-h">${st} <span class="note">${rows.length}</span></div>
        ${rows.map((t) => `
          <div class="trow" data-id="${t.id}" data-state="${esc(t.state)}"
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

    // 迭代记录
    q('#logList').innerHTML = this.logs.length ? this.logs.map((l) => `
      <div class="lrow ${l.kind === 'milestone' ? 'ms' : ''}" style="padding:8px 0;border-bottom:1px solid var(--line-soft)">
        <div style="display:flex;gap:8px;align-items:baseline">
          <span class="note">${this.day(l.created)}</span>
          ${l.kind === 'milestone' ? '<span class="tag on">里程碑</span>' : ''}
          <span style="flex:1">${esc(l.text)}</span>
          <button class="del" data-id="${l.id}" style="border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
        </div>
      </div>`).join('') : '<div class="note">还没记过。做完一件事就写一句，将来回看很有用。</div>';
  },

  // ---- 操作 ----

  async addTask() {
    const inp = this.el.querySelector('#tTitle');
    const title = inp.value.trim();
    if (!title) return;
    await post('/api/tasks/save', {
      project_id: this.cur,
      title,
      state: this.el.querySelector('#tState').value,
      due: this.el.querySelector('#tDue').value || '',
    });
    inp.value = '';
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
    const r = await post('/api/pomodoro/start', {
      project_id: this.cur, task_id: taskId, title,
    });
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
    if (!this.running) return 0;
    return (Date.now() / 1000) - this.running.started;
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
    if (pid) this.cur = +pid;   // 从日历点任务跳过来时带上项目 id
    this.load();
  },

  onHide() {
    // 计时器留着，别因为切页面就停
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
    ];
  },
};
