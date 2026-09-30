/* AI：OpenAI 兼容接口，流式对话 */

const { api, post, toast, esc } = window.WB;

export default {
  id: 'ai',
  name: 'AI',
  el: null,
  messages: [],
  streaming: false,
  chatId: null,
  ctx: null,        // 附加的文件上下文 {path, text}
  compare: [],      // 多模型对比时选中的模型
  sys: '',          // 本对话的系统提示词
  attach: null,     // 待发送的图片 {name, url(dataURL)}

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0;flex-wrap:wrap;gap:6px">
        <span id="aiLabel">模型：-</span>
        <span id="aiState"></span>
        <button class="btn" id="btnModels" style="height:30px;padding:0 12px;font-size:12px">拉取模型</button>
        <select id="modelSel" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;padding:0 8px;background:var(--surface);color:var(--ink);font-size:12px;max-width:200px">
          <option value="">（默认模型）</option>
        </select>
        <select id="chatSel" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;padding:0 8px;background:var(--surface);color:var(--ink);font-size:12px;max-width:200px">
          <option value="">（新对话）</option>
        </select>
        <button class="btn" id="btnNew" style="height:30px;padding:0 12px;font-size:12px;margin-left:auto">新对话</button>
      </div>
      <div class="bar" style="padding-top:0;flex-wrap:wrap;gap:6px">
        <button class="btn" id="btnCmp" style="height:28px;padding:0 10px;font-size:12px">对比模式</button>
        <button class="btn" id="btnPrompt" style="height:28px;padding:0 10px;font-size:12px">Prompt 库</button>
        <button class="btn" id="btnSavePrompt" style="height:28px;padding:0 10px;font-size:12px">存当前输入</button>
        <button class="btn" id="btnExport" style="height:28px;padding:0 10px;font-size:12px">导出对话</button>
        <button class="btn" id="btnTodo" style="height:28px;padding:0 10px;font-size:12px">提炼待办</button>
        <button class="btn" id="btnSys" style="height:28px;padding:0 10px;font-size:12px">系统提示词</button>
        <span id="cmpInfo" class="note"></span>
      </div>
      <div id="sysBox" class="cmp-box" style="display:none">
        <div class="note" style="margin-bottom:6px">
          这段会作为 system 消息拼在每次请求最前面，只作用于<strong>当前这个对话</strong>。
          换对话就是另一份；随对话一起存下来。
        </div>
        <textarea id="sysText" class="sys-ta" placeholder="比如：你是我的航空业分析师，回答一律用中文，先给结论再给依据。"></textarea>
        <div style="margin-top:6px;display:flex;gap:8px;align-items:center">
          <button class="btn primary" id="btnSysSave" style="height:28px;padding:0 12px;font-size:12px">存到本对话</button>
          <button class="btn" id="btnSysClear" style="height:28px;padding:0 12px;font-size:12px">清空</button>
          <span class="note" id="sysMsg"></span>
        </div>
      </div>
      <div id="cmpBox" class="cmp-box" style="display:none"></div>
      <div id="promptBox" class="cmp-box" style="display:none">
        <div class="note" id="promptList">加载中…</div>
      </div>
      <div id="ctxBar" style="display:none" class="ctx-bar">
        <span class="tag on">上下文</span>
        <span id="ctxName" style="flex:1"></span>
        <button class="btn" id="btnCtxDrop" style="height:26px;padding:0 10px;font-size:12px">去掉</button>
      </div>
      <div id="attBar" class="ctx-bar" style="display:none">
        <span class="tag on">图片</span>
        <img id="attThumb" class="att-thumb" alt="">
        <span id="attName" style="flex:1"></span>
        <button class="btn" id="btnAttDrop" style="height:26px;padding:0 10px;font-size:12px">去掉</button>
      </div>
      <div class="chat" id="chat"></div>
      <div class="composer">
        <textarea id="prompt" placeholder="问点什么。Ctrl + Enter 发送"></textarea>
        <button class="btn primary" id="btnSend" style="height:62px">发送</button>
      </div>`;

    // 云站(纯前端、无本机后端)下，问一问(Ollama)需要桌面版后端代理模型请求，这里不可用，给个明确提示
    if (window.CloudSync && window.CloudSync.active()) {
      const n = document.createElement('div');
      n.className = 'note';
      n.style.cssText = 'background:var(--accent-soft,#222);color:var(--accent,#4aa);padding:8px 10px;border-radius:8px;margin-bottom:10px';
      n.textContent = '本机专属：问一问(Ollama)需要桌面版后端来代理模型请求，云站(纯前端)暂不可用。';
      el.insertBefore(n, el.firstChild);
    }

    el.querySelector('#btnCmp').onclick = () => {
      const box = el.querySelector('#cmpBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.loadCompare();
    };
    el.querySelector('#btnPrompt').onclick = () => {
      const box = el.querySelector('#promptBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) this.loadPrompts();
    };
    el.querySelector('#btnSavePrompt').onclick = () => this.savePrompt();
    el.querySelector('#btnExport').onclick = () => this.exportChat();
    el.querySelector('#btnTodo').onclick = () => this.extractTodos();
    el.querySelector('#btnSys').onclick = () => {
      const box = el.querySelector('#sysBox');
      const on = box.style.display !== 'none';
      box.style.display = on ? 'none' : '';
      if (!on) {
        el.querySelector('#sysText').value = this.sys || '';
        el.querySelector('#sysMsg').textContent = '';
        el.querySelector('#sysText').focus();
      }
    };
    el.querySelector('#btnSysSave').onclick = () => this.saveSys();
    el.querySelector('#btnSysClear').onclick = () => {
      el.querySelector('#sysText').value = '';
      this.saveSys(true);
    };
    el.querySelector('#btnAttDrop').onclick = () => this.setAttach(null);
    el.querySelector('#btnCtxDrop').addEventListener('click', () => this.setCtx(null));
    el.querySelector('#btnSend').addEventListener('click', () => this.send());
    el.querySelector('#btnNew').addEventListener('click', () => this.newChat());
    el.querySelector('#btnModels').addEventListener('click', () => this.loadModels());
    el.querySelector('#chatSel').addEventListener('change', () => this.openChat());

    el.querySelector('#prompt').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.send();
      }
    });

    // 拖图进对话：整块聊天区 + 输入框都能接
    const chatBox = el.querySelector('#chat');
    const hot = (on) => chatBox.classList.toggle('drop-on', on);
    ['dragenter', 'dragover'].forEach((ev) => chatBox.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      hot(true);
    }));
    ['dragleave', 'dragend'].forEach((ev) => chatBox.addEventListener(ev, (e) => {
      e.preventDefault();
      if (e.target === chatBox) hot(false);
    }));
    chatBox.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      hot(false);
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) this.attachImage(f);
    });
    el.querySelector('.composer').addEventListener('dragover', (e) => e.preventDefault());
    el.querySelector('.composer').addEventListener('drop', (e) => {
      e.preventDefault();
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) this.attachImage(f);
    });
    // 粘贴图片也收
    el.querySelector('#prompt').addEventListener('paste', (e) => {
      const it = [...((e.clipboardData && e.clipboardData.items) || [])]
        .find((x) => x.type && x.type.startsWith('image/'));
      if (!it) return;
      e.preventDefault();
      this.attachImage(it.getAsFile());
    });
    this.hydrate();

    this.syncStatus();
    this.loadChats();
  },

  /* ---- 系统提示词 ---- */

  async saveSys(silent) {
    const txt = this.el.querySelector('#sysText').value.trim();
    this.sys = txt;
    const msg = this.el.querySelector('#sysMsg');
    if (this.messages.length) {
      await this.saveChat();
      if (msg) msg.textContent = '已存到本对话';
    } else if (msg) {
      msg.textContent = '这条新对话发第一句时一起存';
    }
    if (!silent) toast(txt ? '系统提示词已设' : '系统提示词已清空');
    this.syncSysBtn();
  },

  syncSysBtn() {
    const b = this.el.querySelector('#btnSys');
    if (b) b.textContent = this.sys ? '系统提示词 ●' : '系统提示词';
    const t = this.el.querySelector('#sysText');
    if (t && document.activeElement !== t) t.value = this.sys || '';
  },

  /* ---- 对话历史 ---- */

  async loadChats() {
    const d = await api('/api/chats');
    const sel = this.el.querySelector('#chatSel');
    sel.innerHTML = '<option value="">（新对话）</option>' + (d.rows || []).map((r) =>
      `<option value="${r.id}">${esc(r.title || '对话')}${r.model ? ' · ' + esc(r.model) : ''}</option>`
    ).join('');
    if (this.chatId) sel.value = String(this.chatId);
  },

  async openChat() {
    const id = +this.el.querySelector('#chatSel').value || null;
    if (!id) { this.newChat(); return; }
    const d = await api('/api/chats/get?id=' + id);
    this.chatId = id;
    this.messages = d.messages || [];
    this.sys = d.sys || '';
    this.setAttach(null);
    this.syncSysBtn();
    this.renderAll();
  },

  /* 把 this.messages 整个重画一遍（分支/续写后要用） */
  renderAll() {
    const box = this.el.querySelector('#chat');
    box.innerHTML = '';
    this.messages.forEach((m, i) => {
      if (m.hidden) return;
      this.addMsg(m.role === 'user' ? 'me' : 'ai', m.content, i);
    });
  },

  newChat() {
    this.chatId = null;
    this.messages = [];
    this.sys = '';
    this.setAttach(null);
    this.el.querySelector('#chat').innerHTML = '';
    this.el.querySelector('#chatSel').value = '';
    this.syncSysBtn();
    this.el.querySelector('#sysText').value = '';
  },

  /* 图片存库里太占地方 —— 落盘前换成一行文字说明 */
  stripImages(msgs) {
    return msgs.map((m) => {
      if (!Array.isArray(m.content)) return m;
      const txt = m.content.filter((p) => p.type === 'text').map((p) => p.text).join(' ');
      const n = m.content.filter((p) => p.type === 'image_url').length;
      return { role: m.role, content: `${txt}${n ? `\n[附了 ${n} 张图，图没存进历史]` : ''}`.trim() };
    });
  },

  async saveChat() {
    if (!this.messages.length) return;
    const first = this.messages.find((m) => m.role === 'user');
    const title = typeof first?.content === 'string'
      ? first.content
      : (Array.isArray(first?.content) ? (first.content.find((p) => p.type === 'text')?.text || '看图') : '对话');
    const r = await post('/api/chats/save', {
      id: this.chatId,
      title: title.slice(0, 24),
      model: this.el.querySelector('#modelSel').value || '',
      sys: this.sys || '',
      messages: this.stripImages(this.messages),
    });
    if (r.ok && r.id) {
      this.chatId = r.id;
      this.loadChats();
    }
  },

  /* ---- Prompt 库 ---- */

  async loadPrompts() {
    const box = this.el.querySelector('#promptList');
    const d = await api('/api/prompts');
    const rows = d.rows || [];
    if (!rows.length) {
      box.innerHTML = '<div class="note">还没有。在输入框里写好一段常用提示，点「存当前输入」。</div>';
      return;
    }
    box.innerHTML = rows.map((p) => `
      <div class="p-row" data-id="${p.id}">
        <div style="display:flex;align-items:baseline;gap:8px">
          <b style="font-weight:500">${esc(p.title)}</b>
          ${p.tags ? `<span class="tag">${esc(p.tags)}</span>` : ''}
          <button class="use" style="border:0;background:transparent;color:var(--accent);cursor:pointer;font-size:12px">用</button>
          <button class="rm" style="border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删</button>
        </div>
        <div class="note" style="margin-top:2px">${esc((p.body || '').slice(0, 160))}</div>
      </div>`).join('');

    box.querySelectorAll('.p-row').forEach((row) => {
      row.querySelector('.use').onclick = () => {
        this.el.querySelector('#prompt').value = (rows.find((x) => x.id === +row.dataset.id) || {}).body || '';
        this.el.querySelector('#prompt').focus();
      };
      row.querySelector('.rm').onclick = async () => {
        await post('/api/prompts/del', { id: +row.dataset.id });
        this.loadPrompts();
      };
    });
  },

  async savePrompt() {
    const txt = this.el.querySelector('#prompt').value.trim();
    if (!txt) { toast('输入框是空的'); return; }
    const title = prompt('给这段提示起个名字', txt.slice(0, 16));
    if (!title) return;
    const r = await post('/api/prompts/save', { title, body: txt, tags: '' });
    if (!r.ok) { toast(r.error || '没存上'); return; }
    toast('已存进 Prompt 库');
    this.loadPrompts();
  },

  /* ---- 导出对话 ---- */

  exportChat() {
    if (!this.messages.length) { toast('这个对话还是空的'); return; }
    const model = this.el.querySelector('#modelSel').value || '默认模型';
    const title = (this.messages.find((m) => m.role === 'user') || {}).content || '对话';
    const lines = [
      `# ${title.slice(0, 40)}`,
      '',
      `- 模型：${model}`,
      `- 导出时间：${new Date().toLocaleString('zh-CN')}`,
      '',
      '---',
      '',
    ];
    this.messages.forEach((m) => {
      lines.push(`### ${m.role === 'user' ? '你' : '模型'}`);
      lines.push('');
      lines.push(m.content || '');
      lines.push('');
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `对话-${title.slice(0, 16).replace(/[\\/:*?"<>|]/g, '')}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('已导出 Markdown');
  },

  /* ---- AI 提炼待办 ---- */

  async extractTodos(srcOverride) {
    if (this.streaming) return;
    // 优先用指定的那条回复；没有就用文件上下文；再没有就用最后一轮对话
    let src = typeof srcOverride === 'string' ? srcOverride : '';
    if (!src) src = this.ctx ? `${this.ctx.name}\n${this.ctx.text}` : '';
    if (!src) {
      const last = [...this.messages].reverse()
        .find((m) => m.role === 'assistant' && typeof m.content === 'string');
      src = last ? last.content : '';
    }
    if (!src) { toast('没有可提炼的内容'); return; }

    this.streaming = true;
    const btn = this.el.querySelector('#btnTodo');
    btn.disabled = true;
    btn.textContent = '提炼中…';
    try {
      const ask = '从下面这段内容里提炼出可执行的待办事项。'
        + '只输出待办本身，一行一条，不要编号、不要解释、不要寒暄，'
        + '每条不超过 20 个字。如果内容里没有明确要做的事，就输出「无」。\n\n'
        + src.slice(0, 8000);
      const r = await this.streamChat(this.el.querySelector('#modelSel').value || '',
        [...(this.sys ? [{ role: 'system', content: this.sys }] : []),
         { role: 'user', content: ask }], () => {});
      if (r.error) { toast('失败：' + r.error); return; }
      const items = (r.text || '').split('\n')
        .map((s) => s.replace(/^[\s\-*•\d.、)]+/, '').trim())
        .filter((s) => s && s.length <= 60 && s !== '无');
      if (!items.length) { toast('没提炼出待办'); return; }
      this.showTodos(items);
    } catch (e) {
      toast('失败：' + e.message);
    } finally {
      this.streaming = false;
      btn.disabled = false;
      btn.textContent = '提炼待办';
    }
  },

  showTodos(items) {
    const chat = this.el.querySelector('#chat');
    const wrap = document.createElement('div');
    wrap.className = 'todo-out';
    wrap.innerHTML = `<div class="cmp-q">提炼出 ${items.length} 条待办，勾上要加进「今日」的：</div>` +
      items.map((t, i) => `
        <label class="todo-pick">
          <input type="checkbox" data-i="${i}" checked>
          <span>${esc(t)}</span>
        </label>`).join('') +
      `<div style="margin-top:8px">
        <button class="btn primary" id="btnAddTodos" style="height:30px;padding:0 12px;font-size:12px">加到今天</button>
        <span class="note" style="margin-left:8px" id="todoMsg"></span>
      </div>`;
    chat.appendChild(wrap);
    chat.scrollTop = 99999;

    wrap.querySelector('#btnAddTodos').onclick = async () => {
      const picked = [...wrap.querySelectorAll('input:checked')]
        .map((c) => items[+c.dataset.i]);
      if (!picked.length) { toast('一条都没勾'); return; }
      const d = window.WB.day();
      for (const t of picked) {
        await post('/api/today/add', { day: d, text: t });
      }
      wrap.querySelector('#todoMsg').textContent = `已加 ${picked.length} 条到今天`;
      toast(`加了 ${picked.length} 条`);
      window.WB.refresh();
    };
  },

  /* ---- 多模型对比 ---- */

  async loadCompare() {
    const box = this.el.querySelector('#cmpBox');
    box.innerHTML = '<div class="note">拉取模型…</div>';
    const d = await api('/api/ai/models');
    if (!d.ok || !d.models) {
      box.innerHTML = `<div class="note">拉不到模型：${esc(d.error || '')}</div>`;
      return;
    }
    const pick = (m, on) => {
      const i = this.compare.indexOf(m);
      if (on && i < 0) this.compare.push(m);
      if (!on && i >= 0) this.compare.splice(i, 1);
      this.syncCompare();
    };
    box.innerHTML = `<div class="note" style="margin-bottom:6px">
        勾上要对比的模型（至少两个），发送时会对同一个问题各问一遍，并排显示。
        对比结果不进对话历史。</div>
      <div id="cmpChips"></div>`;
    const chips = box.querySelector('#cmpChips');
    d.models.forEach((m) => {
      const b = document.createElement('button');
      b.className = 'chip' + (this.compare.includes(m) ? ' on' : '');
      b.textContent = m;
      b.onclick = () => {
        const on = !b.classList.contains('on');
        b.classList.toggle('on', on);
        pick(m, on);
      };
      chips.appendChild(b);
    });
    this.syncCompare();
  },

  syncCompare() {
    const info = this.el.querySelector('#cmpInfo');
    info.textContent = this.compare.length > 1
      ? `已选 ${this.compare.length} 个模型：${this.compare.join(' / ')}`
      : (this.compare.length ? '再选一个才对比' : '');
  },

  async compareSend(content) {
    const models = this.compare.slice();
    const msgs = [...this.withSys(this.messages), { role: 'user', content }];
    const label = typeof content === 'string'
      ? content
      : (content.find((p) => p.type === 'text') || {}).text || '（图片）';

    const wrap = document.createElement('div');
    wrap.className = 'cmp-out';
    wrap.innerHTML = `<div class="cmp-q">${esc(label)}</div><div class="cmp-grid">` +
      models.map((m, i) => `<div class="cmp-col">
          <div class="cmp-m">${esc(m)}</div>
          <div class="bub" data-i="${i}">等待…</div>
        </div>`).join('') + '</div>';
    const chat = this.el.querySelector('#chat');
    chat.appendChild(wrap);
    chat.scrollTop = 99999;

    await Promise.all(models.map(async (m, i) => {
      const bub = wrap.querySelector(`[data-i="${i}"]`);
      const t0 = Date.now();
      try {
        const r = await this.streamChat(m, msgs, (t) => { bub.textContent = t; });
        const sec = ((Date.now() - t0) / 1000).toFixed(1);
        bub.textContent = r.error
          ? `出错：${r.error}`
          : (r.text || '（没返回内容）');
        bub.dataset.sec = sec;
      } catch (e) {
        bub.textContent = '失败：' + e.message;
      }
    }));
    chat.scrollTop = 99999;
  },

  async streamChat(model, msgs, onDelta) {
    const res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: msgs, model: model || undefined }),
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let acc = '';
    let err = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const p of parts) {
        const s = p.trim();
        if (!s.startsWith('data:')) continue;
        let o;
        try { o = JSON.parse(s.slice(5).trim()); } catch (_) { continue; }
        if (o.delta) { acc += o.delta; if (onDelta) onDelta(acc); }
        else if (o.error) { err = o.error; }
      }
    }
    return { text: acc, error: err };
  },

  syncStatus() {
    const s = window.WB.status();
    if (!s) return;
    const el = this.el;
    el.querySelector('#aiLabel').textContent = `模型：${s.config.ai.label} / ${s.config.ai.model}`;
    el.querySelector('#aiState').innerHTML = s.config.ai.api_key_set
      ? '<span class="tag ok">key 已配置</span>'
      : '<span class="tag warn">还没填 key</span>';
  },

  onShow(arg) {
    this.syncStatus();
    // 从文件页「问 AI」过来：arg = {file: 'C:\\...'}
    if (arg && arg.file) this.loadFile(arg.file);
  },

  async loadFile(path) {
    const d = await api('/api/files/preview?path=' + encodeURIComponent(path));
    if (d.kind !== 'text' || !d.text) {
      toast(d.hint || '这个文件没法当上下文');
      return;
    }
    const MAX = 12000;
    const text = d.text.length > MAX ? d.text.slice(0, MAX) + '\n…（已截断）' : d.text;
    this.setCtx({ path, name: d.name || path.split('\\').pop(), text });
    toast('已把文件放进上下文');
  },

  setCtx(c) {
    this.ctx = c;
    const bar = this.el.querySelector('#ctxBar');
    bar.style.display = c ? '' : 'none';
    if (c) {
      this.el.querySelector('#ctxName').textContent =
        `${c.name} · ${c.text.length} 字符`;
    }
  },

  /* ---- 图片附件（拖进来 / 粘进来） ---- */

  setAttach(a) {
    this.attach = a;
    const bar = this.el.querySelector('#attBar');
    if (!bar) return;
    bar.style.display = a ? '' : 'none';
    if (a) {
      this.el.querySelector('#attThumb').src = a.url;
      this.el.querySelector('#attName').textContent = `${a.name} · 发送时走视觉模型`;
    }
  },

  attachImage(file) {
    if (!file) return;
    if (!/^image\//.test(file.type || '')) { toast('只能拖图片进来'); return; }
    if (file.size > 6 * 1024 * 1024) { toast('图片太大（超过 6MB），先压一下'); return; }
    const fr = new FileReader();
    fr.onload = () => {
      this.setAttach({ name: file.name || '剪贴板图片', url: fr.result });
      const sel = this.el.querySelector('#modelSel');
      toast(sel.value
        ? '图片挂上了，发送时会一起发过去'
        : '图片挂上了 —— 记得选个能看图的模型（本地目前只有 gemma4:31b 能看图）');
    };
    fr.readAsDataURL(file);
  },

  /* ---- 消息操作：分支 / 复制 / 转待办 / 转资料 / 续写 ---- */

  renderActs() {
    const nodes = [...this.el.querySelectorAll('.msg.ai')];
    const lastAi = nodes[nodes.length - 1];
    nodes.forEach((n) => {
      const b = n.querySelector('[data-a="cont"]');
      if (b) b.style.display = n === lastAi ? '' : 'none';
    });
  },

  async branch(i) {
    if (i == null || !this.messages[i]) { toast('这条找不到'); return; }
    const cut = this.messages.slice(0, i + 1).map((m) => ({ role: m.role, content: m.content }));
    this.newChat();
    this.messages = cut;
    const keepSys = this.sys;
    this.sys = keepSys;              // 系统提示词跟着分支走
    this.syncSysBtn();
    this.renderAll();
    await this.saveChat();
    toast(`已从这条岔出新对话（${cut.length} 条历史）`);
    window.WB.refresh();
  },

  copyMsg(i) {
    const m = this.messages[i];
    const txt = m && (typeof m.content === 'string'
      ? m.content
      : (m.content || []).filter((p) => p.type === 'text').map((p) => p.text).join(' '));
    if (!txt) { toast('没内容可复制'); return; }
    navigator.clipboard.writeText(txt).then(
      () => toast('已复制'),
      () => toast('复制失败，手动选吧'),
    );
  },

  msgToTodo(i) {
    const m = this.messages[i];
    if (!m || typeof m.content !== 'string' || !m.content) { toast('这条提炼不出东西'); return; }
    this.extractTodos(m.content);
  },

  async msgToKb(i) {
    const m = this.messages[i];
    if (!m || typeof m.content !== 'string' || !m.content) { toast('这条存不了'); return; }
    const firstLine = (m.content.split('\n').find((s) => s.trim()) || 'AI 回复').trim();
    const r = await post('/api/kb/save', {
      title: firstLine.slice(0, 40),
      body: m.content,
      tags: 'AI',
      source: 'ai',
    });
    if (!r.ok) { toast(r.error || '没存上'); return; }
    toast('已存进资料库');
  },

  /* 断线续写：把已写了一半的回答当作 assistant 历史，让模型接着往下说 */
  async resume(i) {
    if (this.streaming) return;
    const m = this.messages[i];
    if (!m || m.role !== 'assistant' || typeof m.content !== 'string' || !m.content) {
      toast('这条没有内容可接着写');
      return;
    }
    const base = this.messages.slice(0, i + 1);
    const ask = { role: 'user', content: '继续，接着上面往下写，不要重复已经写过的内容。' };
    this.messages = [...base, ask];
    this.renderAll();
    this.addMsg('me', ask.content);

    this.streaming = true;
    const btn = this.el.querySelector('#btnSend');
    btn.disabled = true;
    const node = this.addMsg('ai', '');
    const bub = node.querySelector('.bub');
    bub.innerHTML = '<span class="caret"></span>';
    try {
      const r = await this.streamChat(
        this.el.querySelector('#modelSel').value || '',
        this.withSys(this.messages),
        (t) => { bub.textContent = t; this.el.querySelector('#chat').scrollTop = 99999; },
      );
      if (r.error) {
        bub.textContent = '出错：' + r.error;
      } else {
        bub.textContent = m.content + (r.text || '');
        this.messages.push({ role: 'assistant', content: r.text || '' });
        await this.saveChat();
      }
    } catch (e) {
      bub.textContent = '请求失败：' + e.message;
    }
    this.streaming = false;
    btn.disabled = false;
    this.renderActs();
  },

  /* 统一拼上前置的 system：本对话系统提示词 + 文件上下文 */
  withSys(msgs) {
    const head = [];
    if (this.sys) head.push({ role: 'system', content: this.sys });
    if (this.ctx) head.push({ role: 'system', content: `用户给了这个文件（${this.ctx.path}）的内容：\n\`\`\`\n${this.ctx.text}\n\`\`\`` });
    return [...head, ...msgs];
  },

  async loadModels() {
    const d = await api('/api/ai/models');
    const sel = this.el.querySelector('#modelSel');
    const st = this.el.querySelector('#aiState');
    if (!d.ok) {
      st.innerHTML = `<span class="tag err">${esc(d.error)}</span>`;
      return;
    }
    sel.innerHTML = '<option value="">（默认模型）</option>';
    d.models.forEach((m) => {
      const o = document.createElement('option');
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    });
    st.innerHTML = `<span class="tag ok">${d.models.length} 个模型</span>`;
  },

  addMsg(role, text, i) {
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    if (i != null) d.dataset.i = String(i);
    const acts = role === 'ai'
      ? `<div class="msg-acts">
           <button data-a="branch">分支</button>
           <button data-a="copy">复制</button>
           <button data-a="todo">→ 待办</button>
           <button data-a="kb">→ 资料</button>
           <button data-a="cont">继续</button>
         </div>`
      : '';
    d.innerHTML = `<div class="who">${role === 'me' ? '你' : '模型'}</div><div class="bub"></div>${acts}`;
    const bub = d.querySelector('.bub');

    if (Array.isArray(text)) {
      const tp = text.find((p) => p.type === 'text');
      bub.textContent = (tp && tp.text) || '';
      text.filter((p) => p.type === 'image_url').forEach((p) => {
        const img = document.createElement('img');
        img.className = 'bub-img';
        img.src = p.image_url.url;
        bub.appendChild(img);
      });
    } else {
      bub.textContent = text == null ? '' : text;
    }

    this.el.querySelector('#chat').appendChild(d);

    if (role === 'ai' && i != null) {
      const idx = i;
      d.querySelectorAll('.msg-acts [data-a]').forEach((b) => {
        b.onclick = () => {
          const a = b.dataset.a;
          if (a === 'branch') this.branch(idx);
          else if (a === 'copy') this.copyMsg(idx);
          else if (a === 'todo') this.msgToTodo(idx);
          else if (a === 'kb') this.msgToKb(idx);
          else if (a === 'cont') this.resume(idx);
        };
      });
    }
    this.el.querySelector('#chat').scrollTop = 99999;
    this.renderActs();
    return d;
  },

  /* 打开模块时把界面拉回上次的状态（系统提示词按钮上的点之类） */
  hydrate() {
    this.syncSysBtn();
    this.setAttach(this.attach);
  },

  async send() {
    if (this.streaming) return;
    const box = this.el.querySelector('#prompt');
    const txt = box.value.trim();
    if (!txt && !this.attach) return;
    box.value = '';

    // 图片挂上了就把这一轮的内容做成多模态数组
    const attach = this.attach;
    const content = attach
      ? [{ type: 'text', text: txt || '看看这张图' },
         { type: 'image_url', image_url: { url: attach.url } }]
      : txt;

    // 勾了两个以上模型就走对比，不写进对话历史
    if (this.compare.length > 1) {
      this.addMsg('me', content);
      this.streaming = true;
      const btn = this.el.querySelector('#btnSend');
      btn.disabled = true;
      try {
        await this.compareSend(content);
      } finally {
        this.streaming = false;
        btn.disabled = false;
        this.setAttach(null);
      }
      return;
    }

    this.addMsg('me', content);
    this.messages.push({ role: 'user', content });
    this.setAttach(null);

    this.streaming = true;
    const btn = this.el.querySelector('#btnSend');
    btn.disabled = true;

    const node = this.addMsg('ai', '');
    const bub = node.querySelector('.bub');
    bub.innerHTML = '<span class="caret"></span>';

    try {
      const r = await this.streamChat(
        this.el.querySelector('#modelSel').value || '',
        this.withSys(this.messages),
        (t) => { bub.textContent = t; this.el.querySelector('#chat').scrollTop = 99999; },
      );
      if (r.error) {
        bub.textContent = '出错了：' + r.error;
        // 失败也别丢东西：把半截回答和错误都留在界面上，可以点「继续」接着写
        if (r.text) this.messages.push({ role: 'assistant', content: r.text });
      } else {
        bub.textContent = r.text || '（没有返回内容）';
        this.messages.push({ role: 'assistant', content: r.text || '' });
        await this.saveChat();
      }
    } catch (e) {
      bub.textContent = '请求失败：' + e.message;
    }
    this.streaming = false;
    btn.disabled = false;
    this.renderActs();
  },

  commands() {
    return [
      { title: '拉取模型列表', hint: 'AI', run: () => this.loadModels() },
      { title: '开一个新对话', hint: 'AI', run: () => this.newChat() },
    ];
  },
};
