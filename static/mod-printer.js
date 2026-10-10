/* 打印机：普通打印机 + 3D 打印机，配对、送印、OpenClaw 派活。
   后端 printers.py + server.py 的 /api/print/*。

   几个刻意的选择：
   - 「导入文件打印」不从 <input type=file> 上传：浏览器拿不到本机真实路径，
     而工作台有全盘文件索引，直接搜着选更顺手。上传只作为手机端的补充。
   - 送印主通道是**系统打印对话框**（先把目标打印机切成默认，再唤起 print 动词）。
     实测这台 Epson：PrintTo 动词没 handler、winspool 直写驱动崩、IPPS 回
     operation-not-supported，只有走系统 UI 才稳——驱动该渲染的让它自己渲染。
   - OpenClaw 派活只负责「产出文件」，产物列出来由人决定印哪张，不自动印。
   - 所有打印接口都**不在** LOCAL_ONLY_PREFIX 里，手机连局域网也能打印。 */

const { api, post, esc, toast, fmtSize } = window.WB;

const KIND_3D = '3D 打印机';
const PRINTABLE = /\.(pdf|png|jpe?g|gif|bmp|webp|tiff?|txt|md|csv|log|json|html?|docx?|xlsx?|pptx?)$/i;

const PROTO_HINT = {
  octoprint: 'OctoPrint（API Key 在 Settings → API 里拿）',
  klipper: 'Klipper / Moonraker（一般不用密钥）',
  prusalink: 'PrusaLink（Bearer 令牌）',
  ipp: 'IPP 直连（网络打印机，需 IP）',
  spool: 'Windows 打印队列（系统已装好的驱动）',
};

