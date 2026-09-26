/* 定时提醒：到点记一笔，列表管理。后端 reminders 表已就绪。 */

const { api, post, esc, toast } = window.WB;

function fmtAt(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}
function toLocalInput(ts) {
  const d = new Date(ts || Date.now() + 3600 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes());
}

export default {
  id: 'reminders',
  name: '提醒',
  el: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>定时提醒</h3>
        <div class="note" style="margin-bottom:8px">到点记一笔，列表管理。配合连接器还能推到微信。</div>
        <div class="bar" style="margin-bottom:8px">
          <button class="btn" id="remNotify">开启桌面通知</button>
          <span class="note" style="margin-left:4px">到点弹窗；不开也用站内提示兜底</span>
        </div>
        <div class="field" style="gap:8px;flex-wrap:wrap">
          <input id="remText" placeholder="提醒内容" style="flex:1;min-width:150px">
          <input id="remAt" type="datetime-local" style="flex:0 0 auto">
          <button class="btn primary" id="remAdd">添加</button>
        </div>
        <div id="remList" class="note" style="margin-top:10px">加载中…</div>
      </div>
    </div>`;
    this.el.querySelector('#remAt').value = toLocalInput(Date.now() + 3600 * 1000);
    this.el.querySelector('#remAdd').onclick = () => this.add();
    this.el.querySelector('#remNotify').onclick = () => window.WB.requestNotify();
    this.el.querySelector('#remText').addEventListener('keydown', (e) => { if (e.key === 'Enter') this.add(); });
    this.el.querySelector('#remList').addEventListener('click', (e) => this.onClick(e));
    this.refresh();
  },

  async add() {
    const text = this.el.querySelector('#remText').value.trim();
    if (!text) { toast('先写提醒内容'); return; }
    const atv = this.el.querySelector('#remAt').value;
    let at = atv ? new Date(atv).getTime() / 1000 : Math.floor(Date.now() / 1000) + 60;
    if (isNaN(at)) at = Math.floor(Date.now() / 1000) + 60;
    try {
      const r = await post('/api/reminders/add', { at, text });
      if (r && r.ok) {
        this.el.querySelector('#remText').value = '';
        this.el.querySelector('#remAt').value = toLocalInput(Date.now() + 3600 * 1000);
        this.refresh();
        window.WB.requestNotify();
      } else toast('添加失败');
    } catch (_) { toast('添加失败'); }
  },

  async onClick(e) {
    const chk = e.target.closest('.rem-chk');
    if (chk) {
      try { await post('/api/reminders/done', { id: +chk.dataset.id, done: chk.dataset.on === '1' ? 0 : 1 }); } catch (_) {}
      this.refresh();
      return;
    }
    const del = e.target.closest('.x');
    if (del) {
      try { await post('/api/reminders/del', { id: +del.dataset.id }); } catch (_) {}
      this.refresh();
    }
  },

  async refresh() {
    const d = await api('/api/reminders');
    const rows = (d.rows || []).slice().sort((a, b) => (a.at || 0) - (b.at || 0));
    const box = this.el.querySelector('#remList');
    if (!rows.length) { box.innerHTML = '<div class="note">还没有提醒</div>'; return; }
    const now = Date.now() / 1000;
    box.innerHTML = rows.map((r) => {
      const done = (r.done || 0) > 0;
      const due = (r.at || 0) < now;
      return `<div class="lrow" style="${done ? 'opacity:.5' : ''}">
        <button class="rem-chk" data-id="${r.id}" data-on="${done ? 1 : 0}" title="标记完成"
          style="${done ? 'background:var(--accent);color:#fff;border-color:var(--accent)' : 'background:var(--surface);color:var(--ink-3);border:1px solid var(--line-strong)'}">${done ? '✓' : '○'}</button>
        <div style="flex:1;min-width:0">${esc(r.text || '')}</div>
        <span class="note" style="width:84px;text-align:right;${due && !done ? 'color:var(--err,#c0392b)' : ''}">${fmtAt(r.at)}</span>
        <button class="x" data-id="${r.id}">×</button>
      </div>`;
    }).join('');
  },

  onShow() { this.refresh(); },

  commands() {
    return [{
      title: '加一个提醒', hint: '提醒', run: () => {
        window.WB.go('reminders');
        this.el.querySelector('#remText').focus();
      },
    }];
  },
};
