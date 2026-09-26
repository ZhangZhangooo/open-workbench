/* 总览仪表盘（默认落地页）：KPI + 系统活动 + 模块健康 + 快速捕捉，下方保留今日清单等 */

const { api, post, toast, esc, day } = window.WB;

function seedArr(seed) {
  const out = [];
  let x = (seed * 9301 + 49297) % 233280;
  if (x <= 0) x = 12345;
  for (let i = 0; i < 7; i++) {
    x = (x * 9301 + 49297) % 233280;
    out.push(22 + (x % 68));
  }
  return out;
}

function spark(arr, cls) {
  const max = Math.max(1, ...arr);
  return `<div class="spark ${cls || ''}">` +
    arr.map((v) => `<i style="height:${Math.round((v / max) * 100)}%"></i>`).join('') +
    `</div>`;
}

const WK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

export default {
  id: 'home',
  name: '客厅',
  el: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div id="rollTip" style="display:none"></div>

        <div class="hero" id="hero">
          <div class="hero-l">
            <div class="hero-greet" id="heroGreet">你好，慢慢</div>
            <div class="hero-date" id="heroDate"></div>
            <div class="hero-clock" id="heroClock">--:--:--</div>
          </div>
          <div class="hero-r">
            <span class="hstat"><i class="hd"></i><b id="hUptime">运行 --:--:--</b></span>
            <span class="hstat"><i class="hd"></i>CPU <b id="heroCpu">--%</b></span>
            <span class="hstat"><i class="hd"></i>内存 <b id="heroMem">--%</b></span>
            <span class="hstat net"><i class="hd"></i>索引 <b id="heroIdx">--</b> 个</span>
          </div>
        </div>

        <div class="ov">
          <div class="ov-head">
            <h1>工作台概览</h1>
            <span class="live">● LIVE</span>
            <span class="date" id="ovDate"></span>
          </div>

          <div class="kpis" id="kpis"></div>

          <div class="grid2">
            <div class="card">
              <div class="ch"><span class="cdot"></span>系统活动 / System activity</div>
              <div class="term" id="ovTerm"></div>
            </div>
            <div class="card">
              <div class="ch"><span class="cdot"></span>模块健康 / Module health</div>
              <div class="health" id="ovHealth"></div>
            </div>
          </div>

          <div class="capbar">
            <b>▸</b>
            <input id="ovCap" placeholder="快速捕捉…（回车即存，自动进资料库）" autocomplete="off">
            <button class="send" id="ovCapSend">捕捉</button>
          </div>
        </div>

        <div class="panel">
          <h3>作业清单</h3>
          <div id="todayList"></div>
          <div class="field" style="margin:10px 0 0">
            <input id="todayIn" placeholder="加一项作业，回车确认">
            <select id="todayProj" style="max-width:150px"></select>
          </div>
        </div>

        <div class="panel">
          <h3>今日什么事</h3>
          <div class="note" style="margin-bottom:8px">随手记今天干了啥，按天存，刷新不丢。</div>
          <textarea id="dayLog" rows="4" placeholder="今天干了啥？上课、写代码、跑了个步…"
            style="width:100%;font-family:inherit;font-size:13.5px;resize:vertical"></textarea>
          <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
            <button class="btn primary" id="btnDayLog">保存</button>
            <span id="dayLogState" style="font-size:12px;color:var(--ink-3)"></span>
          </div>
        </div>

        <div class="panel">
          <h3>让 OpenClaw 帮你写</h3>
          <div class="note" style="margin-bottom:8px">
            它会去翻你今天真实做过的事（项目记录、番茄钟、改过的文件），
            不是凭空编。写出来的东西落在「资料」里，你自己再改。
          </div>
          <div class="field-row">
            <button class="btn" data-gen="diary">写今天的日记</button>
            <button class="btn" data-gen="homework">整理今天的作业</button>
          </div>
          <div id="genOut" style="margin-top:10px"></div>
        </div>

        <div class="panel">
          <h3>习惯打卡</h3>
          <div class="note" style="margin-bottom:8px">
            每天点一下就行。断一天连续数归零 —— 所以别贪多，先立两三个。
          </div>
          <div id="habitList"></div>
          <div class="field-row" style="margin-top:8px">
            <input id="habitIn" placeholder="加一个习惯，回车确认" style="flex:1">
            <button class="btn" id="btnAddHabit">加</button>
          </div>
        </div>

        <div class="panel">
          <h3>快速捕捉</h3>
          <div class="field"><input id="inboxIn" placeholder="随手记，回车存下"></div>
          <div id="inboxList"></div>
        </div>
      </div>`;

    const ti = el.querySelector('#todayIn');
    ti.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      const t = ti.value.trim();
      if (!t) return;
      ti.value = '';
      await post('/api/today/add', {
        day: day(), text: t,
        project_id: +el.querySelector('#todayProj').value || 0,
      });
      this.loadToday();
    });

    this.loadProjOptions();

    const dl = el.querySelector('#dayLog');
    let dlTimer = null;
    const saveDl = () => this.saveDayLog();
    el.querySelector('#btnDayLog').onclick = saveDl;
    dl.addEventListener('input', () => {
      const st = el.querySelector('#dayLogState');
      st.textContent = '输入中…';
      clearTimeout(dlTimer);
      dlTimer = setTimeout(() => { st.textContent = '已自动保存'; saveDl(); }, 1200);
    });

    const hi = el.querySelector('#habitIn');
    const addHabit = async () => {
      const t = hi.value.trim();
      if (!t) return;
      hi.value = '';
      await post('/api/habits/save', { name: t, note: '' });
      this.loadHabits();
    };
    hi.addEventListener('keydown', (e) => { if (e.key === 'Enter') addHabit(); });
    el.querySelector('#btnAddHabit').onclick = addHabit;

    el.querySelector('#habitList').addEventListener('click', async (e) => {
      const row = e.target.closest('.hrow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.del')) {
        await post('/api/habits/del', { id });
      } else {
        const r = await post('/api/habits/toggle', { id, day: day() });
        if (r.ok && r.on && r.streak >= 3) toast(`连续 ${r.streak} 天了`);
      }
      this.loadHabits();
    });

    const ii = el.querySelector('#inboxIn');
    ii.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      const t = ii.value.trim();
      if (!t) return;
      ii.value = '';
      await post('/api/inbox/add', { text: t });
      toast('已记下');
      this.loadInbox();
    });

    el.querySelectorAll('[data-gen]').forEach((b) => {
      b.onclick = () => this.generate(b.dataset.gen, b);
    });

    el.querySelector('#todayList').addEventListener('click', async (e) => {
      const cb = e.target.closest('.cb');
      const x = e.target.closest('.x');
      if (!cb && !x) return;
      const row = e.target.closest('.todo');
      const kind = row.dataset.kind;
      const id = +row.dataset.id;
      if (kind === 'today') {
        if (x) await post('/api/today/del', { id });
        else await post('/api/today/toggle', { id, done: row.classList.contains('done') ? 0 : 1 });
      } else if (kind === 'task') {
        if (cb) await post('/api/tasks/state', { id, state: row.classList.contains('done') ? '待办' : '完成' });
      } else if (kind === 'rem') {
        if (cb) await post('/api/reminders/del', { id });
      }
      this.loadToday();
    });

    el.querySelector('#inboxList').addEventListener('click', async (e) => {
      const cb = e.target.closest('.cb');
      const x = e.target.closest('.x');
      if (!cb && !x) return;
      const row = e.target.closest('.todo');
      const id = +row.dataset.id;
      if (x) await post('/api/inbox/del', { id });
      else await post('/api/inbox/done', { id, done: row.classList.contains('done') ? 0 : 1 });
      this.loadInbox();
    });

    /* 顶部快速捕捉条 */
    const cap = el.querySelector('#ovCap');
    const doCap = async () => {
      const t = cap.value.trim();
      if (!t) return;
      cap.value = '';
      await post('/api/inbox/add', { text: t });
      toast('已捕捉');
      if (window.WB.log) window.WB.log('ok', 'cap', t.slice(0, 28));
      this.loadInbox();
      this.renderKpis();
      this.renderActivity();
    };
    cap.addEventListener('keydown', (e) => { if (e.key === 'Enter') doCap(); });
    el.querySelector('#ovCapSend').onclick = doCap;

    this.refresh();
  },

  async refresh() {
    this.loadToday();
    this.loadInbox();
    this.loadHabits();
    this.loadDayLog();
    this.checkRoll();
    this.renderKpis();
    this.renderHealth();
    this.renderHero();
    this.renderActivity();
  },

  renderHero() {
    const d = new Date();
    const h = d.getHours();
    const greet = h < 5 ? '夜深了，慢慢'
      : h < 11 ? '早上好，慢慢'
      : h < 13 ? '中午好，慢慢'
      : h < 18 ? '下午好，慢慢'
      : h < 23 ? '晚上好，慢慢'
      : '夜深了，慢慢';
    const g = this.el.querySelector('#heroGreet');
    if (g) g.textContent = greet;
    const dt = this.el.querySelector('#heroDate');
    if (dt) dt.textContent = `${d.getFullYear()} 年 ${String(d.getMonth() + 1).padStart(2, '0')} 月 ${String(d.getDate()).padStart(2, '0')} 日 · ${WK[d.getDay()]}`;
    const ov = this.el.querySelector('#ovDate');
    if (ov) ov.textContent = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${WK[d.getDay()]}`;
    const idx = this.el.querySelector('#heroIdx');
    if (idx) {
      const st = window.WB.status();
      idx.textContent = (st && st.count != null) ? st.count.toLocaleString() : '--';
    }
  },

  async renderKpis() {
    const st = window.WB.status();
    const counts = (st && st.counts) || {};
    let today = { rows: [] }, projs = { rows: [] }, inbox = { rows: [] };
    try {
      [today, projs, inbox] = await Promise.all([
        api('/api/today?day=' + day()),
        api('/api/projects'),
        api('/api/inbox'),
      ]);
    } catch (_) { /* 忽略 */ }
    const tN = (today.rows || []).length;
    const doneN = (today.rows || []).filter((r) => r.done).length;
    const pN = (projs.rows || []).length;
    const iN = (inbox.rows || []).length;
    const fN = (st && st.count) || 0;

    const boxes = [
      { lbl: '今日任务', n: tN, sub: `${doneN} 已完成`, arr: seedArr(tN + 1) },
      { lbl: '进行中项目', n: pN, sub: (projs.rows || []).slice(0, 2).map((p) => p.name).join(' · ') || '（暂无）', arr: seedArr(pN + 3), alt: true },
      { lbl: '快速捕捉', n: iN, sub: '随手记', arr: seedArr(iN + 5), alt: true },
      { lbl: '已索引', n: fN, sub: '个文件', arr: seedArr(fN + 7), warn: true },
    ];
    const box = this.el.querySelector('#kpis');
    if (box) box.innerHTML = boxes.map((b) => `
      <div class="kpi">
        <div class="lbl">${b.lbl}</div>
        <div class="n">${b.n}</div>
        <div class="sub">${esc(b.sub)}</div>
        ${spark(b.arr, b.alt ? 'alt' : b.warn ? 'warn' : '')}
      </div>`).join('');
  },

  renderHealth() {
    const box = this.el.querySelector('#ovHealth');
    if (!box) return;
    const mods = (window.WB.modules || []).filter((m) => m && m.name);
    box.innerHTML = mods.map((m) => `
      <div class="hc">
        <span class="hdot"></span>
        <span class="hn">${esc(m.name)}</span>
        <span class="hs">ok</span>
      </div>`).join('');
  },

  renderActivity() {
    const box = this.el.querySelector('#ovTerm');
    if (!box) return;
    const lines = (window.WB.recentLogs && window.WB.recentLogs()) || [];
    if (!lines.length) {
      box.innerHTML = '<div class="ln"><span class="msg">（暂无活动）</span></div>';
      return;
    }
    box.innerHTML = lines.slice().reverse().map((l) => `
      <div class="ln ${l.k || ''}">
        <span class="ts">${l.t}</span>
        <span class="p">${esc(l.p)}</span>
        <span class="msg">${esc(l.m)}</span>
      </div>`).join('');
  },

  async loadDayLog() {
    const d = await api('/api/daylog?day=' + day());
    const ta = this.el.querySelector('#dayLog');
    if (ta && d.text != null) ta.value = d.text;
  },

  async saveDayLog() {
    const ta = this.el.querySelector('#dayLog');
    if (!ta) return;
    const st = this.el.querySelector('#dayLogState');
    await post('/api/daylog/save', { day: day(), text: ta.value });
    if (st) st.textContent = '已保存';
  },

  /* 昨天没勾完的，问一下要不要带过来 —— 不自动挪，免得每天莫名多几条 */
  async checkRoll() {
    const box = this.el.querySelector('#rollTip');
    const y = this.prevDay();
    if (!y) { box.style.display = 'none'; return; }
    const d = await api(`/api/today/pending?day=${y}`);
    const n = (d.rows || []).length;
    if (!n) { box.style.display = 'none'; return; }
    box.style.display = '';
    box.innerHTML = `
      <div class="panel" style="border-color:var(--accent);background:var(--accent-soft)">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <span style="font-size:13px">${esc(y)} 有 <b>${n}</b> 件没做完</span>
          <button class="btn primary" id="btnRoll" style="height:28px;padding:0 10px;font-size:12px">挪到今天</button>
          <button class="btn" id="btnRollNo" style="height:28px;padding:0 10px;font-size:12px">不管</button>
        </div>
        <div class="note" style="margin-top:6px">${(d.rows || []).slice(0, 3).map((r) => esc(r.text)).join(' · ')}</div>
      </div>`;
    this.el.querySelector('#btnRoll').onclick = async () => {
      await post('/api/today/roll', { from: y });
      toast(`已挪 ${n} 件到今天`);
      this.refresh();
    };
    this.el.querySelector('#btnRollNo').onclick = () => {
      box.style.display = 'none';
    };
  },

  prevDay() {
    const p = day().split('-');
    const d = new Date(+p[0], +p[1] - 1, +p[2]);
    d.setDate(d.getDate() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  },

  /* ---- 让 OpenClaw 写日记 / 整理作业 ---- */

  async generate(kind, btn) {
    const out = this.el.querySelector('#genOut');
    const today = day();
    const [todos, projs] = await Promise.all([
      api('/api/today?day=' + today), api('/api/projects'),
    ]);
    const done = (todos.rows || []).filter((r) => r.done).map((r) => r.text);
    const undone = (todos.rows || []).filter((r) => !r.done).map((r) => r.text);
    const plist = (projs.rows || []).map((p) =>
      `${p.name}（${p.status || '进行中'}，已完成 ${p.n_done || 0}/${p.n_task || 0}，下一步：${p.next_step || '没定'}）`).join('；');

    const facts = [
      `日期：${today}`,
      `今天做完的事：${done.length ? done.join('、') : '（没勾任何一件）'}`,
      `今天没做完的：${undone.length ? undone.join('、') : '（没有）'}`,
      `在推的项目：${plist || '（没有项目）'}`,
    ].join('\n');

    const ask = kind === 'diary'
      ? `${facts}\n\n请据此写一篇今天的日记。要求：第一人称，口语，'
        不空话不喊口号，300 字以内。做完的事就写实，没做完的就直说卡在哪，
        不要编造上面没出现的事。`
      : `${facts}\n\n请据此整理一份「今天的作业/待办清单」。要求：
        分「已完成」「待办」「卡住了」三块列出来，每条一行，
        只列上面出现过的事，不要自己加任务。`;

    out.innerHTML = '<div class="note">已交给 OpenClaw，它带着你今天真实的状态去处理，'
      + '结果在 OpenClaw 页里（带「写回工作台」按钮：可存今日 / 资料库 / 项目）。</div>';
    window.WB.go('claw', { task: ask, autorun: true });
    btn.textContent = btn.textContent;
  },

  async loadHabits() {
    const d = await api('/api/habits');
    const box = this.el.querySelector('#habitList');
    const rows = d.rows || [];
    if (!rows.length) {
      box.innerHTML = '<div class="note">还没有习惯。想一个每天都做的事，比如「写 100 字」。</div>';
      return;
    }
    box.innerHTML = rows.map((h) => `
      <div class="hrow${h.done_today ? ' on' : ''}" data-id="${h.id}">
        <div class="hcb">${h.done_today ? '✓' : ''}</div>
        <div class="hn">${esc(h.name)}</div>
        ${h.streak ? `<span class="tag${h.streak >= 3 ? ' on' : ''}">连续 ${h.streak} 天</span>` : ''}
        <button class="del" title="删掉">×</button>
      </div>`).join('');
  },

  async loadProjOptions() {
    const sel = this.el.querySelector('#todayProj');
    if (!sel) return;
    const d = await api('/api/projects');
    const rows = d.rows || [];
    sel.innerHTML = '<option value="0">不挂项目</option>' +
      rows.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  },

  async loadToday() {
    const box = this.el.querySelector('#todayList');
    const [td, tasks, rem, projs] = await Promise.all([
      api('/api/today?day=' + day()),
      api('/api/tasks?project_id=0'),
      api('/api/reminders'),
      api('/api/projects'),
    ]);
    const pmap = {};
    (projs.rows || []).forEach((p) => { pmap[p.id] = p.name; });
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const end = start + 86400;
    const items = [];
    // 项目里的真实任务（未完成）→ 直接进今日
    (tasks.rows || []).forEach((t) => {
      if ((t.state || '') === '完成') return;
      items.push({ kind: 'task', id: t.id, text: t.title, done: false,
        tag: pmap[t.project_id] || '任务', pid: t.project_id });
    });
    // 今天到期的提醒
    (rem.rows || []).forEach((r) => {
      const at = +r.at || 0;
      if (at >= start && at <= end) items.push({ kind: 'rem', id: r.id, text: r.text, done: false, tag: '提醒' });
    });
    // 手动记的今日待办
    (td.rows || []).forEach((r) => items.push({ kind: 'today', id: r.id, text: r.text, done: !!r.done, tag: r.project || '' }));
    if (!items.length) {
      box.innerHTML = '<div class="note">今天还没排活。下面加一条，或去项目里把任务勾起来</div>';
      return;
    }
    box.innerHTML = items.map((it) => this.todayRow(it)).join('');
  },

  todayRow(it) {
    const showX = it.kind === 'today' ? '<button class="x">删除</button>' : '';
    const tag = it.tag ? `<span class="tag" style="flex:none">${esc(it.tag)}</span>` : '';
    return `<div class="todo${it.done ? ' done' : ''}" data-kind="${it.kind}" data-id="${it.id}" data-pid="${it.pid || ''}">`
      + `<div class="cb"></div><div class="tx">${esc(it.text)}</div>${tag}${showX}</div>`;
  },

  async loadInbox() {
    const d = await api('/api/inbox');
    const box = this.el.querySelector('#inboxList');
    box.innerHTML = d.rows.length
      ? d.rows.map(this.rowHTML).join('')
      : '<div class="note">空的。想到什么随手扔进来，之后再归类</div>';
  },

  rowHTML(r) {
    const tag = r.project
      ? `<span class="tag" style="flex:none">${esc(r.project)}</span>` : '';
    return `<div class="todo${r.done ? ' done' : ''}" data-id="${r.id}">
      <div class="cb"></div>
      <div class="tx">${esc(r.text)}</div>
      ${tag}
      <button class="x">删除</button>
    </div>`;
  },

  onShow() {
    this.refresh();
  },

  badge(s) {
    const n = (s.counts && s.counts.inbox) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      {
        title: '记一条',
        hint: '快速捕捉',
        run: async () => {
          const t = prompt('记点什么');
          if (t && t.trim()) {
            await post('/api/inbox/add', { text: t.trim() });
            toast('已记下');
            this.loadInbox();
          }
        },
      },
    ];
  },
};
