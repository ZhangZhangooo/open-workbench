/* 文件：全盘检索、筛选、导出、打开 */

const { api, post, esc, fmtSize, fmtTime } = window.WB;
const ROW = 46;

export default {
  id: 'files',
  name: '文件',
  el: null,
  rows: [],
  total: 0,
  ext: '',
  offset: 0,
  loading: false,
  cap: 3000,
  ticking: false,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="searchbar">
        <input id="q" placeholder="搜文件名，例如 期末 .docx" autocomplete="off">
        <button class="btn" id="btnScan">开始索引</button>
        <button class="btn" id="btnExport">导出 Excel</button>
      </div>
      <div class="searchbar" style="margin-top:-4px">
        <input id="nlq" placeholder="说人话找文件：上周下的那个安装包 / D盘里特别大的视频"
               autocomplete="off" style="font-size:12.5px">
        <button class="btn" id="btnNl">让它找</button>
      </div>
      <div id="nlInfo" class="note" style="padding:0 0 6px"></div>
      <div class="bar">
        <span id="stat">准备就绪</span>
        <span style="margin-left:auto;display:flex;gap:6px;align-items:center">
          <button class="chip" id="mLarge">大文件</button>
          <button class="chip" id="mUsage">空间占用</button>
          <button class="chip" id="mDup">重复文件</button>
          <button class="chip" id="mRecent">最近</button>
          <button class="chip" id="mGrep">全文</button>
          <select id="minSize" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;padding:0 8px;background:var(--surface);color:var(--ink);font-size:12px">
            <option value="0">不限大小</option>
            <option value="1048576">&gt; 1 MB</option>
            <option value="10485760">&gt; 10 MB</option>
            <option value="104857600">&gt; 100 MB</option>
          </select>
        </span>
      </div>
      <div class="progress" id="prog"><i></i></div>
      <div class="chips" id="chips"></div>
      <div class="bar" id="tagBar" style="flex-wrap:wrap;gap:6px;align-items:center">
        <span class="note">标签：</span><span id="tagChips"></span>
        <button class="chip" id="tagClear">清除筛选</button>
      </div>
      <div class="bar" id="bulkBar" style="display:none;flex-wrap:wrap;gap:8px;align-items:center;background:var(--accent-soft);padding:8px 10px;border-radius:8px">
        <span id="bulkN">已选 0 项</span>
        <input id="tagAdd" placeholder="打标签" style="height:32px;width:110px">
        <button class="btn slim" id="bulkTag">加标签</button>
        <input id="bulkDest" placeholder="目标文件夹，如 D:\\整理" style="height:32px;flex:1;min-width:150px">
        <button class="btn slim" id="bulkCopy">复制</button>
        <button class="btn slim" id="bulkMove">移动</button>
        <button class="btn slim" id="bulkTrash">送回收站</button>
        <button class="btn slim" id="bulkClear">取消选择</button>
      </div>
      <div class="listwrap" id="list">
        <div class="spacer" id="spacer"><div class="rows" id="rows"></div></div>
        <div class="empty" id="empty">输入关键词搜索，或先点「开始索引」把三个盘扫一遍</div>
      </div>
      <div id="preview" class="preview"></div>`;

    let t = null;
    el.querySelector('#q').addEventListener('input', () => {
      clearTimeout(t);
      t = setTimeout(() => this.search(true), 220);
    });

    el.querySelector('#minSize').addEventListener('change', () => this.search(true));
    el.querySelector('#mLarge').onclick = () => this.loadMode('large');
    el.querySelector('#mUsage').onclick = () => this.loadMode('usage');
    el.querySelector('#mDup').onclick = () => this.loadMode('dup');
    el.querySelector('#mRecent').onclick = () => this.loadMode('recent');
    el.querySelector('#mGrep').onclick = () => this.loadMode('grep');

    el.querySelector('#list').addEventListener('scroll', () => {
      this.render();
      const l = el.querySelector('#list');
      if (l.scrollTop + l.clientHeight > l.scrollHeight - 600) {
        if (this.rows.length < this.total && this.rows.length < this.cap && !this.loading) {
          this.search(false);
        }
      }
    }, { passive: true });

    el.querySelector('#rows').addEventListener('click', async (e) => {
      const chk = e.target.closest('.fchk');
      if (chk) {
        const p = chk.dataset.p;
        if (chk.checked) this.sel.add(p); else this.sel.delete(p);
        this.renderBulk();
        return;
      }
      const tx = e.target.closest('.tag-x');
      if (tx) {
        await post('/api/file-tags', { path: tx.dataset.p, tag: tx.dataset.t, op: 'del' });
        await this.loadTags();
        this.render();
        return;
      }
      const b = e.target.closest('button');
      if (b) {
        if (b.dataset.act === 'ask') {
          // 问一问现在挂在 OpenClaw 页下面，带 file 过去会自动切到那个标签
          window.WB.go('claw', { file: b.dataset.p });
          return;
        }
        await post('/api/open', { path: b.dataset.p });
        return;
      }
      const row = e.target.closest('.row');
      if (!row) return;
      const r = this.view[+row.dataset.i];
      if (!r) return;
      // 空间占用模式下点目录 = 下钻一层
      if (this.mode === 'usage') {
        this.usageRoot = r.path;
        this.loadMode('usage');
        return;
      }
      this.preview(r.path);
    });

    el.querySelector('#btnNl').addEventListener('click', () => this.nlSearch());
    el.querySelector('#nlq').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.nlSearch();
    });

    el.querySelector('#btnScan').addEventListener('click', async () => {
      const d = await post('/api/scan', {});
      if (!d.ok) el.querySelector('#stat').textContent = d.error || '无法启动';
    });

    el.querySelector('#btnExport').addEventListener('click', async () => {
      if (!this.rows.length) return;
      const rows = this.rows.map((r) => [r.name, r.size, r.ext, fmtTime(r.mtime), r.path]);
      const d = await post('/api/export', { rows });
      if (d.ok) window.location = d.url;
    });

    this.loadStats();
    this.search(true);

    // 标签 / 批量选择
    this.sel = new Set();
    this.tagMap = {};
    this.activeTag = '';
    this.loadTags();

    el.querySelector('#tagClear').onclick = () => { this.activeTag = ''; this.renderTagChips(); this.render(); };
    el.querySelector('#bulkClear').onclick = () => { this.sel.clear(); this.renderBulk(); this.render(); };
    el.querySelector('#bulkTag').onclick = () => this.bulkAddTag();
    el.querySelector('#bulkCopy').onclick = () => this.bulk('copy');
    el.querySelector('#bulkMove').onclick = () => this.bulk('move');
    el.querySelector('#bulkTrash').onclick = () => this.bulk('trash');
  },

  async loadTags() {
    try {
      const d = await api('/api/file-tags');
      this.tagMap = {};
      (d.rows || []).forEach((r) => {
        (this.tagMap[r.path] = this.tagMap[r.path] || []).push(r.tag);
      });
      this.renderTagChips();
    } catch (e) { /* ignore */ }
  },
  renderTagChips() {
    const box = this.el.querySelector('#tagChips');
    if (!box) return;
    const tags = Object.keys(this.tagMap).length ? [...new Set(Object.values(this.tagMap).flat())] : [];
    box.innerHTML = tags.map((t) =>
      `<button class="chip ${this.activeTag === t ? 'on' : ''}" data-tag="${esc(t)}">${esc(t)}</button>`
    ).join('');
    box.querySelectorAll('[data-tag]').forEach((b) => {
      b.onclick = () => { this.activeTag = b.dataset.tag; this.renderTagChips(); this.render(); };
    });
  },
  renderBulk() {
    const bar = this.el.querySelector('#bulkBar');
    if (!bar) return;
    bar.style.display = this.sel.size ? 'flex' : 'none';
    this.el.querySelector('#bulkN').textContent = `已选 ${this.sel.size} 项`;
  },
  async bulkAddTag() {
    const inp = this.el.querySelector('#tagAdd');
    const tag = inp.value.trim();
    if (!tag || !this.sel.size) { toast('先选文件并填标签'); return; }
    for (const p of this.sel) await post('/api/file-tags', { path: p, tag });
    inp.value = '';
    await this.loadTags();
    this.render();
    toast('已打标签：' + tag);
  },
  async bulk(action) {
    if (!this.sel.size) { toast('没选文件'); return; }
    const paths = [...this.sel];
    if (action === 'trash') {
      if (!confirm(`把 ${paths.length} 个文件送进回收站？（可从回收站恢复，不会真删）`)) return;
    } else {
      const dest = this.el.querySelector('#bulkDest').value.trim();
      if (!dest) { toast('先填目标文件夹'); return; }
      if (!confirm(`${action === 'copy' ? '复制' : '移动'} ${paths.length} 个文件到 ${dest}？`)) return;
    }
    const d = await post('/api/files/bulk', { action, paths, dest: this.el.querySelector('#bulkDest').value.trim() });
    const ok = (d.results || []).filter((r) => r.ok).length;
    const fail = (d.results || []).length - ok;
    toast(`完成 ${ok}${fail ? '，失败 ' + fail : ''}`);
    this.sel.clear(); this.renderBulk(); this.render();
  },

  async search(reset) {
    if (reset) {
      this.offset = 0;
      this.rows = [];
    }
    if (this.loading) return;
    this.loading = true;

    const q = this.el.querySelector('#q').value.trim();
    const minSize = this.el.querySelector('#minSize').value;
    const url = `/api/search?q=${encodeURIComponent(q)}&ext=${encodeURIComponent(this.ext)}&min_size=${minSize}&limit=300&offset=${this.offset}`;
    try {
      const d = await api(url);
      this.total = d.total;
      this.rows = this.rows.concat(d.rows);
      this.offset += d.rows.length;
      this.render();
    } catch (e) {
      this.el.querySelector('#stat').textContent = '搜索失败：' + e.message;
    }
    this.loading = false;
  },

  render() {
    const el = this.el;
    const list = el.querySelector('#list');
    const rowsBox = el.querySelector('#rows');
    const spacer = el.querySelector('#spacer');
    const n = this.rows.length;

    this.view = this.activeTag
      ? this.rows.filter((r) => (this.tagMap[r.path] || []).includes(this.activeTag))
      : this.rows;
    const vn = this.view.length;

    el.querySelector('#empty').style.display = n ? 'none' : 'block';
    spacer.style.height = vn * ROW + 'px';

    const stat = el.querySelector('#stat');
    if (!el.querySelector('#q').value && n) {
      let s = `找到 ${this.total.toLocaleString()} 个，已载入 ${this.rows.length.toLocaleString()}`;
      if (this.activeTag) s += `（按标签「${this.activeTag}」筛出 ${vn} 个）`;
      stat.textContent = s;
    }

    if (this.ticking) return;
    this.ticking = true;
    requestAnimationFrame(() => {
      const st = list.scrollTop;
      const h = list.clientHeight;
      const start = Math.max(0, Math.floor(st / ROW) - 4);
      const end = Math.min(vn, Math.ceil((st + h) / ROW) + 4);
      rowsBox.style.transform = `translateY(${start * ROW}px)`;
      rowsBox.innerHTML = this.view
        .slice(start, end)
        .map((r, k) => this.rowHTML(r, start + k))
        .join('');
      this.ticking = false;
    });
  },

  rowHTML(r, i) {
    const tags = (this.tagMap[r.path] || []).map((t) =>
      `<span class="tag-pill">${esc(t)}<button class="tag-x" data-p="${esc(r.path)}" data-t="${esc(t)}">×</button></span>`
    ).join('');
    return `<div class="row" data-i="${i}">
      <input type="checkbox" class="fchk" data-p="${esc(r.path)}" ${this.sel && this.sel.has(r.path) ? 'checked' : ''}>
      <div class="nm">${esc(r.name)}${tags ? `<div class="tags">${tags}</div>` : ''}</div>
      <div class="pt">${esc(r.snip || r.path)}</div>
      <div class="sz">${fmtSize(r.size)}</div>
      <div class="mt">${r.sub || fmtTime(r.mtime)}</div>
      <div class="op">
        <button data-act="ask" data-p="${esc(r.path)}">问 AI</button>
        <button data-act="open" data-p="${esc(r.path)}">打开</button>
      </div>
    </div>`;
  },

  async nlSearch() {
    const inp = this.el.querySelector('#nlq');
    const q = inp.value.trim();
    const info = this.el.querySelector('#nlInfo');
    if (!q) return;
    info.textContent = '正在理解你说的…';
    const d = await api('/api/files/nl?q=' + encodeURIComponent(q), 120);
    if (!d.ok) {
      info.textContent = '失败：' + (d.error || '');
      return;
    }
    const c = d.cond || {};
    const bits = [];
    if (c.kw) bits.push(`关键词「${c.kw}」`);
    if (c.ext) bits.push(`类型 ${c.ext}`);
    if (c.path) bits.push(`路径含 ${c.path}`);
    if (c.min_size_mb) bits.push(`> ${c.min_size_mb} MB`);
    if (c.days) bits.push(`最近 ${c.days} 天`);
    info.innerHTML = `我理解成：${bits.length ? esc(bits.join(' · ')) : '（没拆出条件）'}`
      + ` —— 找到 ${d.total} 个${d.note ? '。' + esc(d.note) : ''}`;
    // 直接把结果摆进列表
    this.mode = 'nl';
    this.rows = d.rows || [];
    this.total = this.rows.length;
    this.render();
  },

  async loadMode(mode) {
    this.mode = mode;
    const el = this.el;
    const stat = el.querySelector('#stat');
    let rows = [];

    if (mode === 'large') {
      const d = await api('/api/files/top-large?limit=80');
      rows = d.rows || [];
      stat.textContent = `最大的 ${rows.length} 个文件`;
    } else if (mode === 'usage') {
      const root = this.usageRoot || 'C:\\';
      const d = await api('/api/files/usage?root=' + encodeURIComponent(root));
      rows = (d.rows || []).map((r) => ({
        name: r.path.split('\\').filter(Boolean).pop() || r.path,
        path: r.path,
        sub: `${r.count} 个`,
        size: r.size,
        mtime: 0,
        ext: '',
      }));
      stat.textContent = `${root} 下各目录占用（点目录名可下钻）`;
    } else if (mode === 'dup') {
      const d = await api('/api/files/dup?min_size=1048576&limit=40');
      rows = (d.rows || []).map((g) => ({
        name: `${g.paths.length} 份重复 · ${(g.paths[0] || '').split('\\').pop()}`,
        path: g.paths[0],
        sub: `可省 ${fmtSize(g.size * (g.paths.length - 1))}`,
        size: g.size,
        mtime: 0,
        ext: '',
      }));
      stat.textContent = `${rows.length} 组重复文件`;
    } else if (mode === 'recent') {
      const d = await api('/api/files/recent?limit=300');
      rows = d.rows || [];
      stat.textContent = `最近改动的 ${rows.length} 个文件`;
    } else if (mode === 'grep') {
      const q = el.querySelector('#q').value.trim();
      if (!q) {
        stat.textContent = '先在搜索框输入要找的内容，再点全文';
        return;
      }
      stat.textContent = '正在翻文件内容…';
      const d = await api('/api/grep?q=' + encodeURIComponent(q) + '&limit=60');
      rows = (d.hits || []).map((h) => ({
        name: h.name,
        path: h.path,
        snip: h.snippet,
        size: 0,
        mtime: 0,
        ext: '',
      }));
      stat.textContent = `翻了 ${d.scanned} 个文本文件，命中 ${rows.length} 个`;
    }

    this.rows = rows;
    this.total = rows.length;
    this.render();
  },

  async preview(path) {
    const box = this.el.querySelector('#preview');
    const d = await api('/api/files/preview?path=' + encodeURIComponent(path));
    if (d.kind === 'image') {
      box.innerHTML = `<div class="pv-head">${esc(d.name)}</div>
        <img src="${d.url}" style="max-width:100%;max-height:150px;display:block">`;
    } else if (d.kind === 'text') {
      box.innerHTML = `<div class="pv-head">${esc(d.name)}${d.truncated ? '（只显示前 60KB）' : ''}
        <button class="ask-ai" data-p="${esc(path)}">问 AI</button>
        <button class="ask-claw" data-p="${esc(path)}">交给 OpenClaw</button></div>
        <pre>${esc(d.text)}</pre>`;
    } else {
      box.innerHTML = `<div class="pv-head">${esc(d.name || '')}</div>
        <div class="note">${esc(d.hint || '没法预览')}</div>`;
    }
    const ab = box.querySelector('.ask-ai');
    if (ab) ab.onclick = () => window.WB.go('claw', { file: ab.dataset.p });
    const cb = box.querySelector('.ask-claw');
    if (cb) cb.onclick = () => window.WB.go('claw', { task: '帮我分析这个文件：' + cb.dataset.p, autorun: false });
    box.classList.add('on');
    this.render();
  },

  async loadStats() {
    const d = await api('/api/stats');
    const box = this.el.querySelector('#chips');
    box.innerHTML = '';
    const mk = (label, val) => {
      const b = document.createElement('button');
      b.className = 'chip' + (this.ext === val ? ' on' : '');
      b.textContent = label;
      b.onclick = () => {
        this.ext = this.ext === val ? '' : val;
        this.search(true);
        this.loadStats();
      };
      box.appendChild(b);
    };
    mk('全部', '');
    d.exts.forEach((e) => mk(`${e.ext} · ${e.count.toLocaleString()}`, e.ext));
  },

  onShow(arg) {
    // 别处跳过来要搜某个东西时（比如文档页生成的那个文件），直接填进搜索框并搜
    if (arg && typeof arg === 'object' && arg.q) {
      const el0 = this.el;
      el0.querySelector('#q').value = arg.q;
      this.search(true);
    }
    const s = window.WB.status();
    const el = this.el;
    if (!s) return;
    el.querySelector('#prog').classList.toggle('on', s.progress.running);
    el.querySelector('#prog').classList.toggle('busy', s.progress.running);
    if (s.progress.running) {
      el.querySelector('#stat').textContent = `正在索引 ${s.progress.scanned.toLocaleString()} 个文件…`;
    }
  },

  commands() {
    return [
      { title: '开始索引全部磁盘', hint: '文件', run: () => post('/api/scan', {}) },
      { title: '导出当前结果为 Excel', hint: '文件', run: async () => {
        if (!this.rows.length) return;
        const rows = this.rows.map((r) => [r.name, r.size, r.ext, fmtTime(r.mtime), r.path]);
        const d = await post('/api/export', { rows });
        if (d.ok) window.location = d.url;
      } },
    ];
  },
};
