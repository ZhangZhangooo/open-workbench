/* 日历：月视图 + 周视图 + 重复日程 + 拖拽 + 统计 + ICS 导出 + 会议纪要。
   本地自建，不依赖任何日历服务。 */

const { api, post, toast, esc, day } = window.WB;

const WEEK = ['一', '二', '三', '四', '五', '六', '日'];

/* 77 颜色分类：色板（值存进 events.color） */
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

/* 73 重复规则 */
const REPEATS = [
  { v: '', n: '不重复' },
  { v: 'daily', n: '每天' },
  { v: 'weekdays', n: '工作日' },
  { v: 'weekly', n: '每周' },
  { v: 'monthly', n: '每月' },
  { v: 'yearly', n: '每年' },
];
const repeatName = (v) => (REPEATS.find((x) => x.v === (v || '')) || REPEATS[0]).n;

/* 75 提前提醒的档位（分钟） */
const REMINDS = [0, 5, 10, 15, 30, 60, 120, 1440];

const pad = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDay = (s) => {
  const [y, m, d] = (s || '').split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};
const addDays = (s, n) => {
  const d = parseDay(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
};
const mondayOf = (s) => {
  const d = parseDay(s);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return ymd(d);
};
const minOf = (s, e) => {
  const p = (t) => {
    const [h, m] = (t || '').split(':').map(Number);
    return (h || 0) * 60 + (m || 0);
  };
  const d = p(e) - p(s);
  return d > 0 ? d : 0;
};
const fmtMin = (m) => {
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h ? `${h} 小时${r ? ' ' + r + ' 分' : ''}` : `${r} 分`;
};

/* 周一开头的月历网格，返回 [{d,n,inMonth}] */
function monthGrid(y, m) {
  const first = new Date(y, m, 1);
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(y, m, 1 - lead);
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    cells.push({ d: ymd(d), n: d.getDate(), inMonth: d.getMonth() === m });
    if (i >= 34 && d.getMonth() !== m && (d.getDay() + 6) % 7 === 6) break;
  }
  return cells;
}

