/* OpenClaw：独立对话窗口。任务是阻塞式的，所以要显示等待计时。 */

const { api, post, toast, esc } = window.WB;

const KEY = 'wb_claw_history';
const SEEN = 'wb_claw_seen';

const QUICK = [
  '看看我下载文件夹里有什么',
  '检查三个盘的剩余空间',
  '把桌面上最占地方的文件列出来',
  '总结我今天的作业清单',
];

/* 一条消息长什么样：正文 + 元信息 + 折叠的原始输出 */
function msgHTML(h) {
  const mine = h.role === 'me';
  const meta = h.meta || {};
  const bits = [];
  if (meta.model) bits.push(meta.model);
  if (meta.duration_ms) bits.push(`OpenClaw 用时 ${(meta.duration_ms / 1000).toFixed(1)}s`);
  if (meta.tokens) bits.push(`${meta.tokens} tokens`);
  if (h.ms) bits.push(`端到端 ${(h.ms / 1000).toFixed(1)}s`);

  return `<div class="msg ${mine ? 'me' : 'ai'}">
    <div class="who">${mine ? '任务' : 'OpenClaw'}</div>
    <div class="bub">
      <div class="claw-text">${esc(h.text || '')}</div>
      ${bits.length ? `<div class="claw-meta">${esc(bits.join(' · '))}</div>` : ''}
      ${h.raw ? `<details class="claw-raw"><summary>原始输出</summary><pre>${esc(h.raw.slice(0, 6000))}</pre></details>` : ''}
    </div>
  </div>`;
}

