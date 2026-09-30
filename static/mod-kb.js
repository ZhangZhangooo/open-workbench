/* J 域 资料 / 知识库（87-94）
   87 全文检索（倒排索引，中文可搜）  88 双链 [[]] + 反向链接
   89 阅读队列（待读/在读/已读）      90 AI 摘要卡
   91 多选批量改标签                  92 相关推荐
   93 整库导出 zip                    94 收藏集
   另保留原有的「加一条 / 文件导入 / 问知识库」。 */

const { api, post, toast, esc, fmtTime, go } = window.WB;

const ST = ['待读', '在读', '已读'];

function stClass(s) {
  const v = s || '待读';
  return v === '已读' ? 'ok' : v === '在读' ? 'mid' : 'todo';
}

export default {
  id: 'kb',
  name: '资料库',
  el: null,
  tab: 'lib',
  q: '',
  status: '',
  favOnly: false,
  cur: 0,            // 正在看详情的条目 id
  sel: new Set(),    // 多选
  graph: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <button class="chip on" data-tab="lib">资料库</button>
        <button class="chip" data-tab="queue">阅读队列</button>
        <button class="chip" data-tab="graph">双链</button>
        <button class="chip" data-tab="ask">提问</button>
        <span class="g" id="kbStat" style="margin-left:auto;font-size:12px"></span>
        <button class="btn" id="kbExport" title="把整库导成 zip（每条一个 .md）">导出整库</button>
      </div>

      <!-- 87 资料库：搜索 / 筛选 / 列表 / 批量 / 详情 -->
      <div class="stack" id="paneLib">
        <div class="panel">
          <div style="display:flex;gap:8px;align-items:center">
            <input id="kSearch" placeholder="搜标题、标签、正文（中文词组也能搜）"
              style="flex:1;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
            <select id="kStatus" class="kb-sel">
              <option value="">全部状态</option>
              ${ST.map((s) => `<option value="${s}">${s}</option>`).join('')}
            </select>
            <button class="chip" id="kFavOnly" title="只看收藏">★ 收藏</button>
            <button class="btn" id="kReindex" title="给老资料补建检索索引">重建索引</button>
          </div>
          <div id="kMeta" class="g" style="margin-top:6px;font-size:12px"></div>
        </div>

        <!-- 详情 -->
        <div class="panel" id="kDetail" style="display:none"></div>

        <!-- 批量操作条 -->
        <div class="panel" id="kBulk" style="display:none">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <b style="font-weight:500" id="kSelN">已选 0 条</b>
            <input id="kBulkTag" placeholder="标签" class="kb-inp">
            <button class="btn" data-op="add">加标签</button>
            <button class="btn" data-op="remove">去标签</button>
            <button class="btn" data-op="replace">清空并设为</button>
            <button class="btn" id="kBulkRead">标为已读</button>
            <button class="btn" id="kBulkUnfav">取消收藏</button>
            <button class="btn" id="kBulkClear" style="margin-left:auto">取消选择</button>
          </div>
        </div>

        <div class="panel">
          <div style="display:flex;align-items:baseline;gap:8px">
            <h3 style="margin:0">已有资料</h3>
            <button class="btn" id="kToggleNew" style="margin-left:auto">+ 新增 / 导入</button>
          </div>
          <div id="kNew" style="display:none;margin-top:10px">
            <div class="field"><label>标题</label><input id="kTitle" placeholder="例如：备份怎么导出"></div>
            <div class="field"><label>标签</label><input id="kTags" placeholder="逗号分隔，可选"></div>
            <div class="field"><label>正文</label><textarea id="kBody" rows="4" placeholder="知识内容；正文里写 [[另一篇标题]] 就会自动生成双链"></textarea></div>
            <div style="display:flex;gap:8px;align-items:center">
              <select id="kNewStatus" class="kb-sel">${ST.map((s) => `<option value="${s}">${s}</option>`).join('')}</select>
              <label class="kb-chk"><input type="checkbox" id="kNewFav"> 收藏</label>
              <button class="btn primary" id="btnKbSave">保存</button>
            </div>
            <hr style="border:0;border-top:1px solid var(--line-soft);margin:14px 0">
            <div class="field"><label>从文件导入</label><input id="kPath" placeholder="C:\\\\Users\\\\...\\\\笔记.docx 或 .txt/.md/.pdf"></div>
            <div class="field"><label>标题(可空)</label><input id="kImpTitle" placeholder="不填就用文件名"></div>
            <div class="field"><label>标签(可空)</label><input id="kImpTags" placeholder="可选"></div>
            <button class="btn" id="btnKbImport">抽取文字并入库</button>
            <div class="note" style="margin-top:6px">支持 .txt/.md/.docx/.pdf/.xlsx/.csv 等，抽出的文字会原样存进资料库。</div>
          </div>
          <div id="kList" class="note" style="margin-top:10px">空</div>
        </div>
      </div>

      <!-- 89 阅读队列 -->
      <div class="stack" id="paneQueue" style="display:none">
        <div class="panel">
          <h3>阅读队列</h3>
          <div class="kb-q" id="kQueue"></div>
          <div class="note" style="margin-top:8px">点任一数字就把资料库按那个状态筛一遍。</div>
        </div>
      </div>

      <!-- 88 双链 -->
      <div class="stack" id="paneGraph" style="display:none">
        <div class="panel">
          <h3>双链总览</h3>
          <div class="note">正文里写 <code>[[标题]]</code> 就会连过去；下面按「被引用数」排。</div>
          <div id="kGraph" class="note" style="margin-top:8px">空</div>
        </div>
      </div>

      <!-- 提问 -->
      <div class="stack" id="paneAsk" style="display:none">
        <div class="panel">
          <h3>问本地资料库</h3>
          <textarea id="kQ" rows="3" placeholder="基于你存进来的资料问我，例如：备份文件在哪里、怎么恢复？"></textarea>
          <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
            <button class="btn primary" id="btnKbAsk">问 AI</button>
            <button class="btn" id="btnKbSelAsk">拿选中的几条问</button>
            <button class="btn" id="btnKbClaw">交给 OpenClaw 干</button>
          </div>
          <div id="kAnswer" class="note" style="margin-top:10px;white-space:pre-wrap"></div>
          <div id="kUsed" class="g" style="margin-top:6px;font-size:12px"></div>
        </div>
      </div>`;

    el.querySelectorAll('[data-tab]').forEach((b) => {
      b.onclick = () => {
        this.tab = b.dataset.tab;
        el.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x === b));
        ['lib', 'queue', 'graph', 'ask'].forEach((t) => {
          el.querySelector('#pane' + t[0].toUpperCase() + t.slice(1)).style.display =
            this.tab === t ? '' : 'none';
        });
        this.load();
      };
    });

    const q = el.querySelector('#kSearch');
    let tmr = 0;
    q.addEventListener('input', () => {
      clearTimeout(tmr);
      tmr = setTimeout(() => { this.q = q.value.trim(); this.load(); }, 220);
    });
    q.addEventListener('keydown', (e) => { if (e.key === 'Enter') { this.q = q.value.trim(); this.load(); } });

    el.querySelector('#kStatus').onchange = (e) => { this.status = e.target.value; this.load(); };
    el.querySelector('#kFavOnly').onclick = (e) => {
      this.favOnly = !this.favOnly;
      e.currentTarget.classList.toggle('on', this.favOnly);
      this.load();
    };
    el.querySelector('#kbExport').onclick = () => {
      location.href = '/api/kb/export';
      toast('正在打包整库…');
    };
    el.querySelector('#kReindex').onclick = async (e) => {
      e.target.disabled = true;
      const r = await post('/api/kb/reindex', {});
      e.target.disabled = false;
      toast(r.ok ? `索引重建完成：${r.n} 条 / ${r.index_size} 词条` : (r.error || '失败'));
      this.load();
    };

    el.querySelector('#kToggleNew').onclick = () => {
      const box = el.querySelector('#kNew');
      box.style.display = box.style.display === 'none' ? '' : 'none';
    };

    el.querySelector('#btnKbSave').onclick = async () => {
      const title = el.querySelector('#kTitle').value.trim();
      const body = el.querySelector('#kBody').value;
      if (!title && !body.trim()) return;
      const r = await post('/api/kb/save', {
        title, body,
        tags: el.querySelector('#kTags').value.trim(),
        status: el.querySelector('#kNewStatus').value,
        fav: el.querySelector('#kNewFav').checked ? 1 : 0,
      });
      if (!r.ok) return toast(r.error || '保存失败');
      el.querySelector('#kTitle').value = '';
      el.querySelector('#kTags').value = '';
      el.querySelector('#kBody').value = '';
      el.querySelector('#kNewFav').checked = false;
      toast('已存入资料库');
      this.load();
    };

    el.querySelector('#btnKbImport').onclick = async () => {
      const path = el.querySelector('#kPath').value.trim();
      if (!path) return;
      const btn = el.querySelector('#btnKbImport');
      btn.disabled = true; btn.textContent = '抽取中…';
      const r = await post('/api/kb/import', {
        path,
        title: el.querySelector('#kImpTitle').value.trim(),
        tags: el.querySelector('#kImpTags').value.trim(),
      });
      btn.disabled = false; btn.textContent = '抽取文字并入库';
      if (!r.ok) return toast(r.error || '导入失败');
      el.querySelector('#kPath').value = '';
      el.querySelector('#kImpTitle').value = '';
      el.querySelector('#kImpTags').value = '';
      toast(`已导入：${r.name}（${r.chars} 字）`);
      this.load();
    };

    // 列表：选择 / 详情 / 收藏 / 删除 / 状态
    const list = el.querySelector('#kList');
    list.addEventListener('click', (e) => this.onListClick(e));

    // 批量
    el.querySelector('#kBulk').addEventListener('click', async (e) => {
      const b = e.target.closest('button[data-op]');
      if (b) {
        const tag = el.querySelector('#kBulkTag').value.trim();
        if (!tag && b.dataset.op !== 'replace') return toast('先填个标签');
        const r = await post('/api/kb/tags', {
          ids: [...this.sel], op: b.dataset.op, tag,
        });
        if (!r.ok) return toast(r.error || '失败');
        toast(`已更新 ${r.n} 条标签`);
        el.querySelector('#kBulkTag').value = '';
        this.load();
        return;
      }
      if (e.target.id === 'kBulkRead') {
        for (const id of this.sel) await post('/api/kb/status', { id, status: '已读' });
        toast(`已把 ${this.sel.size} 条标为已读`);
        this.load();
        return;
      }
      if (e.target.id === 'kBulkUnfav') {
        for (const id of this.sel) await post('/api/kb/fav', { id, on: 0 });
        toast('已取消收藏');
        this.load();
        return;
      }
      if (e.target.id === 'kBulkClear') {
        this.sel.clear();
        this.renderList(this._last || []);
        return;
      }
    });

    el.querySelector('#kQueue').addEventListener('click', (e) => {
      const c = e.target.closest('[data-go]');
      if (!c) return;
      this.status = c.dataset.go;
      this.tab = 'lib';
      el.querySelector('#kStatus').value = this.status;
      el.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x.dataset.tab === 'lib'));
      ['lib', 'queue', 'graph', 'ask'].forEach((t) => {
        el.querySelector('#pane' + t[0].toUpperCase() + t.slice(1)).style.display =
          this.tab === t ? '' : 'none';
      });
      this.load();
    });

    el.querySelector('#kGraph').addEventListener('click', (e) => {
      const a = e.target.closest('[data-open]');
      if (!a) return;
      this.openDetail(+a.dataset.open);
    });

    el.querySelector('#btnKbAsk').onclick = () => this.ask();
    el.querySelector('#btnKbSelAsk').onclick = () => {
      if (!this.sel.size) return toast('先在上面勾几条资料');
      this.ask([...this.sel]);
    };
    el.querySelector('#btnKbClaw').onclick = () => {
      const q2 = el.querySelector('#kQ').value.trim();
      if (!q2) return toast('先写点问题或需求');
      go('claw', { task: '结合我本地资料库的内容，帮我处理这件事：' + q2, autorun: false });
    };

    this.load();
  },

  // ---------- 列表 ----------

  onListClick(e) {
    const row = e.target.closest('.kbrow');
    if (!row) return;
    const id = +row.dataset.id;

    if (e.target.closest('.kbfav')) {
      const on = row.dataset.fav === '1' ? 0 : 1;
      post('/api/kb/fav', { id, on }).then(() => this.load());
      return;
    }
    if (e.target.closest('.del')) {
      if (!confirm('删掉这条资料？')) return;
      post('/api/kb/del', { id }).then(() => this.load());
      return;
    }
    const st = e.target.closest('.kbst');
    if (st) {
      const next = ST[(ST.indexOf(row.dataset.status) + 1) % ST.length] || '待读';
      post('/api/kb/status', { id, status: next }).then(() => this.load());
      return;
    }
    if (e.target.closest('.kbopen')) {
      this.openDetail(id);
      return;
    }
    const cb = e.target.closest('.kbselect');
    if (cb) {
      if (cb.checked) this.sel.add(id); else this.sel.delete(id);
      this.renderBulk();
      return;
    }
    // 点空白处：展开/收起详情
    this.openDetail(this.cur === id ? 0 : id);
  },

  async openDetail(id) {
    const box = this.el.querySelector('#kDetail');
    if (!id) {
      this.cur = 0;
      box.style.display = 'none';
      return;
    }
    this.cur = id;
    box.style.display = '';
    box.innerHTML = '<div class="note">加载中…</div>';
    const d = await api('/api/kb/get?id=' + id);
    if (!d.ok) { box.innerHTML = `<div class="note">${esc(d.error || '读不到')}</div>`; return; }
    const r = d.row || {};
    const st = r.status || '待读';
    box.innerHTML = `
      <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
        <h3 style="margin:0">${esc(r.title || '(无标题)')}</h3>
        <span class="kb-st ${stClass(st)}" style="font-size:11px;padding:1px 6px;border-radius:6px">${esc(st)}</span>
        ${r.fav ? '<span class="tag">★ 收藏</span>' : ''}
        ${r.tags ? `<span class="tag">${esc(r.tags)}</span>` : ''}
        ${r.source === 'file' ? `<span class="tag" title="${esc(r.source_path || '')}">文件</span>` : ''}
        <span class="g" style="margin-left:auto;font-size:11px">${fmtTime(r.updated)}</span>
        <button class="btn" id="kDetClose">收起</button>
      </div>
      <div style="display:flex;gap:6px;margin:10px 0 6px;flex-wrap:wrap">
        ${ST.map((s) => `<button class="chip ${s === st ? 'on' : ''}" data-set="${s}">${s}</button>`).join('')}
        <button class="btn" data-fav="${r.fav ? 0 : 1}">${r.fav ? '取消收藏' : '收藏'}</button>
        <button class="btn" id="kDetEdit">编辑</button>
        <button class="btn" id="kDetAsk">问 AI</button>
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
        <button class="btn" id="kSumAI">让 AI 写摘要</button>
        <span class="g" style="font-size:11px">摘要存在这一条里，下次直接看</span>
      </div>
      <div id="kSumBox" style="display:${r.summary ? '' : 'none'};background:var(--accent-2soft);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;white-space:pre-wrap;font-size:12.5px">${esc(r.summary || '')}</div>
      <div style="font-size:12.5px;color:var(--ink-2);white-space:pre-wrap;max-height:340px;overflow:auto" id="kBodyView">${esc(r.body || '')}</div>
      <div style="margin-top:12px" class="kb-links">
        <div><b style="font-weight:500">↗ 正向链接</b> ${this.linksHtml(d.outlinks, 'open')}</div>
        <div style="margin-top:6px"><b style="font-weight:500">↘ 反向链接</b> ${this.linksHtml(d.backlinks, 'open')}</div>
        <div style="margin-top:6px"><b style="font-weight:500">≈ 相关推荐</b> ${this.linksHtml(d.related, 'open')}</div>
      </div>`;

    const b = (sel) => box.querySelector(sel);
    b('#kDetClose').onclick = () => this.openDetail(0);
    box.querySelectorAll('[data-set]').forEach((x) => {
      x.onclick = async () => { await post('/api/kb/status', { id, status: x.dataset.set }); this.load(); this.openDetail(id); };
    });
    box.querySelectorAll('[data-fav]').forEach((x) => {
      x.onclick = async () => { await post('/api/kb/fav', { id, on: +x.dataset.fav }); this.load(); this.openDetail(id); };
    });
    b('#kDetEdit').onclick = () => this.editInline(box, r);
    b('#kDetAsk').onclick = () => {
      this.tab = 'ask'; this.el.querySelector('#kQ').value = '关于《' + (r.title || '') + '》：';
      this.el.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x.dataset.tab === 'ask'));
      ['lib', 'queue', 'graph', 'ask'].forEach((t) => {
        this.el.querySelector('#pane' + t[0].toUpperCase() + t.slice(1)).style.display = this.tab === t ? '' : 'none';
      });
      this.el.querySelector('#kQ').focus();
    };
    b('#kSumAI').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true; btn.textContent = '生成中…';
      const res = await post('/api/kb/ask', {
        id,
        q: '请为这条资料写一份摘要卡：3-5 条要点 + 一句话结论，直接输出正文，不要客套。',
      });
      btn.disabled = false; btn.textContent = '让 AI 写摘要';
      if (!res.ok) return toast(res.error || '失败');
      await post('/api/kb/summary', { id, summary: res.text });
      const sb = box.querySelector('#kSumBox');
      sb.style.display = ''; sb.textContent = res.text;
      toast('摘要已保存');
      this.load();
    };
  },

  linksHtml(rows, mode) {
    rows = rows || [];
    if (!rows.length) return '<span class="g" style="font-size:12px">（无）</span>';
    return '<span style="display:inline-flex;gap:6px;flex-wrap:wrap">' + rows.map((l) => {
      const t = esc(l.title || '(无标题)');
      if (mode === 'open' && l.id) {
        return `<a href="#" data-open="${l.id}" class="kb-link">${t}</a>`;
      }
      return `<span class="kb-link dim" title="还没这条资料">${t}</span>`;
    }).join('') + '</span>';
  },

  // 详情内联编辑
  editInline(box, r) {
    const view = box.querySelector('#kBodyView');
    view.innerHTML = `
      <div class="field"><label>标题</label><input id="eTitle" value="${esc(r.title || '')}"></div>
      <div class="field"><label>标签</label><input id="eTags" value="${esc(r.tags || '')}"></div>
      <div class="field"><label>正文</label><textarea id="eBody" rows="8">${esc(r.body || '')}</textarea></div>
      <div style="display:flex;gap:8px"><button class="btn primary" id="eSave">保存</button>
      <button class="btn" id="eCancel">取消</button></div>`;
    box.querySelector('#eCancel').onclick = () => this.openDetail(r.id);
    box.querySelector('#eSave').onclick = async () => {
      const res = await post('/api/kb/save', {
        id: r.id,
        title: box.querySelector('#eTitle').value.trim(),
        tags: box.querySelector('#eTags').value.trim(),
        body: box.querySelector('#eBody').value,
        source: r.source || 'manual',
        source_path: r.source_path || '',
      });
      if (!res.ok) return toast(res.error || '保存失败');
      toast('已保存');
      this.load();
      this.openDetail(r.id);
    };
  },

  renderBulk() {
    const bar = this.el.querySelector('#kBulk');
    bar.style.display = this.sel.size ? '' : 'none';
    this.el.querySelector('#kSelN').textContent = `已选 ${this.sel.size} 条`;
  },

  renderList(rows) {
    this._last = rows;
    const box = this.el.querySelector('#kList');
    if (!rows.length) {
      box.innerHTML = '<div class="note">没有资料条目</div>';
      return;
    }
    box.innerHTML = rows.map((r) => {
      const st = r.status || '待读';
      const snip = r.snippet || '';
      const body = (r.body || '');
      const preview = snip ? esc(snip) : (esc(body.slice(0, 300)) + (body.length > 300 ? '…' : ''));
      return `
      <div class="kbrow${this.cur === r.id ? ' on' : ''}" data-id="${r.id}" data-status="${esc(st)}" data-fav="${r.fav ? 1 : 0}">
        <input type="checkbox" class="kbselect" ${this.sel.has(r.id) ? 'checked' : ''}>
        <div style="flex:1;min-width:0">
          <div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap">
            <b class="kb-title kbopen" style="font-weight:500;cursor:pointer">${esc(r.title || '(无标题)')}</b>
            <span class="kb-st kbst ${stClass(st)}" title="点一下换状态" style="cursor:pointer;font-size:11px;padding:1px 6px;border-radius:6px">${esc(st)}</span>
            ${r.tags ? `<span class="tag">${esc(r.tags)}</span>` : ''}
            ${r.source === 'file' ? `<span class="tag" title="${esc(r.source_path || '')}">文件</span>` : ''}
            ${r.summary ? '<span class="tag" title="有摘要">摘要</span>' : ''}
            <span class="g" style="font-size:11px">${r.score ? `命中 ${r.score}` : ''} ${fmtTime(r.updated)}</span>
            <button class="kbfav" title="收藏" style="margin-left:auto;border:0;background:transparent;cursor:pointer;color:${r.fav ? 'var(--warn)' : 'var(--ink-3)'};font-size:13px">${r.fav ? '★' : '☆'}</button>
            <button class="del" style="border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
          </div>
          <div class="kb-body" style="font-size:12.5px;color:var(--ink-2);margin-top:4px;white-space:pre-wrap">${preview}</div>
        </div>
      </div>`;
    }).join('');
  },

  async ask(ids) {
    const q = this.el.querySelector('#kQ').value.trim();
    if (!q) return toast('先写点问题');
    const btn = this.el.querySelector('#btnKbAsk');
    const ans = this.el.querySelector('#kAnswer');
    btn.disabled = true; ans.textContent = '思考中…'; this.el.querySelector('#kUsed').textContent = '';
    const r = await post('/api/kb/ask', ids && ids.length ? { q, ids } : { q });
    btn.disabled = false;
    if (!r.ok) { ans.textContent = '⚠ ' + (r.error || '出问题了'); return; }
    ans.textContent = r.text;
    const used = r.used_titles || [];
    this.el.querySelector('#kUsed').textContent = used.length ? '参考了：' + used.join('、') : '';
  },

  // ---------- 载入 ----------

  async load() {
    if (!this.el) return;

    if (this.tab === 'queue') {
      const q = await api('/api/kb/queue');
      this.el.querySelector('#kQueue').innerHTML = `
        <div class="kb-qc" data-go="待读"><b>${q['待读'] || 0}</b><span>待读</span></div>
        <div class="kb-qc" data-go="在读"><b>${q['在读'] || 0}</b><span>在读</span></div>
        <div class="kb-qc" data-go="已读"><b>${q['已读'] || 0}</b><span>已读</span></div>
        <div class="kb-qc"><b>${q.total || 0}</b><span>总计</span></div>`;
      this.el.querySelector('#kbStat').textContent = q.total ? `${q.total} 条` : '';
      return;
    }

    if (this.tab === 'graph') {
      const g = await api('/api/kb/graph');
      this.graph = g;
      const nodes = g.nodes || [];
      const edges = g.edges || [];
      const deg = {};
      edges.forEach((e) => {
        if (e.src_id) deg[e.src_id] = (deg[e.src_id] || 0) + 1;
        if (e.dst_id) deg[e.dst_id] = (deg[e.dst_id] || 0) + 1;
      });
      const byId = {};
      nodes.forEach((n) => { byId[n.id] = n; });
      const top = nodes.slice().sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0));
      const dang = g.dangling || [];
      this.el.querySelector('#kGraph').innerHTML = `
        <div class="g" style="font-size:12px;margin-bottom:8px">${nodes.length} 个节点 · ${edges.length} 条链接${dang.length ? ` · ${dang.length} 个悬空链接` : ''}</div>
        ${top.map((n) => {
          const outs = edges.filter((e) => e.src_id === n.id);
          const ins = edges.filter((e) => e.dst_id === n.id);
          return `<div class="kb-node">
            <a href="#" data-open="${n.id}" class="kb-link"><b>${esc(n.title || '(无标题)')}</b></a>
            <span class="g" style="font-size:11px">出 ${outs.length} / 入 ${ins.length}</span>
            <div class="g" style="font-size:11.5px;margin-top:3px">${outs.length ? '↗ ' + outs.map((o) => esc(o.dst_title)).join('、') : ''}
            ${ins.length ? (outs.length ? '　' : '') + '↘ ' + ins.map((i2) => esc((byId[i2.src_id] || {}).title || '')).join('、') : ''}</div>
          </div>`;
        }).join('') || '<div class="note">还没有资料</div>'}
        ${dang.length ? `<div class="note" style="margin-top:10px">这些链接指向的标题还不存在：${dang.map(esc).join('、')}</div>` : ''}`;
      this.el.querySelector('#kbStat').textContent = nodes.length ? `${nodes.length} 条` : '';
      return;
    }

    if (this.tab === 'ask') {
      const d = await api('/api/kb');
      this.el.querySelector('#kbStat').textContent = (d.rows || []).length ? `${(d.rows || []).length} 条` : '';
      if (this.sel.size) this.el.querySelector('#btnKbSelAsk').textContent = `拿选中的 ${this.sel.size} 条问`;
      return;
    }

    // 87 资料库
    let rows;
    if (this.q) {
      const d = await api('/api/kb/search?q=' + encodeURIComponent(this.q) + '&limit=60');
      rows = d.rows || [];
      this.el.querySelector('#kMeta').textContent =
        `「${this.q}」命中 ${d.total || 0} 条（用词 ${d.n_terms || 0} 个${d.index_size ? ' / 索引 ' + d.index_size + ' 词条' : ''}）`;
    } else {
      const qs = [];
      if (this.status) qs.push('status=' + encodeURIComponent(this.status));
      if (this.favOnly) qs.push('fav=1');
      const d = await api('/api/kb' + (qs.length ? '?' + qs.join('&') : ''));
      rows = d.rows || [];
      this.el.querySelector('#kMeta').textContent = '';
    }
    this.renderList(rows);
    this.renderBulk();
    const total = rows.length;
    this.el.querySelector('#kbStat').textContent = total ? `${total} 条` : '';
    if (this.cur) this.openDetail(this.cur);
  },

  onShow() {
    this.load();
  },

  badge(s) {
    const n = (s.counts && s.counts.kb) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      { title: '打开资料库', hint: '资料库', run: () => window.WB.go('kb') },
      {
        title: '搜资料库…',
        hint: '资料库',
        run: () => { window.WB.go('kb'); setTimeout(() => { const i = document.querySelector('#kSearch'); if (i) i.focus(); }, 120); },
      },
    ];
  },
};
