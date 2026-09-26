/* 生活专项：设备清单 / 购物预算 / 收入记录，共用一套清单渲染。
 * 房间布局、赚钱看板后面单独做（更大的 UI）。
 */

const { api, post, esc } = window.WB;

/* 每个清单的字段定义：key 对应后端 lists 表的 key */
const SHEETS = [
  {
    key: 'devices', name: '设备清单', hint: '台式机、显示器、路由器…… 位置 + 供电方式记清楚',
    cols: [
      { k: 'name', label: '设备', w: 130 },
      { k: 'loc', label: '位置', w: 110 },
      { k: 'power', label: '供电', w: 110 },
      { k: 'note', label: '备注', w: 0 },
    ],
  },
  {
    key: 'budget', name: '购物预算', hint: '想买的东西，预算和实际都记上，差额一眼看',
    cols: [
      { k: 'item', label: '项目', w: 130 },
      { k: 'plan', label: '预算', w: 90 },
      { k: 'actual', label: '实际', w: 90 },
      { k: 'note', label: '备注', w: 0 },
    ],
  },
  {
    key: 'income', name: '收入记录', hint: '用 AI 赚到的、兼职的、零花的，都记下来',
    cols: [
      { k: 'src', label: '来源', w: 120 },
      { k: 'amt', label: '金额', w: 90 },
      { k: 'date', label: '日期', w: 100 },
      { k: 'note', label: '备注', w: 0 },
    ],
  },
];

/* 数字解析：字段里可能是 "¥120" / "120.5" / 空，统一成 float */
function num(v) {
  if (v == null) return 0;
  const n = parseFloat(String(v).replace(/[^\d.\-]/g, ''));
  return isNaN(n) ? 0 : n;
}

export default {
  id: 'life',
  name: '生活',

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel" id="dash-panel">
        <h3>赚钱看板</h3>
        <div class="note" style="margin-bottom:8px">从「收入记录」「购物预算」自动汇总，记一笔这里就更新</div>
        <div id="dash"></div>
      </div>
      ${SHEETS.map((s) => `
      <div class="panel" data-sheet="${s.key}">
        <h3>${esc(s.name)}</h3>
        <div class="note" style="margin-bottom:8px">${esc(s.hint)}</div>
        <div class="listbox" id="lb-${s.key}"></div>
        <div class="field" style="margin-top:8px" id="add-${s.key}"></div>
      </div>`).join('')}
    </div>`;

    for (const s of SHEETS) {
      // 加一行：每个字段一个 input
      const add = el.querySelector(`#add-${s.key}`);
      add.innerHTML = s.cols.map((c) =>
        `<input data-f="${c.k}" placeholder="${esc(c.label)}" style="max-width:${c.w || 200}px">`
      ).join('') + `<button class="btn primary" data-add="${s.key}" style="height:34px">添加</button>`;
      add.querySelector(`[data-add="${s.key}"]`).onclick = async () => {
        const fields = {};
        add.querySelectorAll('input[data-f]').forEach((i) => {
          if (i.value.trim()) fields[i.dataset.f] = i.value.trim();
        });
        if (!Object.keys(fields).length) return;
        await post('/api/lists/add', { key: s.key, fields });
        add.querySelectorAll('input[data-f]').forEach((i) => (i.value = ''));
        this.load(s);
      };
      el.querySelector(`#lb-${s.key}`).addEventListener('click', async (e) => {
        const x = e.target.closest('.x');
        if (!x) return;
        await post('/api/lists/del', { id: +x.dataset.id });
        this.load(s);
      });
    }
    this.refresh();
  },

  async load(s) {
    const d = await api('/api/lists?key=' + s.key);
    const box = this.el.querySelector(`#lb-${s.key}`);
    const rows = d.rows || [];
    if (!rows.length) {
      box.innerHTML = '<div class="note">还没有，先加一条</div>';
      return;
    }
    box.innerHTML = rows.map((r) => {
      const f = r.fields || {};
      const cells = s.cols.map((c) =>
        `<div style="flex:${c.w ? '0 0 ' + c.w + 'px' : '1 1 0'};min-width:0">${esc(f[c.k] || '')}</div>`
      ).join('');
      return `<div class="lrow">${cells}<button class="x" data-id="${r.id}">×</button></div>`;
    }).join('');
  },

  async loadDash() {
    const box = this.el.querySelector('#dash');
    if (!box) return;
    const [inc, bud] = await Promise.all([
      api('/api/lists?key=income'),
      api('/api/lists?key=budget'),
    ]);
    const incRows = (inc.rows || []).map((r) => r.fields || {});
    const budRows = (bud.rows || []).map((r) => r.fields || {});

    const totalInc = incRows.reduce((s, f) => s + num(f.amt), 0);
    const totalSpend = budRows.reduce((s, f) => s + (num(f.actual) || num(f.plan)), 0);
    const net = totalInc - totalSpend;

    // 按来源汇总收入
    const bySrc = {};
    for (const f of incRows) {
      const k = f.src || '未分类';
      bySrc[k] = (bySrc[k] || 0) + num(f.amt);
    }
    const srcEntries = Object.entries(bySrc).sort((a, b) => b[1] - a[1]);
    const maxSrc = Math.max(1, ...srcEntries.map((e) => e[1]));

    const money = (n) => '¥' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const bar = (label, val, max, cls) =>
      `<div class="dash-bar"><span class="dl">${esc(label)}</span>
        <span class="dt"><span class="df ${cls}" style="width:${Math.round((val / max) * 100)}%"></span></span>
        <span class="dv">${money(val)}</span></div>`;

    box.innerHTML = `
      <div class="dash-stats">
        <div class="ds"><div class="dn">总收入</div><div class="dv inc">${money(totalInc)}</div></div>
        <div class="ds"><div class="dn">总支出</div><div class="dv out">${money(totalSpend)}</div></div>
        <div class="ds"><div class="dn">净结余</div><div class="dv ${net >= 0 ? 'inc' : 'out'}">${money(net)}</div></div>
      </div>
      <h4 style="margin:14px 0 6px">收入来源</h4>
      ${srcEntries.length ? srcEntries.map((e) => bar(e[0], e[1], maxSrc, 'b-inc')).join('') : '<div class="note">还没有收入记录</div>'}
      <h4 style="margin:14px 0 6px">预算差额（实际 − 预算）</h4>
      ${budRows.length ? budRows.map((f) => {
        const plan = num(f.plan), act = num(f.actual);
        const diff = act - plan;
        const diffTxt = (diff === 0 ? '未记实际' : (diff > 0 ? '超 ' : '省 ') + money(Math.abs(diff)));
        return `<div class="dash-bar"><span class="dl">${esc(f.item || '—')}</span>
          <span class="dt"><span class="df b-bud" style="width:${Math.round((plan ? act / Math.max(plan, act) : 1) * 100)}%"></span></span>
          <span class="dv ${diff > 0 ? 'out' : 'inc'}">${diffTxt}</span></div>`;
      }).join('') : '<div class="note">还没有预算项</div>'}
    `;
  },

  refresh() {
    this.loadDash();
    for (const s of SHEETS) this.load(s);
  },

  onShow() { this.refresh(); },
};
