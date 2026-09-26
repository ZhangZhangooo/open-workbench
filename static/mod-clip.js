/* 剪贴板历史：抓取当前剪贴板 + 回贴 + 本地留存。后端 clip 表已就绪。 */

const { api, post, esc, toast } = window.WB;

export default {
  id: 'clip',
  name: '剪贴板',
  el: null,
  rows: [],

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>剪贴板历史</h3>
        <div class="note" style="margin-bottom:8px">点「抓取」把当前剪贴板存进来；点任意一条把它复制回去。本地留存，不上云。</div>
        <div class="field" style="gap:8px">
          <button class="btn primary" id="clipGrab">抓取当前剪贴板</button>
          <button class="btn" id="clipClear">清空</button>
        </div>
        <div id="clipList" class="note" style="margin-top:10px">加载中…</div>
      </div>
    </div>`;
    el.querySelector('#clipGrab').onclick = () => this.grab();
    el.querySelector('#clipClear').onclick = async () => {
      if (!confirm('清空全部剪贴板历史？')) return;
      try { await post('/api/clip/clear'); } catch (_) {}
      this.refresh();
    };
    el.querySelector('#clipList').addEventListener('click', (e) => this.onClick(e));
    this.refresh();
  },

  async grab() {
    let text = '';
    try { text = await navigator.clipboard.readText(); } catch (_) { text = ''; }
    if (!text) {
      const t = prompt('读不到剪贴板（浏览器可能拦了），手动粘贴也行：');
      if (t) text = t;
    }
    if (!text) return;
    try {
      const r = await post('/api/clip/add', { text });
      if (r && r.ok) toast('已存'); else toast('保存失败');
    } catch (_) { toast('保存失败'); }
    this.refresh();
  },

  async onClick(e) {
    const cp = e.target.closest('.clip-copy');
    if (cp) {
      const id = +cp.dataset.id;
      const row = this.rows.find((x) => x.id === id);
      const t = row ? (row.text || '') : '';
      try { await navigator.clipboard.writeText(t); toast('已复制'); } catch (_) { toast('复制失败'); }
      return;
    }
    const del = e.target.closest('.x');
    if (del) {
      try { await post('/api/clip/del', { id: +del.dataset.id }); } catch (_) {}
      this.refresh();
    }
  },

  async refresh() {
    const d = await api('/api/clip');
    const rows = d.rows || [];
    this.rows = rows;
    const box = this.el.querySelector('#clipList');
    if (!rows.length) { box.innerHTML = '<div class="note">还没有记录</div>'; return; }
    box.innerHTML = rows.slice(0, 200).map((r) => {
      const raw = (r.text || '').replace(/\s+/g, ' ');
      const prev = raw.length > 120 ? raw.slice(0, 120) + '…' : raw;
      return `<div class="lrow">
        <button class="clip-copy" data-id="${r.id}" title="点击复制回去"
          style="flex:1;text-align:left;background:none;border:none;color:inherit;cursor:pointer;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0">${esc(prev) || '（空）'}</button>
        <span class="note">${this._ago(r.created)}</span>
        <button class="x" data-id="${r.id}">×</button>
      </div>`;
    }).join('');
  },

  _ago(ts) {
    if (!ts) return '';
    const s = Math.floor(Date.now() / 1000 - ts);
    if (s < 60) return s + '秒前';
    if (s < 3600) return Math.floor(s / 60) + '分前';
    if (s < 86400) return Math.floor(s / 3600) + '时前';
    return Math.floor(s / 86400) + '天前';
  },

  onShow() { this.refresh(); },
};
