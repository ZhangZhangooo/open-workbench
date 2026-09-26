/* 日历：月视图 + 当天日程。本地自建，不依赖任何日历服务。 */

const { api, post, toast, esc, day } = window.WB;

const WEEK = ['一', '二', '三', '四', '五', '六', '日'];

/* 周一开头的月历网格，返回 [{d:'YYYY-MM-DD', inMonth:bool}] */
function monthGrid(y, m) {
  const first = new Date(y, m, 1);
  // getDay(): 0=周日。换算成周一开头：0->6, 1->0 ...
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(y, m, 1 - lead);
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    cells.push({
      d: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
      n: d.getDate(),
      inMonth: d.getMonth() === m,
    });
    if (i >= 34 && d.getMonth() !== m && (d.getDay() + 6) % 7 === 6) break;
  }
  return cells;
}

export default {
  id: 'cal',
  name: '日历',
  el: null,
  cur: null,      // {y, m}
  sel: null,      // 选中的那天 YYYY-MM-DD
  rows: [],
  tasks: [],

  mount(el) {
    this.el = el;
    const now = new Date();
    this.cur = { y: now.getFullYear(), m: now.getMonth() };
    this.sel = day();

    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <button class="btn" id="cPrev" style="height:30px;padding:0 10px;font-size:12px">上个月</button>
        <b id="cTitle" style="font-weight:500;font-size:14px;min-width:110px;text-align:center"></b>
        <button class="btn" id="cNext" style="height:30px;padding:0 10px;font-size:12px">下个月</button>
        <button class="btn" id="cToday" style="height:30px;padding:0 10px;font-size:12px">回今天</button>
        <span style="margin-left:auto;font-size:12px;color:var(--ink-2)" id="cCount"></span>
      </div>
      <div class="stack">
        <div class="panel">
          <div class="cal-head">
            ${WEEK.map((w) => `<div class="cal-w">${w}</div>`).join('')}
          </div>
          <div class="cal-grid" id="cGrid"></div>
        </div>
        <div class="panel">
          <h3 id="cDayTitle">这天</h3>
          <div class="field" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
            <div style="flex:2;min-width:150px"><label>标题</label><input id="eTitle" placeholder="要做什么"></div>
            <div style="width:88px"><label>开始</label><input id="eStart" placeholder="14:00"></div>
            <div style="width:88px"><label>结束</label><input id="eEnd" placeholder="15:00"></div>
          </div>
          <div class="field"><label>备注</label><input id="eNote" placeholder="可留空"></div>
          <button class="btn primary" id="btnAddEv">加到这天</button>
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

    el.querySelector('#cGrid').addEventListener('click', (e) => {
      const c = e.target.closest('[data-d]');
      if (!c) return;
      this.sel = c.dataset.d;
      // 点的是上/下个月的格子，顺手翻页
      const cm = +c.dataset.d.slice(5, 7) - 1;
      if (!c.dataset.in || cm !== this.cur.m) {
        this.cur = { y: +c.dataset.d.slice(0, 4), m: cm };
      }
      this.load();
      el.querySelector('#eTitle').focus();
    });

    el.querySelector('#btnAddEv').onclick = () => this.add();
    el.querySelector('#eTitle').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.add();
    });
    el.querySelector('#eNote').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.add();
    });
    el.querySelector('#cList').addEventListener('click', async (e) => {
      const row = e.target.closest('.erow');
      if (!row) return;
      const id = +row.dataset.id;
      // 到期的任务：点圆圈 = 标完成，点项目名 = 跳到项目页
      if (row.dataset.kind === 'task') {
        if (e.target.closest('.cb')) {
          await post('/api/tasks/state', { id, state: '已完成' });
          toast('任务完成');
          this.load();
        } else if (e.target.closest('.jump')) {
          window.WB.go('projects', +row.dataset.pid || 0);
        }
        return;
      }
      if (row.dataset.kind === 'meet') {
        if (e.target.closest('.del')) { await post('/api/meetings/del', { id }); this.load(); }
        return;
      }
      const x = e.target.closest('.del');
      const cb = e.target.closest('.cb');
      if (!x && !cb) return;
      if (x) await post('/api/events/del', { id });
      else await post('/api/events/done', { id, done: row.classList.contains('done') ? 0 : 1 });
      this.load();
    });

    this.load();
  },

  shift(n) {
    let { y, m } = this.cur;
    m += n;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    this.cur = { y, m };
    this.load();
  },

  async load() {
    const el = this.el;
    const month = `${this.cur.y}-${String(this.cur.m + 1).padStart(2, '0')}`;
    const d = await api(`/api/events?month=${month}`);
    this.rows = d.rows || [];
    this.tasks = d.tasks || [];
    const mres = await api(`/api/meetings?month=${month}`);
    const meets = mres.rows || [];

    el.querySelector('#cTitle').textContent = `${this.cur.y} 年 ${this.cur.m + 1} 月`;

    const byDay = {};
    this.rows.forEach((r) => {
      (byDay[r.day] = byDay[r.day] || []).push(r);
    });
    // 到期的任务当作「那一天的事」混进来，标记 _t 以便区分
    this.tasks.forEach((t) => {
      (byDay[t.due] = byDay[t.due] || []).push({ ...t, _t: 1, day: t.due });
    });
    meets.forEach((mt) => {
      (byDay[mt.day] = byDay[mt.day] || []).push({ ...mt, _m: 1, day: mt.day });
    });

    el.querySelector('#cGrid').innerHTML = monthGrid(this.cur.y, this.cur.m).map((c) => {
      const n = (byDay[c.d] || []).length;
      const undone = (byDay[c.d] || []).filter((r) => !r.done).length;
      const nt = (byDay[c.d] || []).filter((r) => r._t).length;
      return `<div class="cal-cell${c.inMonth ? '' : ' out'}${c.d === this.sel ? ' sel' : ''}${c.d === day() ? ' today' : ''}"
                   data-d="${c.d}"${c.inMonth ? ' data-in="1"' : ''}>
        <div class="cal-n">${c.n}</div>
        ${n ? `<div class="cal-dots">${undone ? `<i class="on"></i>` : '<i></i>'}${nt ? `<i class="t"></i>` : ''}${n > 1 ? `<span class="cal-n2">${n}</span>` : ''}</div>` : ''}
      </div>`;
    }).join('');

    this.renderDay(byDay);
    el.querySelector('#cCount').textContent =
      `本月 ${this.rows.length} 条日程 · ${meets.length} 个会议 · ${this.tasks.length} 个到期任务`;
  },

  renderDay(byDay) {
    const el = this.el;
    const rows = (byDay && byDay[this.sel]) || this.rows.filter((r) => r.day === this.sel);
    el.querySelector('#cDayTitle').textContent =
      `${this.sel} · ${rows.length ? `${rows.length} 条` : '还没有安排'}`;
    const box = el.querySelector('#cList');
    if (!rows.length) {
      box.innerHTML = '<div class="note">这天是空的。上面填一条加进来。</div>';
      return;
    }
    box.innerHTML = rows.map((r) => {
      if (r._t) {
        return `
        <div class="erow task" data-id="${r.id}" data-kind="task" data-pid="${r.project_id || 0}">
          <div class="cb" title="标成已完成"></div>
          <div class="tx">
            <b>${esc(r.title)}</b>
            <span class="tag">到期</span>
            <button class="jump tag" style="border:0;cursor:pointer">${esc(r.project || '未挂项目')}</button>
            <div class="note" style="margin-top:3px">状态：${esc(r.state)} · 点圆圈标完成</div>
          </div>
        </div>`;
      }
      if (r._m) {
        return `
        <div class="erow" data-id="${r.id}" data-kind="meet">
          <div class="tx" style="border-left:3px solid #2f6feb;padding-left:8px">
            <b>${esc(r.title)}</b>
            <span class="tag">会议</span>
            ${r.start ? `<span class="tag">${esc(r.start)}${r.end ? '–' + esc(r.end) : ''}</span>` : ''}
            ${r.location ? `<span class="tag">📍${esc(r.location)}</span>` : ''}
            ${r.link ? `<a class="tag" href="${esc(r.link)}" target="_blank" rel="noopener">入会</a>` : ''}
            ${r.attendees ? `<div class="note" style="margin-top:3px">参会：${esc(r.attendees)}</div>` : ''}
          </div>
          <button class="del">删除</button>
        </div>`;
      }
      return `
      <div class="erow${r.done ? ' done' : ''}" data-id="${r.id}">
        <div class="cb"></div>
        <div class="tx">
          <b>${esc(r.title)}</b>
          ${r.start ? `<span class="tag">${esc(r.start)}${r.end ? '–' + esc(r.end) : ''}</span>` : ''}
          ${r.note ? `<div class="note" style="margin-top:3px">${esc(r.note)}</div>` : ''}
        </div>
        <button class="del">删除</button>
      </div>`;
    }).join('');
  },

  async add() {
    const el = this.el;
    const title = el.querySelector('#eTitle').value.trim();
    if (!title) return;
    const r = await post('/api/events/save', {
      day: this.sel,
      start: el.querySelector('#eStart').value.trim(),
      end: el.querySelector('#eEnd').value.trim(),
      title,
      note: el.querySelector('#eNote').value.trim(),
    });
    if (!r.ok) { toast(r.error || '没加上'); return; }
    el.querySelector('#eTitle').value = '';
    el.querySelector('#eStart').value = '';
    el.querySelector('#eEnd').value = '';
    el.querySelector('#eNote').value = '';
    toast('已加到 ' + this.sel);
    this.load();
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
    ];
  },
};
