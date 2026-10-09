/* 设备间互传文件（电脑 ↔ 手机 / 平板）。
   后端在 transfer.py + server.py 的 /api/transfer/*，字节落在 data/transfer/files/。

   几个刻意的选择，别改回去：
   - 上传用 XHR 不用 fetch：fetch 没有上传进度事件。手机上等一个 200MB 的文件
     却看不到任何反馈，体验极差；XHR 的 upload.onprogress 才有。
   - 前端先按配置挡一道（file.size 比 max_mb / 剩余配额）。别让用户白等几分钟
     才收到"超限"。后端那道校验照样保留，是兜底。
   - 手机入口地址只在**本机访问**时才显示：你人已经在手机上了，再给你看一遍
     地址没意义；而且 /api/remote/status 对局域网来客本来就是 403。
   - 收件箱接口**不在** LOCAL_ONLY_PREFIX 里，手机上才能传/下。别手贱加进去。 */

const { api, post, esc, toast } = window.WB;

const ICON = [
  [/^image\//, '🖼'], [/^video\//, '🎬'], [/^audio\//, '🎵'],
  [/pdf/, '📕'], [/zip|rar|7z|tar|gz/, '🗜'],
  [/word|docx?/, '📄'], [/sheet|excel|xlsx?/, '📊'], [/presentation|pptx?/, '📽'],
  [/^text\/|markdown|json|xml|csv/, '📝'],
];

function iconOf(it) {
  const t = (it.type || '').toLowerCase();
  for (const [re, ic] of ICON) if (re.test(t)) return ic;
  const ext = (it.name || '').split('.').pop().toLowerCase();
  for (const [re, ic] of ICON) if (re.test(ext)) return ic;
  return '📦';
}

export default {
  id: 'transfer',
  name: '互传',
  el: null,
  items: [],
  cfg: {},
  stats: {},
  uploading: 0,

  mount(el) {
    this.el = el;
    el.innerHTML = `<div class="stack">

      <div class="panel" id="tfEntry">
        <h3>手机 / 平板怎么进</h3>
        <div class="note" id="tfEntryNote">正在取地址…</div>
        <div class="field" id="tfEntryRow" style="display:none">
          <code class="tf-url" id="tfUrl"></code>
          <button class="btn" id="tfCopy">复制</button>
        </div>
      </div>

      <div class="panel">
        <h3>传给它 <span class="note" id="tfLimits"></span></h3>
        <div class="tf-drop" id="tfDrop">
          <div class="tf-drop-t">把文件拖进来</div>
          <div class="note">或者点这里选文件 —— 手机上就是"选择文件 / 拍照"</div>
        </div>
        <input type="file" id="tfPick" multiple hidden>
        <div id="tfQueue" class="tf-queue"></div>
      </div>

      <div class="panel">
        <h3>收件箱 <span class="note" id="tfStat"></span></h3>
        <div class="tf-bar"><i id="tfBar"></i></div>
        <div class="field-row tf-tools">
          <button class="btn" id="tfRefresh">刷新</button>
          <label class="note tf-selall">
            <input type="checkbox" id="tfSelAll"> 全选
          </label>
          <button class="btn" id="tfDelSel">删掉选中的</button>
          <button class="btn" id="tfClear">清空</button>
          <span class="tf-spacer"></span>
          <button class="btn" id="tfCfg">容量设置</button>
        </div>
        <div id="tfList" class="tf-list note">加载中…</div>
      </div>

    </div>`;

    const drop = el.querySelector('#tfDrop');
    const pick = el.querySelector('#tfPick');
    drop.onclick = () => pick.click();
    pick.onchange = () => { this.upload(pick.files); pick.value = ''; };

    // 拖拽：手机上不会触发，桌面上很好用
    ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add('on');
    }));
    ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove('on');
    }));
    drop.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length) this.upload(dt.files);
    });

    el.querySelector('#tfCopy').onclick = async () => {
      const u = el.querySelector('#tfUrl').textContent;
      try { await navigator.clipboard.writeText(u); toast('地址已复制'); }
      catch (_) { toast('复制失败，手动选中吧'); }
    };
    el.querySelector('#tfRefresh').onclick = () => this.refresh();
    el.querySelector('#tfClear').onclick = async () => {
      if (!this.items.length) { toast('本来就是空的'); return; }
      if (!confirm(`确定清空收件箱里的 ${this.items.length} 个文件？删了就找不回来了。`)) return;
      try { const r = await post('/api/transfer/clear'); toast(`清掉了 ${r.removed || 0} 个`); }
      catch (_) { toast('清空失败'); }
      this.refresh();
    };
    el.querySelector('#tfDelSel').onclick = () => this.delSelected();
    el.querySelector('#tfSelAll').onchange = (e) => this.toggleAll(e.target.checked);
    el.querySelector('#tfCfg').onclick = () => this.cfgDialog();
    el.querySelector('#tfList').addEventListener('click', (e) => this.onClick(e));

    this.loadEntry();
    this.refresh();
  },

  /* ---------------- 手机入口地址 ---------------- */

  async loadEntry() {
    const note = this.el.querySelector('#tfEntryNote');
    const row = this.el.querySelector('#tfEntryRow');
    let d = null;
    try { d = await api('/api/remote/status'); } catch (_) { d = null; }
    const bare = (d && d.urls_bare) instanceof Array ? d.urls_bare : [];
    if (d && d.ok && bare.length) {
      // 挑一个「像个家用地址」的（192.168 / 10. / 172.16-31）
      const nice = bare.filter((u) => /\/\/(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(u));
      const url = (nice[0] || bare[0]).replace(/\/$/, '');
      this.el.querySelector('#tfUrl').textContent = url;
      row.style.display = '';
      // 老实交代一句：http 明文地址在安卓上装不成真 App（浏览器规定 SW 只能在
      // 安全上下文注册）。iOS 的 Safari 无所谓，照样全屏。别让人以为装坏了。
      note.textContent = '手机连同一个 WiFi，扫不了码就直接输这个地址。'
        + '进去后在浏览器菜单里选「添加到主屏幕」。'
        + '（这条是 http 明文地址 —— 安卓上只能存成书签样式的图标；'
        + '想真全屏、没有地址栏，就用隧道那条 https 地址打开再加。）';
    } else {
      note.textContent = '你现在就是从别的设备进来的，地址就是你浏览器里那个。'
        + '（回电脑上打开这一页，才会显示该给手机输哪个地址。）';
    }
  },

  /* ---------------- 传上去 ---------------- */

  async upload(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    const maxMb = +this.cfg.max_mb || 0;
    const quotaMb = +this.cfg.quota_mb || 0;
    let used = +((this.stats || {}).bytes) || 0;

    for (const f of list) {
      // 先在本地挡一道，省得白等一场
      if (maxMb && f.size > maxMb * 1048576) {
        toast(`「${f.name}」有 ${(f.size / 1048576).toFixed(1)}MB，超过单文件上限 ${maxMb}MB，没传`);
        continue;
      }
      if (quotaMb && used + f.size > quotaMb * 1048576) {
        toast(`收件箱放不下「${f.name}」了，先清点旧的吧`);
        continue;
      }
      const okBytes = await this.one(f);
      if (okBytes > 0) used += okBytes;
    }
    this.refresh();
  },

  one(file) {
    return new Promise((resolve) => {
      const q = this.el.querySelector('#tfQueue');
      const row = document.createElement('div');
      row.className = 'tf-up';
      row.innerHTML = `<span class="tf-up-n">${esc(file.name)}</span>
        <span class="tf-up-bar"><i></i></span>
        <span class="tf-up-p">0%</span>`;
      q.appendChild(row);
      const bar = row.querySelector('.tf-up-bar > i');
      const pct = row.querySelector('.tf-up-p');

      const xhr = new XMLHttpRequest();
      // 文件名走 query：HTTP 头只能装 latin-1，中文名塞进去必炸
      const url = '/api/transfer/upload?name=' + encodeURIComponent(file.name);
      xhr.open('POST', url);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');

      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const p = Math.round(100 * e.loaded / e.total);
        bar.style.width = p + '%';
        pct.textContent = p + '%';
      };
      const done = (cls, text) => {
        row.classList.add(cls);
        pct.textContent = text;
        bar.style.width = '100%';
        setTimeout(() => row.remove(), cls === 'ok' ? 1800 : 6000);
      };
      xhr.onload = () => {
        let r = {};
        try { r = JSON.parse(xhr.responseText || '{}'); } catch (_) { r = {}; }
        if (xhr.status === 200 && r.ok) {
          done('ok', '已收');
          this.items.unshift(r.item);
          resolve(file.size);
        } else {
          done('err', '失败');
          toast(r.error || '上传失败');
          resolve(0);
        }
        this.render();
      };
      xhr.onerror = () => { done('err', '断线'); toast('网络断了，没传上去'); resolve(0); };
      xhr.onabort = () => { done('err', '取消'); resolve(0); };
      row.title = '点一下可以取消';
      row.onclick = () => { if (xhr.readyState !== 4) xhr.abort(); };
      xhr.send(file);
    });
  },

  /* ---------------- 收件箱 ---------------- */

  async refresh() {
    let d = null;
    try { d = await api('/api/transfer/list'); } catch (_) { d = null; }
    if (!d || !d.ok) {
      this.el.querySelector('#tfList').innerHTML =
        `<div class="note">读不到收件箱。刷新页面试试；要是还不行，看电脑上那个黑窗口有没有报错。</div>`;
      return;
    }
    this.items = d.items || [];
    this.cfg = d.cfg || {};
    this.stats = d.stats || {};
    const lm = this.el.querySelector('#tfLimits');
    lm.textContent = `单文件上限 ${this.cfg.max_mb || '∞'} MB · 保留 ${this.cfg.keep_hours || '∞'} 小时`;
    this.render();
  },

  render() {
    const list = this.el.querySelector('#tfList');
    const st = this.stats || {};
    this.el.querySelector('#tfStat').textContent =
      `${st.count || 0} 个 · ${st.bytes_h || '0 B'}`;
    this.el.querySelector('#tfBar').style.width =
      Math.min(100, +st.used_pct || 0) + '%';
    this.el.querySelector('#tfBar').title =
      `已用 ${st.bytes_h || '0 B'}${st.quota_mb ? ' / 上限 ' + st.quota_mb + ' MB' : '（不限）'} · 盘上剩 ${st.free_h || '?'}`;

    if (!this.items.length) {
      list.innerHTML = `<div class="note">空的。上面拖文件进来，或者用手机打开这个页面传。</div>`;
      return;
    }
    list.innerHTML = this.items.map((it) => {
      const left = this._left(it.expire_at);
      return `<div class="tf-item" data-id="${esc(it.id)}">
        <input type="checkbox" class="tf-ck" data-id="${esc(it.id)}">
        <span class="tf-ic">${iconOf(it)}</span>
        <span class="tf-n" title="${esc(it.name)}">${esc(it.name)}</span>
        <span class="tf-m">${esc(it.size_h)}</span>
        <span class="tf-m tf-from">${esc(it.src || '')}</span>
        <span class="tf-m tf-ago">${this._ago(it.created)}</span>
        <span class="tf-m tf-left" title="下载次数">${it.hits ? '↓' + it.hits : ''}${left ? ' · ' + left : ''}</span>
        <a class="btn tf-dl" href="/api/transfer/get?id=${encodeURIComponent(it.id)}" download>下载</a>
        <button class="x tf-x" data-id="${esc(it.id)}">×</button>
      </div>`;
    }).join('');
  },

  onClick(e) {
    const x = e.target.closest('.tf-x');
    if (!x) return;
    const id = x.dataset.id;
    const it = this.items.find((i) => i.id === id);
    if (!confirm(`删掉「${it ? it.name : id}」？`)) return;
    post('/api/transfer/del', { ids: [id] }).then(() => this.refresh()).catch(() => toast('删除失败'));
  },

  toggleAll(on) {
    this.el.querySelectorAll('.tf-ck').forEach((c) => { c.checked = on; });
  },

  async delSelected() {
    const ids = Array.from(this.el.querySelectorAll('.tf-ck'))
      .filter((c) => c.checked).map((c) => c.dataset.id);
    if (!ids.length) { toast('先勾几个'); return; }
    if (!confirm(`删掉选中的 ${ids.length} 个文件？`)) return;
    try { const r = await post('/api/transfer/del', { ids }); toast(`删了 ${r.removed || 0} 个`); }
    catch (_) { toast('删除失败'); }
    this.el.querySelector('#tfSelAll').checked = false;
    this.refresh();
  },

  cfgDialog() {
    const c = this.cfg || {};
    const max = prompt('单个文件上限（MB，0 = 不限）：', c.max_mb);
    if (max === null) return;
    const quo = prompt('收件箱总容量上限（MB，0 = 不限）：', c.quota_mb);
    if (quo === null) return;
    const keep = prompt('文件保留多少小时（0 = 永不过期）：', c.keep_hours);
    if (keep === null) return;
    post('/api/transfer/cfg/save', {
      max_mb: +max || 0, quota_mb: +quo || 0, keep_hours: +keep || 0,
    }).then((r) => { this.cfg = (r && r.cfg) || this.cfg; toast('设置已存'); this.refresh(); })
      .catch(() => toast('保存失败'));
  },

  /* ---------------- 时间小工具 ---------------- */

  _ago(ts) {
    if (!ts) return '';
    const s = Math.floor(Date.now() / 1000 - ts);
    if (s < 60) return s + '秒前';
    if (s < 3600) return Math.floor(s / 60) + '分前';
    if (s < 86400) return Math.floor(s / 3600) + '时前';
    return Math.floor(s / 86400) + '天前';
  },

  _left(expireAt) {
    if (!expireAt) return '';
    const s = Math.floor(expireAt - Date.now() / 1000);
    if (s <= 0) return '要过期了';
    if (s < 3600) return Math.floor(s / 60) + '分后过期';
    if (s < 86400) return Math.floor(s / 3600) + '时后过期';
    return Math.floor(s / 86400) + '天后过期';
  },

  badge(d) {
    const n = d && d.counts && d.counts.transfer;
    return n ? String(n) : '';
  },

  onShow() { this.refresh(); },

  commands() {
    return [
      { title: '互传：刷新收件箱', hint: '互传', run: () => this.refresh() },
      {
        title: '互传：清空收件箱',
        hint: '互传',
        run: () => { if (confirm('清空收件箱？')) post('/api/transfer/clear').then(() => this.refresh()); },
      },
    ];
  },
};
