/* 任务中心：今日清单全量版
 * 优先级 / 子任务 / 重复 / 估时对实际 / 番茄绑定 / 批量 / 模板 / 日回顾 / 连击 / 热力条
 */

const { api, post, toast, esc, day } = window.WB;

const PRI = [
  { v: 0, lbl: 'P0', cls: 'p0', tip: '今天必须干完' },
  { v: 1, lbl: 'P1', cls: 'p1', tip: '尽量今天干' },
  { v: 2, lbl: 'P2', cls: 'p2', tip: '排着就行' },
];
const REP = { daily: '每天', weekly: '每周', monthly: '每月' };

/* 备注用的小型 markdown：标题 / 列表 / 粗体 / 代码。先转义再排版，安全。 */
function md(src) {
  const esc1 = esc(src || '');
  const lines = esc1.split(/\n/);
  const out = [];
  let inList = false;
  const inline = (s) => s
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  for (let ln of lines) {
    const h = ln.match(/^###\s+(.*)/);
    if (h) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<b style="display:block;margin-top:6px">${h[1]}</b>`);
    } else if (/^[-*]\s+/.test(ln)) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${inline(ln.replace(/^[-*]\s+/, ''))}</li>`);
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      if (ln) out.push(`<p>${inline(ln)}</p>`);
    }
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

function addDays(ds, n) {
  const p = ds.split('-');
  const d = new Date(+p[0], +p[1] - 1, +p[2]);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function mmss(sec) {
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default {
  id: 'tasks',
  name: '任务',
  el: null,
  _d: null,        // 当前查看的日期
  _sel: new Set(), // 批量选中的任务 id
  _batch: false,   // 批量模式开关
  _pomo: null,     // 绑任务的番茄 { id, started, today_id }
  _timer: null,    // 秒表 interval
  _noteOpen: 0,    // 展开备注编辑的任务 id
  _ov: null,       // 当前弹层

  mount(el) {
    this.el = el;
    this._d = day();
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <div class="tk-top">
            <button class="btn slim" data-nav="-1">◀</button>
            <span class="tk-date" id="tkDate"></span>
            <button class="btn slim" data-nav="1">▶</button>
            <button class="btn slim" id="tkToday">今天</button>
            <span class="tk-streak" id="tkStreak" title="连续有完成记录的天数"></span>
            <span style="flex:1"></span>
            <button class="btn slim" id="tkReview">日回顾</button>
            <button class="btn slim" id="tkTpl">模板</button>
            <button class="btn slim" id="tkBatch">批量</button>
          </div>
          <div class="tk-heat" id="tkHeat" title="最近 30 天完成密度"></div>

          <div id="tkList" style="margin-top:6px"></div>

          <div class="field" style="margin:10px 0 0">
            <input id="tkIn" placeholder="要干啥？回车加，写清楚点" style="flex:1;min-width:180px">
            <select id="tkPri" style="max-width:70px" title="优先级">
              <option value="0">P0</option><option value="1" selected>P1</option><option value="2">P2</option>
            </select>
            <input id="tkEst" type="number" min="0" placeholder="分钟" style="max-width:72px" title="预计用时（分钟）">
            <select id="tkRep" style="max-width:84px" title="重复">
              <option value="">不重复</option>
              <option value="daily">每天</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
            <select id="tkProj" style="max-width:140px"></select>
          </div>

          <div class="tk-bar" id="tkBar" style="display:none">
            <b id="tkBarN">0</b> 选中
            <button class="btn slim" data-bop="all">全选</button>
            <button class="btn slim" data-bop="done">完成</button>
            <button class="btn slim" data-bop="undone">取消完成</button>
            <button class="btn slim" data-bop="defer">推到明天</button>
            <button class="btn slim" data-bop="del">删除</button>
            <button class="btn slim" data-bop="exit">退出批量</button>
          </div>
        </div>
      </div>`;

    /* 事件：日期导航 */
    el.querySelectorAll('[data-nav]').forEach((b) => {
      b.onclick = () => { this._d = addDays(this._d, +b.dataset.nav); this.refresh(); };
    });
    el.querySelector('#tkToday').onclick = () => { this._d = day(); this.refresh(); };
    el.querySelector('#tkReview').onclick = () => this.openReview();
    el.querySelector('#tkTpl').onclick = () => this.openTpl();
    el.querySelector('#tkBatch').onclick = () => {
      this._batch = !this._batch;
      if (!this._batch) this._sel.clear();
      el.querySelector('#tkBatch').classList.toggle('primary', this._batch);
      this.loadToday();
    };
    el.querySelectorAll('[data-bop]').forEach((b) => {
      b.onclick = () => this.batch(b.dataset.bop);
    });

    /* 加任务 */
    const ti = el.querySelector('#tkIn');
    ti.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      const t = ti.value.trim();
      if (!t) return;
      ti.value = '';
      await post('/api/today/add', {
        day: this._d, text: t,
        priority: Number(el.querySelector('#tkPri').value),
        est: +el.querySelector('#tkEst').value || 0,
        repeat: el.querySelector('#tkRep').value || '',
        project_id: +el.querySelector('#tkProj').value || 0,
      });
      el.querySelector('#tkEst').value = '';
      this.loadToday();
    });

    /* 列表交互（全走代理） */
    el.querySelector('#tkList').addEventListener('click', (e) => this.onListClick(e));
    el.querySelector('#tkList').addEventListener('keydown', (e) => {
      const ta = e.target.closest('.tk-note textarea');
      if (ta && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        ta.closest('.tk-note').querySelector('[data-act="notesave"]').click();
      }
    });

    this.loadProjOptions();
    this.refresh();
  },

  async refresh() {
    await this.loadToday();
    this.loadStats();
  },

  onShow() {
    this.refresh();
  },

  /* ---------- 数据 ---------- */

  async loadProjOptions() {
    const sel = this.el.querySelector('#tkProj');
    if (!sel) return;
    const d = await api('/api/projects');
    sel.innerHTML = '<option value="0">不挂项目</option>' +
      (d.rows || []).map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  },

  async loadToday() {
    const box = this.el.querySelector('#tkList');
    if (!box) return;
    const td = await api('/api/today?day=' + this._d);
    const rows = td.rows || [];
    const kids = {};
    rows.filter((r) => +r.parent_id).forEach((r) => {
      (kids[+r.parent_id] = kids[+r.parent_id] || []).push(r);
    });
    const parents = rows.filter((r) => !+r.parent_id);
    if (!parents.length) {
      box.innerHTML = `<div class="note">${this._d === day()
        ? '今天还没排活。下面加一条，或者把昨天没完成的挪过来。'
        : '这天没有任务。'}</div>`;
    } else {
      box.innerHTML = parents.map((p) =>
        this.rowHTML(p, kids[p.id])).join('');
    }
    this.loadPomo();
    this.renderBar();
  },

  async loadStats() {
    const box = this.el.querySelector('#tkHeat');
    const st = this.el.querySelector('#tkStreak');
    if (!box || !st) return;
    const d = await api('/api/today/stats');
    const days = d.days || [];
    const max = Math.max(1, ...days.map((x) => x.n));
    box.innerHTML = days.map((x) => {
      const op = x.n ? 0.25 + 0.75 * (x.n / max) : 0;
      return `<i style="background:${x.n ? 'var(--accent)' : 'var(--line)'};opacity:${x.n ? op.toFixed(2) : '1'}"
        title="${x.day} 完成 ${x.n} 件"></i>`;
    }).join('');
    st.innerHTML = d.streak ? `🔥 连续 ${d.streak} 天` : '还没开张';
    const dt = this.el.querySelector('#tkDate');
    if (dt) dt.textContent = this._d + (this._d === day() ? '（今天）' : '');
  },

  /* 已有绑任务的番茄：接着显示计时 */
  async loadPomo() {
    const d = await api('/api/pomodoro');
    const r = d.running;
    if (r && +r.today_id) {
      this._pomo = { id: r.id, started: r.started, today_id: +r.today_id };
      this.startTimer();
      this.renderListPomo();
    } else if (this._pomo) {
      this._pomo = null;
      this.stopTimer();
      this.renderListPomo();
    }
  },

  startTimer() {
    this.stopTimer();
    this._timer = setInterval(() => this.renderListPomo(), 1000);
    this.renderListPomo();
  },

  stopTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  renderListPomo() {
    if (!this.el) return;
    this.el.querySelectorAll('[data-act="pomo"]').forEach((b) => {
      const id = +b.closest('.todo').dataset.id;
      const on = this._pomo && this._pomo.today_id === id;
      b.classList.toggle('on', !!on);
      b.title = on ? '点一下结束并记时长' : '对着这条开个番茄';
      if (on) {
        const el = Math.floor(Date.now() / 1000) - this._pomo.started;
        b.innerHTML = `<span class="tk-pomo">${mmss(el)}</span> ⏹`;
      } else {
        b.innerHTML = '▶番茄';
      }
    });
  },

  /* ---------- 渲染 ---------- */

  rowHTML(r, children) {
    const pri = PRI[r.priority] || PRI[1];
    const isChild = !!+r.parent_id;
    const runHere = this._pomo && this._pomo.today_id === r.id;
    const tags = [];
    if (!isChild && r.n_sub) tags.push(`<span class="tag" title="子任务进度">子 ${r.n_sub_done}/${r.n_sub}</span>`);
    if (r.repeat) tags.push(`<span class="tag" title="重复任务，完成自动排下个周期">↻ ${REP[r.repeat]}</span>`);
    if (r.done && (r.act || r.est)) {
      tags.push(`<span class="tag ${r.act > (r.est || r.act) ? 'warn' : 'ok'}" title="预估 vs 实际用时">估 ${Math.round(r.est)} / 实 ${Math.round(r.act)} 分</span>`);
    } else if (r.est) {
      tags.push(`<span class="tag" title="预计用时">约 ${Math.round(r.est)} 分</span>`);
    }
    if (r.project) tags.push(`<span class="tag">${esc(r.project)}</span>`);

    const btns = [];
    if (this._batch) btns.push(`<span class="bs${this._sel.has(r.id) ? ' on' : ''}" data-act="sel">${this._sel.has(r.id) ? '✓' : ''}</span>`);
    if (!isChild) btns.push(`<button class="act" data-act="sub" title="加一条子任务">＋子</button>`);
    btns.push(`<button class="act${r.note ? ' on' : ''}" data-act="note" title="${r.note ? '改备注' : '写点备注（支持 markdown）'}">备注</button>`);
    if (!isChild) btns.push(`<button class="act" data-act="pomo">▶番茄</button>`);
    if (!isChild) btns.push(`<button class="act" data-act="cal" title="一键变成日历上的时间块">→日程</button>`);
    if (!isChild) btns.push(`<button class="act" data-act="defer" title="推到明天">⏭</button>`);
    btns.push('<button class="act" data-act="del">删除</button>');

    const run = runHere ? ' pomo-here' : '';
    const html = `
      <div class="todo${r.done ? ' done' : ''}${isChild ? ' child' : ''}${run}" data-id="${r.id}" data-pri="${r.priority}">
        <div class="cb" data-act="cb"></div>
        <span class="tk-p ${pri.cls}" data-act="pri" title="${pri.tip}，点一下换">${pri.lbl}</span>
        <div class="tx">${esc(r.text)}</div>
        ${tags.join('')}
        ${btns.join('')}
      </div>`;
    const noteHtml = this._noteOpen === r.id ? this.noteHTML(r) : '';
    const kidsHtml = (children || []).map((c) => this.rowHTML(c)).join('');
    return html + noteHtml + kidsHtml;
  },

  noteHTML(r) {
    return `
      <div class="tk-note" data-id="${r.id}">
        <textarea placeholder="写点备注：### 小标题、- 列表、**粗体**、\`代码\` 都行">${esc(r.note || '')}</textarea>
        <div style="display:flex;gap:8px;margin-top:6px;align-items:center">
          <button class="btn slim primary" data-act="notesave">保存</button>
          <button class="btn slim" data-act="noteclose">收起</button>
          ${r.note ? '<button class="btn slim" data-act="noteclear">清空</button>' : ''}
        </div>
        ${r.note ? `<div class="tk-md" style="margin-top:8px;border-top:1px dashed var(--line);padding-top:8px">${md(r.note)}</div>` : ''}
      </div>`;
  },

  /* ---------- 交互 ---------- */

  async onListClick(e) {
    const hit = e.target.closest('[data-act]');
    if (!hit) return;
    const row = hit.closest('.todo');
    if (!row) {
      // 备注条上的按钮（保存/收起/清空）没有 .todo 父级
      const noteBox = hit.closest('.tk-note');
      if (noteBox) await this.onNoteAct(hit.dataset.act, +noteBox.dataset.id, noteBox);
      return;
    }
    const id = +row.dataset.id;
    const act = hit.dataset.act;
    const pri = +row.dataset.pri;

    if (act === 'cb') {
      const r = await post('/api/today/toggle', { id, done: row.classList.contains('done') ? 0 : 1 });
      if (r.ok) {
        const rd = await api('/api/today?day=' + this._d);
        const me = (rd.rows || []).find((x) => x.id === id);
        if (me && me.repeat && !row.classList.contains('done')) toast(`已完成，下个周期（${REP[me.repeat]}）已自动排上`);
      }
      this.refresh();
    } else if (act === 'pri') {
      await post('/api/today/priority', { id, p: (pri + 1) % 3 });
      this.loadToday();
    } else if (act === 'sub') {
      const t = prompt('子任务是啥？（小的、能单独勾的那步）');
      if (t && t.trim()) {
        await post('/api/today/sub', { parent_id: id, text: t.trim(), day: this._d });
        this.loadToday();
      }
    } else if (act === 'note') {
      this._noteOpen = this._noteOpen === id ? 0 : id;
      this.loadToday();
    } else if (act === 'pomo') {
      await this.togglePomo(id);
    } else if (act === 'cal') {
      await this.toEvent(id, row);
    } else if (act === 'defer') {
      const r = await post('/api/today/defer', { id });
      toast(r.ok ? `已推到 ${r.to}` : (r.error || '没推成'));
      this.refresh();
    } else if (act === 'del') {
      await post('/api/today/del', { id });
      this.refresh();
    } else if (act === 'sel') {
      if (this._sel.has(id)) this._sel.delete(id); else this._sel.add(id);
      this.loadToday();
    }
  },

  async onNoteAct(act, id, noteBox) {
    if (!id) return;
    if (act === 'notesave') {
      const ta = noteBox.querySelector('textarea');
      await post('/api/today/note', { id, note: ta ? ta.value : '' });
      toast('备注已存');
      this._noteOpen = 0;
      this.loadToday();
    } else if (act === 'noteclose') {
      this._noteOpen = 0;
      this.loadToday();
    } else if (act === 'noteclear') {
      await post('/api/today/note', { id, note: '' });
      this._noteOpen = 0;
      this.loadToday();
    }
  },

  async togglePomo(id) {
    if (this._pomo && this._pomo.today_id === id) {
      const r = await post('/api/today/pomo', { op: 'stop' });
      this._pomo = null;
      this.stopTimer();
      if (r.ok) toast(`番茄结束，${r.minutes} 分钟已记到任务上`);
      this.loadToday();
    } else {
      const r = await post('/api/today/pomo', { op: 'start', id });
      if (r.ok) {
        this._pomo = { id: r.id, started: r.started, today_id: id };
        this.startTimer();
        this.renderListPomo();
        toast('番茄开始，再点一下结束并记时长');
      } else toast(r.error || '开不起来');
    }
  },

  /* 时间块：任务 → 日程。开始时间默认下一个半点，时长用预估或 30 分钟。 */
  async toEvent(id, row) {
    const now = new Date();
    let h = now.getHours(), m = now.getMinutes() > 30 ? 0 : 30;
    if (now.getMinutes() > 30) h += 1;
    const def = `${String(h).padStart(2, '0')}:${m === 0 ? '00' : '30'}`;
    const t = prompt('几点开始？（HH:MM）', def);
    if (!t) return;
    const mt = t.trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!mt) { toast('时间格式不对，要 HH:MM'); return; }
    const td = await api('/api/today?day=' + this._d);
    const me = (td.rows || []).find((x) => x.id === id) || {};
    const dur = Math.max(15, Math.round(me.est || 30));
    const sh = +mt[1], sm = +mt[2];
    let eh = sh + Math.floor((sm + dur) / 60), em = (sm + dur) % 60;
    if (eh >= 24) { eh = 23; em = 55; }
    const r = await post('/api/events/save', {
      day: this._d, title: me.text || '任务时间块',
      start: `${String(sh).padStart(2, '0')}:${String(sm).padStart(2, '0')}`,
      end: `${String(eh).padStart(2, '0')}:${String(em).padStart(2, '0')}`,
      note: me.note || '', source: 'task',
    });
    toast(r.ok ? '已排进日历' : '没排上');
  },

  /* ---------- 批量 ---------- */

  renderBar() {
    const bar = this.el.querySelector('#tkBar');
    if (!bar) return;
    bar.style.display = this._batch ? '' : 'none';
    const n = this.el.querySelector('#tkBarN');
    if (n) n.textContent = this._sel.size;
  },

  async batch(op) {
    if (op === 'exit') {
      this._batch = false; this._sel.clear();
      this.el.querySelector('#tkBatch').classList.remove('primary');
      this.loadToday();
      return;
    }
    if (op === 'all') {
      const td = await api('/api/today?day=' + this._d);
      (td.rows || []).filter((r) => !+r.parent_id).forEach((r) => this._sel.add(r.id));
      this.loadToday();
      return;
    }
    if (!this._sel.size) { toast('先勾几条'); return; }
    const r = await post('/api/today/batch', { ids: [...this._sel], op });
    if (r.ok) {
      toast(`${op === 'done' ? '完成' : op === 'undone' ? '已取消' : op === 'defer' ? '已推到明天' : '已删'} ${r.n} 条`);
      this._sel.clear();
      this.refresh();
    }
  },

  /* ---------- 弹层 ---------- */

  overlay(html) {
    this.closeOverlay();
    const ov = document.createElement('div');
    ov.className = 'tk-ov';
    ov.innerHTML = `<div class="tk-modal">${html}</div>`;
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) this.closeOverlay(); });
    document.body.appendChild(ov);
    this._ov = ov;
    return ov;
  },

  closeOverlay() {
    if (this._ov) { this._ov.remove(); this._ov = null; }
  },

  /* 日回顾：完成 / 未完 / 番茄 / 捕捉 / 日程 一屏给全 */
  async openReview() {
    const d = this._d;
    const r = await api('/api/today/review?day=' + d);
    const li = (a, cls) => a.length
      ? a.map((t) => `<li>${esc(t)}</li>`).join('')
      : `<li style="color:var(--ink-3)">（没有）</li>`;
    const evs = (r.events || []).map((x) =>
      `<li>${esc(String(x.start || '').slice(0, 5))}–${esc(String(x.end || '').slice(0, 5))} ${esc(x.title)}</li>`).join('')
      || '<li style="color:var(--ink-3)">（没有日程）</li>';
    this.overlay(`
      <h3 style="margin:0 0 4px">日回顾 · ${d}</h3>
      <div class="note" style="margin-bottom:10px">全是当天的真实记录，不是编的。</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
        <div>
          <b style="color:var(--ok)">✓ 完成 ${r.done.length} 件</b>
          <ul class="tk-rlist">${li(r.done)}</ul>
        </div>
        <div>
          <b style="color:var(--warn)">○ 没完成 ${r.undone.length} 件</b>
          <ul class="tk-rlist">${li(r.undone)}</ul>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin:12px 0 4px;flex-wrap:wrap">
        <span class="tag">🍅 番茄 ${r.pomo_count} 个 / ${r.pomo_minutes} 分钟</span>
        <span class="tag">捕捉 ${r.captures} 条</span>
        <span class="tag">日程 ${r.events.length} 个</span>
      </div>
      <div><b>当天日程</b><ul class="tk-rlist">${evs}</ul></div>
      ${r.daylog ? `<div style="margin-top:10px"><b>今日什么事的日志</b><div class="note">${esc(r.daylog).slice(0, 300)}</div></div>` : ''}
      <div style="display:flex;gap:8px;margin-top:14px">
        <button class="btn slim primary" data-rv="save">存为资料</button>
        <button class="btn slim" data-rv="claw">交给 OpenClaw 写成日记</button>
        <button class="btn slim" data-rv="close">关掉</button>
      </div>`);

    this._ov.querySelectorAll('[data-rv]').forEach((b) => {
      b.onclick = async () => {
        const v = b.dataset.rv;
        if (v === 'close') { this.closeOverlay(); return; }
        const body = [
          `# ${d} 日回顾`, '',
          `## 完成（${r.done.length} 件）`,
          ...(r.done.length ? r.done.map((t) => `- [x] ${t}`) : ['- （没有）']),
          `## 没完成（${r.undone.length} 件）`,
          ...(r.undone.length ? r.undone.map((t) => `- [ ] ${t}`) : ['- （没有）']),
          '', `番茄：${r.pomo_count} 个，共 ${r.pomo_minutes} 分钟；捕捉 ${r.captures} 条。`,
        ].join('\n');
        if (v === 'save') {
          await post('/api/notes/save', { title: `日回顾 ${d}`, body, tags: '回顾' });
          toast('已存到资料里');
          this.closeOverlay();
        } else if (v === 'claw') {
          const facts = `日期：${d}\n完成：${r.done.join('、') || '（没有）'}\n没完成：${r.undone.join('、') || '（没有）'}\n番茄：${r.pomo_count} 个共 ${r.pomo_minutes} 分钟\n随手记：${r.captures} 条`;
          this.closeOverlay();
          window.WB.go('claw', {
            task: `${facts}\n\n请据此写一篇当天的日记：第一人称、口语、不喊口号，`
              + `300 字以内。做完的写实，没做完的直说卡在哪，不要编上面没有的事。`,
            autorun: true,
          });
        }
      };
    });
  },

  /* 模板：把一整套任务存下来 / 一键铺到某天 */
  async openTpl() {
    const d = await api('/api/today/templates');
    const tds = await api('/api/today?day=' + this._d);
    const cur = (tds.rows || []).filter((r) => !+r.parent_id).map((r) => r.text);
    const list = (d.rows || []).map((t) => {
      let items = [];
      try { items = JSON.parse(t.items || '[]'); } catch (_) { /* 忽略 */ }
      return `
        <div class="tk-tpl">
          <div>
            <b>${esc(t.name)}</b>
            <span class="note" style="margin-left:6px">${items.length} 条</span>
            <div class="note">${items.slice(0, 4).map(esc).join(' · ')}${items.length > 4 ? ' …' : ''}</div>
          </div>
          <div style="display:flex;gap:6px;flex:none">
            <button class="btn slim primary" data-tpl="apply" data-id="${t.id}">铺到 ${this._d === day() ? '今天' : this._d}</button>
            <button class="btn slim" data-tpl="del" data-id="${t.id}">删</button>
          </div>
        </div>`;
    }).join('') || '<div class="note">还没有模板。下面把当前这天的任务存成一套。</div>';

    this.overlay(`
      <h3 style="margin:0 0 4px">任务模板</h3>
      <div class="note" style="margin-bottom:10px">常用组合（比如「上课三件套」）存一次，每天一键铺。</div>
      <div id="tplList">${list}</div>
      <div class="field" style="margin-top:12px">
        <input id="tplName" placeholder="模板名，如：早课三件套" style="flex:1">
        <button class="btn slim primary" id="tplSave">把 ${this._d === day() ? '今天' : this._d} 的 ${cur.length} 条存成模板</button>
      </div>`);

    this._ov.querySelector('#tplSave').onclick = async () => {
      const name = this._ov.querySelector('#tplName').value.trim() || `模板 ${this._d}`;
      if (!cur.length) { toast('这天没有任务可存'); return; }
      await post('/api/today/template/save', { name, items: cur });
      toast('模板已存');
      this.openTpl();
    };
    this._ov.querySelectorAll('[data-tpl]').forEach((b) => {
      b.onclick = async () => {
        const id = +b.dataset.id;
        if (b.dataset.tpl === 'apply') {
          const r = await post('/api/today/template/apply', { id, day: this._d });
          toast(r.ok ? `已铺 ${r.n} 条到 ${this._d}` : '没铺上');
          this.closeOverlay();
          this.refresh();
        } else {
          await post('/api/today/template/del', { id });
          this.openTpl();
        }
      };
    });
  },

  /* ---------- 其他 ---------- */

  badge(s) {
    const n = (s.counts && s.counts.today_undone) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      {
        title: '加任务',
        hint: '今日',
        run: async () => {
          const t = prompt('要干啥？');
          if (t && t.trim()) {
            await post('/api/today/add', { day: day(), text: t.trim() });
            this._d = day();
            this.refresh();
            window.WB.go('tasks');
          }
        },
      },
      {
        title: '今日回顾',
        hint: '看今天干了啥',
        run: async () => { this._d = day(); window.WB.go('tasks'); this.openReview(); },
      },
    ];
  },
};