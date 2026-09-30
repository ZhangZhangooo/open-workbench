/* K 域 生活（95-104）
   95 预算记账 / 96 超支预警 / 97 设备台账 / 99 充电区 /
   100 网络拓扑 / 101 采购清单 / 102 收入看板 / 104 体重简记
   （98 房间布局图在「房间」页、103 习惯打卡在「习惯」页，各自独立。）
   老版把设备/预算/收入存在通用 lists 表里，首次打开会自动搬到新表。 */

const { api, post, toast, esc, day } = window.WB;

const money = (n) => '¥' + (n || 0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
const TABS = [
  ['money', '记账'], ['board', '收入看板'], ['dev', '设备/充电'],
  ['net', '网络拓扑'], ['buy', '采购清单'], ['weight', '体重'],
];

export default {
  id: 'life',
  name: '生活',
  el: null,
  tab: 'money',
  month: day().slice(0, 7),
  cats: [],
  charge: ['', '充电中', '已满', '待充', '不用充'],

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="chips" id="lifeTabs">
        ${TABS.map(([k, n], i) => `<button class="chip${i === 0 ? ' on' : ''}" data-t="${k}">${n}</button>`).join('')}
      </div>

      <!-- 95 记账 + 96 超支预警 -->
      <div class="stack" id="paneMoney">
        <div class="panel">
          <h3>记一笔</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input type="date" id="lgDay" style="width:150px">
            <select id="lgKind" style="height:30px">
              <option>支出</option><option>收入</option>
            </select>
            <input id="lgAmt" placeholder="金额" style="width:100px;height:30px">
            <input id="lgCat" list="lgCatList" placeholder="分类" style="width:120px;height:30px">
            <datalist id="lgCatList"></datalist>
            <input id="lgNote" placeholder="备注" style="flex:1;min-width:140px;height:30px">
            <button class="btn primary" id="lgAdd">记下</button>
          </div>
          <div class="note" style="margin-top:6px">分类随便填，常记的几个会自动出现在提示里；支出记完立刻帮你看有没有超阈值。</div>
        </div>

        <div class="panel">
          <div style="display:flex;gap:8px;align-items:center">
            <h3 style="margin:0">本月总览</h3>
            <input type="month" id="lgMonth" style="margin-left:auto">
          </div>
          <div class="dash-stats" id="lgSum" style="margin-top:10px"></div>
          <h4 style="margin:14px 0 4px">支出分类</h4>
          <div id="lgCats"></div>
        </div>

        <div class="panel">
          <h3>超支预警</h3>
          <div class="note" style="margin-bottom:8px">给分类设个月度阈值，超了就红字提醒；也能一键推到微信/连接器。</div>
          <div id="lgOver"></div>
          <div id="lgLimits" style="margin-top:10px"></div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <button class="btn primary" id="lgLimSave">保存阈值</button>
            <button class="btn" id="lgPush">推到连接器</button>
          </div>
        </div>

        <div class="panel">
          <h3>流水</h3>
          <div class="listbox" id="lgRows"></div>
        </div>
      </div>

      <!-- 102 收入看板 -->
      <div class="stack" id="paneBoard" style="display:none">
        <div class="panel">
          <h3>月度对比</h3>
          <div class="note" style="margin-bottom:8px">收入、支出、净结余逐月排开，看趋势用。</div>
          <div id="bdBox"></div>
        </div>
      </div>

      <!-- 97 设备台账 + 99 充电区 -->
      <div class="stack" id="paneDev" style="display:none">
        <div class="panel">
          <h3>加设备</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="dvName" placeholder="设备名" style="width:140px;height:30px">
            <input id="dvKind" placeholder="类型(显示器/路由…)" style="width:150px;height:30px">
            <input id="dvZone" placeholder="位置(桌面/床头)" style="width:130px;height:30px">
            <span class="note">购入</span><input type="date" id="dvBought" style="width:150px">
            <input id="dvWar" type="number" placeholder="保修月" style="width:88px;height:30px">
            <input id="dvPrice" type="number" placeholder="价格" style="width:96px;height:30px">
            <select id="dvCharge" style="height:30px">${this.charge.map((c) => `<option value="${c}">${c || '不登记充电'}</option>`).join('')}</select>
            <button class="btn primary" id="dvAdd">添加</button>
          </div>
        </div>
        <div class="panel">
          <h3>充电区</h3>
          <div id="dvChargeBoard"></div>
        </div>
        <div class="panel">
          <h3>设备台账</h3>
          <div class="note" style="margin-bottom:8px">保修剩余天数按购入日 + 保修月数算；点充电状态循环切换。</div>
          <div class="listbox" id="dvRows"></div>
        </div>
      </div>

      <!-- 100 网络拓扑 -->
      <div class="stack" id="paneNet" style="display:none">
        <div class="panel">
          <h3>加节点</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="ntName" placeholder="名字(光猫/主路由/交换机…)" style="width:190px;height:30px">
            <input id="ntKind" placeholder="类型" style="width:110px;height:30px">
            <select id="ntParent" style="height:30px;max-width:170px"><option value="0">— 上游：无 —</option></select>
            <input id="ntPort" placeholder="端口(如 LAN1)" style="width:120px;height:30px">
            <input id="ntIp" placeholder="IP" style="width:130px;height:30px">
            <button class="btn primary" id="ntAdd">添加</button>
          </div>
        </div>
        <div class="panel">
          <h3>拓扑</h3>
          <div id="ntRows" class="note">空</div>
        </div>
      </div>

      <!-- 101 采购清单 -->
      <div class="stack" id="paneBuy" style="display:none">
        <div class="panel">
          <h3>想买什么</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="wsName" placeholder="物品" style="width:150px;height:30px">
            <input id="wsPrice" type="number" placeholder="价格" style="width:96px;height:30px">
            <input id="wsShop" placeholder="店铺/平台" style="width:130px;height:30px">
            <input id="wsUrl" placeholder="链接" style="flex:1;min-width:140px;height:30px">
            <select id="wsPri" style="height:30px">
              <option value="1">高优先级</option><option value="2" selected>中</option><option value="3">低</option>
            </select>
            <select id="wsStatus" style="height:30px"></select>
            <button class="btn primary" id="wsAdd">加入清单</button>
          </div>
        </div>
        <div class="panel">
          <div class="dash-stats" id="wsSum"></div>
          <div style="display:flex;gap:6px;margin:12px 0 6px;flex-wrap:wrap" id="wsFilter"></div>
          <div class="listbox" id="wsRows"></div>
        </div>
      </div>

      <!-- 104 体重简记 -->
      <div class="stack" id="paneWeight" style="display:none">
        <div class="panel">
          <h3>记一次</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input type="date" id="wtDay" style="width:150px">
            <input id="wtKg" type="number" step="0.1" placeholder="kg" style="width:100px;height:30px">
            <input id="wtNote" placeholder="备注(早上/饭后…)" style="flex:1;min-width:120px;height:30px">
            <button class="btn primary" id="wtAdd">记下</button>
          </div>
          <div class="dash-stats" id="wtStats" style="margin-top:12px"></div>
        </div>
        <div class="panel">
          <h3>曲线</h3>
          <svg id="wtSvg" style="width:100%;height:180px"></svg>
          <div class="listbox" id="wtRows" style="margin-top:8px"></div>
        </div>
      </div>`;

    el.querySelector('#lifeTabs').addEventListener('click', (e) => {
      const b = e.target.closest('[data-t]');
      if (!b) return;
      this.tab = b.dataset.t;
      el.querySelectorAll('[data-t]').forEach((x) => x.classList.toggle('on', x === b));
      const panes = { money: 'Money', board: 'Board', dev: 'Dev', net: 'Net', buy: 'Buy', weight: 'Weight' };
      for (const k in panes) {
        el.querySelector('#pane' + panes[k]).style.display = this.tab === k ? '' : 'none';
      }
      this.load();
    });

    // 95
    el.querySelector('#lgDay').value = day();
    el.querySelector('#lgMonth').value = this.month;
    el.querySelector('#lgMonth').onchange = (e) => {
      this.month = e.target.value || day().slice(0, 7);
      this.load();
    };
    el.querySelector('#lgAdd').onclick = async () => {
      const amt = parseFloat(el.querySelector('#lgAmt').value);
      if (!amt) return toast('金额还没填');
      const r = await post('/api/ledger/add', {
        day: el.querySelector('#lgDay').value || day(),
        kind: el.querySelector('#lgKind').value,
        amount: amt,
        category: el.querySelector('#lgCat').value.trim(),
        note: el.querySelector('#lgNote').value.trim(),
      });
      if (!r.ok) return toast(r.error || '记不上');
      if ((r.over || []).length) {
        toast('⚠ 超了：' + r.over.map((o) => `${o.cat} ${money(o.used)}/${money(o.limit)}`).join('、'));
      } else toast('记上了');
      el.querySelector('#lgAmt').value = '';
      el.querySelector('#lgNote').value = '';
      this.load();
    };
    el.querySelector('#lgLimSave').onclick = async () => {
      const limits = {};
      el.querySelectorAll('#lgLimits input[data-cat]').forEach((i) => {
        const v = parseFloat(i.value);
        if (v > 0) limits[i.dataset.cat] = v;
      });
      const r = await post('/api/budget/save', { limits });
      toast(r.ok ? `存了 ${Object.keys(r.limits).length} 个分类阈值` : '存不上');
      this.load();
    };
    el.querySelector('#lgPush').onclick = async () => {
      const r = await post('/api/budget/push', { month: this.month });
      if (!r.ok) return toast(r.error || '推不了');
      toast('已推送：' + (r.sent || []).join('、'));
    };
    el.querySelector('#lgRows').addEventListener('click', async (e) => {
      const x = e.target.closest('.x');
      if (!x) return;
      await post('/api/ledger/del', { id: +x.dataset.id });
      this.load();
    });

    // 97 / 99
    el.querySelector('#dvAdd').onclick = async () => {
      const name = el.querySelector('#dvName').value.trim();
      if (!name) return toast('设备名还没填');
      const r = await post('/api/devices/save', {
        name, kind: el.querySelector('#dvKind').value.trim(),
        zone: el.querySelector('#dvZone').value.trim(),
        bought: el.querySelector('#dvBought').value,
        warranty: el.querySelector('#dvWar').value || 0,
        price: el.querySelector('#dvPrice').value || 0,
        charge: el.querySelector('#dvCharge').value,
      });
      if (!r.ok) return toast(r.error || '存不上');
      ['dvName', 'dvKind', 'dvZone', 'dvBought', 'dvWar', 'dvPrice'].forEach((i) => {
        el.querySelector('#' + i).value = '';
      });
      toast('设备已入库');
      this.load();
    };
    el.querySelector('#dvRows').addEventListener('click', async (e) => {
      const row = e.target.closest('.lrow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.x')) {
        await post('/api/devices/del', { id });
        return this.load();
      }
      const ch = e.target.closest('[data-charge]');
      if (ch) {
        const cur = row.dataset.charge || '';
        const next = this.charge[(this.charge.indexOf(cur) + 1) % this.charge.length];
        await post('/api/devices/charge', { id, charge: next });
        this.load();
      }
    });

    // 100
    el.querySelector('#ntAdd').onclick = async () => {
      const name = el.querySelector('#ntName').value.trim();
      if (!name) return toast('名字还没填');
      const r = await post('/api/netmap/save', {
        name, kind: el.querySelector('#ntKind').value.trim(),
        parent: +el.querySelector('#ntParent').value || 0,
        port: el.querySelector('#ntPort').value.trim(),
        ip: el.querySelector('#ntIp').value.trim(),
      });
      if (!r.ok) return toast(r.error || '存不上');
      ['ntName', 'ntKind', 'ntPort', 'ntIp'].forEach((i) => { el.querySelector('#' + i).value = ''; });
      this.load();
    };
    el.querySelector('#ntRows').addEventListener('click', async (e) => {
      const x = e.target.closest('.x');
      if (!x) return;
      await post('/api/netmap/del', { id: +x.dataset.id });
      this.load();
    });

    // 101
    el.querySelector('#wsAdd').onclick = async () => {
      const name = el.querySelector('#wsName').value.trim();
      if (!name) return toast('物品名还没填');
      const r = await post('/api/wishes/save', {
        name, price: el.querySelector('#wsPrice').value || 0,
        shop: el.querySelector('#wsShop').value.trim(),
        url: el.querySelector('#wsUrl').value.trim(),
        priority: +el.querySelector('#wsPri').value,
        status: el.querySelector('#wsStatus').value,
      });
      if (!r.ok) return toast(r.error || '加不上');
      ['wsName', 'wsPrice', 'wsShop', 'wsUrl'].forEach((i) => { el.querySelector('#' + i).value = ''; });
      this.load();
    };
    el.querySelector('#wsRows').addEventListener('click', async (e) => {
      const row = e.target.closest('.lrow');
      if (!row) return;
      const id = +row.dataset.id;
      if (e.target.closest('.x')) {
        await post('/api/wishes/del', { id });
        return this.load();
      }
      const b = e.target.closest('[data-act]');
      if (!b) return;
      if (b.dataset.act === 'buy') {
        const r = await post('/api/wishes/buy', { id });
        const ov = (r.over || []);
        toast(ov.length ? '已购并记账，注意超支：' + ov.map((o) => o.cat).join('、') : '已购并记了一笔支出');
        this.load();
        return;
      }
      const st = b.dataset.act;                  // 想要 / 比价中 / 已购 / 不买了
      await post('/api/wishes/save', {
        id, name: row.dataset.name, price: +row.dataset.price,
        shop: row.dataset.shop, url: row.dataset.url,
        priority: +row.dataset.pri, status: st, note: row.dataset.note,
      });
      this.load();
    });

    // 104
    el.querySelector('#wtDay').value = day();
    el.querySelector('#wtAdd').onclick = async () => {
      const kg = parseFloat(el.querySelector('#wtKg').value);
      if (!kg) return toast('体重还没填');
      const r = await post('/api/weights/add', {
        day: el.querySelector('#wtDay').value || day(), kg,
        note: el.querySelector('#wtNote').value.trim(),
      });
      if (!r.ok) return toast(r.error || '记不上');
      toast(r.replaced ? '这天已有记录，已覆盖' : '记上了');
      el.querySelector('#wtKg').value = '';
      el.querySelector('#wtNote').value = '';
      this.load();
    };
    el.querySelector('#wtRows').addEventListener('click', async (e) => {
      const x = e.target.closest('.x');
      if (!x) return;
      await post('/api/weights/del', { id: +x.dataset.id });
      this.load();
    });

    // 老数据搬家（只跑一次，跑过就跳过）
    post('/api/life/migrate', {}).then((r) => {
      if (r && !r.skipped && r.n) toast(`已把旧的 ${r.n} 条清单数据搬到新表`);
    }).catch(() => {});
    this.load();
  },

  // ---------- 载入 ----------

  async load() {
    if (!this.el) return;
    if (this.tab === 'money') return this.loadMoney();
    if (this.tab === 'board') return this.loadBoard();
    if (this.tab === 'dev') return this.loadDev();
    if (this.tab === 'net') return this.loadNet();
    if (this.tab === 'buy') return this.loadBuy();
    if (this.tab === 'weight') return this.loadWeight();
  },

  async loadMoney() {
    const d = await api('/api/ledger?month=' + encodeURIComponent(this.month));
    const s = d.summary || {};
    this.cats = s.cats || [];
    const dl = this.el.querySelector('#lgCatList');
    if (dl && !dl.dataset.done) {
      dl.innerHTML = this.cats.map((c) => `<option value="${esc(c)}"></option>`).join('');
      dl.dataset.done = '1';
    }
    this.el.querySelector('#lgSum').innerHTML = `
      <div class="ds"><div class="dn">${esc(s.month || this.month)} 收入</div><div class="dv inc">${money(s.income)}</div></div>
      <div class="ds"><div class="dn">支出</div><div class="dv out">${money(s.expense)}</div></div>
      <div class="ds"><div class="dn">结余</div><div class="dv ${(s.net || 0) >= 0 ? 'inc' : 'out'}">${money(s.net)}</div></div>
      <div class="ds"><div class="dn">笔数</div><div class="dv">${s.n || 0}</div></div>`;

    const cats = s.by_cat || [];
    const mx = Math.max(1, ...cats.map((c) => c.used));
    this.el.querySelector('#lgCats').innerHTML = cats.length
      ? cats.map((c) => `<div class="dash-bar"><span class="dl">${esc(c.cat)}</span>
          <span class="dt"><span class="df b-bud" style="width:${Math.round((c.used / mx) * 100)}%"></span></span>
          <span class="dv">${money(c.used)}</span></div>`).join('')
      : '<div class="note">这个月还没有支出</div>';

    // 96：阈值 + 超标
    const b = await api('/api/budget?month=' + encodeURIComponent(this.month));
    const chk = (b && b.check) || {};
    const over = chk.over || [];
    this.el.querySelector('#lgOver').innerHTML = over.length
      ? over.map((o) => `<div class="dash-bar"><span class="dl" style="color:var(--err)">⚠ ${esc(o.cat)}</span>
          <span class="dt"><span class="df" style="width:${Math.min(100, o.pct)}%;background:var(--err)"></span></span>
          <span class="dv out">${money(o.used)}/${money(o.limit)}</span></div>`).join('')
      : '<div class="note">' + (chk.limit_n ? '这个月没有超支，稳' : '还没设阈值，下面填一个') + '</div>';
    const lim = (b && b.limits) || {};
    const catList = [...new Set([...this.cats, ...Object.keys(lim), ...(chk.rows || []).map((r) => r.cat)])];
    this.el.querySelector('#lgLimits').innerHTML = catList.map((c) =>
      `<div class="lg-lim"><span class="lg-lim-n">${esc(c)}</span>
        <input type="number" data-cat="${esc(c)}" placeholder="不限" value="${lim[c] || ''}"></div>`).join('')
      || '<div class="note">先记几笔支出，这里会自动列出分类</div>';

    const rows = d.rows || [];
    this.el.querySelector('#lgRows').innerHTML = rows.length
      ? rows.map((r) => `<div class="lrow">
          <div style="flex:0 0 92px" class="note">${esc(r.day || '')}</div>
          <div style="flex:0 0 42px" class="${r.kind === '收入' ? 'inc' : 'out'}">${esc(r.kind || '')}</div>
          <div style="flex:0 0 84px;text-align:right" class="${r.kind === '收入' ? 'inc' : 'out'}">${money(r.amount)}</div>
          <div style="flex:0 0 76px"><span class="tag">${esc(r.category || '其它')}</span></div>
          <div style="flex:1;min-width:0;color:var(--ink-2)">${esc(r.note || '')}</div>
          <button class="x" data-id="${r.id}">×</button>
        </div>`).join('')
      : '<div class="note">这个月还没有流水</div>';
  },

  async loadBoard() {
    const d = await api('/api/ledger/months?limit=12');
    const ms = (d.months || []).slice().reverse();     // 时间正序，左旧右新
    const mx = Math.max(1, ...ms.map((m) => Math.max(m.income, m.expense)));
    const box = this.el.querySelector('#bdBox');
    if (!ms.length) { box.innerHTML = '<div class="note">还没有任何收支记录</div>'; return; }
    box.innerHTML = `
      <div class="dash-stats" style="margin-bottom:12px">
        <div class="ds"><div class="dn">累计收入</div><div class="dv inc">${money(ms.reduce((s, m) => s + m.income, 0))}</div></div>
        <div class="ds"><div class="dn">累计支出</div><div class="dv out">${money(ms.reduce((s, m) => s + m.expense, 0))}</div></div>
        <div class="ds"><div class="dn">月均结余</div><div class="dv">${money(ms.reduce((s, m) => s + m.net, 0) / ms.length)}</div></div>
      </div>` + ms.map((m) => `
        <div class="bd-month">
          <div class="bd-m">${esc(m.month)}</div>
          <div style="flex:1">
            <div class="dash-bar"><span class="dl">收入</span>
              <span class="dt"><span class="df b-inc" style="width:${Math.round((m.income / mx) * 100)}%"></span></span>
              <span class="dv inc">${money(m.income)}</span></div>
            <div class="dash-bar"><span class="dl">支出</span>
              <span class="dt"><span class="df" style="width:${Math.round((m.expense / mx) * 100)}%;background:var(--err)"></span></span>
              <span class="dv out">${money(m.expense)}</span></div>
            <div class="dash-bar"><span class="dl">净结余</span>
              <span class="dt"><span class="df b-bud" style="width:${Math.round((Math.abs(m.net) / mx) * 100)}%"></span></span>
              <span class="dv ${m.net >= 0 ? 'inc' : 'out'}">${money(m.net)}</span></div>
          </div>
          <div class="note bd-n">${m.n} 笔</div>
        </div>`).join('');
  },

  async loadDev() {
    const d = await api('/api/devices');
    const rows = d.rows || [];
    const cb = (d.charge) || {};
    this.el.querySelector('#dvChargeBoard').innerHTML = `
      <div class="note" style="margin-bottom:6px">充电中 ${cb.n_charging || 0} 台 ｜ 待充 ${cb.n_pending || 0} 台</div>
      ${(cb.zones || []).length ? (cb.zones || []).map((z) => `
        <div class="czone">
          <div class="czone-t">${esc(z.zone)}</div>
          <div class="czone-i">${z.items.map((i) => `<span class="tag" style="${i.charge === '充电中' ? 'background:var(--warn-soft);color:var(--warn)' : i.charge === '已满' ? 'background:var(--accent-soft);color:var(--ok)' : ''}">${esc(i.name)}${i.charge ? ' · ' + esc(i.charge) : ''}</span>`).join('')}</div>
        </div>`).join('') : '<div class="note">还没有登记位置或充电状态的设备</div>'}`;

    this.el.querySelector('#dvRows').innerHTML = rows.length
      ? rows.map((r) => {
        const wl = r.warranty_left;
        const wtxt = wl == null ? '—'
          : (wl < 0 ? `<span class="out">过保 ${-wl} 天</span>`
            : wl < 90 ? `<span style="color:var(--warn)">剩 ${wl} 天</span>` : `剩 ${wl} 天`);
        return `<div class="lrow" data-id="${r.id}" data-charge="${esc(r.charge || '')}">
          <div style="flex:0 0 150px"><b style="font-weight:500">${esc(r.name || '')}</b></div>
          <div style="flex:0 0 110px" class="note">${esc(r.kind || '')}</div>
          <div style="flex:0 0 90px"><span class="tag">${esc(r.zone || '未分区')}</span></div>
          <div style="flex:0 0 100px" class="note">${esc(r.bought || '未记购入')}</div>
          <div style="flex:0 0 110px;font-size:12.5px">${wtxt}</div>
          <div style="flex:0 0 84px;text-align:right" class="note">${r.price ? money(r.price) : ''}</div>
          <button data-charge="1" class="btn slim" style="flex:0 0 auto">${r.charge || '不登记充电'}</button>
          <button class="x" data-id="${r.id}">×</button>
        </div>`;
      }).join('')
      : '<div class="note">还没有设备，上面加一个</div>';
  },

  async loadNet() {
    const d = await api('/api/netmap');
    const rows = d.rows || [];
    const sel = this.el.querySelector('#ntParent');
    sel.innerHTML = '<option value="0">— 上游：无 —</option>' +
      rows.map((r) => `<option value="${r.id}">${'　'.repeat(r.depth || 0)}${esc(r.name || '')}</option>`).join('');
    this.el.querySelector('#ntRows').className = '';
    this.el.querySelector('#ntRows').innerHTML = rows.length
      ? rows.map((r) => `<div class="lrow" style="padding-left:${(r.depth || 0) * 18}px">
          <div style="flex:0 0 210px">${(r.depth || 0) ? '└ ' : ''}<b style="font-weight:500">${esc(r.name || '')}</b></div>
          <div style="flex:0 0 100px"><span class="tag">${esc(r.kind || '—')}</span></div>
          <div style="flex:0 0 120px" class="note">${esc(r.ip || '')}</div>
          <div style="flex:0 0 100px" class="note">${r.port ? '端口 ' + esc(r.port) : ''}</div>
          <div style="flex:1;min-width:0" class="note">${esc(r.note || '')}</div>
          <button class="x" data-id="${r.id}">×</button>
        </div>`).join('')
      : '<div class="note">还没记录设备，先加光猫/路由</div>';
  },

  async loadBuy() {
    const d = await api('/api/wishes');
    const rows = d.rows || [];
    const states = d.states || ['想要', '比价中', '已购', '不买了'];
    const sel = this.el.querySelector('#wsStatus');
    if (!sel.dataset.done) {
      sel.innerHTML = states.map((s) => `<option>${s}</option>`).join('');
      sel.dataset.done = '1';
      this.el.querySelector('#wsFilter').innerHTML =
        '<button class="chip on" data-st="">全部</button>' +
        states.map((s) => `<button class="chip" data-st="${s}">${s}</button>`).join('');
      this.el.querySelector('#wsFilter').addEventListener('click', (e) => {
        const b = e.target.closest('[data-st]');
        if (!b) return;
        this.wsFilter = b.dataset.st;
        this.el.querySelectorAll('#wsFilter .chip').forEach((x) => x.classList.toggle('on', x === b));
        this.loadBuy();
      });
    }
    this.el.querySelector('#wsSum').innerHTML = `
      <div class="ds"><div class="dn">想买总额</div><div class="dv">${money(d.want_total)}</div></div>
      <div class="ds"><div class="dn">已购花掉</div><div class="dv out">${money(d.bought_total)}</div></div>
      <div class="ds"><div class="dn">条目</div><div class="dv">${rows.length}</div></div>`;

    const show = this.wsFilter ? rows.filter((r) => r.status === this.wsFilter) : rows;
    const pri = { 1: '高', 2: '中', 3: '低' };
    const cls = { 想要: '', 比价中: 'color:var(--warn)', 已购: 'color:var(--ok)', 不买了: 'color:var(--ink-3)' };
    this.el.querySelector('#wsRows').innerHTML = show.length
      ? show.map((r) => `<div class="lrow" data-id="${r.id}" data-name="${esc(r.name || '')}"
            data-price="${r.price || 0}" data-shop="${esc(r.shop || '')}" data-url="${esc(r.url || '')}"
            data-pri="${r.priority || 2}" data-note="${esc(r.note || '')}">
          <div style="flex:0 0 170px">
            ${r.url ? `<a href="${esc(r.url)}" target="_blank" class="kb-link">${esc(r.name || '')}</a>` : `<b style="font-weight:500">${esc(r.name || '')}</b>`}
          </div>
          <div style="flex:0 0 84px;text-align:right">${money(r.price)}</div>
          <div style="flex:0 0 96px" class="note">${esc(r.shop || '')}</div>
          <div style="flex:0 0 60px"><span class="tag">${pri[r.priority] || '中'}</span></div>
          <div style="flex:0 0 74px;font-size:12.5px">
            <span style="${cls[r.status] || ''}">${esc(r.status || '')}</span></div>
          <div style="flex:1;min-width:0" class="note">${r.status === '已购' && r.bought_at ? '购于 ' + esc(r.bought_at) : esc(r.note || '')}</div>
          ${r.status === '已购' ? '' : '<button class="btn slim" data-act="buy">已购</button>'}
          ${r.status !== '比价中' && r.status !== '已购' ? '<button class="btn slim" data-act="比价中">比价</button>' : ''}
          <button class="x" data-id="${r.id}">×</button>
        </div>`).join('')
      : '<div class="note">清单是空的</div>';
  },

  async loadWeight() {
    const d = await api('/api/weights');
    const st = d.stats || {};
    const rows = d.rows || [];
    this.el.querySelector('#wtStats').innerHTML = st.n
      ? `<div class="ds"><div class="dn">最新</div><div class="dv">${st.last.kg} kg</div></div>
         <div class="ds"><div class="dn">较首条</div><div class="dv ${st.delta <= 0 ? 'inc' : 'out'}">${st.delta > 0 ? '+' : ''}${st.delta} kg</div></div>
         <div class="ds"><div class="dn">区间</div><div class="dv">${st.min}~${st.max}</div></div>
         <div class="ds"><div class="dn">近 7 次均值</div><div class="dv">${st.avg7} kg</div></div>
         <div class="ds"><div class="dn">记录</div><div class="dv">${st.n} 条</div></div>`
      : '<div class="ds"><div class="dn">还没有记录</div><div class="dv">—</div></div>';

    // 迷你折线
    const svg = this.el.querySelector('#wtSvg');
    const series = st.series || [];
    if (series.length < 2) {
      svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="currentColor" font-size="12" opacity=".5">至少记两次才能画线</text>';
    } else {
      const W = 600, H = 180, P = 24;
      const vs = series.map((r) => r.kg);
      const lo = Math.min(...vs), hi = Math.max(...vs);
      const span = (hi - lo) || 1;
      const X = (i) => P + (i * (W - 2 * P)) / (series.length - 1);
      const Y = (v) => H - P - ((v - lo) / span) * (H - 2 * P);
      const pts = series.map((r, i) => `${X(i).toFixed(1)},${Y(r.kg).toFixed(1)}`).join(' ');
      const dots = series.map((r, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(r.kg).toFixed(1)}" r="2.6" fill="var(--accent)"/>`).join('');
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svg.innerHTML = `
        <polyline points="${pts}" fill="none" stroke="var(--accent-2)" stroke-width="2"/>
        ${dots}
        <text x="${P}" y="14" font-size="11" fill="currentColor" opacity=".65">${hi} kg</text>
        <text x="${P}" y="${H - 6}" font-size="11" fill="currentColor" opacity=".65">${lo} kg</text>`;
    }

    this.el.querySelector('#wtRows').innerHTML = rows.length
      ? rows.map((r) => `<div class="lrow">
          <div style="flex:0 0 110px" class="note">${esc(r.day || '')}</div>
          <div style="flex:0 0 80px"><b style="font-weight:500">${r.kg} kg</b></div>
          <div style="flex:1;min-width:0" class="note">${esc(r.note || '')}</div>
          <button class="x" data-id="${r.id}">×</button>
        </div>`).join('')
      : '<div class="note">还没有体重记录</div>';
  },

  refresh() { this.load(); },

  // go('life', {tab:'buy'}) 这种直达用法
  onShow(arg) {
    if (arg && arg.tab && arg.tab !== this.tab) {
      this.tab = arg.tab;
      const panes = { money: 'Money', board: 'Board', dev: 'Dev', net: 'Net', buy: 'Buy', weight: 'Weight' };
      this.el.querySelectorAll('[data-t]').forEach((x) => x.classList.toggle('on', x.dataset.t === this.tab));
      for (const k in panes) {
        this.el.querySelector('#pane' + panes[k]).style.display = this.tab === k ? '' : 'none';
      }
    }
    this.load();
  },

  commands() {
    return [
      { title: '打开生活（记账/设备/采购）', hint: '生活', run: () => window.WB.go('life') },
      { title: '记一笔支出…', hint: '生活', run: () => window.WB.go('life', { tab: 'money' }) },
    ];
  },
};
