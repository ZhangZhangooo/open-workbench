/* 系统：CPU / 内存 / 磁盘 / 进程 + 四个工具（剪贴板历史 / 截图标注 / 定时提醒 / 内置终端）。
 * 工具都是本地功能，不涉及外部账号。
 */

const { api, post, toast, esc, fmtSize } = window.WB;

/* 极简 VT/ANSI 终端模拟器：维护一个二维字符缓冲，吃下 ConPTY 吐出的转义序列，
 * 渲染成带颜色的 HTML。支持 SGR 颜色/粗体、\r \n \b、光标定位、清屏、行内擦除。
 * 不做 256/真彩（PowerShell 用不到），够还原提示符和彩色输出。 */
const ANSI_FG = {
  30: '#4b4b4b', 31: '#cd3131', 32: '#0dbc79', 33: '#e5e510', 34: '#2472c8',
  35: '#bc3fbc', 36: '#11a8cd', 37: '#e5e5e5',
  90: '#666666', 91: '#f14c4c', 92: '#23d18b', 93: '#f5f543', 94: '#3b8eea',
  95: '#d670d6', 96: '#29b8db', 97: '#ffffff',
};
const ANSI_BG = {
  40: '#4b4b4b', 41: '#cd3131', 42: '#0dbc79', 43: '#e5e510', 44: '#2472c8',
  45: '#bc3fbc', 46: '#11a8cd', 47: '#e5e5e5',
  100: '#666666', 101: '#f14c4c', 102: '#23d18b', 103: '#f5f543', 104: '#3b8eea',
  105: '#d670d6', 106: '#29b8db', 107: '#ffffff',
};

class TermEmu {
  constructor(cols = 120, maxRows = 2000) {
    this.cols = cols; this.maxRows = maxRows;
    this.lines = [[]];
    this.cx = 0; this.cy = 0;
    this.fg = null; this.bg = null; this.bold = false;
  }
  ensure(y) { while (this.lines.length <= y) this.lines.push([]); return this.lines[y]; }
  put(ch) {
    if (this.cx >= this.cols) { this.cx = 0; this.cy++; }
    const line = this.ensure(this.cy);
    line[this.cx] = { ch, fg: this.fg, bg: this.bg, bold: this.bold };
    this.cx++;
  }
  nl() { this.cx = 0; this.cy++; this.ensure(this.cy); this._trim(); }
  _trim() {
    if (this.lines.length > this.maxRows) {
      const drop = this.lines.length - this.maxRows;
      this.lines.splice(0, drop);
      this.cy = Math.max(0, this.cy - drop);
    }
  }
  clearScreen() { this.lines = [[]]; this.cx = 0; this.cy = 0; }
  sgr(buf) {
    const ps = buf.split(';').map((s) => (s === '' ? 0 : parseInt(s, 10)));
    for (const p of ps) {
      if (p === 0) { this.fg = null; this.bg = null; this.bold = false; }
      else if (p === 1) this.bold = true;
      else if (p === 22) this.bold = false;
      else if (p >= 30 && p <= 37) this.fg = ANSI_FG[p];
      else if (p >= 90 && p <= 97) this.fg = ANSI_FG[p];
      else if (p >= 40 && p <= 47) this.bg = ANSI_BG[p];
      else if (p >= 100 && p <= 107) this.bg = ANSI_BG[p];
      // 38/48（256/真彩）忽略，保持当前色
    }
  }
  csi(buf, fin) {
    const n = (buf === '' ? 1 : parseInt(buf.replace(/[^0-9].*$/, ''), 10) || 1);
    if (fin === 'm') this.sgr(buf);
    else if (fin === 'H' || fin === 'f') {
      const parts = buf.split(';');
      const r = (parseInt(parts[0], 10) || 1) - 1;
      const c = (parseInt(parts[1], 10) || 1) - 1;
      this.cy = Math.max(0, r); this.cx = Math.max(0, c); this.ensure(this.cy);
    } else if (fin === 'J') { if (buf === '2' || buf === '3') this.clearScreen(); }
    else if (fin === 'K') {
      const line = this.ensure(this.cy);
      if (buf === '1') line.splice(0, this.cx);
      else if (buf === '2') line.length = 0;
      else line.length = this.cx; // 擦到行尾
    } else if (fin === 'A') this.cy = Math.max(0, this.cy - n);
    else if (fin === 'B') { this.cy += n; this.ensure(this.cy); }
    else if (fin === 'C') this.cx += n;
    else if (fin === 'D') this.cx = Math.max(0, this.cx - n);
    else if (fin === 'E') { this.cx = 0; this.cy += n; this.ensure(this.cy); }
    else if (fin === 'G') this.cx = Math.max(0, n - 1);
  }
  feed(s) {
    let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (c === '\x1b') {
        const nx = s[i + 1];
        if (nx === '[') {
          let j = i + 2, b = '';
          while (j < s.length && !/[A-Za-z]/.test(s[j])) { b += s[j]; j++; }
          this.csi(b, s[j]); i = j + 1;
        } else if (nx === ']') { // OSC（标题等），读到 BEL 或 ST 为止
          let j = i + 2;
          while (j < s.length && s[j] !== '\x07' && s[j] !== '\x1b') j++;
          i = (s[j] === '\x07') ? j + 1 : j + 2;
        } else { i += 2; }
        continue;
      }
      if (c === '\r') { this.cx = 0; i++; continue; }
      if (c === '\n') { this.nl(); i++; continue; }
      if (c === '\b') { if (this.cx > 0) this.cx--; i++; continue; }
      if (c === '\x0c' || c === '\x0b') { this.clearScreen(); i++; continue; }
      if (c < ' ' || c === ' ') { i++; continue; }
      this.put(c); i++;
    }
  }
  render() {
    const esc2 = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');
    let html = '';
    for (const line of this.lines) {
      if (!line.length) { html += '\n'; continue; }
      let cur = '', run = '';
      const flush = () => {
        if (run) html += cur ? `<span style="${cur}">${esc2(run)}</span>` : esc2(run);
        cur = ''; run = '';
      };
      let last = null;
      for (const cell of line) {
        const st = (cell.fg ? `color:${cell.fg}` : '') +
          (cell.bg ? `;background:${cell.bg}` : '') +
          (cell.bold ? ';font-weight:bold' : '');
        if (st !== last) { flush(); last = st; }
        cur = st; run += cell.ch;
      }
      flush();
      html += '\n';
    }
    return html;
  }
}