function bridgeSummary(action, p) {
  const g = (k, d = '') => (p && p[k] != null ? p[k] : d);
  switch (action) {
    case 'today/add': return '今日待办：' + g('text');
    case 'kb/save': return '资料库：' + g('title');
    case 'projects/save': return '项目：' + g('name');
    case 'cal/add': return '日历：' + g('day') + ' ' + g('start') + '–' + g('end') + ' ' + g('title');
    case 'reminders/add': return '提醒：' + g('text') +
      (p && p.at ? ' @' + new Date(p.at * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');
    case 'inbox/add': return '捕捉：' + g('text');
    default: return action + (p && p.id ? ' #' + p.id : '');
  }
}

export default {
  id: 'claw',
  name: 'OpenClaw',
  el: null,
  history: [],
  running: false,
  timer: null,
  tab: 'ask',     // ask = 问一问（Ollama） / run = 干活（OpenClaw agent） / docs = 文档
  aiMod: null,
  docsMod: null,
  agent: '',          // 选中的 agent id，空 = 默认
  ctxParts: null,     // 注入哪些模块的数据；null = 全给
  tpls: [],           // 场景模板
  histRows: [],       // 当前历史列表
  onlyFav: false,     // 历史是否只看常用
  queueTimer: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="tabs">
        <button class="tab on" data-tab="ask">问一问（Ollama）</button>
        <button class="tab" data-tab="run">干活（OpenClaw）</button>
        <button class="tab" data-tab="docs">文档（WPS 全套）</button>
      </div>

      <div id="paneAsk"></div>

      <div id="paneDocs" style="display:none"></div>

      <div id="paneRun" style="display:none">
      <details class="guide" id="clawGuide"${localStorage.getItem(SEEN) ? '' : ' open'}>
        <summary>这是什么？能干什么？怎么用</summary>
        <div class="guide-body">
          <p><b>页里有三个标签，别搞混：</b>
            「问一问」是直接跟模型聊天，它只动嘴；
            「干活」是 OpenClaw，它会真的去执行——翻你的文件、跑命令、查系统状态，
            然后带着结果回来；
            「文档」是读写 Office 全套：导入 pdf/docx/pptx/xlsx 让模型读，
            或者让模型直接写出 Word / PPT / Excel。</p>
          <p><b>怎么用：</b>下面输入框写一句「干什么」而不是「是什么」。
            说「检查三个盘的剩余空间」，别说「磁盘空间是什么」。
            Ctrl + Enter 执行，通常 2~10 秒回，复杂的可能要一分钟。</p>
          <p><b>心里有数：</b>它在你本机跑，能读你的文件。
            别让它干你没想清楚的事；真要删东西它应该会先问。
            每次执行完会显示用的模型和耗时，原始输出折在「原始输出」里。</p>
          <p class="note">下面是它的能力面板：当前有哪些 agent、健康状况、定时任务。
            这些是只读查询，不会改任何东西。</p>
        </div>
      </details>

      <div class="bar" style="padding-top:0;flex-wrap:wrap;gap:6px">
        <span id="clawState"></span>
        <label class="note" style="display:flex;align-items:center;gap:4px;cursor:pointer;margin-left:6px">
          <input type="checkbox" id="ctxOn" checked> 带入上下文
        </label>
        <button class="btn" id="btnCtxPick" style="height:28px;padding:0 10px;font-size:12px">选哪些</button>
        <span class="note" style="margin-left:4px">agent</span>
        <select id="agentSel" class="cl-mini" style="max-width:160px">
          <option value="">（默认 agent）</option>
        </select>
        <button class="btn" id="btnCap" style="height:28px;padding:0 10px;font-size:12px">能力面板</button>
        <button class="btn" id="btnStats" style="height:28px;padding:0 10px;font-size:12px">运行统计</button>
        <button class="btn" id="btnClear" style="height:28px;padding:0 10px;font-size:12px;margin-left:auto">清空记录</button>
      </div>
      <div id="ctxPick" class="cap-box" style="display:none"></div>
      <div id="capBox" class="cap-box" style="display:none"></div>
      <div id="statBox" class="cap-box" style="display:none"></div>
      <div id="tplRow" style="display:flex;gap:6px;flex-wrap:wrap;padding-bottom:6px">
        ${QUICK.map((q, i) => `<button class="chip" data-q="${i}">${esc(q)}</button>`).join('')}
      </div>
      <div class="bar" style="padding-top:0;gap:6px;flex-wrap:wrap">
        <button class="btn" id="btnQueue" style="height:28px;padding:0 10px;font-size:12px">排队跑</button>
        <span class="note" id="queueInfo"></span>
      </div>
      <details class="guide" id="queueBox">
        <summary>任务队列（一件一件跑，不互相抢）</summary>
        <div id="queueList" class="note">加载中…</div>
      </details>
      <details class="guide" id="runHistBox">
        <summary>近期运行（已写入工作台，非仅本地）</summary>
        <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap;align-items:center">
          <input id="histQ" class="hist-q" placeholder="搜历史任务或结果里的词">
          <button class="btn slim" id="btnHistGo">搜</button>
          <button class="btn slim" id="btnHistFav">只看常用</button>
          <button class="btn slim" id="btnDiff">对比勾选的两条</button>
        </div>
        <div id="runHist" class="note">加载中…</div>
        <div id="diffBox" class="diff-box" style="display:none"></div>
      </details>
      <details class="guide" id="bridgeBox">
        <summary>待确认操作（OpenClaw 提交的工作台写操作，需你确认才执行）</summary>
        <div id="bridgeList" class="note">加载中…</div>
      </details>
      <details class="guide" id="auditBox">
        <summary>桥动作审计（提交 / 确认 / 拒绝都留痕）</summary>
        <div id="auditList" class="note">加载中…</div>
      </details>
      <div class="chat" id="clawChat"></div>
      <div class="composer">
        <textarea id="clawInput" placeholder="让 OpenClaw 干点什么。Ctrl + Enter 执行"></textarea>
        <button class="btn primary" id="btnRun" style="height:62px">执行</button>
      </div>
      </div>`;

    // 云站(纯前端、无本机后端)下，OpenClaw 干活/文件/终端/系统这些本机功能不可用，给个明确提示
    if (window.CloudSync && window.CloudSync.active()) {
      const n = document.createElement('div');
      n.className = 'note';
      n.style.cssText = 'background:var(--accent-soft,#222);color:var(--accent,#4aa);padding:8px 10px;border-radius:8px;margin-bottom:10px';
      n.textContent = '本机专属：OpenClaw 干活、文件、终端、系统需要桌面版(本机后端)，云站是纯前端用不了；问一问(Ollama)同理。';
      el.insertBefore(n, el.querySelector('.tabs'));
    }

    // 标签切换：问一问是懒加载的 mod-ai.js，切过去时才装配
    el.querySelectorAll('.tab').forEach((b) => {
      b.onclick = () => this.switchTab(b.dataset.tab);
    });

    el.querySelectorAll('[data-q]').forEach((b) => {
      b.onclick = () => {
        el.querySelector('#clawInput').value = QUICK[+b.dataset.q];
        el.querySelector('#clawInput').focus();
      };
    });
    el.querySelector('#tplRow').addEventListener('click', (e) => {
      const b = e.target.closest('[data-tpl]');
      if (!b) return;
      const t = (this.tpls || []).find((x) => x.id === b.dataset.tpl);
      if (!t) return;
      el.querySelector('#clawInput').value = t.task;
      el.querySelector('#clawInput').focus();
      toast('模板已填进输入框：' + t.name);
    });

    el.querySelector('#clawGuide').addEventListener('toggle', (e) => {
      if (!e.target.open) localStorage.setItem(SEEN, '1');
    });

    el.querySelector('#btnCap').onclick = () => {
      const box = el.querySelector('#capBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.loadCaps();
    };

    el.querySelector('#btnStats').onclick = () => {
      const box = el.querySelector('#statBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.loadStats();
    };

    el.querySelector('#btnCtxPick').onclick = () => {
      const box = el.querySelector('#ctxPick');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.renderCtxPick();
    };

    el.querySelector('#btnQueue').onclick = () => this.enqueue();
    el.querySelector('#btnHistGo').onclick = () => this.loadRuns(true);
    el.querySelector('#btnHistFav').onclick = () => {
      this.onlyFav = !this.onlyFav;
      el.querySelector('#btnHistFav').classList.toggle('on', this.onlyFav);
      this.loadRuns(true);
    };
    el.querySelector('#btnDiff').onclick = () => this.showDiff();
    el.querySelector('#histQ').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); this.loadRuns(true); }
    });
    el.querySelector('#auditBox').addEventListener('toggle', (e) => {
      if (e.target.open) this.loadAudit();
    });

    el.querySelector('#btnRun').onclick = () => this.run();
    el.querySelector('#btnClear').onclick = () => {
      this.history = [];
      this.onlyFav = false;
      el.querySelector('#btnHistFav').classList.remove('on');
      localStorage.removeItem(KEY);
      el.querySelector('#clawChat').innerHTML = '';
    };

    el.querySelector('#clawInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.run();
      }
    });

    this.loadHistory();
    this.checkInfo();
    this.loadTemplates();
    this.loadAgents();
    this.switchTab('ask');
  },

  /* ---- 场景模板（49）与 agent 下拉（51） ---- */

  async loadTemplates() {
    try {
      const d = await api('/api/claw/templates');
      const rows = d.rows || [];
      if (!rows.length) return;
      this.tpls = rows;
      const box = this.el.querySelector('#tplRow');
      if (!box) return;
      box.innerHTML = rows.map((t) =>
        `<button class="chip tpl" data-tpl="${esc(t.id)}" title="${esc(t.task)}">${esc(t.name)}</button>`
      ).join('') + box.innerHTML;
    } catch (_) { /* 保持默认 chips */ }
  },

  async loadAgents() {
    const sel = this.el.querySelector('#agentSel');
    if (!sel) return;
    try {
      const d = await api('/api/claw/agents');
      const rows = d.agents || [];
      sel.innerHTML = '<option value="">（默认 agent）</option>' + rows.map((a) =>
        `<option value="${esc(a.id)}">${esc(a.id)}${a.default ? ' · 默认' : ''}</option>`
      ).join('');
    } catch (_) { /* 拉不到就只留默认 */ }
  },

  /* ---- 上下文选择器（50） ---- */

  renderCtxPick() {
    const box = this.el.querySelector('#ctxPick');
    const ITEMS = [
      ['today', '今日待办'], ['projects', '项目'], ['kb', '资料库'],
      ['daylog', '今日日志'], ['habits', '习惯'], ['inbox', '快速捕捉'], ['cal', '日程'],
    ];
    const on = this.ctxParts;   // null = 全给
    box.innerHTML = `<div class="note" style="margin-bottom:6px">
        勾选要注入给 OpenClaw 的工作台数据。不勾的项目它完全看不到，也就不会乱碰。</div>
      <div id="ctxChips">${ITEMS.map(([k, label]) =>
        `<button class="chip${on === null || on.includes(k) ? ' on' : ''}" data-ctx="${k}">${label}</button>`
      ).join('')}</div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
        <button class="btn primary" id="btnCtxAll" style="height:28px;padding:0 12px;font-size:12px">全选</button>
        <button class="btn" id="btnCtxNone" style="height:28px;padding:0 12px;font-size:12px">全不选</button>
        <span class="note" id="ctxMsg"></span>
      </div>`;
    box.querySelectorAll('[data-ctx]').forEach((b) => {
      b.onclick = () => {
        const cur = this.ctxParts === null ? ITEMS.map((x) => x[0]) : [...this.ctxParts];
        const k = b.dataset.ctx;
        const i = cur.indexOf(k);
        if (i >= 0) cur.splice(i, 1); else cur.push(k);
        this.ctxParts = cur;
        b.classList.toggle('on', i < 0);
      };
    });
    box.querySelector('#btnCtxAll').onclick = () => { this.ctxParts = null; this.renderCtxPick(); };
    box.querySelector('#btnCtxNone').onclick = () => { this.ctxParts = []; this.renderCtxPick(); };
  },

  switchTab(tab, arg) {
    this.tab = tab;
    if (this.bridgeTimer) { clearInterval(this.bridgeTimer); this.bridgeTimer = null; }
    const el = this.el;
    el.querySelectorAll('.tab').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
    el.querySelector('#paneAsk').style.display = tab === 'ask' ? '' : 'none';
    el.querySelector('#paneRun').style.display = tab === 'run' ? '' : 'none';
    el.querySelector('#paneDocs').style.display = tab === 'docs' ? '' : 'none';
    if (tab === 'ask') this.ensureAI(arg);
    if (tab === 'docs') this.ensureDocs(arg);
    if (tab === 'run') {
      this.loadRuns();
      this.loadBridge();
      this.loadQueue();
      if (this.bridgeTimer) clearInterval(this.bridgeTimer);
      this.bridgeTimer = setInterval(() => { this.loadBridge(); this.loadQueue(); }, 4000);
      if (arg && arg.task) {
        const inp = el.querySelector('#clawInput');
        if (inp) { inp.value = arg.task; inp.focus(); }
      }
    }
  },

  async ensureAI(arg) {
    if (this.aiMod) {
      if (this.aiMod.onShow) this.aiMod.onShow(arg);
      return;
    }
    const box = this.el.querySelector('#paneAsk');
    box.innerHTML = '<div class="note">加载中…</div>';
    try {
      const m = (await import('./mod-ai.js')).default;
      box.innerHTML = '';
      m.mount(box);
      this.aiMod = m;
      if (arg && m.onShow) m.onShow(arg);
    } catch (e) {
      box.innerHTML = `<div class="note">问一问加载失败：${esc(e.message)}</div>`;
    }
  },

  async ensureDocs(arg) {
    if (this.docsMod) {
      if (this.docsMod.onShow) this.docsMod.onShow(arg);
      return;
    }
    const box = this.el.querySelector('#paneDocs');
    box.innerHTML = '<div class="note">加载中…</div>';
    try {
      const m = (await import('./mod-docs.js')).default;
      box.innerHTML = '';
      m.mount(box);
      this.docsMod = m;
      if (arg && m.onShow) m.onShow(arg);
    } catch (e) {
      box.innerHTML = `<div class="note">文档页加载失败：${esc(e.message)}</div>`;
    }
  },

  async checkInfo() {
    const st = this.el.querySelector('#clawState');
    try {
      const d = await api('/api/claw/info');
      st.innerHTML = d.exists
        ? '<span class="tag ok">OpenClaw 已就位</span>'
        : '<span class="tag err">没找到 OpenClaw</span>';
    } catch (_) {
      st.innerHTML = '<span class="tag err">状态未知</span>';
    }
  },

  /* ---- 能力面板：只读查询 agent / 健康 / 定时任务 ---- */

  async loadCaps() {
    const box = this.el.querySelector('#capBox');
    box.innerHTML = '<div class="note">查询中…</div>';
    const [h, a] = await Promise.all([api('/api/claw/health'), api('/api/claw/agents')]);

    const gw = h.gateway_up
      ? '<span class="tag ok">Gateway 在线（18789）</span>'
      : '<span class="tag warn">Gateway 没在跑，会自动回退本地模式</span>';
    const agents = (a.agents || []).map((x) => `
      <div class="cap-row">
        <b>${esc(x.id)}</b>
        ${x.default ? '<span class="tag on">默认</span>' : ''}
        <span class="note">${esc(x.model || '未指定模型')}</span>
      </div>`).join('') || '<div class="note">没读到 agent</div>';

    box.innerHTML = `
      <div class="cap-sec">
        <div class="cap-h">健康</div>
        <div class="cap-row">
          <span class="tag ${h.cli_exists ? 'ok' : 'err'}">${h.cli_exists ? 'CLI 已装' : 'CLI 缺失'}</span>
          ${gw}
          ${h.version ? `<span class="note">${esc(h.version)}</span>` : ''}
        </div>
        <div class="note" style="margin-top:4px">${esc(h.cli_path || '')}</div>
      </div>
      <div class="cap-sec">
        <div class="cap-h">可用 agent（${(a.agents || []).length}）</div>
        ${agents}
        <div class="note" style="margin-top:4px">
          agent 是分开的工作间，各有各的配置。目前跑任务用的是「默认」那个。
        </div>
      </div>
      <div class="cap-sec">
        <div class="cap-h">定时任务</div>
        <div id="cronBox"><button class="btn" id="btnCron" style="height:28px;padding:0 10px;font-size:12px">查一下</button></div>
      </div>`;

    box.querySelector('#btnCron').onclick = () => this.loadCron();
  },

  async loadCron() {
    const b = this.el.querySelector('#cronBox');
    b.innerHTML = '<div class="note">查询中…</div>';
    const d = await api('/api/claw/automations');
    if (!d.ok) {
      b.innerHTML = `<div class="note">读不到：${esc(d.error || '未知原因')}
        <br>OpenClaw 的定时任务在某些环境下会去碰系统计划任务，被系统拦了就读不到。
        不影响其它功能。</div>`;
      return;
    }
    b.innerHTML = `<pre class="cap-raw">${esc(d.raw || '（没有定时任务）')}</pre>`;
  },

  loadHistory() {
    try {
      this.history = JSON.parse(localStorage.getItem(KEY) || '[]');
    } catch (_) {
      this.history = [];
    }
    const box = this.el.querySelector('#clawChat');
    box.innerHTML = this.history.map(msgHTML).join('');
    box.scrollTop = 99999;
  },

  addMsg(role, text, ms, meta, raw) {
    const d = document.createElement('div');
    d.innerHTML = msgHTML({ role, text, ms, meta, raw });
    const node = d.firstElementChild;
    this.el.querySelector('#clawChat').appendChild(node);
    this.el.querySelector('#clawChat').scrollTop = 99999;
    return node;
  },

  async run() {
    if (this.running) return;
    const box = this.el.querySelector('#clawInput');
    const task = box.value.trim();
    if (!task) return;
    box.value = '';

    this.addMsg('me', task);
    this.history.push({ role: 'me', text: task });

    this.running = true;
    const btn = this.el.querySelector('#btnRun');
    btn.disabled = true;

    const t0 = Date.now();
    const node = this.addMsg('claw', '执行中…');
    const bub = node.querySelector('.claw-text');
    this.timer = setInterval(() => {
      bub.textContent = `执行中… 已等待 ${((Date.now() - t0) / 1000).toFixed(0)}s`;
    }, 1000);

    try {
      const d = await post('/api/openclaw', {
        task,
        ctx: this.el.querySelector('#ctxOn').checked,
        ctx_parts: this.ctxParts,
        agent: this.el.querySelector('#agentSel').value || '',
      });
      clearInterval(this.timer);
      const ms = Date.now() - t0;
      let text = d.ok
        ? (d.reply || '（OpenClaw 没返回正文）')
        : `失败：${d.error || d.reply || '未知原因'}`;
      if (d.retried) {
        text += d.ok
          ? '\n\n（第一次网关抽风，自动重试了一次才成）'
          : `\n\n（已自动重试一次仍失败；首错：${d.first_error || ''}）`;
      }
      node.remove();
      const mnode = this.addMsg('claw', text, ms, { ...(d.meta || {}), dur: d.dur }, d.raw);
      if (d.ok) this.appendWriteback(mnode, task, text);
      this.history.push({ role: 'claw', text, ms, meta: d.meta, raw: d.raw });
      if (this.history.length > 40) this.history = this.history.slice(-40);
      localStorage.setItem(KEY, JSON.stringify(this.history));
    } catch (e) {
      clearInterval(this.timer);
      node.remove();
      this.addMsg('claw', '请求失败：' + e.message);
    }

    this.loadRuns();
    this.running = false;
    btn.disabled = false;
  },

  /* ---- 任务队列（43）：丢进去排队，一件一件跑 ---- */

  async enqueue() {
    const box = this.el.querySelector('#clawInput');
    const task = box.value.trim();
    if (!task) { toast('先写点什么再排队'); return; }
    const d = await post('/api/openclaw/queue', {
      task,
      ctx: this.el.querySelector('#ctxOn').checked,
      ctx_parts: this.ctxParts,
      agent: this.el.querySelector('#agentSel').value || '',
    });
    if (!d.ok) { toast(d.error || '入队失败'); return; }
    box.value = '';
    this.addMsg('me', task);
    this.addMsg('claw', `已排进队列（第 ${d.id} 号，前面还有 ${d.waiting - 1} 件）。跑完会出现在下面的队列里。`);
    toast('已排队');
    this.loadQueue();
  },

  async loadQueue() {
    const box = this.el.querySelector('#queueList');
    if (!box) return;
    try {
      const d = await api('/api/openclaw/queue');
      const rows = (d.rows || []).slice().reverse();
      const info = this.el.querySelector('#queueInfo');
      if (info) {
        info.textContent = rows.length
          ? `队列 ${rows.length} 件（等 ${d.waiting}｜跑 ${d.running}）`
          : '队列空着';
      }
      const sb = this.el.querySelector('#queueBox summary');
      if (sb) sb.textContent = rows.length
        ? `任务队列（等 ${d.waiting}｜跑 ${d.running}｜共 ${rows.length}）`
        : '任务队列（空）';
      if (!rows.length) { box.innerHTML = '<span class="note">队列是空的。写个任务点「排队跑」。</span>'; return; }
      const tag = { waiting: ['', '等'], running: ['warn', '跑'], done: ['ok', '成'], failed: ['err', '败'] };
      box.innerHTML = rows.map((r) => {
        const [cls, label] = tag[r.status] || ['', r.status];
        return `<div style="display:flex;gap:8px;align-items:baseline;padding:5px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
          <span class="tag ${cls}" style="flex:none">${label}</span>
          <span class="note" style="flex:none">#${r.id}</span>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.task || '')}</span>
          <span class="note" style="flex:none">${r.ms ? (r.ms / 1000).toFixed(1) + 's' : ''}</span>
        </div>${r.preview ? `<div class="note" style="padding:0 0 5px 26px">${esc(r.preview.slice(0, 160))}</div>` : ''}`;
      }).join('');
    } catch (_) {
      box.innerHTML = '<span class="note">读取失败</span>';
    }
  },

  /* ---- 结果写回工作台：让 OpenClaw 的输出真正落进工作台的各个模块 ---- */

  appendWriteback(node, task, text) {
    const act = document.createElement('div');
    act.className = 'claw-actions';
    act.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin-top:8px';
    const mk = (label, fn) => {
      const b = document.createElement('button');
      b.className = 'btn';
      b.style.cssText = 'height:28px;padding:0 10px;font-size:12px';
      b.textContent = label;
      b.onclick = fn;
      return b;
    };
    act.appendChild(mk('提炼待办→今日', () => this.extractToToday(text)));
    act.appendChild(mk('加入今日', () => this.addToToday(text)));
    act.appendChild(mk('存资料库', () => this.saveToKb(task, text)));
    act.appendChild(mk('存为项目', () => this.saveAsProject(task)));
    act.appendChild(mk('快速捕捉', () => this.quickCapture(text)));
    act.appendChild(mk('推到微信', () => this.pushToWechat(task, text)));
    node.querySelector('.bub').appendChild(act);
  },

  extractToToday(text) {
    const items = (text || '').split('\n')
      .map((s) => s.replace(/^[\s\-*•\d.、)]+/, '').trim())
      .filter((s) => s && s.length <= 60 && s !== '无');
    if (!items.length) { toast('没提炼出待办'); return; }
    const day = window.WB.day();
    let n = 0;
    const go = () => {
      post('/api/today/add', { day, text: items[n] }).then((r) => {
        n++;
        if (n < items.length) go();
        else { toast(`已加 ${items.length} 条到今日`); window.WB.refresh && window.WB.refresh(); this.loadRuns(); }
      });
    };
    go();
  },

  addToToday(text) {
    const day = window.WB.day();
    const t = (text || '').replace(/\s+/g, ' ').trim().slice(0, 200);
    if (!t) { toast('没有可加入的内容'); return; }
    post('/api/today/add', { day, text: t }).then((r) => {
      if (r && r.ok) { toast('已加入今日'); window.WB.refresh && window.WB.refresh(); }
      else toast('加入失败');
    });
  },

  saveToKb(task, text) {
    const title = ((task || '').split('\n')[0] || 'OpenClaw 结果').slice(0, 60).trim();
    post('/api/kb/save', { title, body: text, tags: 'openclaw' }).then((r) => {
      toast(r && r.ok ? '已存入资料库' : '存入失败');
    });
  },

  saveAsProject(task) {
    const name = ((task || '').split('\n')[0] || 'OpenClaw 项目').slice(0, 40).trim();
    post('/api/projects/save', { name, status: '进行中', next_step: '' }).then((r) => {
      toast(r && r.ok ? '已存为项目' : '存入失败');
    });
  },

  quickCapture(text) {
    const t = (text || '').replace(/\s+/g, ' ').trim().slice(0, 2000);
    if (!t) { toast('没有可捕捉的内容'); return; }
    post('/api/inbox/add', { text: t }).then((r) => {
      toast(r && r.ok ? '已快速捕捉' : '捕捉失败');
    });
  },

  async pushToWechat(task, text) {
    const t = (text || '').replace(/\s+/g, ' ').trim();
    if (!t) { toast('没有可推的内容'); return; }
    const d = await api('/api/connectors');
    const rows = d.rows || [];
    if (!rows.length) { toast('还没配连接器：去设置里加一个微信推送'); return; }
    const c = rows.find((x) => x.enabled !== false) || rows[0];
    const r = await post('/api/connectors/push', {
      id: c.id, title: (task || 'OpenClaw 结果').slice(0, 60), content: text,
    });
    toast(r && r.ok ? '已推到微信' : '推送失败：' + (r && r.error || ''));
  },

  /* ---- 统一活动流：读工作台里记的 openclaw_runs（含搜索 44 / 常用 45 / 对比 46） ---- */

  async loadRuns(useQuery) {
    const box = this.el.querySelector('#runHist');
    if (!box) return;
    const q = useQuery ? (this.el.querySelector('#histQ').value || '').trim() : '';
    try {
      const d = this.onlyFav
        ? await api('/api/openclaw/favs')
        : (q
          ? await api('/api/openclaw/search?q=' + encodeURIComponent(q) + '&limit=50')
          : await api('/api/openclaw/history?limit=20'));
      let rows = d.rows || [];
      if (this.onlyFav && q) {
        rows = rows.filter((r) => (r.task || '').includes(q) || (r.reply || '').includes(q));
      }
      this.histRows = rows;
      const sb = this.el.querySelector('#runHistBox summary');
      const base = this.onlyFav ? '常用任务' : (q ? `搜「${q}」` : '近期运行');
      if (sb) sb.textContent = `${base}（${rows.length} 条，已写入工作台）`;
      if (!rows.length) {
        box.innerHTML = `<span class="note">${q ? '没搜到。换个词试试。' : (this.onlyFav ? '还没有标常用。点记录左边的 ☆ 收藏。' : '还没有运行记录')}</span>`;
        return;
      }
      box.innerHTML = rows.map((r) => `
        <div class="run-row" data-id="${r.id}" style="display:flex;gap:7px;align-items:baseline;padding:5px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
          <button class="fav-star${r.fav ? ' on' : ''}" data-act="fav" title="${r.fav ? '取消常用' : '标为常用'}">${r.fav ? '★' : '☆'}</button>
          <input type="checkbox" class="run-pick" data-act="pick" style="flex:none">
          <span class="tag ${r.ok ? 'ok' : 'err'}" style="flex:none">${r.ok ? '成' : '败'}</span>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                title="${esc(r.task || '')}">${esc(r.task || '')}</span>
          ${r.agent ? `<span class="note" style="flex:none">${esc(r.agent)}</span>` : ''}
          ${r.dur ? `<span class="note" style="flex:none">${Number(r.dur).toFixed(1)}s</span>` : ''}
          <span class="note" style="flex:none">${esc((r.ts ? new Date(r.ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''))}</span>
          <button class="btn slim" data-act="rerun" style="flex:none">重跑</button>
        </div>`).join('');

      box.querySelectorAll('.run-row [data-act]').forEach((b) => {
        const id = +b.closest('.run-row').dataset.id;
        b.onclick = () => {
          const a = b.dataset.act;
          if (a === 'fav') this.toggleFav(id);
          else if (a === 'rerun') this.rerun(id);
          else if (a === 'pick') { /* 勾选由 showDiff 读 */ }
        };
      });
    } catch (_) {
      box.innerHTML = '<span class="note">读取失败</span>';
    }
  },

  async toggleFav(id) {
    const r = await post('/api/openclaw/fav', { id });
    if (!r.ok) { toast(r.error || '没成功'); return; }
    toast(r.fav ? '已标为常用，下次一键重跑' : '已取消常用');
    this.loadRuns();
  },

  async rerun(id) {
    if (this.running) { toast('正在跑一件，等它完了再重跑'); return; }
    const row = this.histRows.find((x) => x.id === id) || {};
    this.running = true;
    const btn = this.el.querySelector('#btnRun');
    if (btn) btn.disabled = true;
    const node = this.addMsg('claw', '重跑中…');
    const bub = node.querySelector('.claw-text');
    try {
      const d = await post('/api/openclaw/rerun', {
        id,
        ctx: this.el.querySelector('#ctxOn').checked,
        ctx_parts: this.ctxParts,
        agent: this.el.querySelector('#agentSel').value || '',
      });
      node.remove();
      const text = d.ok ? (d.reply || '（没返回正文）') : `失败：${d.error || '未知原因'}`;
      const mnode = this.addMsg('claw', `【重跑 #${id}】${row.task || d.task || ''}\n\n${text}`,
        (d.dur || 0) * 1000, d.meta, d.raw);
      if (d.ok) this.appendWriteback(mnode, row.task || d.task || '', text);
    } catch (e) {
      node.remove();
      this.addMsg('claw', '重跑失败：' + e.message);
    }
    this.running = false;
    if (btn) btn.disabled = false;
    this.loadRuns();
  },

  /* 结果对比（46）：把勾选的两条完整正文取回来做 diff */
  async showDiff() {
    const picked = [...this.el.querySelectorAll('.run-row')]
      .filter((n) => n.querySelector('.run-pick') && n.querySelector('.run-pick').checked)
      .map((n) => +n.dataset.id);
    const box = this.el.querySelector('#diffBox');
    if (picked.length !== 2) { toast('勾两条才能对比（不多不少）'); return; }
    box.style.display = '';
    box.innerHTML = '<div class="note">取回两次结果…</div>';
    const [a, b] = await Promise.all(picked.map((id) => api('/api/openclaw/get?id=' + id)));
    if (!a.ok || !b.ok) { box.innerHTML = '<div class="note">有一条取不回来了</div>'; return; }
    const ra = a.row || {}, rb = b.row || {};
    const la = (ra.reply || '').split('\n');
    const lb = (rb.reply || '').split('\n');
    const ops = this.diffLines(la, lb);
    const add = ops.filter((o) => o.k === '+').length;
    const del = ops.filter((o) => o.k === '-').length;
    box.innerHTML = `<div class="note" style="margin-bottom:6px">
        上面那条 #${ra.id}（${ra.ok ? '成' : '败'}）↔ 下面 #${rb.id}（${rb.ok ? '成' : '败'}）
        · 差 ${add} 行新增 / ${del} 行删除</div>` +
      ops.map((o) => `<div class="dr ${o.k === '+' ? 'add' : o.k === '-' ? 'del' : ''}">${
        o.k === ' ' ? '&nbsp;&nbsp;' : esc(o.k) + ' '}${esc(o.t)}</div>`).join('');
  },

  /* 行级 diff：先掐掉相同的头尾，中间用朴素 LCS —— 结果文本都不长，够用 */
  diffLines(a, b) {
    let s = 0;
    while (s < a.length && s < b.length && a[s] === b[s]) s++;
    let ea = a.length - 1;
    let eb = b.length - 1;
    while (ea >= s && eb >= s && a[ea] === b[eb]) { ea--; eb--; }
    const midA = a.slice(s, ea + 1);
    const midB = b.slice(s, eb + 1);
    const out = a.slice(0, s).map((t) => ({ k: ' ', t }));
    const n = midA.length;
    const m = midB.length;
    if (n * m > 40000) {   // 太大就退化成「全删全加」，别把浏览器卡死
      midA.forEach((t) => out.push({ k: '-', t }));
      midB.forEach((t) => out.push({ k: '+', t }));
    } else {
      const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          dp[i][j] = midA[i] === midB[j]
            ? dp[i + 1][j + 1] + 1
            : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      let i = 0;
      let j = 0;
      while (i < n && j < m) {
        if (midA[i] === midB[j]) { out.push({ k: ' ', t: midA[i] }); i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ k: '-', t: midA[i] }); i++; }
        else { out.push({ k: '+', t: midB[j] }); j++; }
      }
      while (i < n) { out.push({ k: '-', t: midA[i] }); i++; }
      while (j < m) { out.push({ k: '+', t: midB[j] }); j++; }
    }
    for (let k = ea + 1; k < a.length; k++) out.push({ k: ' ', t: a[k] });
    return out;
  },

  /* ---- 运行统计（47） ---- */

  async loadStats() {
    const box = this.el.querySelector('#statBox');
    box.innerHTML = '<div class="note">算…</div>';
    try {
      const [d7, d30] = await Promise.all([
        api('/api/openclaw/stats?days=7'),
        api('/api/openclaw/stats?days=30'),
      ]);
      const card = (label, s) => `
        <div class="cap-sec">
          <div class="cap-h">${label}</div>
          ${s.n ? `<div class="cap-row">
            <span class="tag ${s.rate >= 90 ? 'ok' : s.rate >= 60 ? 'warn' : 'err'}">成功 ${s.rate}%</span>
            <span class="note">${s.ok_n} 成 / ${s.fail_n} 败 · 共 ${s.n} 次</span>
          </div>
          <div class="cap-row">
            <span class="note">平均 ${s.avg}s · P95 ${s.p95}s · 最慢 ${s.slowest}s</span>
          </div>` : '<div class="note">这段时间还没跑过。</div>'}
        </div>`;
      box.innerHTML = card('最近 7 天', d7) + card('最近 30 天', d30) +
        `<div class="note" style="margin-top:4px">P95 = 100 次里有 95 次比它快。用它估「最坏大概等多久」。</div>`;
    } catch (e) {
      box.innerHTML = `<div class="note">算不出来：${esc(e.message)}</div>`;
    }
  },

  /* ---- 桥动作审计（52） ---- */

  async loadAudit() {
    const box = this.el.querySelector('#auditList');
    if (!box) return;
    box.innerHTML = '加载中…';
    try {
      const d = await api('/api/bridge/audit?limit=100');
      const rows = d.rows || [];
      const sb = this.el.querySelector('#auditBox summary');
      if (sb) sb.textContent = `桥动作审计（${rows.length} 条留痕）`;
      if (!rows.length) { box.innerHTML = '<span class="note">还没有桥动作。OpenClaw 提交写操作时会自动留痕。</span>'; return; }
      const DEC = {
        submitted: ['', '已提交'], confirmed: ['ok', '已执行'],
        confirmed_failed: ['err', '执行失败'], rejected: ['warn', '已拒绝'],
      };
      box.innerHTML = rows.map((r) => {
        const [cls, label] = DEC[r.decision] || ['', r.decision];
        return `<div style="padding:6px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
          <div style="display:flex;gap:8px;align-items:baseline">
            <span class="tag ${cls}" style="flex:none">${label}</span>
            <span class="tag" style="flex:none">${esc(r.action || '')}</span>
            <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.summary || '')}</span>
            <span class="note" style="flex:none">${esc(r.actor || '')}</span>
            <span class="note" style="flex:none">${esc(r.ts ? new Date(r.ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '')}</span>
          </div>
          ${r.result && r.result !== 'ok' ? `<div class="note" style="padding-left:6px">${esc(r.result.slice(0, 200))}</div>` : ''}
        </div>`;
      }).join('');
    } catch (_) {
      box.innerHTML = '<span class="note">读取失败</span>';
    }
  },

  /* ---- 神经桥待审队列：OpenClaw 提交的写操作，用户确认后才执行 ---- */

  async loadBridge() {
    const box = this.el.querySelector('#bridgeList');
    if (!box) return;
    const n = this.el.querySelector('#bridgeBox');
    try {
      const d = await api('/api/bridge/pending');
      const rows = (d.rows || []);
      if (!rows.length) {
        box.innerHTML = '<span class="note">没有待确认的操作</span>';
        if (n) n.querySelector('summary').textContent = '待确认操作（无）';
        return;
      }
      if (n) n.querySelector('summary').textContent = `待确认操作（${rows.length} 条待你确认）`;
      box.innerHTML = rows.map((r) => `
        <div class="bridge-row" data-id="${r.id}" style="display:flex;gap:8px;align-items:baseline;padding:6px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
          <span class="tag">${esc(r.action)}</span>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(bridgeSummary(r.action, r.payload))}</span>
          <button class="btn ok" data-act="confirm" style="height:24px;padding:0 8px;font-size:11px">确认</button>
          <button class="btn" data-act="reject" style="height:24px;padding:0 8px;font-size:11px">拒绝</button>
        </div>`).join('');
      box.querySelectorAll('[data-act]').forEach((b) => {
        b.onclick = async () => {
          const id = +b.closest('.bridge-row').dataset.id;
          if (b.dataset.act === 'confirm') {
            const r = await post('/api/bridge/confirm', { id });
            if (r.ok) toast(r.result && r.result.ok ? '已执行' : '执行失败：' + (r.result && r.result.error || ''));
            else toast('执行失败：' + (r.error || ''));
            window.WB.refresh && window.WB.refresh();
          } else {
            await post('/api/bridge/reject', { id });
            toast('已拒绝');
          }
          this.loadBridge();
        };
      });
    } catch (_) {
      box.innerHTML = '<span class="note">读取失败</span>';
    }
  },

  /* 别处跳过来（跨模块触发 / 命令）：
   *   {file:...}        → 问一问标签并带文件
   *   {task:'...'}       → 干活标签并预填（autorun:true 则直接执行）
   *   {tab:'docs'|'ask'} → 直达对应标签
   */
  onShow(arg) {
    if (arg && arg.file) {
      this.switchTab('ask', arg);
    } else if (arg && arg.task) {
      this.switchTab('run', arg);
      if (arg.autorun) setTimeout(() => { if (!this.running) this.run(); }, 60);
    } else if (arg && arg.tab) {
      this.switchTab(arg.tab, arg);
    } else if (this.tab === 'ask' && this.aiMod && this.aiMod.onShow) {
      this.aiMod.onShow();
    }
    this.checkInfo();
  },

  commands() {
    const mine = [
      { title: '切到「问一问」', hint: 'OpenClaw', run: () => {
        window.WB.go('claw');
        this.switchTab('ask');
      } },
      { title: '让 OpenClaw 执行一个任务', hint: 'OpenClaw', run: async () => {
        const t = prompt('任务内容');
        if (!t) return;
        window.WB.go('claw');           // 没打开过就先切过去，mount 完才有输入框
        this.switchTab('run');
        this.el.querySelector('#clawInput').value = t;
        await this.run();
      } },
      { title: '清空 OpenClaw 对话记录', hint: 'OpenClaw', run: () => {
        this.history = [];
        localStorage.removeItem(KEY);
        if (this.el) this.el.querySelector('#clawChat').innerHTML = '';
        toast('已清空');
      } },
    ];
    // AI（问一问）不再单独注册成模块，它的命令从这里转发出去
    const ai = this.aiMod && typeof this.aiMod.commands === 'function'
      ? this.aiMod.commands() : [];
    return [...ai, ...mine];
  },
};
