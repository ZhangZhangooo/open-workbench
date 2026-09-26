/* 本地知识库：存笔记/导入文件当知识，问 AI 时自动带上下文 */

const { api, post, toast, esc } = window.WB;

export default {
  id: 'kb',
  name: '知识库',
  el: null,
  tab: 'entries',

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <button class="chip on" data-tab="entries">知识</button>
        <button class="chip" data-tab="ask">提问</button>
        <span class="g" id="kbStat" style="margin-left:auto;font-size:12px"></span>
      </div>

      <!-- 知识：增 / 导入 / 列表 -->
      <div class="stack" id="paneEntries">
        <div class="panel">
          <h3>加一条知识</h3>
          <div class="field"><label>标题</label><input id="kTitle" placeholder="例如：备份怎么导出"></div>
          <div class="field"><label>标签</label><input id="kTags" placeholder="逗号分隔，可选"></div>
          <div class="field"><label>正文</label><textarea id="kBody" rows="4" placeholder="知识内容，越具体越好；支持长文本"></textarea></div>
          <button class="btn primary" id="btnKbSave">保存</button>
        </div>

        <div class="panel">
          <h3>从文件导入</h3>
          <div class="field"><label>文件路径</label><input id="kPath" placeholder="C:\\\\Users\\\\...\\\\笔记.docx 或 .txt/.md/.pdf"></div>
          <div class="field"><label>标题(可空)</label><input id="kImpTitle" placeholder="不填就用文件名"></div>
          <div class="field"><label>标签(可空)</label><input id="kImpTags" placeholder="可选"></div>
          <button class="btn" id="btnKbImport">抽取文字并入库</button>
          <div class="note" style="margin-top:6px">支持 .txt/.md/.docx/.pdf/.xlsx/.csv 等，抽出的文字会原样存进知识库。</div>
        </div>

        <div class="panel">
          <h3>已有知识</h3>
          <div class="field"><input id="kSearch" placeholder="搜标题、标签、正文" style="width:100%;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px"></div>
          <div id="kList" class="note">空</div>
        </div>
      </div>

      <!-- 提问 -->
      <div class="stack" id="paneAsk" style="display:none">
        <div class="panel">
          <h3>问本地知识库</h3>
          <textarea id="kQ" rows="3" placeholder="基于你存进来的知识问我，例如：备份文件在哪里、怎么恢复？"></textarea>
          <button class="btn primary" id="btnKbAsk">问 AI</button>
          <button class="btn" id="btnKbClaw">交给 OpenClaw 干</button>
          <div id="kAnswer" class="note" style="margin-top:10px;white-space:pre-wrap"></div>
          <div id="kUsed" class="g" style="margin-top:6px;font-size:12px"></div>
        </div>
      </div>`;

    el.querySelectorAll('[data-tab]').forEach((b) => {
      b.onclick = () => {
        this.tab = b.dataset.tab;
        el.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x === b));
        el.querySelector('#paneEntries').style.display = this.tab === 'entries' ? '' : 'none';
        el.querySelector('#paneAsk').style.display = this.tab === 'ask' ? '' : 'none';
        this.load();
      };
    });

    el.querySelector('#btnKbSave').onclick = async () => {
      const title = el.querySelector('#kTitle').value.trim();
      const body = el.querySelector('#kBody').value;
      if (!title && !body.trim()) return;
      const r = await post('/api/kb/save', {
        title, body, tags: el.querySelector('#kTags').value.trim(),
      });
      if (!r.ok) return toast(r.error || '保存失败');
      el.querySelector('#kTitle').value = '';
      el.querySelector('#kTags').value = '';
      el.querySelector('#kBody').value = '';
      toast('已存入知识库');
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

    el.querySelector('#kSearch').addEventListener('input', () => this.load());

    el.querySelector('#kList').addEventListener('click', async (e) => {
      const del = e.target.closest('.del');
      if (!del) return;
      const id = +e.target.closest('.krow').dataset.id;
      await post('/api/kb/del', { id });
      this.load();
    });

    el.querySelector('#btnKbAsk').onclick = async () => {
      const q = el.querySelector('#kQ').value.trim();
      if (!q) return;
      const btn = el.querySelector('#btnKbAsk');
      const ans = el.querySelector('#kAnswer');
      btn.disabled = true; ans.textContent = '思考中…'; el.querySelector('#kUsed').textContent = '';
      const r = await post('/api/kb/ask', { q });
      btn.disabled = false;
      if (!r.ok) { ans.textContent = '⚠ ' + (r.error || '出问题了'); return; }
      ans.textContent = r.text;
      const used = (r.used_titles || []);
      el.querySelector('#kUsed').textContent = used.length
        ? '参考了：' + used.join('、') : '';
    };

    el.querySelector('#btnKbClaw').onclick = () => {
      const q = el.querySelector('#kQ').value.trim();
      if (!q) return toast('先写点问题或需求');
      // 交给 OpenClaw 干活标签：上下文注入会带上资料库近期内容，结果可写回工作台
      window.WB.go('claw', { task: '结合我本地知识库的内容，帮我处理这件事：' + q, autorun: false });
    };

    this.load();
  },

  async load() {
    const d = await api('/api/kb');
    const rows = d.rows || [];
    const stat = this.el.querySelector('#kbStat');
    if (stat) stat.textContent = rows.length ? `${rows.length} 条` : '';

    if (this.tab === 'ask') return;

    const q = this.el.querySelector('#kSearch').value.trim().toLowerCase();
    let show = rows;
    if (q) {
      show = rows.filter((r) =>
        ((r.title || '') + (r.tags || '') + (r.body || '')).toLowerCase().includes(q));
    }
    const box = this.el.querySelector('#kList');
    if (!show.length) {
      box.innerHTML = '<div class="note">没有知识条目</div>';
      return;
    }
    box.innerHTML = show.map((r) => `
      <div class="krow" data-id="${r.id}" style="padding:10px 0;border-bottom:1px solid var(--line-soft)">
        <div style="display:flex;gap:10px;align-items:baseline">
          <b style="font-weight:500">${esc(r.title || '(无标题)')}</b>
          ${r.tags ? `<span class="tag">${esc(r.tags)}</span>` : ''}
          ${r.source === 'file' ? `<span class="tag" title="${esc(r.source_path || '')}">文件</span>` : ''}
          <button class="del" style="margin-left:auto;border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
        </div>
        <div style="font-size:12.5px;color:var(--ink-2);margin-top:4px;white-space:pre-wrap">${esc((r.body || '').slice(0, 400))}${(r.body || '').length > 400 ? '…' : ''}</div>
      </div>`).join('');
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
      { title: '打开本地知识库', hint: '知识库', run: () => window.WB.go('kb') },
    ];
  },
};
