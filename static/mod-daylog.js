/* 每日日志：随手记当天，自动保存。后端 daylog 表已就绪。 */

const { api, post, toast } = window.WB;

function todayISO() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

export default {
  id: 'daylog',
  name: '日志',
  el: null,
  _t: null,

  mount(el) {
    this.el = el;
    const day = todayISO();
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>每日日志 · ${day}</h3>
        <div class="note" style="margin-bottom:8px">随手记今天发生的事、想法、决定。停手 1.2 秒自动保存。</div>
        <textarea id="dayBody" style="width:100%;min-height:260px;resize:vertical;border:1px solid var(--line-strong);border-radius:8px;padding:10px;background:var(--surface);color:var(--ink);font-size:13px;line-height:1.7"></textarea>
        <div class="field" style="margin-top:8px;justify-content:space-between">
          <span id="dayStat" class="note"></span>
          <button class="btn primary" id="daySave">保存</button>
        </div>
      </div>
    </div>`;
    el.querySelector('#daySave').onclick = () => this.save();
    const ta = el.querySelector('#dayBody');
    ta.addEventListener('input', () => {
      this._stat();
      clearTimeout(this._t);
      this._t = setTimeout(() => this.save(), 1200);
    });
    this.refresh();
  },

  _stat() {
    const ta = this.el.querySelector('#dayBody');
    const t = ta.value;
    this.el.querySelector('#dayStat').textContent = t ? (t.length + ' 字 · 自动保存中') : '';
  },

  async refresh() {
    const d = await api('/api/daylog?day=' + todayISO());
    this.el.querySelector('#dayBody').value = d.text || '';
    this._stat();
  },

  async save() {
    try {
      const r = await post('/api/daylog/save', { day: todayISO(), text: this.el.querySelector('#dayBody').value });
      if (r && r.ok) toast('已保存');
    } catch (_) { toast('保存失败'); }
  },

  onShow() { this.refresh(); },
};