export default {
  id: 'cal',
  name: '日历',
  el: null,
  cur: null,         // {y, m}
  sel: null,         // 选中那天 YYYY-MM-DD
  view: 'month',     // 'month' | 'week'（71）
  rows: [],
  tasks: [],
  meets: [],
  editId: 0,         // 正在编辑的日程 id
  drag: null,        // 拖拽中的 {id, occ}
  stats: null,       // 74 统计缓存

  mount(el) {
    this.el = el;
    const now = new Date();
    this.cur = { y: now.getFullYear(), m: now.getMonth() };
    this.sel = day();

    el.innerHTML = `
      <div class="bar" style="padding-top:0;gap:6px">
        <button class="btn" id="cPrev" style="height:30px;padding:0 10px;font-size:12px">‹</button>
        <b id="cTitle" style="font-weight:500;font-size:14px;min-width:130px;text-align:center"></b>
        <button class="btn" id="cNext" style="height:30px;padding:0 10px;font-size:12px">›</button>
        <button class="btn" id="cToday" style="height:30px;padding:0 10px;font-size:12px">今天</button>
        <div style="display:flex;margin-left:8px;border:1px solid var(--line);border-radius:8px;overflow:hidden">
          <button class="btn" id="cMonth" style="height:30px;padding:0 10px;font-size:12px;border:0;border-radius:0">月</button>
          <button class="btn" id="cWeek" style="height:30px;padding:0 10px;font-size:12px;border:0;border-radius:0">周</button>
        </div>
        <button class="btn" id="cStats" style="height:30px;padding:0 10px;font-size:12px">统计</button>
        <a class="btn" id="cIcs" style="height:30px;padding:0 10px;font-size:12px;display:inline-flex;align-items:center">导出 ICS</a>
        <span style="margin-left:auto;font-size:12px;color:var(--ink-2)" id="cCount"></span>
      </div>
      <div id="cStatsBox" style="display:none"></div>
      <div class="stack">
        <div class="panel" id="cBoard"></div>
        <div class="panel">
          <h3 id="cDayTitle">这天</h3>
          <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:2;min-width:150px"><label>标题</label><input id="eTitle" placeholder="要做什么"></div>
            <div style="width:82px"><label>开始</label><input id="eStart" placeholder="14:00"></div>
            <div style="width:82px"><label>结束</label><input id="eEnd" placeholder="15:00"></div>
            <div style="width:104px"><label>重复</label><select id="eRepeat">${REPEATS.map((r) => `<option value="${r.v}">${r.n}</option>`).join('')}</select></div>
            <div style="width:132px"><label>重复截止</label><input id="eUntil" type="date" title="留空表示一直重复"></div>
          </div>
          <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
            <div style="width:120px"><label>颜色</label><select id="eColor">${COLORS.map((c) => `<option value="${c.v}">${c.n}</option>`).join('')}</select></div>
            <div style="width:150px"><label>提前提醒</label><select id="eRemind">${REMINDS.map((m) => `<option value="${m}">${m ? (m >= 60 ? `${m / 60} 小时` : `${m} 分钟`) : '不提醒'}</option>`).join('')}</select></div>
            <div style="flex:2;min-width:150px"><label>备注</label><input id="eNote" placeholder="可留空"></div>
          </div>
          <div class="bar" style="padding:0">
            <button class="btn primary" id="btnAddEv">加到这天</button>
            <button class="btn" id="btnCancelEd" style="display:none;height:30px;font-size:12px">取消编辑</button>
            <span class="note" style="margin-left:auto">提醒会同时弹桌面通知，并推送到已启用的连接器</span>
          </div>
          <div id="cList" style="margin-top:12px"></div>
        </div>
      </div>`;

    el.querySelector('#cPrev').onclick = () => this.shift(-1);
    el.querySelector('#cNext').onclick = () => this.shift(1);
    el.querySelector('#cToday').onclick = () => {
      const n = new Date();
      this.cur = { y: n.getFullYear(), m: n.getMonth() };
      this.sel = day();
      this.load();
    };
    el.querySelector('#cMonth').onclick = () => this.setView('month');
    el.querySelector('#cWeek').onclick = () => this.setView('week');
    el.querySelector('#cStats').onclick = () => this.toggleStats();
    el.querySelector('#btnAddEv').onclick = () => this.save();
    el.querySelector('#btnCancelEd').onclick = () => this.resetForm();
    ['eTitle', 'eNote'].forEach((id) => {
      el.querySelector('#' + id).addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.save();
      });
    });

    // 71 视图里点格子 = 选日期
    el.querySelector('#cBoard').addEventListener('click', (e) => {
      const c = e.target.closest('[data-d]');
      if (!c) return;
      if (e.target.closest('[data-act]')) return;
      if (e.target.closest('.ev-block')) return;
      this.sel = c.dataset.d;
      const cm = +c.dataset.d.slice(5, 7) - 1;
      if (!c.dataset.in || cm !== this.cur.m) this.cur = { y: +c.dataset.d.slice(0, 4), m: cm };
      this.load();
      const t = this.el.querySelector('#eTitle');
      if (t) t.focus();
    });

    // 72 拖拽改时间：把事件块拖到别的日期
    const board = el.querySelector('#cBoard');
    board.addEventListener('dragstart', (e) => {
      const b = e.target.closest('.ev-block');
      if (!b) return;
      this.drag = { id: +b.dataset.id, occ: b.dataset.occ };
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', JSON.stringify(this.drag)); } catch (_) { /* 忽略 */ }
      b.classList.add('dragging');
    });
    board.addEventListener('dragend', (e) => {
      const b = e.target.closest('.ev-block');
      if (b) b.classList.remove('dragging');
      this.drag = null;
    });
    board.addEventListener('dragover', (e) => {
      const c = e.target.closest('[data-d]');
      if (!c || !this.drag) return;
      e.preventDefault();
      c.classList.add('drop-hint');
    });
    board.addEventListener('dragleave', (e) => {
      const c = e.target.closest('[data-d]');
      if (c) c.classList.remove('drop-hint');
    });
    board.addEventListener('drop', (e) => {
      const c = e.target.closest('[data-d]');
      if (!c) return;
      board.querySelectorAll('.drop-hint').forEach((x) => x.classList.remove('drop-hint'));
      e.preventDefault();
      let g = this.drag;
      try { g = JSON.parse(e.dataTransfer.getData('text/plain')) || g; } catch (_) { /* 用 this.drag */ }
      if (!g || !g.id) return;
      this.move(g.id, g.occ, c.dataset.d);
    });

    // 78 会议纪要 / 单次删除 / 完成 / 编辑
    el.querySelector('#cList').addEventListener('click', (e) => this.rowClick(e));

    this.load();
  },

  setView(v) {
    this.view = v;
    this.el.querySelector('#cMonth').classList.toggle('active', v === 'month');
    this.el.querySelector('#cWeek').classList.toggle('active', v === 'week');
    this.load();
  },

  shift(n) {
    if (this.view === 'week') {
      this.sel = addDays(this.sel, n * 7);
      this.cur = { y: +this.sel.slice(0, 4), m: +this.sel.slice(5, 7) - 1 };
    } else {
      let { y, m } = this.cur;
      m += n;
      if (m < 0) { m = 11; y -= 1; }
      if (m > 11) { m = 0; y += 1; }
      this.cur = { y, m };
    }
    this.load();
  },

  win() {
    // 当前视图对应的取数窗口
    if (this.view === 'week') {
      const a = mondayOf(this.sel);
      return { a, b: addDays(a, 6) };
    }
    const a = `${this.cur.y}-${pad(this.cur.m + 1)}-01`;
    const b = ymd(new Date(this.cur.y, this.cur.m + 1, 0));
    return { a, b };
  },

  async load() {
    const el = this.el;
    if (!el || !el.querySelector('#cBoard')) return;
    const { a, b } = this.win();
    const d = await api(`/api/events?from=${a}&to=${b}`);
    this.rows = d.rows || [];
    this.tasks = d.tasks || [];
    const mres = await api(`/api/meetings?month=${this.cur.y}-${pad(this.cur.m + 1)}`);
    this.meets = (mres.rows || []).filter((m) => m.day >= a && m.day <= b);

    if (this.view === 'week') this.renderWeek();
    else this.renderMonth();
    this.renderDay();
    el.querySelector('#cIcs').href = `/api/events/ics?from=${a}&to=${b}`;
  },

  /* ---------- 月视图 ---------- */
  renderMonth() {
    const el = this.el;
    const byDay = this.byDay();
    el.querySelector('#cTitle').textContent = `${this.cur.y} 年 ${this.cur.m + 1} 月`;
    el.querySelector('#cBoard').innerHTML =
      `<div class="cal-head">${WEEK.map((w) => `<div class="cal-w">${w}</div>`).join('')}</div>
       <div class="cal-grid" id="cGrid">${monthGrid(this.cur.y, this.cur.m).map((c) => {
        const list = byDay[c.d] || [];
        const undone = list.filter((r) => !r.done).length;
        const nt = list.filter((r) => r._t).length;
        const cols = [...new Set(list.map((r) => r.color).filter(Boolean))].slice(0, 3);
        return `<div class="cal-cell${c.inMonth ? '' : ' out'}${c.d === this.sel ? ' sel' : ''}${c.d === day() ? ' today' : ''}"
                     data-d="${c.d}"${c.inMonth ? ' data-in="1"' : ''}>
          <div class="cal-n">${c.n}</div>
          ${list.length ? `<div class="cal-dots">${undone ? '<i class="on"></i>' : '<i></i>'}${nt ? '<i class="t"></i>' : ''}
            ${cols.map((v) => `<i style="background:${colorOf(v)}"></i>`).join('')}
            ${list.length > 1 ? `<span class="cal-n2">${list.length}</span>` : ''}</div>` : ''}
        </div>`;
      }).join('')}</div>`;
    el.querySelector('#cCount').textContent =
      `${this.rows.length} 条日程 · ${this.meets.length} 个会议 · ${this.tasks.length} 个到期任务`;
  },

  /* ---------- 71 周视图 ---------- */
  renderWeek() {
    const el = this.el;
    const mon = mondayOf(this.sel);
    const a = mon;
    const b = addDays(mon, 6);
    const byDay = this.byDay();
    el.querySelector('#cTitle').textContent = `${a.slice(5)} ~ ${b.slice(5)}（本周）`;
    const days = Array.from({ length: 7 }, (_, i) => addDays(a, i));
    el.querySelector('#cBoard').innerHTML =
      `<div class="wk-grid">${days.map((ds, i) => {
        const list = (byDay[ds] || []).slice().sort((x, y) => (x.start || '').localeCompare(y.start || ''));
        return `<div class="wk-col${ds === this.sel ? ' sel' : ''}${ds === day() ? ' today' : ''}" data-d="${ds}" data-in="1">
          <div class="wk-head"><b>周${WEEK[i]}</b><span>${ds.slice(5)}</span></div>
          <div class="wk-body">
            ${list.length ? list.map((r) => this.blockHtml(r, ds)).join('') : '<div class="note" style="font-size:11px">—</div>'}
          </div>
        </div>`;
      }).join('')}</div>`;
    el.querySelector('#cCount').textContent =
      `本周 ${this.rows.length} 条 · 拖动色块可改日期`;
  },

  blockHtml(r, ds) {
    const kind = r._m ? 'meet' : r._t ? 'task' : 'ev';
    const col = r._m ? '#2f6feb' : r._t ? '#d4a72c' : colorOf(r.color);
    const time = r.start ? `${esc(r.start)}${r.end ? '–' + esc(r.end) : ''}` : '';
    const flags = [];
    if (r.repeat) flags.push(`<span class="ev-f">${repeatName(r.repeat)}</span>`);
    if (r.virtual && !r._m && !r._t) flags.push('<span class="ev-f">某次</span>');
    return `<div class="ev-block" data-id="${r.id}" data-occ="${ds}" data-kind="${kind}"
                 ${kind === 'ev' ? 'draggable="true"' : ''}
                 style="border-left:3px solid ${col}">
      <div class="ev-t">${time || '全天'}</div>
      <div class="ev-x">${esc(r.title)}${flags.join('')}</div>
    </div>`;
  },

  byDay() {
    const m = {};
    this.rows.forEach((r) => { (m[r.day] = m[r.day] || []).push(r); });
    this.tasks.forEach((t) => { (m[t.due] = m[t.due] || []).push({ ...t, _t: 1, day: t.due }); });
    this.meets.forEach((mt) => { (m[mt.day] = m[mt.day] || []).push({ ...mt, _m: 1, day: mt.day }); });
    return m;
  },

  renderDay() {
    const el = this.el;
    const byDay = this.byDay();
    const rows = (byDay[this.sel] || []).slice().sort((x, y) => (x.start || '').localeCompare(y.start || ''));
    const minutes = rows.reduce((s, r) => s + minOf(r.start, r.end), 0);
    el.querySelector('#cDayTitle').textContent =
      `${this.sel} · ${rows.length ? `${rows.length} 条 · 共 ${fmtMin(minutes)}` : '还没有安排'}`;
    const box = el.querySelector('#cList');
    if (!rows.length) {
      box.innerHTML = '<div class="note">这天是空的。上面填一条加进来。</div>';
      return;
    }
    box.innerHTML = rows.map((r) => {
      if (r._t) {
        return `<div class="erow task" data-id="${r.id}" data-kind="task" data-pid="${r.project_id || 0}">
          <div class="cb" title="标成已完成"></div>
          <div class="tx"><b>${esc(r.title)}</b><span class="tag">到期</span>
            <button class="jump tag" data-act="jump" style="border:0;cursor:pointer">${esc(r.project || '未挂项目')}</button>
            <div class="note" style="margin-top:3px">状态：${esc(r.state)}</div></div>
        </div>`;
      }
      if (r._m) {
        return `<div class="erow" data-id="${r.id}" data-kind="meet">
          <div class="tx" style="border-left:3px solid #2f6feb;padding-left:8px">
            <b>${esc(r.title)}</b><span class="tag">会议</span>
            ${r.start ? `<span class="tag">${esc(r.start)}${r.end ? '–' + esc(r.end) : ''}</span>` : ''}
            ${r.location ? `<span class="tag">📍${esc(r.location)}</span>` : ''}
            ${r.link ? `<a class="tag" href="${esc(r.link)}" target="_blank" rel="noopener">入会</a>` : ''}
            ${r.attendees ? `<div class="note" style="margin-top:3px">参会：${esc(r.attendees)}</div>` : ''}
          </div>
          <button class="btn" data-act="minutes" data-id="${r.id}" style="height:26px;font-size:12px">纪要</button>
          <button class="del" data-act="del">删除</button>
        </div>`;
      }
      const tags = [];
      if (r.repeat) tags.push(`<span class="tag">${repeatName(r.repeat)}${r.repeat_until ? ' 至 ' + esc(r.repeat_until) : ''}</span>`);
      if (r.virtual) tags.push('<span class="tag">重复中的某次</span>');
      if (r.remind_before) tags.push(`<span class="tag">提前 ${r.remind_before >= 60 ? r.remind_before / 60 + ' 小时' : r.remind_before + ' 分钟'}</span>`);
      return `<div class="erow${r.done ? ' done' : ''}" data-id="${r.id}" data-kind="ev" data-occ="${r.occ || r.day}">
        <div class="cb" data-act="done"></div>
        <div class="tx" style="border-left:3px solid ${colorOf(r.color)};padding-left:8px">
          <b>${esc(r.title)}</b>
          ${r.start ? `<span class="tag">${esc(r.start)}${r.end ? '–' + esc(r.end) : ''}</span>` : ''}
          ${tags.join('')}
          ${r.note ? `<div class="note" style="margin-top:3px">${esc(r.note)}</div>` : ''}
        </div>
        <button class="btn" data-act="edit" style="height:26px;font-size:12px">改</button>
        ${r.virtual ? '<button class="del" data-act="exdate">删这次</button>' : '<button class="del" data-act="del">删除</button>'}
      </div>`;
    }).join('');
  },

  async rowClick(e) {
    const row = e.target.closest('.erow');
    if (!row) return;
    const id = +row.dataset.id;
    const act = (e.target.closest('[data-act]') || {}).dataset
      ? e.target.closest('[data-act]').dataset.act
      : (e.target.closest('.cb') ? 'done' : e.target.closest('.del') ? 'del' : '');
    if (row.dataset.kind === 'task') {
      if (e.target.closest('.cb')) {
        await post('/api/tasks/state', { id, state: '已完成' });
        toast('任务完成');
        this.load();
      } else if (e.target.closest('[data-act="jump"]')) {
        window.WB.go('projects', +row.dataset.pid || 0);
      }
      return;
    }
    if (row.dataset.kind === 'meet') {
      if (act === 'minutes') return this.minutes(id);
      if (act === 'del') { await post('/api/meetings/del', { id }); this.load(); }
      return;
    }
    if (act === 'edit') return this.startEdit(id);
    if (act === 'exdate') {
      const r = await post('/api/events/exdate', { id, day: row.dataset.occ });
      toast(r.ok ? '这一次删掉了' : (r.error || '没删掉'));
      return this.load();
    }
    if (act === 'del' || e.target.closest('.del')) {
      await post('/api/events/del', { id });
      return this.load();
    }
    if (act === 'done' || e.target.closest('.cb')) {
      await post('/api/events/done', { id, done: row.classList.contains('done') ? 0 : 1 });
      return this.load();
    }
  },

  /* 72 拖拽落点 */
  async move(id, occ, toDay) {
    if (!toDay || toDay === occ) return;
    const r = await post('/api/events/move', { id, occ, day: toDay });
    if (!r.ok) { toast(r.error || '没挪成'); return; }
    toast(r.moved === 'split' ? '这一次挪到 ' + toDay + '（已单独成条）' : '已挪到 ' + toDay);
    this.load();
  },

  startEdit(id) {
    const r = this.rows.find((x) => x.id === id) || {};
    const el = this.el;
    this.editId = id;
    this.sel = r.base_day || r.day || this.sel;
    el.querySelector('#eTitle').value = r.title || '';
    el.querySelector('#eStart').value = r.start || '';
    el.querySelector('#eEnd').value = r.end || '';
    el.querySelector('#eNote').value = r.note || '';
    el.querySelector('#eRepeat').value = r.repeat || '';
    el.querySelector('#eUntil').value = r.repeat_until || '';
    el.querySelector('#eColor').value = r.color || '';
    el.querySelector('#eRemind').value = String(r.remind_before || 0);
    el.querySelector('#btnAddEv').textContent = '保存修改';
    el.querySelector('#btnCancelEd').style.display = '';
    el.querySelector('#eTitle').focus();
  },

  resetForm() {
    const el = this.el;
    this.editId = 0;
    ['eTitle', 'eStart', 'eEnd', 'eNote', 'eUntil'].forEach((i) => { el.querySelector('#' + i).value = ''; });
    el.querySelector('#eRepeat').value = '';
    el.querySelector('#eColor').value = '';
    el.querySelector('#eRemind').value = '0';
    el.querySelector('#btnAddEv').textContent = '加到这天';
    el.querySelector('#btnCancelEd').style.display = 'none';
  },

  async save() {
    const el = this.el;
    const title = el.querySelector('#eTitle').value.trim();
    if (!title) { toast('标题得填'); return; }
    const body = {
      day: this.sel,
      start: el.querySelector('#eStart').value.trim(),
      end: el.querySelector('#eEnd').value.trim(),
      title,
      note: el.querySelector('#eNote').value.trim(),
      repeat: el.querySelector('#eRepeat').value,
      repeat_until: el.querySelector('#eUntil').value,
      color: el.querySelector('#eColor').value,
      remind_before: +el.querySelector('#eRemind').value || 0,
    };
    if (this.editId) body.id = this.editId;
    const r = await post('/api/events/save', body);
    if (!r.ok) { toast(r.error || '没存上'); return; }
    toast(this.editId ? '改好了' : '已加到 ' + this.sel);
    this.resetForm();
    this.load();
  },

  /* 74 时长统计 */
  async toggleStats() {
    const box = this.el.querySelector('#cStatsBox');
    if (box.style.display !== 'none') { box.style.display = 'none'; return; }
    const period = this.view === 'week' ? 'week' : 'month';
    const d = await api(`/api/events/stats?period=${period}`);
    this.stats = d;
    const max = Math.max(1, ...(d.days || []).map((x) => x.min));
    box.style.display = '';
    box.innerHTML = `<div class="panel" style="margin-bottom:12px">
      <div class="bar" style="padding-top:0">
        <b style="font-size:13px">${period === 'week' ? '本周' : '本月'}时长统计</b>
        <span class="note" style="margin-left:auto">${esc(d.from)} ~ ${esc(d.to)}</span>
      </div>
      <div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px;margin:6px 0 10px">
        <span>日程 <b>${fmtMin(d.event_min || 0)}</b>（${d.event_n || 0} 条）</span>
        <span>会议 <b>${fmtMin(d.meet_min || 0)}</b>（${d.meet_n || 0} 场）</span>
        <span>合计 <b>${fmtMin(d.total_min || 0)}</b></span>
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        ${(d.days || []).map((x) => `<div style="display:flex;align-items:center;gap:8px;font-size:11px">
          <span style="width:78px;color:var(--ink-2)">${esc(x.day)}</span>
          <span style="flex:1;background:var(--hover);border-radius:4px;height:10px;overflow:hidden">
            <span style="display:block;height:100%;width:${Math.round((x.min / max) * 100)}%;background:var(--accent)"></span>
          </span>
          <span style="width:70px;text-align:right">${fmtMin(x.min)}</span>
        </div>`).join('') || '<div class="note">这段没有安排。</div>'}
      </div>
    </div>`;
  },

  /* 78 会议纪要：拉提示词 → 交给 OpenClaw 写 → 结果可存进资料库 */
  async minutes(id) {
    const el = this.el;
    const d = await api(`/api/meetings/minutes?id=${id}`);
    if (!d.ok) { toast(d.error || '取不到会议'); return; }
    let box = el.querySelector('#cMinBox');
    if (!box) {
      box = document.createElement('div');
      box.id = 'cMinBox';
      el.querySelector('#cList').after(box);
    }
    box.innerHTML = `<div class="panel" style="margin-top:12px">
      <div class="bar" style="padding-top:0">
        <b style="font-size:13px">会议纪要 · ${esc(d.row.title || '')}</b>
        <button class="btn primary" id="cMinRun" style="height:28px;font-size:12px;margin-left:auto">让 AI 写纪要</button>
        <button class="btn" id="cMinClose" style="height:28px;font-size:12px">收起</button>
      </div>
      <pre class="note" style="white-space:pre-wrap;font-size:12px;max-height:150px;overflow:auto">${esc(d.prompt)}</pre>
      <div id="cMinOut"></div>
    </div>`;
    box.querySelector('#cMinClose').onclick = () => box.remove();
    box.querySelector('#cMinRun').onclick = async () => {
      const out = box.querySelector('#cMinOut');
      out.innerHTML = '<div class="note">正在让 OpenClaw 写，可能要一会儿…</div>';
      const r = await post('/api/openclaw', { task: d.prompt, ctx: false, timeout: 240 });
      if (!r.ok) { out.innerHTML = `<div class="note err">失败：${esc(r.error || '未知')}</div>`; return; }
      const txt = r.reply || '';
      out.innerHTML = `<textarea id="cMinText" style="width:100%;min-height:180px;font-size:12px">${esc(txt)}</textarea>
        <div class="bar" style="padding:6px 0 0">
          <button class="btn" id="cMinKb">存进资料库</button>
          <button class="btn" id="cMinDl">存成文档</button>
        </div>`;
      out.querySelector('#cMinKb').onclick = async () => {
        const body = out.querySelector('#cMinText').value;
        const rr = await post('/api/kb/save', { title: '会议纪要 · ' + (d.row.title || '') + ' · ' + (d.row.day || ''), body, tags: '会议纪要' });
        toast(rr.ok ? '已存进资料库' : (rr.error || '没存上'));
      };
      out.querySelector('#cMinDl').onclick = async () => {
        const rr = await post('/api/docs/make', {
          kind: 'word', title: '会议纪要 · ' + (d.row.title || ''),
          md: out.querySelector('#cMinText').value,
        });
        toast(rr.ok ? '已生成文档：' + (rr.file || rr.url || '') : (rr.error || '没生成'));
      };
    };
  },

  onShow() {
    this.load();
  },

  badge(s) {
    const n = (s.counts && s.counts.events) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      { title: '给今天加个日程', hint: '日历', run: async () => {
        const t = prompt('要做什么');
        if (!t) return;
        window.WB.go('cal');
        this.sel = day();
        await post('/api/events/save', { day: this.sel, title: t, start: '', end: '', note: '' });
        this.load();
      } },
      { title: '看本周时长统计', hint: '日历', run: async () => {
        window.WB.go('cal');
        this.view = 'week';
        this.setView('week');
        const box = this.el.querySelector('#cStatsBox');
        if (box.style.display === 'none') await this.toggleStats();
      } },
      { title: '导出日历 ICS', hint: '日历', run: () => {
        const { a, b } = this.win();
        window.open(`/api/events/ics?from=${a}&to=${b}`, '_blank');
      } },
    ];
  },
};