export default {
  id: 'printer',
  name: '打印机',
  el: null,
  devices: [],
  jobs: [],
  produced: [],
  env: {},
  picked: null,          // {path, name, size}
  prepared: null,        // {pdf, name, size}
  searchRows: [],
  dev3d: null,
  status3d: null,
  statusTimer: null,
  busy: false,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">

      <div class="panel">
        <h3>设备 <span class="note" id="pnEnv"></span></h3>
        <div id="devList"></div>
        <div class="field-row">
          <button class="btn" id="btnScan">扫描局域网里的 3D 打印机</button>
          <button class="btn" id="btnPair">手动配对…</button>
          <button class="btn" id="btnRefreshDev">刷新</button>
        </div>
        <div id="scanOut"></div>
      </div>

      <div class="panel">
        <h3>打印一个文件</h3>
        <div class="note">从全盘索引里找，或直接在本机选一个文件。手机上可以用「文件」App 上传到收件箱再过来。</div>
        <div class="field-row">
          <input id="fq" placeholder="搜文件名，比如 报告 / invoice / 课程表" style="flex:1">
          <button class="btn" id="btnFSearch">搜</button>
          <button class="btn" id="btnPickLocal">本机选文件</button>
        </div>
        <div id="pickBox" class="note"></div>
        <div id="fsOut"></div>
        <div class="field-row" id="sendRow">
          <select id="printerSel"></select>
          <button class="btn" id="btnSend" disabled>打印</button>
          <span class="note" id="sendHint"></span>
        </div>
      </div>

      <div class="panel">
        <h3>让 OpenClaw 去做</h3>
        <div class="note">它把结果写成文件放进产物区 —— 你先看内容，再决定印哪张。</div>
        <div class="field-row">
          <input id="agentTask" placeholder="比如：把今天的待办整理成一张能贴墙上的清单" style="flex:1">
          <button class="btn" id="btnAgent">派活</button>
        </div>
        <div id="agentOut"></div>
        <div id="prodList"></div>
      </div>

      <div class="panel" id="p3d" style="display:none">
        <h3>3D 打印 <span class="note" id="p3dName"></span></h3>
        <div id="s3d"></div>
        <div class="field-row">
          <input type="file" id="gcode" accept=".gcode,.gco,.g" hidden>
          <button class="btn" id="btnGcode">选 G-code 开始打印</button>
          <button class="btn" id="btnPause">暂停</button>
          <button class="btn" id="btnResume">继续</button>
          <button class="btn" id="btnStop">取消</button>
        </div>
      </div>

      <div class="panel">
        <h3>任务记录 <button class="btn" id="btnClearJobs">清空</button></h3>
        <div id="jobList"></div>
      </div>

    </div>`;

    const q = (s) => el.querySelector(s);
    q('#btnRefreshDev').onclick = () => this.loadDev();
    q('#btnScan').onclick = () => this.scan();
    q('#btnPair').onclick = () => this.pair();
    q('#btnFSearch').onclick = () => this.search();
    q('#fq').onkeydown = (e) => { if (e.key === 'Enter') this.search(); };
    q('#btnPickLocal').onclick = () => this.pickLocal();
    q('#btnSend').onclick = () => this.send();
    q('#btnAgent').onclick = () => this.agent();
    q('#btnClearJobs').onclick = async () => {
      await post('/api/print/jobs/clear', {});
      this.jobs = [];
      this.renderJobs();
    };
    q('#btnGcode').onclick = () => q('#gcode').click();
    q('#gcode').onchange = (e) => this.sendGcode(e.target.files[0]);
    q('#btnPause').onclick = () => this.ctrl3d('pause');
    q('#btnResume').onclick = () => this.ctrl3d('resume');
    q('#btnStop').onclick = () => this.ctrl3d('cancel');

    this.loadEnv();
    this.loadDev();
    this.loadJobs();
    this.loadProduced();
  },

  onShow() {
    this.loadDev();
    this.loadProduced();
  },

  async loadEnv() {
    try {
      const d = await api('/api/print/env');
      this.env = d;
      const bits = [];
      bits.push(d.is_win ? 'Windows' : '非 Windows');
      if (d.browser) bits.push('转 PDF 用 ' + d.browser.split('\\').pop());
      else bits.push('⚠️ 没找到 Chrome/Edge，文本类文件转不了 PDF');
      if (d.default_printer) bits.push('默认打印机：' + d.default_printer);
      this.el.querySelector('#pnEnv').textContent = bits.join(' · ');
    } catch (e) { /* 忽略 */ }
  },

  async loadDev() {
    try {
      const d = await api('/api/print/devices');
      this.devices = d.devices || [];
      this.renderDev();
    } catch (e) {
      toast('读设备失败：' + e.message);
    }
  },

  fillSel() {
    const sel = this.el.querySelector('#printerSel');
    if (!sel) return;
    const list = this.devices.filter((d) => d.kind !== KIND_3D);
    const keep = sel.value;
    sel.innerHTML = list.length
      ? list.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}${d.default ? '（默认）' : ''}</option>`).join('')
      : '<option value="">还没有普通打印机</option>';
    if (keep && list.some((d) => d.id === keep)) sel.value = keep;
    else if (list.length) {
      const def = list.find((d) => d.default);
      if (def) sel.value = def.id;
    }
    sel.onchange = () => this.sendHint();
    this.sendHint();
  },

  renderDev() {
    this.fillSel();
    const box = this.el.querySelector('#devList');
    if (!this.devices.length) {
      box.innerHTML = '<div class="note">没发现任何打印机。先在 Windows「设置 → 蓝牙和其他设备 → 打印机」里装好驱动。</div>';
      return;
    }
    box.innerHTML = this.devices.map((d) => {
      const is3d = d.kind === KIND_3D;
      const cap = [];
      if (d.default) cap.push('默认');
      if (is3d) cap.push(d.proto);
      else if (d.proto === 'spool') cap.push('系统队列');
      if (d.jobs) cap.push('队列 ' + d.jobs + ' 个作业');
      if (d.status) cap.push(d.status);
      return `<div class="tf-item pv-item" data-id="${esc(d.id)}">
        <div class="tf-n">${esc(d.name)} ${d.enabled === false ? '<span class="tag-pill">已停用</span>' : ''}</div>
        <div class="tf-sub">${esc(is3d ? (d.host + ':' + (d.port || 80)) : (d.driver || d.port_name || ''))}${cap.length ? ' · ' + esc(cap.join(' · ')) : ''}</div>
        <div class="tf-acts">
          ${is3d
            ? `<button class="btn" data-a="use3d" data-id="${esc(d.id)}">选中</button>
               <button class="btn" data-a="test" data-id="${esc(d.id)}">测试连接</button>
               ${d.builtin ? '' : `<button class="btn" data-a="del" data-id="${esc(d.id)}">删除</button>`}`
            : `<button class="btn" data-a="pick" data-id="${esc(d.id)}">用它打印</button>
               ${d.builtin ? '' : `<button class="btn" data-a="del" data-id="${esc(d.id)}">删除</button>`}`}
        </div>
      </div>`;
    }).join('');

    box.querySelectorAll('button[data-a]').forEach((b) => {
      b.onclick = async () => {
        const id = b.dataset.id;
        const d = this.devices.find((x) => x.id === id);
        if (b.dataset.a === 'del') {
          if (!confirm(`删除设备「${d.name}」？`)) return;
          await post('/api/print/del', { id });
          this.loadDev();
          return;
        }
        if (b.dataset.a === 'pick') {
          this.el.querySelector('#printerSel').value = id;
          this.sendHint();
          document.querySelector('.mod.on')?.scrollIntoView({ block: 'nearest' });
          toast('已选 ' + d.name + '，选个文件就能印');
          return;
        }
        if (b.dataset.a === 'use3d') {
          this.dev3d = d;
          this.el.querySelector('#p3d').style.display = '';
          this.el.querySelector('#p3dName').textContent = d.name + ' @ ' + d.host;
          this.poll3d();
          return;
        }
        b.disabled = true;
        b.textContent = '测试中…';
        try {
          const r = await post('/api/print/test', { id });
          if (r.ok) toast('连上了：' + (r.status_text || r.detail || 'OK'));
          else toast('连不上：' + (r.status_text || r.error || '未知'), 1);
        } catch (e) {
          toast('测试失败：' + e.message, 1);
        }
        b.disabled = false;
        b.textContent = '测试连接';
      };
    });
  },

  // ---------- 局域网扫描 3D ----------
  async scan() {
    const out = this.el.querySelector('#scanOut');
    const btn = this.el.querySelector('#btnScan');
    btn.disabled = true;
    btn.textContent = '扫描中…';
    out.innerHTML = '<div class="note">正在扫本机所在的网段（约 1 秒一档，会花十几秒）…</div>';
    try {
      const d = await post('/api/print/discover', { timeout: 1.2 });
      const found = (d.found || []).filter((x) => x.kind);
      const others = (d.found || []).filter((x) => !x.kind);
      let html = '';
      if (found.length) {
        html += '<div class="note">认得出是 3D 打印机的：</div>';
        html += found.map((f) => `<div class="tf-item">
          <div class="tf-n">${esc(f.name)}</div>
          <div class="tf-sub">${esc(f.kind)} · ${esc(f.detail || '')} · ${f.ip}:${f.ports.join(',')}</div>
          <div class="tf-acts"><button class="btn" data-add="${esc(JSON.stringify(f))}">配对它</button></div>
        </div>`).join('');
      }
      if (others.length) {
        html += '<div class="note">开着端口但不像 3D 打印机的（没认出来就是没认出来，不瞎猜）：</div>';
        html += others.map((f) => `<div class="tf-item"><div class="tf-n">${esc(f.ip)}</div><div class="tf-sub">端口 ${esc(f.ports.join(','))}</div></div>`).join('');
      }
      if (!d.found || !d.found.length) html = '<div class="note">这一段网里没扫到开端口的设备。3D 打印机一般是 7125（OctoPrint/Moonraker）或 80/8080。</div>';
      out.innerHTML = html + `<div class="note">扫了 ${d.dur}s</div>`;
      out.querySelectorAll('button[data-add]').forEach((b) => {
        b.onclick = async () => {
          const f = JSON.parse(b.dataset.add);
          await post('/api/print/add', {
            name: f.name || f.ip, kind: KIND_3D, proto: f.kind,
            host: f.ip, port: f.ports.includes(7125) ? 7125 : f.ports[0],
          });
          toast('已配对，记得填 API Key（OctoPrint 需要）');
          this.loadDev();
        };
      });
    } catch (e) {
      out.innerHTML = '<div class="note">扫描失败：' + esc(e.message) + '</div>';
    }
    btn.disabled = false;
    btn.textContent = '扫描局域网里的 3D 打印机';
  },

  async pair() {
    const name = prompt('设备名字（比如 Ender 3 / Prusa MK4）', '我的 3D 打印机');
    if (!name) return;
    const host = prompt('它的 IP 地址（不知道就先点上面「扫描」）', '192.168.0.50');
    if (!host) return;
    let proto = 'octoprint';
    for (const [i, k] of ['octoprint', 'klipper', 'prusalink'].entries()) {
      alert(`${i + 1}. ${PROTO_HINT[k]}`);
    }
    const pick = prompt('选协议：输入 1 / 2 / 3', '1');
    if (pick === '2') proto = 'klipper';
    else if (pick === '3') proto = 'prusalink';
    const port = prompt('端口（OctoPrint/Klipper 一般 7125，PrusaLink 一般 80）',
      proto === 'klipper' ? '7125' : proto === 'prusalink' ? '80' : '7125');
    const key = prompt('API Key（OctoPrint 必填，Klipper/PrusaLink 可以留空回车）', '');
    if (key === null) return;
    await post('/api/print/add', {
      name, kind: KIND_3D, proto, host: host.trim(), port: Number(port) || 7125, api_key: (key || '').trim(),
    });
    toast('配对完成，正在测试…');
    this.loadDev();
    const d = (await api('/api/print/devices')).devices.slice(-1)[0];
    if (d) {
      const r = await post('/api/print/test', { id: d.id });
      toast(r.ok ? '连上了' : '连不上：' + (r.error || r.status_text || ''));
    }
  },

  // ---------- 选文件 ----------
  async search() {
    const q = this.el.querySelector('#fq').value.trim();
    const out = this.el.querySelector('#fsOut');
    out.innerHTML = '<div class="note">搜索引中…</div>';
    try {
      const d = await api(`/api/search?q=${encodeURIComponent(q)}&limit=120`);
      const rows = (d.rows || []).filter((r) => r.path && PRINTABLE.test(r.path));
      this.searchRows = rows;
      if (!rows.length) {
        out.innerHTML = '<div class="note">没找到能打印的文件。换个关键词，或者用上面的「本机选文件」。</div>';
        return;
      }
      out.innerHTML = `<div class="note">找到 ${rows.length} 个能打印的，点一下选中：</div>` +
        rows.slice(0, 60).map((r, i) => `<div class="tf-item pv-item" data-i="${i}">
          <div class="tf-n">${esc(r.name || r.path.split(/[\\\\/]/).pop())}</div>
          <div class="tf-sub">${esc(fmtSize(r.size || 0))} · ${esc(r.path)}</div>
        </div>`).join('');
      out.querySelectorAll('.pv-item').forEach((d2) => {
        d2.onclick = () => this.choose(rows[Number(d2.dataset.i)].path,
          rows[Number(d2.dataset.i)].name || rows[Number(d2.dataset.i)].path.split(/[\\\\/]/).pop());
      });
    } catch (e) {
      out.innerHTML = '<div class="note">搜索失败：' + esc(e.message) + '</div>';
    }
  },

  async pickLocal() {
    if (!window.showOpenFilePicker) {
      toast('这个浏览器不支持直接选本机文件，用上面的搜索框', 1);
      return;
    }
    try {
      const [h] = await window.showOpenFilePicker({
        types: [{ description: '能打印的文件', accept: { 'application/octet-stream': ['.pdf', '.png', '.jpg', '.jpeg', '.txt', '.md', '.csv', '.html', '.docx', '.xlsx', '.pptx'] } }],
        multiple: false,
      });
      const f = await h.getFile();
      this.choose(f.name, f.name, null);
    } catch (e) {
      if (e.name !== 'AbortError') toast('选文件失败：' + e.message, 1);
    }
  },

  choose(path, name, size) {
    this.picked = { path, name, size: size || 0 };
    this.prepared = null;
    this.el.querySelector('#pickBox').innerHTML =
      `已选：<b>${esc(name)}</b><br><span class="note">${esc(path)}</span>`;
    this.el.querySelector('#sendHint').textContent = '点「打印」会先转成 PDF（要几秒）';
    this.el.querySelector('#btnSend').disabled = !this.el.querySelector('#printerSel').value;
  },

  sendHint() {
    const sel = this.el.querySelector('#printerSel');
    const d = this.devices.find((x) => x.id === sel.value);
    const s = this.el.querySelector('#sendHint');
    if (!this.picked) s.textContent = '';
    else if (!d) s.textContent = '先在上面的下拉里选一台打印机';
    else s.textContent = `用「${d.name}」打印`;
    this.el.querySelector('#btnSend').disabled = !(this.picked && d);
  },

  async send() {
    const sel = this.el.querySelector('#printerSel');
    const dev = this.devices.find((x) => x.id === sel.value);
    if (!this.picked || !dev) return;
    const btn = this.el.querySelector('#btnSend');
    btn.disabled = true;
    btn.textContent = '准备中…';
    try {
      // 3D 打印机不走 PDF，直接送原文件
      if (dev.kind === KIND_3D) {
        await this.send3dFile(dev, this.picked.path);
        return;
      }
      const prep = await post('/api/print/prepare', { path: this.picked.path });
      if (!prep.ok) {
        toast('准备失败：' + prep.error, 1);
        return;
      }
      btn.textContent = '送印中…';
      const r = await post('/api/print/send', {
        printer_id: dev.id, path: prep.pdf, title: this.picked.name,
        opts: { mode: 'dialog' },
      });
      if (r.ok) {
        toast('已经交给系统打印了，去打印框里点「打印」');
        this.el.querySelector('#sendHint').innerHTML =
          `打印框打开后点「打印」。打完可以 <a href="#" id="restoreDef">把默认打印机改回去</a>`;
        const a = this.el.querySelector('#restoreDef');
        if (a) a.onclick = async (e) => {
          e.preventDefault();
          const d2 = await post('/api/print/restore-default', { printer: r.result.old_default });
          toast(d2.ok ? '默认打印机已改回 ' + r.result.old_default : '改回失败：' + d2.detail);
        };
      } else {
        toast('送印失败：' + (r.result?.error || '未知'), 1);
      }
      this.loadJobs();
    } catch (e) {
      toast('出错：' + e.message, 1);
    }
    btn.disabled = false;
    btn.textContent = '打印';
    this.sendHint();
  },

  // ---------- OpenClaw 派活 ----------
  async agent() {
    const inp = this.el.querySelector('#agentTask');
    const task = inp.value.trim();
    if (!task) {
      toast('先说说要它做什么', 1);
      return;
    }
    const btn = this.el.querySelector('#btnAgent');
    const out = this.el.querySelector('#agentOut');
    btn.disabled = true;
    btn.textContent = '它在想…';
    out.innerHTML = '<div class="note">OpenClaw 正在干活（可能要几十秒）。产物会列在下面，<b>不会自动打印</b>。</div>';
    try {
      const d = await post('/api/print/agent', { task, timeout: 240 });
      out.innerHTML = `<div class="note">${d.ok ? '干完了。' : '没成功：' + esc(d.error)}</div>` +
        (d.reply ? `<pre class="pv-reply">${esc(d.reply.slice(0, 4000))}</pre>` : '');
      if (d.produced && d.produced.length) {
        this.produced = d.produced.concat(this.produced);
      }
      this.renderProduced();
      this.loadJobs();
    } catch (e) {
      out.innerHTML = '<div class="note">派活失败：' + esc(e.message) + '</div>';
    }
    btn.disabled = false;
    btn.textContent = '派活';
  },

  async loadProduced() {
    try {
      const d = await api('/api/print/stage');
      this.produced = (d.rows || []).map((r) => ({ name: r.name, path: d.dir + '\\' + r.name, size: r.size }));
      this.renderProduced();
    } catch (e) { /* 忽略 */ }
  },

  renderProduced() {
    const box = this.el.querySelector('#prodList');
    if (!this.produced.length) {
      box.innerHTML = '<div class="note">还没有产物。让 OpenClaw 干个活，或者把文件拖到「互传」页传进来。</div>';
      return;
    }
    box.innerHTML = '<div class="note">产物 —— 先点开看看，满意再打印：</div>' +
      this.produced.map((p, i) => `<div class="tf-item pv-item" data-i="${i}">
        <div class="tf-n">${esc(p.name)}</div>
        <div class="tf-sub">${esc(fmtSize(p.size || 0))}</div>
        <div class="tf-acts">
          <a class="btn" href="/api/print/preview?name=${encodeURIComponent(p.name)}" target="_blank">看</a>
          <button class="btn" data-a="pick" data-i="${i}">选它打印</button>
          <button class="btn" data-a="dl" data-i="${i}">下载</button>
        </div>
      </div>`).join('');
    box.querySelectorAll('button[data-a]').forEach((b) => {
      const p = this.produced[Number(b.dataset.i)];
      if (b.dataset.a === 'pick') {
        b.onclick = () => {
          this.choose(p.path, p.name, p.size);
          document.querySelector('.mod.on')?.querySelector('#fsOut')?.scrollIntoView({ block: 'center' });
          toast('已选，下面点「打印」');
        };
      } else if (b.dataset.a === 'dl') {
        b.onclick = () => {
          window.open('/api/print/preview?name=' + encodeURIComponent(p.name), '_blank');
        };
      }
    });
  },

  // ---------- 3D ----------
  async poll3d() {
    if (!this.dev3d) return;
    try {
      const d = await api('/api/print/3d/status?id=' + encodeURIComponent(this.dev3d.id));
      this.status3d = d.status || {};
      this.render3d();
    } catch (e) { /* 忽略 */ }
    if (this.statusTimer) clearTimeout(this.statusTimer);
    this.statusTimer = setTimeout(() => this.poll3d(), 4000);
  },

  render3d() {
    const s = this.status3d || {};
    const t = (a) => (a && a.length === 2 ? `${a[0]}° / 目标 ${a[1]}°` : '—');
    this.el.querySelector('#s3d').innerHTML = `
      <div class="pv-state">${esc(s.state || '未知')}</div>
      <div class="pv-bar"><i style="width:${Math.max(0, Math.min(100, s.progress || 0))}%"></i></div>
      <div class="note">进度 ${s.progress || 0}%${s.eta_min ? ' · 还剩约 ' + s.eta_min + ' 分钟' : ''}${s.file ? ' · ' + esc(s.file) : ''}</div>
      <div class="note">喷头 ${esc(t(s.nozzle))} · 热床 ${esc(t(s.bed))}${s.raw_err ? ' · ' + esc(s.raw_err) : ''}</div>`;
  },

  async ctrl3d(action) {
    if (!this.dev3d) return;
    const r = await post('/api/print/3d/control', { id: this.dev3d.id, action });
    toast(r.ok ? (action + ' 已执行') : ('失败：' + (r.error || '未知')), r.ok ? 0 : 1);
    this.poll3d();
  },

  async sendGcode(file) {
    if (!file || !this.dev3d) return;
    toast('还没做 G-code 上传端点，先用「互传」把文件传到电脑，再在这里选它', 1);
    this.el.querySelector('#gcode').value = '';
  },

  async send3dFile(dev, path) {
    const r = await post('/api/print/send', {
      printer_id: dev.id, path, title: path.split(/[\\/]/).pop(), opts: { print_now: true },
    });
    if (r.ok) {
      toast('已送到 ' + dev.name + ' 开始打印');
      this.dev3d = dev;
      this.el.querySelector('#p3d').style.display = '';
      this.el.querySelector('#p3dName').textContent = dev.name + ' @ ' + dev.host;
      this.poll3d();
    } else {
      toast('3D 打印失败：' + (r.result?.error || '未知'), 1);
    }
  },

  async loadJobs() {
    try {
      const d = await api('/api/print/jobs');
      this.jobs = d.jobs || [];
      this.renderJobs();
    } catch (e) { /* 忽略 */ }
  },

  renderJobs() {
    const box = this.el.querySelector('#jobList');
    if (!this.jobs.length) {
      box.innerHTML = '<div class="note">还没有打印记录。</div>';
      return;
    }
    const when = (ts) => new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
    box.innerHTML = this.jobs.slice(0, 30).map((j) => `<div class="tf-item">
      <div class="tf-n">${esc(j.title || j.file)}</div>
      <div class="tf-sub">${esc(j.printer)} · ${esc(j.channel || '')} · ${esc(when(j.created))}</div>
      <div class="tf-acts">${j.status === 'error'
        ? `<span class="note err">${esc((j.detail || '').slice(0, 120))}</span>` : ''}</div>
    </div>`).join('');
  },

  badge(d) {
    const c = (d && d.counts && d.counts.printer) || 0;
    return c ? String(c) : '';
  },

  commands() {
    return [
      { name: '打印机', run: () => WB.go('printer') },
      { name: '打印机 · 找 3D 打印机', run: () => WB.go('printer') },
    ];
  },
};