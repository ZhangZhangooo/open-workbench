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
        <span id="cmpInfo" class="note"></span>
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

    this.syncStatus();
    this.loadChats();
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
    const box = this.el.querySelector('#chat');
    box.innerHTML = '';
    this.messages.forEach((m) => this.addMsg(m.role === 'user' ? 'me' : 'ai', m.content));
  },

  newChat() {
    this.chatId = null;
    this.messages = [];
    this.el.querySelector('#chat').innerHTML = '';
    this.el.querySelector('#chatSel').value = '';
  },

  async saveChat() {
    if (!this.messages.length) return;
    const first = this.messages.find((m) => m.role === 'user');
    const r = await post('/api/chats/save', {
      id: this.chatId,
      title: (first ? first.content : '对话').slice(0, 24),
      model: this.el.querySelector('#modelSel').value || '',
      messages: this.messages,
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

  async extractTodos() {
    if (this.streaming) return;
    // 有上下文就用上下文，否则用最后一轮对话内容
    let src = this.ctx ? `${this.ctx.name}\n${this.ctx.text}` : '';
    if (!src) {
      const last = [...this.messages].reverse().find((m) => m.role === 'assistant');
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
        [{ role: 'user', content: ask }], () => {});
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

  async compareSend(txt) {
    const models = this.compare.slice();
    const base = this.ctx
      ? [{ role: 'system', content: `用户给了这个文件（${this.ctx.path}）的内容：\n\`\`\`\n${this.ctx.text}\n\`\`\`` },
         ...this.messages]
      : this.messages;
    const msgs = [...base, { role: 'user', content: txt }];

    const wrap = document.createElement('div');
    wrap.className = 'cmp-out';
    wrap.innerHTML = `<div class="cmp-q">${esc(txt)}</div><div class="cmp-grid">` +
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

  addMsg(role, text) {
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    d.innerHTML = `<div class="who">${role === 'me' ? '你' : '模型'}</div><div class="bub"></div>`;
    this.el.querySelector('#chat').appendChild(d);
    d.querySelector('.bub').textContent = text;
    this.el.querySelector('#chat').scrollTop = 99999;
    return d;
  },

  async send() {
    if (this.streaming) return;
    const box = this.el.querySelector('#prompt');
    const txt = box.value.trim();
    if (!txt) return;
    box.value = '';

    // 勾了两个以上模型就走对比，不写进对话历史
    if (this.compare.length > 1) {
      this.addMsg('me', txt);
      this.streaming = true;
      const btn = this.el.querySelector('#btnSend');
      btn.disabled = true;
      try {
        await this.compareSend(txt);
      } finally {
        this.streaming = false;
        btn.disabled = false;
      }
      return;
    }

    this.addMsg('me', txt);
    this.messages.push({ role: 'user', content: txt });

    this.streaming = true;
    const btn = this.el.querySelector('#btnSend');
    btn.disabled = true;

    const node = this.addMsg('ai', '');
    const bub = node.querySelector('.bub');
    bub.innerHTML = '<span class="caret"></span>';
    let acc = '';

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // 文件上下文作为 system 前置，不进 this.messages —— 历史里不留大段文件内容
          messages: this.ctx
            ? [{ role: 'system', content: `用户给了这个文件（${this.ctx.path}）的内容：\n\`\`\`\n${this.ctx.text}\n\`\`\`` },
               ...this.messages]
            : this.messages,
          model: this.el.querySelector('#modelSel').value || undefined,
        }),
      });
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
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
          if (o.delta) {
            acc += o.delta;
            bub.textContent = acc;
            this.el.querySelector('#chat').scrollTop = 99999;
          } else if (o.error) {
            bub.textContent = '出错了：' + o.error;
            this.streaming = false;
            btn.disabled = false;
            return;
          }
        }
      }
      bub.textContent = acc || '（没有返回内容）';
      this.messages.push({ role: 'assistant', content: acc });
      await this.saveChat();
    } catch (e) {
      bub.textContent = '请求失败：' + e.message;
    }
    this.streaming = false;
    btn.disabled = false;
  },

  commands() {
    return [
      { title: '拉取模型列表', hint: 'AI', run: () => this.loadModels() },
      { title: '开一个新对话', hint: 'AI', run: () => this.newChat() },
    ];
  },
};
