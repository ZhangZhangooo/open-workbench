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
          <input type="checkbox" id="ctxOn" checked> 带入工作台上下文
        </label>
        <button class="btn" id="btnCap" style="height:30px;padding:0 12px;font-size:12px">能力面板</button>
        <button class="btn" id="btnClear" style="height:30px;padding:0 12px;font-size:12px;margin-left:auto">清空记录</button>
      </div>
      <div id="capBox" class="cap-box" style="display:none"></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;padding-bottom:8px">
        ${QUICK.map((q, i) => `<button class="chip" data-q="${i}">${esc(q)}</button>`).join('')}
      </div>
      <details class="guide" id="runHistBox">
        <summary>近期运行（已写入工作台，非仅本地）</summary>
        <div id="runHist" class="note">加载中…</div>
      </details>
      <details class="guide" id="bridgeBox">
        <summary>待确认操作（OpenClaw 提交的工作台写操作，需你确认才执行）</summary>
        <div id="bridgeList" class="note">加载中…</div>
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

    el.querySelector('#clawGuide').addEventListener('toggle', (e) => {
      if (!e.target.open) localStorage.setItem(SEEN, '1');
    });

    el.querySelector('#btnCap').onclick = () => {
      const box = el.querySelector('#capBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.loadCaps();
    };

    el.querySelector('#btnRun').onclick = () => this.run();
    el.querySelector('#btnClear').onclick = () => {
      this.history = [];
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
    this.switchTab('ask');
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
      if (this.bridgeTimer) clearInterval(this.bridgeTimer);
      this.bridgeTimer = setInterval(() => this.loadBridge(), 4000);
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
      const d = await post('/api/openclaw', { task, ctx: this.el.querySelector('#ctxOn').checked });
      clearInterval(this.timer);
      const ms = Date.now() - t0;
      const text = d.ok
        ? (d.reply || '（OpenClaw 没返回正文）')
        : `失败：${d.error || d.reply || '未知原因'}`;
      node.remove();
      const mnode = this.addMsg('claw', text, ms, d.meta, d.raw);
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

  /* ---- 统一活动流：读工作台里记的 openclaw_runs ---- */

  async loadRuns() {
    const box = this.el.querySelector('#runHist');
    if (!box) return;
    try {
      const d = await api('/api/openclaw/history?limit=20');
      const rows = (d.rows || []);
      if (!rows.length) { box.innerHTML = '<span class="note">还没有运行记录</span>'; return; }
      box.innerHTML = rows.map((r) => `
        <div style="display:flex;gap:8px;align-items:baseline;padding:5px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
          <span class="tag ${r.ok ? 'ok' : 'err'}" style="flex:none">${r.ok ? '成' : '败'}</span>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.task || '')}</span>
          <span class="note" style="flex:none">${esc((r.ts ? new Date(r.ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''))}</span>
        </div>`).join('');
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
