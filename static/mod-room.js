/* 房间布局：20 平米长方形房间的交互式平面图。
 * SVG 直角坐标系里 1 单位 = 1 厘米，地板放在 translate(M,M) 的 <g> 里，
 * 拖拽用 floor.getScreenCTM() 把鼠标坐标换算回厘米，跟缩放无关。
 * 布局存进 room_layouts 表（data 是一段 JSON），支持多方案保存/载入。
 */

const { api, post, esc, toast } = window.WB;

const M = 40;        // 画布外边距（厘米）
const GRID = 10;     // 吸附网格（厘米）
const CATALOG = [
  { type: '床(单人)', w: 100, h: 200 },
  { type: '床(双人)', w: 150, h: 200 },
  { type: '书桌', w: 120, h: 60 },
  { type: '台式机主机', w: 22, h: 45 },
  { type: '显示器', w: 60, h: 18 },
  { type: '椅子', w: 45, h: 45 },
  { type: '衣柜', w: 100, h: 55 },
  { type: '书架', w: 80, h: 30 },
  { type: '路由器', w: 18, h: 14 },
  { type: '充电区', w: 60, h: 40 },
  { type: '沙发', w: 180, h: 80 },
  { type: '茶几', w: 100, h: 50 },
  { type: '植物', w: 30, h: 30 },
];
let _uid = 1;
const uid = () => 'i' + (_uid++) + Date.now().toString(36);

function snap(v) { return Math.round(v / GRID) * GRID; }
function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

