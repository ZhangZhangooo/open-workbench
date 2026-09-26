/* 技能库：WorkBuddy 本机技能 + OpenClaw / ClawHub，两源合一搜 */

const { api, toast, esc } = window.WB;

export default {
  id: 'skills',
  name: '技能库',
  el: null,
  all: [],        // 合一后的列表
  q: '',
  src: 'all',     // all | wb | claw
  onlyOk: false,  // 只看能用的

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0;flex-wrap:wrap;gap:6px">
        <input id="skQ" placeholder="搜技能名或说明" style="height:30px;flex:1;min-width:160px;
               border:1px solid var(--line-strong);border-radius:8px;padding:0 10px;
               background:var(--surface);color:var(--ink);font-size:12px">
        <select id="skSrc" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;
                padding:0 8px;background:var(--surface);color:var(--ink);font-size:12px">
          <option value="all">全部来源</option>
          <option value="wb">WorkBuddy 本机</option>
          <option value="claw">OpenClaw / ClawHub</option>
        </select>
        <label style="font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:4px">
          <input type="checkbox" id="skOk"> 只看能用的
        </label>
        <span id="skCount" class="note" style="margin-left:auto"></span>
      </div>
      <div class="stack">
      <div class="panel">
        <div class="note" style="margin-bottom:8px">
          WorkBuddy 技能是本机文件夹里的 SKILL.md，装上就能用；
          OpenClaw 那栏是它自带的技能，灰色的是缺依赖（要装别的程序或填 key）用不了。
        </div>
        <div id="skList" class="note">加载中…</div>
      </div>
      </div>`;

    el.querySelector('#skQ').addEventListener('input', (e) => {
      this.q = e.target.value.trim().toLowerCase();
      this.render();
    });
    el.querySelector('#skSrc').addEventListener('change', (e) => {
      this.src = e.target.value;
      this.render();
    });
    el.querySelector('#skOk').addEventListener('change', (e) => {
      this.onlyOk = e.target.checked;
      this.render();
    });

    // 列表点击：ClawHub 技能「下载/安装」
    el.querySelector('#skList').addEventListener('click', async (e) => {
      const btn = e.target.closest('.sk-btn');
      if (!btn || btn.disabled) return;
      const name = btn.dataset.name;
      btn.disabled = true;
      btn.classList.add('busy');
      btn.textContent = '安装中…';
      let r;
      try {
        r = await post('/api/skills/install', { name, source: 'claw' });
      } catch (err) {
        r = { ok: false, error: String(err && err.message || err) };
      }
      btn.classList.remove('busy');
      if (r && r.ok) {
        toast('「' + name + '」装好了');
        btn.textContent = '已装';
        btn.classList.add('done');
        btn.disabled = true;
        this.load();
      } else {
        const err = (r && (r.error || (r.raw || '').slice(0, 120))) || '安装失败';
        toast('安装失败：' + String(err).slice(0, 70));
        btn.textContent = '重试';
        btn.classList.add('install');
        btn.disabled = false;
      }
    });

    this.load();
  },

  async load() {
    const d = await api('/api/skills');
    const wb = (d.wb && d.wb.rows) || [];
    const claw = (d.claw && d.claw.rows) || [];
    this.all = [
      ...wb.map((x) => ({
        name: x.name, desc: x.desc, src: x.src, srcKey: 'wb',
        ok: true, path: x.path, why: '',
      })),
      ...claw.map((x) => ({
        name: x.name, desc: x.desc, src: 'OpenClaw', srcKey: 'claw',
        ok: x.eligible && !x.disabled,
        path: '',
        why: (x.missing_bins || []).length ? `缺 ${x.missing_bins.join(' / ')}` : '',
      })),
    ];
    this.render();
  },

  render() {
    const box = this.el.querySelector('#skList');
    let rows = this.all;
    if (this.src !== 'all') rows = rows.filter((r) => r.srcKey === this.src);
    if (this.onlyOk) rows = rows.filter((r) => r.ok);
    if (this.q) {
      rows = rows.filter((r) =>
        (r.name + ' ' + r.desc + ' ' + r.src).toLowerCase().includes(this.q));
    }

    this.el.querySelector('#skCount').textContent =
      `${rows.length} / ${this.all.length} 个`;

    if (!rows.length) {
      box.innerHTML = '<div class="note">没匹配到。换个词试试。</div>';
      return;
    }

    // 能用的排前面
    rows = [...rows].sort((a, b) => (b.ok ? 1 : 0) - (a.ok ? 1 : 0) || a.name.localeCompare(b.name));

    box.innerHTML = rows.slice(0, 300).map((r) => {
      const btn = r.srcKey === 'claw'
        ? (r.ok
            ? '<button class="sk-btn done" disabled>已装</button>'
            : '<button class="sk-btn install" data-name="' + esc(r.name) + '">下载</button>')
        : '';
      return `
      <div class="sk-row${r.ok ? '' : ' off'}">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
          <b style="font-weight:500">${esc(r.name)}</b>
          <span class="tag">${esc(r.src)}</span>
          ${r.ok ? '<span class="tag ok">可用</span>' : '<span class="tag warn">用不了</span>'}
          ${r.why ? `<span class="note">${esc(r.why)}</span>` : ''}
          ${btn}
        </div>
        <div class="note" style="margin-top:3px">${esc(r.desc || '没写说明')}</div>
        ${r.path ? `<div class="note" style="margin-top:2px;opacity:.7;font-size:11.5px">${esc(r.path)}</div>` : ''}
      </div>`;
    }).join('');
  },

  onShow() {
    if (!this.all.length) this.load();
  },

  badge() {
    return '';
  },

  commands() {
    return [
      { title: '搜技能', hint: '技能库', run: async () => {
        const q = prompt('搜什么技能');
        if (q === null) return;
        window.WB.go('skills');
        this.q = q.trim().toLowerCase();
        this.el.querySelector('#skQ').value = q;
        if (!this.all.length) await this.load();
        this.render();
      } },
      { title: '只看能用的技能', hint: '技能库', run: () => {
        window.WB.go('skills');
        this.onlyOk = true;
        this.el.querySelector('#skOk').checked = true;
        if (!this.all.length) this.load(); else this.render();
      } },
    ];
  },
};
