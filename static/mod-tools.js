/* 小工具盒子：纯前端，零依赖。时间戳 / 密码 / Base64 / 文本 / 哈希。 */

export default {
  id: 'tools',
  name: '小工具',
  el: null,
  _tsTimer: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">
      <div class="panel">
        <h3>时间戳</h3>
        <div class="field" style="gap:8px;flex-wrap:wrap">
          <span class="note" id="tsNow">—</span>
          <button class="btn" id="tsCopy">复制当前秒</button>
        </div>
        <div class="field" style="margin-top:8px;gap:8px;flex-wrap:wrap">
          <input id="tsIn" placeholder="时间戳(秒或毫秒)">
          <button class="btn" id="tsToDate">→ 日期</button>
          <span id="tsOut" class="note"></span>
        </div>
        <div class="field" style="gap:8px;flex-wrap:wrap">
          <input id="dateIn" type="datetime-local">
          <button class="btn" id="dateToTs">→ 时间戳</button>
          <span id="dateOut" class="note"></span>
        </div>
      </div>

      <div class="panel">
        <h3>密码生成</h3>
        <div class="field" style="gap:8px;flex-wrap:wrap;align-items:center">
          <input id="pwLen" type="number" value="16" min="4" max="64" style="width:70px">
          <label class="note"><input type="checkbox" id="pwUp" checked> 大写</label>
          <label class="note"><input type="checkbox" id="pwLow" checked> 小写</label>
          <label class="note"><input type="checkbox" id="pwNum" checked> 数字</label>
          <label class="note"><input type="checkbox" id="pwSym"> 符号</label>
          <button class="btn primary" id="pwGen">生成</button>
        </div>
        <div class="field" style="margin-top:8px;gap:8px">
          <input id="pwOut" readonly style="flex:1;min-width:160px">
          <button class="btn" id="pwCopy">复制</button>
        </div>
      </div>

      <div class="panel">
        <h3>Base64 编解码</h3>
        <textarea id="b64in" placeholder="输入文本" style="width:100%;min-height:70px;resize:vertical;border:1px solid var(--line-strong);border-radius:8px;padding:8px;background:var(--surface);color:var(--ink)"></textarea>
        <div class="field" style="margin-top:8px;gap:8px;flex-wrap:wrap">
          <button class="btn" id="b64en">编码 →</button>
          <button class="btn" id="b64de">← 解码</button>
          <button class="btn" id="b64copy">复制结果</button>
        </div>
        <textarea id="b64out" readonly placeholder="结果" style="width:100%;min-height:70px;margin-top:8px;resize:vertical;border:1px solid var(--line-strong);border-radius:8px;padding:8px;background:var(--surface-2);color:var(--ink)"></textarea>
      </div>

      <div class="panel">
        <h3>文本统计 / 去重</h3>
        <textarea id="txIn" placeholder="每行一条，自动统计行数、字数，并给出去重结果" style="width:100%;min-height:90px;resize:vertical;border:1px solid var(--line-strong);border-radius:8px;padding:8px;background:var(--surface);color:var(--ink)"></textarea>
        <div class="field" style="margin-top:8px;gap:8px;flex-wrap:wrap">
          <button class="btn" id="txStat">统计</button>
          <button class="btn" id="txUniq">去重</button>
        </div>
        <div id="txOut" class="note" style="margin-top:8px"></div>
      </div>

      <div class="panel">
        <h3>SHA-256 哈希</h3>
        <textarea id="hashIn" placeholder="输入文本" style="width:100%;min-height:60px;resize:vertical;border:1px solid var(--line-strong);border-radius:8px;padding:8px;background:var(--surface);color:var(--ink)"></textarea>
        <div class="field" style="margin-top:8px;gap:8px;flex-wrap:wrap">
          <button class="btn" id="hashGo">计算</button>
          <button class="btn" id="hashCopy">复制</button>
        </div>
        <div id="hashOut" class="note" style="margin-top:8px;word-break:break-all"></div>
      </div>
    </div>`;

    const now = () => Math.floor(Date.now() / 1000);
    const tick = () => { this.el.querySelector('#tsNow').textContent = '当前：' + now() + ' 秒'; };
    tick();
    this._tsTimer = setInterval(tick, 1000);
    this.el.querySelector('#tsCopy').onclick = () => { navigator.clipboard.writeText(String(now())); toast('已复制'); };
    this.el.querySelector('#tsToDate').onclick = () => {
      let v = this.el.querySelector('#tsIn').value.trim();
      if (!v) return;
      v = parseFloat(v);
      if (v < 1e12) v *= 1000;
      const d = new Date(v);
      this.el.querySelector('#tsOut').textContent = isNaN(d) ? '无效' : d.toLocaleString();
    };
    this.el.querySelector('#dateToTs').onclick = () => {
      const v = this.el.querySelector('#dateIn').value;
      if (!v) return;
      const ms = new Date(v).getTime();
      this.el.querySelector('#dateOut').textContent = Math.floor(ms / 1000) + ' 秒 / ' + ms + ' 毫秒';
    };
    this.el.querySelector('#dateIn').value = new Date().toISOString().slice(0, 16);

    const gen = () => {
      const len = Math.max(4, Math.min(64, parseInt(this.el.querySelector('#pwLen').value) || 16));
      let pool = '';
      if (this.el.querySelector('#pwUp').checked) pool += 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
      if (this.el.querySelector('#pwLow').checked) pool += 'abcdefghijklmnopqrstuvwxyz';
      if (this.el.querySelector('#pwNum').checked) pool += '0123456789';
      if (this.el.querySelector('#pwSym').checked) pool += '!@#$%^&*()-_=+';
      if (!pool) pool = 'abcdefghijklmnopqrstuvwxyz';
      let s = '';
      const arr = new Uint32Array(len);
      crypto.getRandomValues(arr);
      for (let i = 0; i < len; i++) s += pool[arr[i] % pool.length];
      this.el.querySelector('#pwOut').value = s;
    };
    this.el.querySelector('#pwGen').onclick = gen;
    gen();
    this.el.querySelector('#pwCopy').onclick = () => {
      const v = this.el.querySelector('#pwOut').value;
      if (v) { navigator.clipboard.writeText(v); toast('已复制'); }
    };

    this.el.querySelector('#b64en').onclick = () => {
      const v = this.el.querySelector('#b64in').value;
      try { this.el.querySelector('#b64out').value = btoa(unescape(encodeURIComponent(v))); }
      catch (e) { this.el.querySelector('#b64out').value = '编码失败'; }
    };
    this.el.querySelector('#b64de').onclick = () => {
      const v = this.el.querySelector('#b64in').value.trim();
      try { this.el.querySelector('#b64out').value = decodeURIComponent(escape(atob(v))); }
      catch (e) { this.el.querySelector('#b64out').value = '解码失败（不是合法 Base64）'; }
    };
    this.el.querySelector('#b64copy').onclick = () => {
      const v = this.el.querySelector('#b64out').value;
      if (v) { navigator.clipboard.writeText(v); toast('已复制'); }
    };

    this.el.querySelector('#txStat').onclick = () => {
      const lines = this.el.querySelector('#txIn').value.split('\n');
      const nz = lines.filter((l) => l.trim());
      this.el.querySelector('#txOut').textContent = `共 ${lines.length} 行，非空 ${nz.length} 行，字符 ${this.el.querySelector('#txIn').value.length} 个`;
    };
    this.el.querySelector('#txUniq').onclick = () => {
      const seen = new Set();
      const out = [];
      this.el.querySelector('#txIn').value.split('\n').forEach((l) => {
        const k = l.trim();
        if (k && !seen.has(k)) { seen.add(k); out.push(l); }
      });
      this.el.querySelector('#txIn').value = out.join('\n');
      this.el.querySelector('#txOut').textContent = `去重后 ${out.length} 行`;
    };

    this.el.querySelector('#hashGo').onclick = async () => {
      const v = this.el.querySelector('#hashIn').value;
      try {
        const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(v));
        const a = Array.from(new Uint8Array(buf));
        this.el.querySelector('#hashOut').textContent = a.map((x) => x.toString(16).padStart(2, '0')).join('');
      } catch (e) { this.el.querySelector('#hashOut').textContent = '计算失败'; }
    };
    this.el.querySelector('#hashCopy').onclick = () => {
      const v = this.el.querySelector('#hashOut').textContent;
      if (v) { navigator.clipboard.writeText(v); toast('已复制'); }
    };
  },

  onShow() {},
  onHide() { if (this._tsTimer) { clearInterval(this._tsTimer); this._tsTimer = null; } },
};

function toast(m) { if (window.WB && window.WB.toast) window.WB.toast(m); }