export default {
  id: 'room',
  name: '房间',
  el: null,
  data: { w: 500, h: 400, items: [] },
  rid: 0,
  sel: null,
  drag: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="room-wrap">
        <div class="room-main">
          <div class="room-bar">
            <input id="roomName" placeholder="方案名，如 方案A" style="max-width:160px">
            <button class="btn primary" id="roomSave">保存方案</button>
            <button class="btn" id="roomNew">新建</button>
            <select id="roomPick" style="max-width:150px"><option value="">— 载入方案 —</option></select>
            <button class="btn" id="roomDel">删除方案</button>
            <span class="note" id="roomState"></span>
          </div>
          <div class="room-bar">
            <span class="note">房间尺寸</span>
            <input id="roomW" type="number" min="200" max="900" style="width:74px"> × <input id="roomH" type="number" min="200" max="900" style="width:74px"> 厘米
            <button class="btn" id="roomApply">应用尺寸</button>
            <label class="note" style="margin-left:8px"><input type="checkbox" id="roomSnap" checked> 吸附网格</label>
          </div>
          <svg id="roomSvg" class="room-svg" xmlns="http://www.w3.org/2000/svg"></svg>
        </div>
        <div class="room-side">
          <h3>添加家具</h3>
          <div id="roomCat" class="room-cat"></div>
          <h3 style="margin-top:14px">选中物品</h3>
          <div id="roomSel" class="note">点图里的方块选中</div>
          <h3 style="margin-top:14px">占用</h3>
          <div id="roomStat"></div>
          <h3 style="margin-top:14px">物品清单</h3>
          <div id="roomItems" class="listbox"></div>
        </div>
      </div>`;

    // 目录按钮
    el.querySelector('#roomCat').innerHTML = CATALOG.map((c) =>
      `<button class="btn slim" data-type="${esc(c.type)}">+ ${esc(c.type)}</button>`
    ).join('');
    el.querySelector('#roomCat').addEventListener('click', (e) => {
      const b = e.target.closest('[data-type]');
      if (b) this.addItem(b.dataset.type);
    });

    el.querySelector('#roomSave').onclick = () => this.save();
    el.querySelector('#roomNew').onclick = () => this.newPlan();
    el.querySelector('#roomDel').onclick = () => this.delPlan();
    el.querySelector('#roomApply').onclick = () => this.applyDims();
    el.querySelector('#roomPick').onchange = (e) => {
      if (e.target.value) this.load(+e.target.value);
    };

    // 拖拽用：在 svg 上监听 pointerdown，命中 item 才进入拖拽
    const svg = el.querySelector('#roomSvg');
    this.svg = svg;
    svg.addEventListener('pointerdown', (e) => this.onDown(e));
    window.addEventListener('pointermove', (e) => this.onMove(e));
    window.addEventListener('pointerup', () => this.onUp());

    this.refreshList();
    this.render();
  },

  addItem(type) {
    const c = CATALOG.find((x) => x.type === type) || { w: 60, h: 60 };
    const it = {
      id: uid(), type,
      x: Math.round((this.data.w - c.w) / 2 / GRID) * GRID,
      y: Math.round((this.data.h - c.h) / 2 / GRID) * GRID,
      w: c.w, h: c.h, rot: 0,
    };
    this.data.items.push(it);
    this.sel = it.id;
    this.render();
    this.scheduleSave();
  },

  onDown(e) {
    const g = e.target.closest('.ritem');
    if (!g) { this.sel = null; this.render(); return; }
    const it = this.data.items.find((x) => x.id === g.dataset.id);
    if (!it) return;
    this.sel = it.id;
    const local = this.toLocal(e);
    this.drag = { id: it.id, offX: local.x - it.x, offY: local.y - it.y, moved: false };
    g.classList.add('dragging');
    e.preventDefault();
    this.renderSel();
  },

  onMove(e) {
    if (!this.drag) return;
    const it = this.data.items.find((x) => x.id === this.drag.id);
    if (!it) return;
    const local = this.toLocal(e);
    let nx = local.x - this.drag.offX;
    let ny = local.y - this.drag.offY;
    if (this.el.querySelector('#roomSnap').checked) { nx = snap(nx); ny = snap(ny); }
    it.x = clamp(nx, 0, this.data.w - it.w);
    it.y = clamp(ny, 0, this.data.h - it.h);
    this.drag.moved = true;
    // 直接改元素位置，避免整图重绘丢拖拽
    const g = this.svg.querySelector(`.ritem[data-id="${it.id}"]`);
    if (g) g.setAttribute('transform', `translate(${it.x},${it.y})`);
  },

  onUp() {
    if (!this.drag) return;
    const moved = this.drag.moved;
    this.drag = null;
    if (moved) { this.render(); this.scheduleSave(); }
  },

  toLocal(e) {
    const ctm = this.floor.getScreenCTM().inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm);
    return { x: p.x, y: p.y };
  },

  applyDims() {
    const w = clamp(+this.el.querySelector('#roomW').value || 500, 200, 900);
    const h = clamp(+this.el.querySelector('#roomH').value || 400, 200, 900);
    this.data.w = w; this.data.h = h;
    this.data.items.forEach((it) => {
      it.x = clamp(snap(it.x), 0, w - it.w);
      it.y = clamp(snap(it.y), 0, h - it.h);
    });
    this.render();
    this.scheduleSave();
  },

  render() {
    const { w, h, items } = this.data;
    this.el.querySelector('#roomW').value = w;
    this.el.querySelector('#roomH').value = h;
    const svg = this.svg;
    svg.setAttribute('viewBox', `0 0 ${w + 2 * M} ${h + 2 * M}`);
    // 网格
    let grid = '';
    for (let x = 0; x <= w; x += GRID) grid += `<line x1="${x}" y1="0" x2="${x}" y2="${h}"/>`;
    for (let y = 0; y <= h; y += GRID) grid += `<line x1="0" y1="${y}" x2="${w}" y2="${y}"/>`;
    const itemsSvg = items.map((it) => this.itemSvg(it)).join('');
    svg.innerHTML = `
      <g class="floor" transform="translate(${M},${M})">
        <rect class="room-bg" x="0" y="0" width="${w}" height="${h}"/>
        <g class="grid">${grid}</g>
        ${itemsSvg}
        <rect class="room-wall" x="0" y="0" width="${w}" height="${h}"/>
      </g>`;
    this.floor = svg.querySelector('.floor');
    this.renderSel();
    this.renderStat();
    this.renderItems();
  },

  itemSvg(it) {
    const sel = it.id === this.sel ? ' sel' : '';
    const fs = it.h >= 40 ? 13 : 11;
    return `<g class="ritem${sel}" data-id="${it.id}" transform="translate(${it.x},${it.y})">
      <rect width="${it.w}" height="${it.h}" rx="3"/>
      <text x="${it.w / 2}" y="${it.h / 2}" font-size="${fs}" text-anchor="middle" dominant-baseline="middle">${esc(it.type)}</text>
    </g>`;
  },

  renderSel() {
    const box = this.el.querySelector('#roomSel');
    const it = this.data.items.find((x) => x.id === this.sel);
    if (!it) { box.className = 'note'; box.textContent = '点图里的方块选中'; return; }
    box.className = '';
    box.innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
        <b>${esc(it.type)}</b>
        <button class="btn slim" id="selRot">旋转 90°</button>
        <button class="btn slim" id="selDel">删除</button>
      </div>
      <div class="note">位置 ${it.x}×${it.y} cm ｜ 尺寸 ${it.w}×${it.h} cm</div>`;
    box.querySelector('#selRot').onclick = () => {
      const nw = it.h, nh = it.w;
      it.x = clamp(it.x, 0, this.data.w - nw);
      it.y = clamp(it.y, 0, this.data.h - nh);
      it.w = nw; it.h = nh; it.rot = (it.rot + 90) % 180;
      this.render(); this.scheduleSave();
    };
    box.querySelector('#selDel').onclick = () => {
      this.data.items = this.data.items.filter((x) => x.id !== it.id);
      this.sel = null; this.render(); this.scheduleSave();
    };
  },

  renderStat() {
    const used = this.data.items.reduce((s, it) => s + it.w * it.h, 0);
    const total = this.data.w * this.data.h;
    const pct = total ? (used / total * 100) : 0;
    this.el.querySelector('#roomStat').innerHTML = `
      <div class="dash-bar"><span class="dl">总面积</span><span class="dt"></span>
        <span class="dv">${(total / 10000).toFixed(2)} ㎡</span></div>
      <div class="dash-bar"><span class="dl">家具占用</span>
        <span class="dt"><span class="df b-inc" style="width:${pct.toFixed(1)}%"></span></span>
        <span class="dv">${pct.toFixed(1)}%</span></div>
      <div class="note">剩余可用 ${((total - used) / 10000).toFixed(2)} ㎡</div>`;
  },

  renderItems() {
    const box = this.el.querySelector('#roomItems');
    if (!this.data.items.length) { box.innerHTML = '<div class="note">还没有家具</div>'; return; }
    box.innerHTML = this.data.items.map((it) =>
      `<div class="lrow" data-id="${it.id}"><div style="flex:1">${esc(it.type)}</div>
       <div class="note">${it.w}×${it.h}</div></div>`
    ).join('');
    box.querySelectorAll('.lrow').forEach((r) => {
      r.onclick = () => { this.sel = r.dataset.id; this.render(); };
    });
  },

  async refreshList() {
    try {
      const d = await api('/api/room/list');
      const sel = this.el.querySelector('#roomPick');
      if (!sel) return;
      sel.innerHTML = '<option value="">— 载入方案 —</option>' +
        (d || []).map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join('');
    } catch (e) { /* ignore */ }
  },

  async save() {
    const name = (this.el.querySelector('#roomName').value || '未命名方案').trim();
    const r = await post('/api/room/save', { name, data: this.data, id: this.rid });
    if (r && r.id) this.rid = r.id;
    this.el.querySelector('#roomState').textContent = '已保存 ' + new Date().toLocaleTimeString();
    toast('方案已保存');
    this.refreshList();
  },

  async load(id) {
    const r = await post('/api/room/get', { id });
    if (!r || !r.id) return;
    this.rid = r.id;
    this.data = r.data && r.data.items ? r.data : { w: 500, h: 400, items: [] };
    if (!this.data.items) this.data.items = [];
    this.sel = null;
    this.el.querySelector('#roomName').value = r.name || '';
    this.render();
    toast('已载入：' + (r.name || ''));
  },

  newPlan() {
    this.rid = 0;
    this.data = { w: 500, h: 400, items: [] };
    this.sel = null;
    this.el.querySelector('#roomName').value = '';
    this.render();
  },

  async delPlan() {
    if (!this.rid) { toast('当前是未保存的新方案'); return; }
    await post('/api/room/del', { id: this.rid });
    this.rid = 0; this.data = { w: 500, h: 400, items: [] }; this.sel = null;
    this.el.querySelector('#roomName').value = '';
    this.render(); this.refreshList();
    toast('方案已删除');
  },

  scheduleSave() {
    clearTimeout(this._t);
    this._t = setTimeout(() => { if (this.rid) this.save(); }, 1500);
    this.el.querySelector('#roomState').textContent = '编辑中…';
  },

  refresh() { this.refreshList(); },
  onShow() { this.refreshList(); },
};