export default {
  id: 'system',
  name: '系统',
  el: null,
  timer: null,
  _remTimer: null,
  _remFired: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="bar" style="padding-top:0">
        <button class="btn" id="btnRefresh" style="height:30px;padding:0 12px;font-size:12px">刷新</button>
        <span id="sysState" style="font-size:12px;color:var(--ink-2)"></span>
      </div>
      <div class="stack">
        <div class="panel">
          <h3>资源</h3>
          <div id="sysStats" class="note">读取中…</div>
        </div>
        <div class="panel">
          <h3>进程（按内存占用排）</h3>
          <div class="note" style="margin-bottom:8px">结束进程会直接 taskkill /F，别乱点。</div>
          <div id="procList"></div>
        </div>

        <div class="panel">
          <h3>剪贴板历史</h3>
          <div class="note" style="margin-bottom:8px">在工作台里复制/粘贴的文字会自动记下来；也可手动粘贴保存。点一条复制回去。</div>
          <textarea id="clipIn" placeholder="粘贴或输入，点保存" rows="2" style="width:100%;resize:vertical"></textarea>
          <div style="margin-top:6px"><button class="btn primary" id="clipSave">保存这条</button>
            <button class="btn" id="clipClear">清空</button></div>
          <div class="listbox" id="clipList" style="margin-top:10px"></div>
        </div>

        <div class="panel">
          <h3>截图标注</h3>
          <div class="note" style="margin-bottom:8px">选一张图，在图上画矩形 / 箭头 / 文字，下载标注图。</div>
          <input type="file" id="annoFile" accept="image/*">
          <div style="margin:8px 0;display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn slim" data-tool="rect">矩形</button>
            <button class="btn slim" data-tool="arrow">箭头</button>
            <button class="btn slim" data-tool="text">文字</button>
            <button class="btn slim" data-tool="free">自由线</button>
            <button class="btn slim" id="annoUndo">撤销</button>
            <button class="btn slim" id="annoClear">清空</button>
            <button class="btn slim primary" id="annoDown">下载 PNG</button>
            <span class="note" id="annoTool">当前：矩形</span>
          </div>
          <div style="overflow:auto;max-height:520px;border:1px solid var(--line-soft);border-radius:8px">
            <canvas id="annoCanvas" style="display:block;cursor:crosshair"></canvas>
          </div>
        </div>

        <div class="panel">
          <h3>定时提醒</h3>
          <div class="note" style="margin-bottom:8px">到点后工作台弹提示（需本页开着）。本机可用，不依赖外部日历。</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input type="datetime-local" id="remAt" style="height:34px">
            <input id="remText" placeholder="提醒内容" style="flex:1;min-width:160px;height:34px">
            <button class="btn primary" id="remAdd">添加</button>
          </div>
          <div class="listbox" id="remList" style="margin-top:10px"></div>
        </div>

        <div class="panel">
          <h3>内置终端 <span id="termMode" class="tag"></span></h3>
          <div class="note" style="margin-bottom:8px">⚠️ 在<strong>你本机</strong>执行命令，权限等同你自己。别跑不认识的命令。点终端区域即可输入。</div>
          <div style="position:relative">
            <pre id="termOut" tabindex="0" style="background:#0c0c0c;color:#e5e5e5;border-radius:8px;padding:10px;max-height:300px;min-height:120px;overflow:auto;font-size:12.5px;line-height:1.45;white-space:pre;margin:0 0 8px;outline:none"></pre>
            <textarea id="termCap" aria-hidden="true" spellcheck="false" autocomplete="off"
              style="position:absolute;inset:0;width:100%;height:100%;margin:0;padding:10px;border:0;outline:none;resize:none;background:transparent;color:transparent;caret-color:transparent;overflow:hidden;white-space:pre;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.45"></textarea>
          </div>
          <div id="termBar" style="display:flex;gap:8px;align-items:center">
            <span style="align-self:center;color:var(--ink-3)">$</span>
            <input id="termIn" placeholder="dir / ipconfig / python -c ..." style="flex:1;height:34px;font-family:monospace">
            <button class="btn primary" id="termRun">运行</button>
            <button class="btn" id="termRestart" style="display:none">重启</button>
          </div>
        </div>
      </div>`;

    el.querySelector('#btnRefresh').onclick = () => this.load();
    el.querySelector('#procList').addEventListener('click', async (e) => {
      const k = e.target.closest('.kill');
      if (!k) return;
      if (!confirm(`结束 ${k.dataset.name} (PID ${k.dataset.pid})？`)) return;
      await post('/api/system/kill', { pid: +k.dataset.pid });
      this.load();
    });

    this.bindClip();
    this.bindAnno();
    this.bindRem();
    this.bindTerm();

    this.load();
    this.loadClip();
    this.loadRem();
    this.startRemPoll();
  },

  /* ---------- 资源 ---------- */
  async load() {
    const el = this.el;
    el.querySelector('#sysState').textContent = '采样中…';
    const d = await api('/api/system');
    const bar = (label, used, total) => {
      const pct = total ? Math.round(used * 100 / total) : 0;
      return `<div style="margin-bottom:10px">
        <div style="display:flex;font-size:12.5px;margin-bottom:4px">
          <span>${label}</span>
          <span style="margin-left:auto;color:var(--ink-2)">${fmtSize(used)} / ${fmtSize(total)} · ${pct}%</span>
        </div>
        <div style="height:6px;background:var(--line);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:var(--accent);transition:width .4s var(--ease)"></div>
        </div>
      </div>`;
    };
    let h = bar('内存', d.mem.used, d.mem.total);
    h += `<div style="font-size:12.5px;margin-bottom:12px">CPU ${d.cpu}% · ${d.cores} 核</div>`;
    (d.disks || []).forEach((k) => { h += bar(`磁盘 ${k.root}`, k.used, k.total); });
    el.querySelector('#sysStats').innerHTML = h;
    el.querySelector('#procList').innerHTML = (d.procs || []).map((p) => `
      <div style="display:flex;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.name)}</span>
        <span style="color:var(--ink-3);font-variant-numeric:tabular-nums">${fmtSize(p.mem)}</span>
        <button class="kill" data-pid="${p.pid}" data-name="${esc(p.name)}"
          style="border:1px solid var(--line-strong);background:transparent;border-radius:6px;font-size:11px;padding:2px 8px;color:var(--ink-2);cursor:pointer">结束</button>
      </div>`).join('');
    el.querySelector('#sysState').textContent = '刚更新';
  },

  /* ---------- 剪贴板历史 ---------- */
  bindClip() {
    if (!window.__clipBound) {
      window.__clipBound = true;
      document.addEventListener('paste', (e) => {
        const t = e.clipboardData && e.clipboardData.getData('text');
        if (t && t.trim()) this.clipCapture(t);
      });
    }
    this.el.querySelector('#clipSave').onclick = async () => {
      const ta = this.el.querySelector('#clipIn');
      const t = ta.value.trim();
      if (!t) return;
      await post('/api/clip/add', { text: t });
      ta.value = '';
      this.loadClip();
    };
    this.el.querySelector('#clipClear').onclick = async () => {
      await post('/api/clip/clear', {});
      this.loadClip();
    };
    this.el.querySelector('#clipList').addEventListener('click', async (e) => {
      const cp = e.target.closest('.clip-copy');
      const dl = e.target.closest('.clip-del');
      if (cp) {
        try { await navigator.clipboard.writeText(cp.dataset.text); toast('已复制'); } catch (_) {}
        return;
      }
      if (dl) { await post('/api/clip/del', { id: +dl.dataset.id }); this.loadClip(); }
    });
  },
  async clipCapture(text) {
    const r = await post('/api/clip/add', { text });
    if (r && r.ok && !r.dup) this.loadClip();
  },
  async loadClip() {
    const d = await api('/api/clip');
    const box = this.el.querySelector('#clipList');
    const rows = (d.rows || []).slice(0, 100);
    if (!rows.length) { box.innerHTML = '<div class="note">还没有记录</div>'; return; }
    box.innerHTML = rows.map((r) => `
      <div class="lrow"><div style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.text)}">${esc(r.text)}</div>
      <button class="btn slim clip-copy" data-text="${esc(r.text).replace(/"/g, '&quot;')}">复制</button>
      <button class="clip-del x" data-id="${r.id}" style="opacity:1;position:static;margin-left:6px">×</button></div>`).join('');
  },

  /* ---------- 截图标注 ---------- */
  bindAnno() {
    const cv = this.el.querySelector('#annoCanvas');
    const ctx = cv.getContext('2d');
    this.anno = { cv, ctx, img: null, tool: 'rect', shapes: [], drawing: null, sx: 0, sy: 0 };
    this.el.querySelectorAll('[data-tool]').forEach((b) => {
      b.onclick = () => {
        this.anno.tool = b.dataset.tool;
        this.el.querySelector('#annoTool').textContent = '当前：' + b.textContent;
      };
    });
    this.el.querySelector('#annoFile').onchange = (e) => this.annoLoad(e.target.files[0]);
    this.el.querySelector('#annoUndo').onclick = () => { this.anno.shapes.pop(); this.annoRedraw(); };
    this.el.querySelector('#annoClear').onclick = () => { this.anno.shapes = []; this.annoRedraw(); };
    this.el.querySelector('#annoDown').onclick = () => {
      const a = document.createElement('a');
      a.download = '标注图.png';
      a.href = cv.toDataURL('image/png');
      a.click();
    };
    cv.addEventListener('pointerdown', (e) => this.annoDown(e));
    cv.addEventListener('pointermove', (e) => this.annoMove(e));
    window.addEventListener('pointerup', () => this.annoUp());
  },
  annoLoad(file) {
    if (!file) return;
    const fr = new FileReader();
    fr.onload = () => {
      const img = new Image();
      img.onload = () => {
        const max = 900;
        let w = img.naturalWidth, h = img.naturalHeight;
        if (w > max) { h = Math.round(h * max / w); w = max; }
        this.anno.cv.width = w; this.anno.cv.height = h;
        this.anno.img = img; this.anno.shapes = [];
        this.annoRedraw();
      };
      img.src = fr.result;
    };
    fr.readAsDataURL(file);
  },
  annoPos(e) {
    const r = this.anno.cv.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (this.anno.cv.width / r.width), y: (e.clientY - r.top) * (this.anno.cv.height / r.height) };
  },
  annoDown(e) {
    if (!this.anno.img) return;
    const p = this.annoPos(e);
    const t = this.anno.tool;
    if (t === 'text') {
      const s = prompt('输入文字：');
      if (s) { this.anno.shapes.push({ type: 'text', x: p.x, y: p.y, text: s }); this.annoRedraw(); }
      return;
    }
    this.anno.drawing = { type: t, x1: p.x, y1: p.y, x2: p.x, y2: p.y };
  },
  annoMove(e) {
    if (!this.anno.drawing) return;
    const p = this.annoPos(e);
    this.anno.drawing.x2 = p.x; this.anno.drawing.y2 = p.y;
    this.annoRedraw();
  },
  annoUp() {
    if (this.anno.drawing) { this.anno.shapes.push(this.anno.drawing); this.anno.drawing = null; this.annoRedraw(); }
  },
  annoRedraw() {
    const { ctx, cv, img, shapes, drawing } = this.anno;
    ctx.clearRect(0, 0, cv.width, cv.height);
    if (img) ctx.drawImage(img, 0, 0);
    ctx.lineWidth = 3; ctx.strokeStyle = '#e23b3b'; ctx.fillStyle = '#e23b3b';
    ctx.font = '20px sans-serif';
    const all = drawing ? shapes.concat([drawing]) : shapes;
    for (const s of all) {
      if (s.type === 'rect') ctx.strokeRect(s.x1, s.y1, s.x2 - s.x1, s.y2 - s.y1);
      else if (s.type === 'free' || s.type === 'arrow') {
        ctx.beginPath(); ctx.moveTo(s.x1, s.y1); ctx.lineTo(s.x2, s.y2); ctx.stroke();
        if (s.type === 'arrow') {
          const a = Math.atan2(s.y2 - s.y1, s.x2 - s.x1), L = 12;
          ctx.beginPath();
          ctx.moveTo(s.x2, s.y2);
          ctx.lineTo(s.x2 - L * Math.cos(a - 0.4), s.y2 - L * Math.sin(a - 0.4));
          ctx.moveTo(s.x2, s.y2);
          ctx.lineTo(s.x2 - L * Math.cos(a + 0.4), s.y2 - L * Math.sin(a + 0.4));
          ctx.stroke();
        }
      } else if (s.type === 'text') ctx.fillText(s.text, s.x, s.y);
    }
  },

  /* ---------- 定时提醒 ---------- */
  bindRem() {
    this.el.querySelector('#remAdd').onclick = async () => {
      const at = this.el.querySelector('#remAt').value;
      const text = this.el.querySelector('#remText').value.trim();
      if (!at || !text) { toast('填时间和内容'); return; }
      const ts = new Date(at).getTime() / 1000;
      await post('/api/reminders/add', { at: ts, text });
      this.el.querySelector('#remText').value = '';
      this.loadRem();
    };
    this.el.querySelector('#remList').addEventListener('click', async (e) => {
      const done = e.target.closest('.rem-done');
      const del = e.target.closest('.rem-del');
      if (done) { await post('/api/reminders/done', { id: +done.dataset.id, done: done.checked ? 1 : 0 }); this.loadRem(); }
      else if (del) { await post('/api/reminders/del', { id: +del.dataset.id }); this.loadRem(); }
    });
  },
  async loadRem() {
    const d = await api('/api/reminders');
    const box = this.el.querySelector('#remList');
    const rows = d.rows || [];
    if (!rows.length) { box.innerHTML = '<div class="note">还没有提醒</div>'; return; }
    const now = Date.now() / 1000;
    box.innerHTML = rows.map((r) => {
      const t = new Date(r.at * 1000);
      const ts = t.toLocaleString();
      const past = r.at <= now;
      return `<div class="lrow">
        <input type="checkbox" class="rem-done" data-id="${r.id}" ${r.done ? 'checked' : ''} style="margin-right:8px">
        <div style="flex:1;min-width:0"><span style="${r.done ? 'text-decoration:line-through;color:var(--ink-3)' : (past && !r.done ? 'color:#e23b3b;font-weight:600' : '')}">${esc(r.text)}</span>
          <div class="note">${ts}</div></div>
        <button class="rem-del x" data-id="${r.id}" style="opacity:1;position:static;margin-left:6px">×</button>
      </div>`;
    }).join('');
  },
  startRemPoll() {
    if (this._remTimer) return;
    this._remFired = new Set();
    this._remTimer = setInterval(async () => {
      try {
        const d = await api('/api/reminders');
        const now = Date.now() / 1000;
        for (const r of (d.rows || [])) {
          if (!r.done && r.at <= now && !this._remFired.has(r.id)) {
            this._remFired.add(r.id);
            toast('⏰ ' + r.text);
            this.loadRem();
          }
        }
      } catch (_) {}
    }, 15000);
  },

  /* ---------- 内置终端 ---------- */
  bindTerm() {
    this.termHist = []; this.termI = 0;
    this.termES = null; this.emu = null; this.termMode = 'run';
    const out = this.el.querySelector('#termOut');
    const cap = this.el.querySelector('#termCap');
    const inp = this.el.querySelector('#termIn');
    const bar = this.el.querySelector('#termBar');
    const restart = this.el.querySelector('#termRestart');
    const modeTag = this.el.querySelector('#termMode');

    const computeSize = () => ({
      cols: Math.max(20, Math.floor(out.clientWidth / 7.4) || 120),
      rows: Math.max(6, Math.floor(out.clientHeight / 18) || 30),
    });

    // 非交互兜底：输入 + 运行按钮
    const run = async () => {
      const cmd = inp.value;
      if (!cmd.trim()) return;
      this.termHist.push(cmd); this.termI = this.termHist.length;
      out.textContent += '$ ' + cmd + '\n';
      const r = await post('/api/term/run', { cmd });
      if (!r.ok) out.textContent += (r.error || '执行失败') + '\n';
      else {
        if (r.out) out.textContent += r.out + '\n';
        if (r.err) out.textContent += r.err + '\n';
        out.textContent += '[exit ' + r.code + ']\n';
      }
      out.scrollTop = out.scrollHeight;
      inp.value = '';
    };

    // 用 rAF 节流重渲染：PTY 输出常是一连串小帧，逐帧整屏重绘会卡，合到下一帧只画一次
    let raf = null;
    const renderOut = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = null;
        if (this.emu) { out.innerHTML = this.emu.render(); out.scrollTop = out.scrollHeight; }
      });
    };

    const openInteractive = () => {
      const es = new EventSource('/api/term/out');
      this.termES = es;
      es.onmessage = (e) => {
        try { this.emu.feed(atob(e.data)); renderOut(); }
        catch (_) { /* 忽略坏帧 */ }
      };
      es.addEventListener('closed', () => {
        this.emu.feed('\r\n[终端已关闭 —— 点「重启」或切走再回来恢复]\r\n');
        renderOut();
        this.termES = null;
        try { es.close(); } catch (_) {}
      });
      es.onerror = () => { /* 断线由 closed 事件或重连处理 */ };
    };

    const startInteractive = async () => {
      const sz = computeSize();
      const r = await post('/api/term/start', sz);
      if (!r.ok) { // 本机不支持 ConPTY，退回非交互模式
        this.termMode = 'run';
        modeTag.textContent = '非交互';
        modeTag.title = r.error || '';
        bar.style.display = 'flex';
        inp.style.display = '';
        restart.style.display = 'none';
        return;
      }
      this.termMode = 'interactive';
      modeTag.textContent = '交互';
      // 交互模式下隐藏明文输入框，只留「重启」便于断线后重连
      bar.style.display = 'flex';
      inp.style.display = 'none';
      restart.style.display = '';
      this.emu = new TermEmu(sz.cols);
      openInteractive();
      cap.focus();
    };

    restart.onclick = () => {
      if (this.termES) { try { this.termES.close(); } catch (_) {} this.termES = null; }
      startInteractive();
    };

    // 交互模式：在终端区直接敲键盘，把字符/VT 序列喂给 PTY
    const keyToSeq = (e) => {
      if (e.key === 'Enter') return '\r';
      if (e.key === 'Backspace') return '\x7f';
      if (e.key === 'Tab') return '\t';
      if (e.key === 'Escape') return '\x1b';
      if (e.key === 'ArrowUp') return '\x1b[A';
      if (e.key === 'ArrowDown') return '\x1b[B';
      if (e.key === 'ArrowRight') return '\x1b[C';
      if (e.key === 'ArrowLeft') return '\x1b[D';
      if (e.key === 'Home') return '\x1b[H';
      if (e.key === 'End') return '\x1b[F';
      if (e.key === 'Delete') return '\x1b[3~';
      if (e.ctrlKey && e.key.length === 1) {
        const code = e.key.toUpperCase().charCodeAt(0) - 64;
        if (code >= 1 && code <= 26) return String.fromCharCode(code);
      }
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) return e.key;
      return null;
    };
    // 交互模式：在透明捕获层（textarea）上敲键盘 —— IME 中文也能输入，且有真实光标。
    // 控制键转 VT 序列发给 PTY；正在组字的 IME 让给 compositionend 处理，避免重复/错位。
    cap.addEventListener('keydown', (e) => {
      if (this.termMode !== 'interactive' || !this.termES) return;
      if (e.isComposing || e.key === 'Process') return;
      const s = keyToSeq(e);
      if (s !== null) { e.preventDefault(); post('/api/term/in', { data: s }); }
    });
    cap.addEventListener('compositionend', (e) => {
      if (this.termMode !== 'interactive' || !this.termES) return;
      if (e.data) post('/api/term/in', { data: e.data });
      cap.value = '';
    });
    // 非 IME 的可打印字符会落进 textarea（preventDefault 已拦，但兜底清掉，防止堆积）
    cap.addEventListener('input', () => { if (cap.value && !cap.isComposing) cap.value = ''; });
    cap.addEventListener('click', () => { if (this.termMode === 'interactive') cap.focus(); });
    // 粘贴：直接把剪贴板文字送进 PTY（Ctrl+V 也走这里）
    cap.addEventListener('paste', (e) => {
      if (this.termMode !== 'interactive' || !this.termES) return;
      const text = (e.clipboardData || window.clipboardData).getData('text');
      if (text) { e.preventDefault(); post('/api/term/in', { data: text }); }
    });

    // 尺寸变化同步给 PTY（最佳努力）
    if (typeof ResizeObserver !== 'undefined') {
      this._termRO = new ResizeObserver(() => {
        if (this.termMode === 'interactive') {
          const sz = computeSize();
          post('/api/term/resize', sz);
        }
      });
      this._termRO.observe(out);
    }

    this.termStartInteractive = startInteractive;
    this.el.querySelector('#termRun').onclick = run;
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); run(); }
      else if (e.key === 'ArrowUp') { if (this.termI > 0) { this.termI--; inp.value = this.termHist[this.termI] || ''; } }
      else if (e.key === 'ArrowDown') { if (this.termI < this.termHist.length) { this.termI++; inp.value = this.termHist[this.termI] || ''; } }
    });

    // 首次进入：尝试交互模式
    startInteractive();
  },

  onShow() {
    this.load(); this.loadClip(); this.loadRem();
    // 交互会话断了就重连（切走再回来）
    if (this.termMode === 'interactive' && !this.termES && this.termStartInteractive) {
      this.termStartInteractive();
    }
  },

  commands() {
    return [{ title: '刷新系统资源', hint: '系统', run: () => this.load() }];
  },
};
