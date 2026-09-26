/* 番茄钟：专注计时 + 今日统计 + 历史。后端 pomodoro 表已就绪。 */

const { api, post, toast } = window.WB;

export default {
  id: 'pomo',
  name: '番茄钟',
  el: null,
  timer: null,
  running: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>专注计时</h3>
        <div id="pomoState" class="note">加载中…</div>
        <div id="pomoTimer" style="font-size:42px;font-weight:600;letter-spacing:1px;margin:6px 0;font-variant-numeric:tabular-nums">00:00</div>
        <div class="field" style="gap:8px">
          <input id="pomoTitle" placeholder="在做什么？（可选）" style="flex:1;min-width:160px">
          <button class="btn primary" id="pomoToggle">开始</button>
        </div>
      </div>
      <div class="panel">
        <h3>今日</h3>
        <div id="pomoToday" class="note">—</div>
      </div>
      <div class="panel">
        <h3>历史</h3>
        <div id="pomoHist" class="note">—</div>
      </div>
    </div>`;
    el.querySelector('#pomoToggle').onclick = () => this.toggle();
    el.querySelector('#pomoTitle').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.toggle();
    });
    this.refresh();
  },

  async toggle() {
    const btn = this.el.querySelector('#pomoToggle');
    btn.disabled = true;
    try {
      if (this.running) {
        const r = await post('/api/pomodoro/stop', { id: this.running.id });
        toast(r && r.ok ? ('已记录 ' + (r.minutes || 0) + ' 分钟') : '结束失败');
      } else {
        const title = this.el.querySelector('#pomoTitle').value.trim();
        const r = await post('/api/pomodoro/start', { title, project_id: 0, task_id: 0 });
        toast(r && r.ok ? '开始专注' : '开始失败');
      }
    } catch (e) { toast('出错了'); }
    btn.disabled = false;
    this.refresh();
  },

  async refresh() {
    const d = await api('/api/pomodoro');
    this.running = d.running || null;
    const st = this.el.querySelector('#pomoState');
    const btn = this.el.querySelector('#pomoToggle');
    const title = this.el.querySelector('#pomoTitle');
    if (this.running) {
      st.textContent = '进行中：' + (this.running.title || '（未命名）');
      btn.textContent = '结束';
      title.disabled = true;
    } else {
      st.textContent = '空闲，开始一段专注吧';
      btn.textContent = '开始';
      title.disabled = false;
    }
    const t = d.today || { minutes: 0, count: 0 };
    this.el.querySelector('#pomoToday').textContent =
      `今天已专注 ${t.minutes} 分钟，共 ${t.count} 段`;
    const hist = this.el.querySelector('#pomoHist');
    const rows = d.rows || [];
    if (!rows.length) hist.innerHTML = '<div class="note">还没有记录</div>';
    else hist.innerHTML = rows.slice(0, 30).map((r) => `
      <div class="lrow">
        <div style="flex:1;min-width:0">${esc(r.title || '专注')}</div>
        <div class="note">${(r.project ? '· ' + esc(r.project) : '')}</div>
        <div style="width:58px;text-align:right">${r.minutes || 0}′</div>
        <div class="note" style="width:74px;text-align:right">${this._fmt(r.started)}</div>
      </div>`).join('');
    this._tick();
  },

  _fmt(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, '0');
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  },

  _tick() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    const run = this.running;
    const disp = this.el.querySelector('#pomoTimer');
    if (!run || !run.started) { disp.textContent = '00:00'; return; }
    const upd = () => {
      const s = Math.max(0, Math.floor(Date.now() / 1000 - run.started));
      disp.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    };
    upd();
    this.timer = setInterval(upd, 1000);
  },

  onShow() { this.refresh(); },

  commands() {
    return [{
      title: '开始番茄钟', hint: '专注', run: () => {
        window.WB.go('pomo');
        if (!this.running) this.toggle();
      },
    }];
  },
};

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
