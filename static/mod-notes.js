/* 资料：Markdown 笔记 + 链接收藏 + 搜索 */

const { api, post, toast, esc } = window.WB;

export default {
  id: 'notes',
  name: '资料',
  el: null,
  tab: 'note',

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <button class="chip on" data-tab="note">笔记</button>
        <button class="chip" data-tab="link">链接</button>
        <input id="nSearch" placeholder="搜标题、正文、标签" style="flex:1;min-width:120px;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
      </div>
      <div class="stack">
        <div class="panel" id="paneNote">
          <h3>写笔记</h3>
          <div class="field"><label>标题</label><input id="nTitle" placeholder="随手一个标题"></div>
          <div class="field"><label>标签</label><input id="nTags" placeholder="逗号分隔，例如 voxelcraft,bug"></div>
          <div class="field"><label>正文</label><input id="nBody" placeholder="支持 Markdown，回车保存"></div>
          <button class="btn primary" id="btnSaveNote">保存</button>
        </div>

        <div class="panel" id="paneLink" style="display:none">
          <h3>收藏链接</h3>
          <div class="field"><label>标题</label><input id="lTitle" placeholder="起个名字"></div>
          <div class="field"><label>网址</label><input id="lUrl" placeholder="https://..."></div>
          <div class="field"><label>标签</label><input id="lTags" placeholder="可选"></div>
          <button class="btn primary" id="btnAddLink">收藏</button>
        </div>

        <div class="panel">
          <h3 id="listTitle">笔记</h3>
          <div id="nList" class="note">空</div>
        </div>
      </div>`;

    el.querySelectorAll('[data-tab]').forEach((b) => {
      b.onclick = () => {
        this.tab = b.dataset.tab;
        el.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x === b));
        el.querySelector('#paneNote').style.display = this.tab === 'note' ? '' : 'none';
        el.querySelector('#paneLink').style.display = this.tab === 'link' ? '' : 'none';
        el.querySelector('#listTitle').textContent = this.tab === 'note' ? '笔记' : '链接';
        this.load();
      };
    });

    el.querySelector('#btnSaveNote').onclick = async () => {
      const title = el.querySelector('#nTitle').value.trim();
      if (!title) return;
      await post('/api/notes/save', {
        title,
        body: el.querySelector('#nBody').value,
        tags: el.querySelector('#nTags').value.trim(),
      });
      el.querySelector('#nTitle').value = '';
      el.querySelector('#nBody').value = '';
      el.querySelector('#nTags').value = '';
      toast('已保存');
      this.load();
    };

    el.querySelector('#btnAddLink').onclick = async () => {
      const url = el.querySelector('#lUrl').value.trim();
      if (!url) return;
      await post('/api/links/add', {
        title: el.querySelector('#lTitle').value.trim() || url,
        url,
        tags: el.querySelector('#lTags').value.trim(),
      });
      el.querySelector('#lTitle').value = '';
      el.querySelector('#lUrl').value = '';
      el.querySelector('#lTags').value = '';
      toast('已收藏');
      this.load();
    };

    el.querySelector('#nSearch').addEventListener('input', () => this.load());

    el.querySelector('#nList').addEventListener('click', async (e) => {
      const del = e.target.closest('.del');
      if (!del) return;
      const row = e.target.closest('.nrow');
      const id = +row.dataset.id;
      await post(this.tab === 'note' ? '/api/notes/del' : '/api/links/del', { id });
      this.load();
    });

    this.load();
  },

  async load() {
    const q = this.el.querySelector('#nSearch').value.trim().toLowerCase();
    const d = this.tab === 'note' ? await api('/api/notes') : await api('/api/links');
    const box = this.el.querySelector('#nList');

    let rows = d.rows || [];
    if (q) {
      rows = rows.filter((r) =>
        ((r.title || '') + (r.body || '') + (r.url || '') + (r.tags || '')).toLowerCase().includes(q)
      );
    }

    if (!rows.length) {
      box.innerHTML = '<div class="note">没有内容</div>';
      return;
    }

    box.innerHTML = rows.map((r) => `
      <div class="nrow" data-id="${r.id}" style="padding:10px 0;border-bottom:1px solid var(--line-soft)">
        <div style="display:flex;gap:10px;align-items:baseline">
          <b style="font-weight:500">${esc(r.title || '(无标题)')}</b>
          ${r.tags ? `<span class="tag">${esc(r.tags)}</span>` : ''}
          <button class="del" style="margin-left:auto;border:0;background:transparent;color:var(--ink-3);cursor:pointer;font-size:12px">删除</button>
        </div>
        ${this.tab === 'note'
          ? `<div style="font-size:12.5px;color:var(--ink-2);margin-top:4px;white-space:pre-wrap">${esc(r.body || '')}</div>`
          : `<div style="font-size:12.5px;margin-top:4px"><a href="${esc(r.url)}" target="_blank" style="color:var(--accent)">${esc(r.url)}</a></div>`}
      </div>`).join('');
  },

  onShow() {
    this.load();
  },

  badge(s) {
    const n = ((s.counts && s.counts.notes) || 0) + ((s.counts && s.counts.links) || 0);
    return n ? String(n) : '';
  },

  commands() {
    return [
      { title: '快速收藏一个链接', hint: '资料', run: async () => {
        const url = prompt('网址');
        if (!url) return;
        await post('/api/links/add', { title: url, url, tags: '' });
        toast('已收藏');
        this.load();
      } },
    ];
  },
};
