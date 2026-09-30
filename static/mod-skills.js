/* 技能库：WorkBuddy 本机技能 + OpenClaw / ClawHub，两源合一搜
   115 收藏钉顶 / 116 依赖说明 / 117 自定义目录 / 118 运行统计 / 119 双源模糊搜 / 120 推荐 */

const { api, post, toast, esc, fmtTime } = window.WB;

// 119 模糊匹配：完全包含得分最高，否则退回「按顺序出现」的子序列匹配
function fuzzy(q, text) {
  if (!q) return 0;
  const t = (text || '').toLowerCase();
  if (!t) return -1;
  if (t.includes(q)) return 100 + Math.min(50, (q.length / t.length) * 50);
  let i = 0, first = -1;
  for (let j = 0; j < t.length && i < q.length; j++) {
    if (t[j] === q[i]) { if (first < 0) first = j; i++; }
  }
  if (i < q.length) return -1;
  return 30 - Math.min(25, first);
}

// 命中片段高亮（先转义再替换，避免 XSS）
function hl(text, q) {
  const s = esc(text || '');
  if (!q) return s;
  try {
    const re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
    return s.replace(re, '<b class="sk-hl">$1</b>');
  } catch (e) { return s; }
}

export default {
  id: 'skills',
  name: '技能库',
  el: null,
  all: [],          // 合一后的列表
  q: '',
  src: 'all',       // all | wb | claw
  onlyOk: false,    // 只看能用的
  favOnly: false,   // 只看收藏
  favs: new Set(),  // key 集合
  stats: {},        // key -> {runs,last_run,...}
  statTotal: 0,
  dirs: [],
  recs: [],
  hasProfile: false,
  scored: [],       // 本轮带分数的行

  key(r) { return r.srcKey + '|' + r.name; },

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0;flex-wrap:wrap;gap:6px">
        <input id="skQ" placeholder="搜技能名 / 说明 / 依赖（支持模糊）" style="height:30px;flex:1;min-width:170px;
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
        <label style="font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:4px">
          <input type="checkbox" id="skFav"> 只看收藏
        </label>
        <span id="skCount" class="note" style="margin-left:auto"></span>
      </div>
      <div class="stack">
        <div class="panel" id="skRecPanel" style="display:none">
          <h3>按你的使用习惯推荐</h3>
          <div id="skRec" class="note"></div>
        </div>
        <div class="panel">
          <h3>自定义技能目录</h3>
          <div class="note" style="margin-bottom:6px">
            指一个文件夹进去，里面每个含 SKILL.md 的子目录都会被当成一个技能扫进来（本机技能，不上传）。
          </div>
          <div class="sk-dirbar">
            <input id="skDirPath" placeholder="比如 D:\\my-skills" class="sk-in">
            <input id="skDirLabel" placeholder="备注（可空）" class="sk-in" style="max-width:130px">
            <button id="skDirAdd" class="sk-btn">注册</button>
          </div>
          <div id="skDirs" class="note" style="margin-top:8px"></div>
        </div>
        <div class="panel" id="skStatPanel" style="display:none">
          <h3>运行统计 <span id="skStatSum" class="note"></span></h3>
          <div id="skStats"></div>
        </div>
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
      this.src = e.target.value; this.render();
    });
    el.querySelector('#skOk').addEventListener('change', (e) => {
      this.onlyOk = e.target.checked; this.render();
    });
    el.querySelector('#skFav').addEventListener('change', (e) => {
      this.favOnly = e.target.checked; this.render();
    });

    // 117 注册自定义目录
    el.querySelector('#skDirAdd').addEventListener('click', () => this.addDir());    el.querySelector('#skDirPath').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.addDir();
    });
    el.querySelector('#skDirs').addEventListener('click', async (e) => {
      const b = e.target.closest('.sk-dir-del');
      if (!b) return;
      const r = await post('/api/skills/dir/del', { id: Number(b.dataset.id) });
      if (r && r.ok) { toast('已移除'); this.load(); }
    });

    // 120 点推荐就去搜它
    el.querySelector('#skRec').addEventListener('click', (e) => {
      const c = e.target.closest('.sk-rec');
      if (!c) return;
      const q = c.dataset.name;
      this.el.querySelector('#skQ').value = q;
      this.q = q.toLowerCase();
      this.render();
      this.el.querySelector('#skList').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    // 主列表：收藏 / 记一次 / 安装
    el.querySelector('#skList').addEventListener('click', (e) => this.onListClick(e));

    this.load();
  },

  async addDir() {
    const p = this.el.querySelector('#skDirPath');
    const l = this.el.querySelector('#skDirLabel');
    const path = p.value.trim();
    if (!path) { toast('填个目录'); return; }
    let r;
    try { r = await post('/api/skills/dir/add', { path, label: l.value.trim() }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (r && r.ok) {
      toast(r.dup ? '这个目录已经在了' : '注册好了');
      p.value = ''; l.value = '';
      this.load();
    } else {
      toast('不行：' + String((r && r.error) || '目录不对').slice(0, 60));
    }
  },

  // 列表点击：收藏 / 记一次 / 安装
  async onListClick(e) {
    const star = e.target.closest('.sk-star');
    if (star) {
      const key = star.dataset.key;
      const on = this.favs.has(key) ? 0 : 1;
      let r;
      try { r = await post('/api/skills/fav', { key, on }); }
      catch (err) { r = { ok: false }; }
      if (r && r.ok) {
        if (r.fav) this.favs.add(key); else this.favs.delete(key);
        toast(r.fav ? '⭐ 钉顶了' : '取消钉顶');
        this.render();
      } else toast('没成');
      return;
    }

    const use = e.target.closest('.sk-use');
    if (use) {
      const key = use.dataset.key;
      let r;
      try { r = await post('/api/skills/use', { key, name: use.dataset.name, src: use.dataset.src }); }
      catch (err) { r = { ok: false }; }
      if (r && r.ok) {
        this.stats[key] = r.row || { runs: ((this.stats[key] || {}).runs || 0) + 1 };
        try { await navigator.clipboard.writeText(use.dataset.name); } catch (err) { /* 剪贴板不给就算 */ }
        toast('记一次，技能名已复制');
        this.render();
      } else toast('没记上');
      return;
    }

    const btn = e.target.closest('.sk-btn');
    if (!btn || btn.disabled || !btn.classList.contains('install')) return;
    const name = btn.dataset.name;
    btn.disabled = true;
    btn.classList.add('busy');
    btn.textContent = '安装中…';
    let r;
    try { r = await post('/api/skills/install', { name, source: 'claw' }); }
    catch (err) { r = { ok: false, error: String((err && err.message) || err) }; }
    btn.classList.remove('busy');
    if (r && r.ok) {
      toast('「' + name + '」装好了');
      btn.textContent = '已装';
      btn.classList.add('done');
      this.load();
    } else {
      const err = (r && (r.error || (r.raw || '').slice(0, 120))) || '安装失败';
      toast('安装失败：' + String(err).slice(0, 70));
      btn.textContent = '重试';
      btn.classList.add('install');
      btn.disabled = false;
    }
  },

  async load() {
    const d = await api('/api/skills');
    const wb = (d.wb && d.wb.rows) || [];
    const claw = (d.claw && d.claw.rows) || [];
    this.favs = new Set(d.fav || []);
    this.stats = {};
    ((d.stats && d.stats.rows) || []).forEach((r) => { this.stats[r.key] = r; });
    this.statTotal = (d.stats && d.stats.total) || 0;
    this.dirs = d.dirs || [];

    this.all = [
      ...wb.map((x) => ({
        name: x.name, desc: x.desc, src: x.src, srcKey: 'wb',
        ok: true, path: x.path, why: '',
        deps: x.deps || [],
      })),
      ...claw.map((x) => ({
        name: x.name, desc: x.desc, src: 'OpenClaw', srcKey: 'claw',
        ok: !!(x.eligible && !x.disabled),
        path: '',
        why: (x.missing_bins || []).length ? `缺 ${x.missing_bins.join(' / ')}` : '',
        deps: (x.missing_bins || []).map((b) => ({ name: b, ok: false })),
      })),
    ];

    this.render();
    this.renderDirs();
    this.loadRecs();
  },

  async loadRecs() {
    let r;
    try { r = await api('/api/skills/recommend'); } catch (e) { r = null; }
    this.recs = (r && r.rows) || [];
    this.hasProfile = !!(r && r.has_profile);
    this.renderRecs();
  },

  renderRecs() {
    const box = this.el.querySelector('#skRec');
    const panel = this.el.querySelector('#skRecPanel');
    if (!this.recs.length) { panel.style.display = 'none'; return; }
    panel.style.display = '';
    box.innerHTML = `
      <div class="sk-recwrap">${this.recs.map((r) => `
        <div class="sk-rec" data-name="${esc(r.name)}" title="点一下去搜它">
          <b>${esc(r.name)}</b>
          <span class="tag">${esc(r.src)}</span>
          <div class="note sk-recwhy">${esc(r.reason)}</div>
        </div>`).join('')}</div>
      ${this.hasProfile ? '' : '<div class="note" style="margin-top:6px">用得越多，这里推得越准。</div>'}`;
  },

  renderDirs() {
    const box = this.el.querySelector('#skDirs');
    if (!this.dirs.length) { box.innerHTML = '还没注册自定义目录。'; return; }
    box.innerHTML = this.dirs.map((d) => `
      <div class="sk-dir">
        <b>${esc(d.label || '自定义')}</b>
        <span class="note" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
              title="${esc(d.path)}">${esc(d.path)}</span>
        <button class="sk-dir-del" data-id="${d.id}">移除</button>
      </div>`).join('');
  },

  renderStats() {
    const panel = this.el.querySelector('#skStatPanel');
    const box = this.el.querySelector('#skStats');
    const rows = Object.values(this.stats).sort((a, b) =>
      (b.runs || 0) - (a.runs || 0) || (b.last_run || 0) - (a.last_run || 0)).slice(0, 8);
    if (!rows.length) { panel.style.display = 'none'; return; }
    panel.style.display = '';
    const max = Math.max(1, ...rows.map((r) => r.runs || 1));
    this.el.querySelector('#skStatSum').textContent =
      `累计 ${this.statTotal} 次 · ${Object.keys(this.stats).length} 个技能用过`;
    box.innerHTML = rows.map((r) => `
      <div class="sk-stat-row">
        <span class="sk-stat-name" title="${esc(r.name || r.key)}">${esc(r.name || r.key)}</span>
        <span class="sk-bar"><i style="width:${Math.round((r.runs || 1) / max * 100)}%"></i></span>
        <span class="note">${r.runs || 0} 次</span>
      </div>`).join('');
  },

  render() {
    const box = this.el.querySelector('#skList');
    const q = this.q;
    const toks = q ? q.split(/\s+/).filter(Boolean) : [];
    let rows = this.all;

    // 119 双源模糊搜：每个词都要命中（AND），命中越好排越前
    if (toks.length) {
      const scored = [];
      for (const r of rows) {
        const hay = [r.name, r.desc, r.src, (r.deps || []).map((d) => d.name).join(' ')].join(' ');
        let total = 0, miss = false;
        for (const t of toks) {
          const s = fuzzy(t, hay);
          if (s < 0) { miss = true; break; }
          total += s;
        }
        if (!miss) { scored.push({ r, score: total }); }
      }
      scored.sort((a, b) => b.score - a.score);
      rows = scored.map((x) => x.r);
    }

    if (this.src !== 'all') rows = rows.filter((r) => r.srcKey === this.src);
    if (this.onlyOk) rows = rows.filter((r) => r.ok);
    if (this.favOnly) rows = rows.filter((r) => this.favs.has(this.key(r)));

    this.el.querySelector('#skCount').textContent =
      `${rows.length} / ${this.all.length} 个` + (this.favs.size ? ` · ⭐${this.favs.size}` : '');

    this.renderStats();

    if (!rows.length) {
      box.innerHTML = `<div class="note">没匹配到。换个词试试。${this.favOnly ? '（只看收藏时先点 ⭐ 钉几个）' : ''}</div>`;
      return;
    }

    // 排序：收藏 > 可用 > （有搜索时按相关度，否则按名字）；搜索时保留相关度
    if (!toks.length) {
      rows = [...rows].sort((a, b) =>
        (this.favs.has(this.key(b)) ? 1 : 0) - (this.favs.has(this.key(a)) ? 1 : 0)
        || (b.ok ? 1 : 0) - (a.ok ? 1 : 0)
        || a.name.localeCompare(b.name));
    } else {
      // 搜索时收藏和可用只做微调
      rows = [...rows].sort((a, b) =>
        (this.favs.has(this.key(b)) ? 1 : 0) - (this.favs.has(this.key(a)) ? 1 : 0));
    }

    box.innerHTML = rows.slice(0, 300).map((r) => {
      const key = this.key(r);
      const fav = this.favs.has(key);
      const st = this.stats[key];
      const btn = r.srcKey === 'claw'
        ? (r.ok
            ? '<button class="sk-btn done" disabled>已装</button>'
            : '<button class="sk-btn install" data-name="' + esc(r.name) + '">下载</button>')
        : '';
      const deps = (r.deps || []).map((d) =>
        `<span class="sk-dep${d.ok ? '' : ' miss'}" title="${d.ok ? '本机找得到' : '本机没找到，可能要装或填 key'}">`
        + `${esc(d.name)}${d.ok ? '' : ' · 缺'}</span>`).join('');
      return `
      <div class="sk-row${r.ok ? '' : ' off'}">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
          <button class="sk-star${fav ? ' on' : ''}" data-key="${esc(key)}"
                  title="${fav ? '取消钉顶' : '钉顶'}">${fav ? '⭐' : '☆'}</button>
          <b style="font-weight:500">${hl(r.name, this.q)}</b>
          <span class="tag">${esc(r.src)}</span>
          ${r.ok ? '<span class="tag ok">可用</span>' : '<span class="tag warn">用不了</span>'}
          ${st && st.runs ? `<span class="tag on">用过 ${st.runs} 次</span>` : ''}
          ${r.why ? `<span class="note">${esc(r.why)}</span>` : ''}
          <button class="sk-use" data-key="${esc(key)}" data-name="${esc(r.name)}"
                  data-src="${esc(r.src)}" title="记一次使用并复制技能名">记一次</button>
          ${btn}
        </div>
        <div class="note" style="margin-top:3px">${hl(r.desc, this.q) || '没写说明'}</div>
        ${deps ? `<div class="sk-deps">依赖：${deps}</div>` : ''}
        ${r.path ? `<div class="note" style="margin-top:2px;opacity:.7;font-size:11.5px">${esc(r.path)}</div>` : ''}
        ${st && st.last_run ? `<div class="note" style="opacity:.6;font-size:11px">上次 ${fmtTime(st.last_run)}</div>` : ''}
      </div>`;
    }).join('');
  },

  onShow(arg) {
    if (!this.all.length) { this.load(); return; }
    if (arg) {
      this.q = String(arg).toLowerCase();
      const qi = this.el.querySelector('#skQ');
      if (qi) qi.value = arg;
      this.render();
    }
  },

  badge() { return ''; },

  commands() {
    return [
      { title: '搜技能', hint: '技能库', run: async () => {
        const q = prompt('搜什么技能');
        if (q === null) return;
        window.WB.go('skills');
        if (!this.all.length) await this.load();
        this.q = q.trim().toLowerCase();
        this.el.querySelector('#skQ').value = q;
        this.render();
      } },
      { title: '只看能用的技能', hint: '技能库', run: () => {
        window.WB.go('skills');
        this.onlyOk = true;
        this.el.querySelector('#skOk').checked = true;
        if (!this.all.length) this.load(); else this.render();
      } },
      { title: '只看收藏的技能', hint: '技能库', run: () => {
        window.WB.go('skills');
        this.favOnly = true;
        this.el.querySelector('#skFav').checked = true;
        if (!this.all.length) this.load(); else this.render();
      } },
      { title: '让技能库推荐几个', hint: '技能库', run: () => {
        window.WB.go('skills');
        if (!this.all.length) this.load();
      } },
    ];
  },
};
