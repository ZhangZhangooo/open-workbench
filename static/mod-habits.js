/* 习惯打卡：连续天数 + 今日勾选。后端 habits / checkins 表已就绪。 */

const { api, post, esc, toast } = window.WB;

function todayISO() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

export default {
  id: 'habits',
  name: '习惯打卡',
  el: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>习惯打卡</h3>
        <div class="note" style="margin-bottom:8px">每天点一下，自动记连续天数 🔥</div>
        <div id="habList" class="note">加载中…</div>
        <div class="field" style="margin-top:10px;gap:8px">
          <input id="habName" placeholder="新习惯，如 背单词/喝水/运动" style="flex:1;min-width:150px">
          <input id="habNote" placeholder="备注（可选）" style="flex:1;min-width:110px">
          <button class="btn primary" id="habAdd">添加</button>
        </div>
      </div>
    </div>`;
    el.querySelector('#habAdd').onclick = () => this.add();
    el.querySelector('#habName').addEventListener('keydown', (e) => { if (e.key === 'Enter') this.add(); });
    el.querySelector('#habNote').addEventListener('keydown', (e) => { if (e.key === 'Enter') this.add(); });
    el.querySelector('#habList').addEventListener('click', (e) => this.onListClick(e));
    this.refresh();
  },

  async add() {
    const name = this.el.querySelector('#habName').value.trim();
    if (!name) return;
    const note = this.el.querySelector('#habNote').value.trim();
    await post('/api/habits/save', { name, note });
    this.el.querySelector('#habName').value = '';
    this.el.querySelector('#habNote').value = '';
    this.refresh();
  },

  async onListClick(e) {
    const chk = e.target.closest('.hab-chk');
    if (chk) {
      try { await post('/api/habits/toggle', { id: +chk.dataset.id, day: todayISO() }); } catch (_) {}
      this.refresh();
      return;
    }
    const del = e.target.closest('.x');
    if (del) {
      if (!confirm('删除这个习惯？打卡记录也会没')) return;
      try { await post('/api/habits/del', { id: +del.dataset.id }); } catch (_) {}
      this.refresh();
    }
  },

  async refresh() {
    const d = await api('/api/habits');
    const rows = d.rows || [];
    const box = this.el.querySelector('#habList');
    if (!rows.length) { box.innerHTML = '<div class="note">还没有习惯，加一个开始打卡</div>'; return; }
    box.innerHTML = rows.map((h) => {
      const on = (h.done_today || 0) > 0;
      const fire = h.streak > 0 ? ('🔥' + h.streak) : '未打卡';
      return `<div class="lrow" style="align-items:center">
        <button class="hab-chk" data-id="${h.id}" title="今日打卡"
          style="${on ? 'background:var(--accent);color:#fff;border-color:var(--accent)' : 'background:var(--surface);color:var(--ink-3);border:1px solid var(--line-strong)'}">${on ? '✓' : '○'}</button>
        <div style="flex:1;min-width:0">
          <div style="font-weight:500">${esc(h.name)}</div>
          ${h.note ? `<div class="note">${esc(h.note)}</div>` : ''}
        </div>
        <span class="tag">${fire}</span>
        <button class="x" data-id="${h.id}">×</button>
      </div>`;
    }).join('');
  },

  onShow() { this.refresh(); },
};
