/* 会议：本地会议预订 + 会前提醒。零依赖，提醒复用 reminders 机制。 */

const { api, post, toast, esc, day } = window.WB;

const REM_OPTS = [5, 10, 15, 30, 60];

export default {
  id: 'meet',
  name: '会议',
  el: null,
  rows: [],

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <h3>预订会议</h3>
          <div class="field"><label>标题</label><input id="mTitle" placeholder="如：周会 / 无人机训练复盘"></div>
          <div class="field" style="display:flex;gap:8px;flex-wrap:wrap">
            <div style="flex:1.2;min-width:140px"><label>日期</label><input id="mDay" type="date"></div>
            <div style="width:90px"><label>开始</label><input id="mStart" placeholder="14:00"></div>
            <div style="width:90px"><label>结束</label><input id="mEnd" placeholder="15:00"></div>
          </div>
          <div class="field" style="display:flex;gap:8px;flex-wrap:wrap">
            <div style="flex:1;min-width:150px"><label>地点（可选）</label><input id="mLoc" placeholder="如：会议室A / 腾讯会议"></div>
            <div style="flex:1;min-width:180px"><label>线上链接 / 会议号（可选）</label><input id="mLink" placeholder="https://... 或 会议号"></div>
          </div>
          <div class="field"><label>参会人（可选，逗号分隔）</label><input id="mAtt" placeholder="如：慢慢,小吴"></div>
          <div class="field"><label>备注（可选）</label><input id="mNote" placeholder="议题、准备事项…"></div>
          <div class="field" style="display:flex;gap:8px;align-items:flex-end">
            <div style="width:170px"><label>会前提醒（分钟）</label>
              <select id="mRem">${REM_OPTS.map((o) => `<option value="${o}"${o === 10 ? ' selected' : ''}>会前 ${o} 分钟</option>`).join('')}</select>
            </div>
            <button class="btn primary" id="btnAddMeet" style="flex:1">预订</button>
          </div>
          <div class="note" style="margin-top:6px">保存后会自动在工作台提醒里加一条「会议提醒」，到点弹窗。删除会议会同时清掉它的提醒。</div>
        </div>
        <div class="panel">
          <h3>即将到来的会议</h3>
          <div id="mList" class="note">加载中…</div>
        </div>
      </div>`;

    el.querySelector('#mDay').value = day();
    el.querySelector('#btnAddMeet').onclick = () => this.add();
    ['mTitle', 'mStart', 'mEnd'].forEach((i) =>
      el.querySelector('#' + i).addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.add();
      }));
    el.querySelector('#mList').addEventListener('click', async (e) => {
      const del = e.target.closest('.del');
      if (!del) return;
      const id = +del.dataset.id;
      await post('/api/meetings/del', { id });
      toast('已取消会议');
      this.load();
    });

    this.load();
  },

  async load() {
    const el = this.el;
    const d = await api('/api/meetings?month=');
    this.rows = (d.rows || []).sort((a, b) =>
      (a.day + (a.start || '')).localeCompare(b.day + (b.start || '')));
    const box = el.querySelector('#mList');
    if (!this.rows.length) {
      box.innerHTML = '<div class="note">还没有会议。上面填一条预订上。</div>';
      return;
    }
    const now = day();
    box.innerHTML = this.rows.map((r) => {
      const past = r.day < now || (r.day === now && r.end && r.end < this._nowHM());
      const when = `${esc(r.day)} ${r.start ? esc(r.start) : ''}${r.end ? '–' + esc(r.end) : ''}`;
      return `
      <div class="erow${past ? ' done' : ''}" data-id="${r.id}" style="border-left:3px solid #2f6feb">
        <div class="tx">
          <b>${esc(r.title)}</b>
          <span class="tag">${when}</span>
          ${r.location ? `<span class="tag">📍${esc(r.location)}</span>` : ''}
          ${r.remind_before ? `<span class="tag">会前 ${r.remind_before} 分提醒</span>` : ''}
          ${r.attendees ? `<div class="note" style="margin-top:3px">参会：${esc(r.attendees)}</div>` : ''}
          ${r.link ? `<div class="note" style="margin-top:3px"><a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.link)}</a></div>` : ''}
          ${r.note ? `<div class="note" style="margin-top:3px">${esc(r.note)}</div>` : ''}
        </div>
        <button class="del">取消</button>
      </div>`;
    }).join('');
  },

  _nowHM() {
    const n = new Date();
    return String(n.getHours()).padStart(2, '0') + ':' + String(n.getMinutes()).padStart(2, '0');
  },

  async add() {
    const el = this.el;
    const title = el.querySelector('#mTitle').value.trim();
    if (!title) { toast('标题不能为空'); return; }
    const r = await post('/api/meetings/save', {
      day: el.querySelector('#mDay').value || day(),
      start: el.querySelector('#mStart').value.trim(),
      end: el.querySelector('#mEnd').value.trim(),
      title,
      location: el.querySelector('#mLoc').value.trim(),
      link: el.querySelector('#mLink').value.trim(),
      attendees: el.querySelector('#mAtt').value.trim(),
      note: el.querySelector('#mNote').value.trim(),
      remind_before: +el.querySelector('#mRem').value || 10,
    });
    if (!r.ok) { toast(r.error || '没加上'); return; }
    el.querySelector('#mTitle').value = '';
    el.querySelector('#mStart').value = '';
    el.querySelector('#mEnd').value = '';
    el.querySelector('#mLoc').value = '';
    el.querySelector('#mLink').value = '';
    el.querySelector('#mAtt').value = '';
    el.querySelector('#mNote').value = '';
    toast('会议已预订，会前自动提醒');
    this.load();
  },

  onShow() { this.load(); },

  badge(s) {
    const n = (s.counts && s.counts.meetings) || 0;
    return n ? String(n) : '';
  },

  commands() {
    return [
      { title: '预订一个会议', hint: '会议', run: async () => {
        const t = prompt('会议标题');
        if (!t) return;
        window.WB.go('meet');
        this.el.querySelector('#mTitle').value = t;
        this.el.querySelector('#mStart').focus();
      } },
    ];
  },
};
