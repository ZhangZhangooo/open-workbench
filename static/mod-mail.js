/* 邮件 G 域：直连 IMAP/SMTP（邮箱大师没有开放 API）。
   63 多账号 / 64 收件规则 / 65 附件批量下载 / 66 转待办 /
   67 正文搜索 / 68 草稿箱 / 69 定时发送 / 70 未读角标 */

const { api, post, toast, esc, fmtSize } = window.WB;

const PRESETS = {
  '163': ['imap.163.com', 993, 'smtp.163.com', 465],
  '126': ['imap.126.com', 993, 'smtp.126.com', 465],
  'yeah': ['imap.yeah.net', 993, 'smtp.yeah.net', 465],
  'qq': ['imap.qq.com', 993, 'smtp.qq.com', 465],
  'gmail': ['imap.gmail.com', 993, 'smtp.gmail.com', 465],
  'outlook': ['outlook.office365.com', 993, 'smtp.office365.com', 587],
};

const DRAFT_KEY = 'wb_mail_draft';

const OUT_TEXT = { pending: '排队中', sent: '已发送', failed: '失败', canceled: '已取消' };
const OUT_TAG = { pending: '', sent: 'ok', failed: 'err', canceled: '' };

/* 引用原文：每行前加 > */
function quote(text, prefix = '> ') {
  return (text || '').split('\n').map((l) => prefix + l).join('\n');
}

function p2(n) { return String(n).padStart(2, '0'); }

/* 时间戳（秒）→ "2026-09-27 15:04" */
function fmtAt(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/* 时间戳 → <input type="datetime-local"> 需要的值；不给就默认一小时后 */
function toLocalInput(ts) {
  const d = ts ? new Date(ts * 1000) : new Date(Date.now() + 3600 * 1000);
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}`;
}

/* 未读角标自己驱动服务端缓存：status 每 2 秒轮一次，不能在那里等 IMAP。
   这里每 2 分钟轻轻敲一次 /api/mail/unread，值由 /api/status 回读。 */
let _unreadAt = 0;

export default {
  id: 'mail',
  name: '邮件',
  el: null,
  current: null,     // 正在看的那封
  acctId: '',
  accts: [],
  draftId: 0,
  _tab: 'inbox',
  _inboxLoaded: false,

  /* ---------- 70 未读角标 ---------- */
  badge(d) {
    const cfg = (d && d.config) || {};
    const m = cfg.mail || {};
    const n = cfg.mail_unread || 0;
    const now = Date.now();
    if (m.user && now - _unreadAt > 120000) {
      _unreadAt = now;
      api('/api/mail/unread').catch(() => {});
    }
    return n > 0 ? String(n) : '';
  },

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="tabs" id="mailTabs">
          <button class="tab on" data-tab="inbox">收件箱</button>
          <button class="tab" data-tab="compose">写邮件</button>
          <button class="tab" data-tab="drafts">草稿箱</button>
          <button class="tab" data-tab="outbox">发件箱</button>
          <button class="tab" data-tab="accounts">账号</button>
          <button class="tab" data-tab="rules">规则</button>
        </div>

        <!-- 收件箱 -->
        <div data-pane="inbox">
          <div class="panel">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
              <button class="btn" id="btnRefresh" style="height:30px;padding:0 12px;font-size:12px">刷新</button>
              <label style="font-size:12.5px;color:var(--ink-2);display:flex;gap:6px;align-items:center">
                <input type="checkbox" id="mUnseen"> 只看未读
              </label>
              <input id="mSearch" placeholder="搜主题或发件人" style="flex:1;min-width:130px;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
              <input id="mFull" placeholder="搜正文（搜本机缓存过的信，离线也能搜）" style="flex:1;min-width:130px;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
              <button class="btn" id="btnFull" style="height:30px;padding:0 12px;font-size:12px">搜正文</button>
            </div>
            <div id="mailList" class="note">还没连</div>
          </div>

          <div class="panel" id="mailViewPanel" style="display:none">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
              <h3 style="margin:0">读信</h3>
              <button class="btn" id="btnReply" style="height:28px;padding:0 10px;font-size:12px">回复</button>
              <button class="btn" id="btnForward" style="height:28px;padding:0 10px;font-size:12px">转发</button>
              <button class="btn" id="btnCloseMail" style="height:28px;padding:0 10px;font-size:12px;margin-left:auto">收起</button>
            </div>
            <div id="mailView"></div>
          </div>
        </div>

        <!-- 写邮件 -->
        <div data-pane="compose" style="display:none">
          <div class="panel">
            <h3>写邮件</h3>
            <div class="field"><label>收件人</label><input id="mTo" placeholder="someone@example.com"></div>
            <div class="field"><label>主题</label><input id="mSubj"></div>
            <div class="field">
              <label>正文</label>
              <textarea id="mBody" rows="9" placeholder="正文，可以直接换行。Ctrl + Enter 发送"></textarea>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <button class="btn primary" id="btnSendMail">发送</button>
              <button class="btn" id="btnSaveDraft" style="height:32px;padding:0 12px;font-size:12px">存草稿</button>
              <button class="btn" id="btnClearMail" style="height:32px;padding:0 12px;font-size:12px">清空</button>
              <span id="sendState"></span>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;border-top:1px solid var(--line-soft);padding-top:12px">
              <span class="note" style="margin:0">定时发送</span>
              <input type="datetime-local" id="mAt" style="height:30px;padding:0 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
              <button class="btn" id="btnSchedule" style="height:30px;padding:0 12px;font-size:12px">加入发件箱</button>
              <span id="scheduleState"></span>
            </div>
          </div>
        </div>

        <!-- 草稿箱 -->
        <div data-pane="drafts" style="display:none">
          <div class="panel">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <h3 style="margin:0">草稿箱</h3>
              <button class="btn" id="btnNewDraft" style="height:28px;padding:0 10px;font-size:12px">写新邮件</button>
            </div>
            <div id="draftList" class="note">读取中…</div>
          </div>
        </div>

        <!-- 发件箱 -->
        <div data-pane="outbox" style="display:none">
          <div class="panel">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <h3 style="margin:0">发件箱（定时）</h3>
              <button class="btn" id="btnOutboxRun" style="height:28px;padding:0 10px;font-size:12px">立即检查发送</button>
            </div>
            <div class="note" style="margin-bottom:8px">到点的邮件由后台每 20 秒自动发一次，这里可以手动催一下。</div>
            <div id="outboxList" class="note">读取中…</div>
          </div>
        </div>

        <!-- 账号 -->
        <div data-pane="accounts" style="display:none">
          <div class="panel">
            <h3>邮箱账号</h3>
            <div class="note" style="margin-bottom:10px">
              可以挂多个邮箱。密码那一栏填<b>授权码</b>，不是登录密码 ——
              要去邮箱网页版设置里开启 IMAP/SMTP 服务后生成。
            </div>
            <div id="acctList"></div>
            <button class="btn primary" id="btnAcctNew" style="margin-top:10px">+ 新增账号</button>

            <div id="acctForm" style="display:none;margin-top:12px;border-top:1px solid var(--line-soft);padding-top:12px">
              <div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap">
                ${Object.keys(PRESETS).map((k) => `<button class="btn" data-preset="${k}" style="height:28px;padding:0 10px;font-size:12px">${k}</button>`).join('')}
              </div>
              <div class="field"><label>备注名</label><input id="acctName" placeholder="比如 主力邮箱"></div>
              <div class="field"><label>邮箱</label><input id="mUser" placeholder="you@163.com"></div>
              <div class="field"><label>授权码</label><input id="mPass" type="password" placeholder="留空则不改"></div>
              <div class="field"><label>IMAP</label><input id="mImap" placeholder="imap.163.com"></div>
              <div class="field"><label>IMAP 端口</label><input id="mImapPort" value="993"></div>
              <div class="field"><label>SMTP</label><input id="mSmtp" placeholder="smtp.163.com"></div>
              <div class="field"><label>SMTP 端口</label><input id="mSmtpPort" value="465"></div>
              <div class="field"><label>加密</label>
                <select id="mTls" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12.5px">
                  <option value="">自动（465 SSL / 587 STARTTLS）</option>
                  <option value="ssl">强制 SSL</option>
                  <option value="starttls">STARTTLS</option>
                  <option value="none">不加密（本机中继）</option>
                </select>
              </div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <button class="btn primary" id="btnSaveMail">保存并测试</button>
                <button class="btn" id="btnAcctCancel" style="height:32px;padding:0 12px;font-size:12px">取消</button>
                <span id="mailCfgState"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 规则 -->
        <div data-pane="rules" style="display:none">
          <div class="panel">
            <h3>收件规则</h3>
            <div class="note" style="margin-bottom:10px">来信命中就自动打标签，收件箱列表里直接显示。</div>
            <div id="ruleList" class="note">读取中…</div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;border-top:1px solid var(--line-soft);padding-top:12px">
              <input id="rName" placeholder="规则名" style="width:110px;height:30px;padding:0 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
              <select id="rField" style="height:30px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
                <option value="from">发件人</option>
                <option value="subject">主题</option>
                <option value="any">都看</option>
              </select>
              <input id="rContains" placeholder="包含…" style="width:140px;height:30px;padding:0 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
              <input id="rTag" placeholder="标签" style="width:90px;height:30px;padding:0 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
              <button class="btn" id="btnRuleAdd" style="height:30px;padding:0 12px;font-size:12px">添加</button>
            </div>
          </div>
        </div>
      </div>`;

    // 标签页
    el.querySelectorAll('#mailTabs .tab').forEach((b) => {
      b.onclick = () => this.tab(b.dataset.tab);
    });

    // 预设
    el.querySelectorAll('[data-preset]').forEach((b) => {
      b.onclick = () => {
        const [ih, ip, sh, sp] = PRESETS[b.dataset.preset];
        el.querySelector('#mImap').value = ih;
        el.querySelector('#mImapPort').value = ip;
        el.querySelector('#mSmtp').value = sh;
        el.querySelector('#mSmtpPort').value = sp;
      };
    });

    // 收件箱
    el.querySelector('#btnRefresh').onclick = () => { this._inboxLoaded = true; this.load(); };
    el.querySelector('#mUnseen').onchange = () => this.load();
    el.querySelector('#mSearch').addEventListener('keydown', (e) => { if (e.key === 'Enter') this.load(); });
    el.querySelector('#btnFull').onclick = () => this.fullSearch();
    el.querySelector('#mFull').addEventListener('keydown', (e) => { if (e.key === 'Enter') this.fullSearch(); });

    // 读信
    el.querySelector('#btnReply').onclick = () => this.reply(false);
    el.querySelector('#btnForward').onclick = () => this.reply(true);
    el.querySelector('#btnCloseMail').onclick = () => this.closeView();

    // 写信
    el.querySelector('#btnSendMail').onclick = () => this.send();
    el.querySelector('#btnSaveDraft').onclick = () => this.saveDraftToServer(true);
    el.querySelector('#btnClearMail').onclick = () => this.clearCompose();
    el.querySelector('#btnSchedule').onclick = () => this.schedule();
    el.querySelector('#mBody').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.send(); }
    });

    // 草稿箱 / 发件箱
    el.querySelector('#btnNewDraft').onclick = () => { this.draftId = 0; this.tab('compose'); };
    el.querySelector('#btnOutboxRun').onclick = () => this.outboxRun();

    // 账号
    el.querySelector('#btnAcctNew').onclick = () => this.showAcctForm(null);
    el.querySelector('#btnAcctCancel').onclick = () => this.hideAcctForm();
    el.querySelector('#btnSaveMail').onclick = () => this.saveAcct();

    // 规则
    el.querySelector('#btnRuleAdd').onclick = () => this.addRule();

    // 草稿自动存，写一半关掉页面不至于丢
    ['#mTo', '#mSubj', '#mBody'].forEach((sel) => {
      el.querySelector(sel).addEventListener('input', () => this.saveLocalDraft());
    });

    el.querySelector('#mAt').value = toLocalInput(0);
    this.restoreLocalDraft();
  },

  tab(name) {
    const el = this.el;
    this._tab = name;
    el.querySelectorAll('#mailTabs .tab').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    el.querySelectorAll('[data-pane]').forEach((p) => { p.style.display = p.dataset.pane === name ? '' : 'none'; });
    if (name === 'drafts') this.loadDrafts();
    else if (name === 'outbox') this.loadOutbox();
    else if (name === 'accounts') this.loadAccounts();
    else if (name === 'rules') this.loadRules();
    else if (name === 'inbox' && !this._inboxLoaded) { this._inboxLoaded = true; this.load(); }
  },

  onShow() {
    this.loadAccounts();
    this.loadRules();
    if (this._tab === 'inbox' && !this._inboxLoaded) { this._inboxLoaded = true; this.load(); }
  },

  /* ---------- 63 多账号 ---------- */

  async loadAccounts() {
    const d = await api('/api/mail/accounts');
    this.acctId = d.active || '';
    this.accts = d.rows || [];
    const box = this.el.querySelector('#acctList');
    if (!this.accts.length) {
      box.innerHTML = '<div class="note">还没加账号，点下面新增一个</div>';
      return;
    }
    box.innerHTML = this.accts.map((a) => `<div class="item" style="align-items:center">
      <div class="s" style="white-space:normal;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
        <b>${esc(a.name || a.user)}</b>
        <span style="color:var(--ink-3)">${esc(a.user)}</span>
        ${a.active ? '<span class="tag ok">当前</span>' : ''}
        ${a.password_set ? '' : '<span class="tag err">缺授权码</span>'}
        <span style="margin-left:auto"></span>
        ${a.active ? '' : `<button class="btn" data-act="${esc(String(a.id))}" style="height:26px;padding:0 8px;font-size:12px">启用</button>`}
        <button class="btn" data-edit="${esc(String(a.id))}" style="height:26px;padding:0 8px;font-size:12px">编辑</button>
        <button class="btn" data-del="${esc(String(a.id))}" style="height:26px;padding:0 8px;font-size:12px">删</button>
      </div>
    </div>`).join('');
    box.querySelectorAll('[data-act]').forEach((n) => { n.onclick = () => this.activate(n.dataset.act); });
    box.querySelectorAll('[data-edit]').forEach((n) => {
      n.onclick = () => this.showAcctForm(this.accts.find((x) => String(x.id) === n.dataset.edit));
    });
    box.querySelectorAll('[data-del]').forEach((n) => { n.onclick = () => this.delAcct(n.dataset.del); });
  },

  showAcctForm(rec) {
    const el = this.el;
    const f = el.querySelector('#acctForm');
    f.style.display = '';
    el.querySelector('#acctId').value = rec ? String(rec.id) : '';
    el.querySelector('#acctName').value = rec ? (rec.name || '') : '';
    el.querySelector('#mUser').value = rec ? (rec.user || '') : '';
    el.querySelector('#mPass').value = '';
    el.querySelector('#mImap').value = rec ? (rec.imap_host || '') : '';
    el.querySelector('#mImapPort').value = rec ? (rec.imap_port || 993) : 993;
    el.querySelector('#mSmtp').value = rec ? (rec.smtp_host || '') : '';
    el.querySelector('#mSmtpPort').value = rec ? (rec.smtp_port || 465) : 465;
    el.querySelector('#mTls').value = rec ? (rec.smtp_tls || '') : '';
    el.querySelector('#mailCfgState').innerHTML = '';
  },

  hideAcctForm() {
    this.el.querySelector('#acctForm').style.display = 'none';
    this.el.querySelector('#mailCfgState').innerHTML = '';
  },

  async saveAcct() {
    const el = this.el;
    const pass = el.querySelector('#mPass').value;
    const body = {
      id: el.querySelector('#acctId').value.trim(),
      name: el.querySelector('#acctName').value.trim(),
      user: el.querySelector('#mUser').value.trim(),
      imap_host: el.querySelector('#mImap').value.trim(),
      imap_port: el.querySelector('#mImapPort').value.trim(),
      smtp_host: el.querySelector('#mSmtp').value.trim(),
      smtp_port: el.querySelector('#mSmtpPort').value.trim(),
      smtp_tls: el.querySelector('#mTls').value,
      ...(pass ? { password: pass } : {}),
    };
    const st = el.querySelector('#mailCfgState');
    if (!body.user) { st.innerHTML = '<span class="tag err">邮箱地址没填</span>'; return; }
    const d = await post('/api/mail/accounts/save', body);
    if (!d.ok) { st.innerHTML = `<span class="tag err">${esc(d.error || '存不了')}</span>`; return; }
    el.querySelector('#mPass').value = '';
    this.acctId = d.active || '';
    await this.loadAccounts();
    st.innerHTML = '<span class="tag">正在测试连接…</span>';
    const r = await post('/api/mail/test', {});
    st.innerHTML = this.diagHTML(r);
    if (r.ok) { this._inboxLoaded = true; this.load(); }
  },

  async activate(id) {
    const d = await post('/api/mail/accounts/active', { id });
    if (!d.ok) { toast(d.error || '切不过去'); return; }
    this.acctId = d.id;
    await this.loadAccounts();
    toast(`已切到 ${d.user || '该账号'}`);
    this._inboxLoaded = true;
    this.closeView();
    this.load();
  },

  async delAcct(id) {
    const a = this.accts.find((x) => String(x.id) === String(id));
    if (!window.confirm(`删掉账号「${(a && (a.name || a.user)) || id}」？配置会一起移除。`)) return;
    const d = await post('/api/mail/accounts/del', { id });
    if (d.ok) { await this.loadAccounts(); toast('已删除'); }
  },

  /* 邮箱连不上时只给一行报错等于没说，把每一步摊开 */
  diagHTML(r) {
    const steps = r.steps || [];
    const head = r.ok
      ? `<span class="tag ok">连接成功${r.count != null ? ` · 收件箱 ${r.count} 封` : ''}</span>`
      : `<span class="tag err">${esc(r.error || '失败')}</span>`;
    if (!steps.length) return head;
    const rows = steps.map((s) => `
      <div class="diag-row">
        <span class="tag ${s.ok ? 'ok' : 'err'}">${s.ok ? '通过' : '卡住'}</span>
        <span class="diag-name">${esc(s.name)}</span>
        <span class="diag-detail">${esc(s.detail || '')}</span>
      </div>`).join('');
    return `${head}<div class="diag">${rows}</div>`;
  },

  /* ---------- 收件箱 ---------- */

  async load() {
    const el = this.el;
    const q = el.querySelector('#mSearch').value.trim();
    const unseen = el.querySelector('#mUnseen').checked;
    const box = el.querySelector('#mailList');
    box.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api(`/api/mail/list?limit=40&unseen=${unseen ? 1 : 0}&q=${encodeURIComponent(q)}`);
    if (!d.ok) {
      box.innerHTML = `<span class="tag err">${esc(d.error || '读取失败')}</span>
        <div class="note" style="margin-top:8px">去「账号」标签点「保存并测试」，能看到卡在哪一步</div>`;
      return;
    }
    if (!d.rows.length) {
      box.innerHTML = '<div class="note">没有邮件</div>';
      return;
    }
    box.innerHTML = d.rows.map((r) => `<div class="item mail-item${this.current && this.current.uid === r.uid ? ' on' : ''}" data-uid="${esc(r.uid)}">
        <div class="t">${esc(r.date)}</div>
        <div class="s">${r.starred ? '<span style="color:var(--warn)">★</span> ' : ''}${esc(r.subject || '(无主题)')} <span style="color:var(--ink-3)">· ${esc(r.from)}</span>${r.tags ? ` <span class="tag" style="font-size:11px">${esc(r.tags)}</span>` : ''}</div>
      </div>`).join('');
    box.querySelectorAll('[data-uid]').forEach((n) => {
      n.onclick = () => this.open(n.dataset.uid);
    });
  },

  /* ---------- 67 正文搜索（本机缓存） ---------- */

  async fullSearch() {
    const el = this.el;
    const q = el.querySelector('#mFull').value.trim();
    const box = el.querySelector('#mailList');
    if (!q) { this.load(); return; }
    box.innerHTML = '<span class="tag">搜索中…</span>';
    const d = await api(`/api/mail/search?q=${encodeURIComponent(q)}`);
    const rows = d.rows || [];
    const head = `<div class="note">本机缓存里命中 ${rows.length} 封（共缓存 ${d.cached_total || 0} 封）</div>`;
    box.innerHTML = head + (rows.length ? rows.map((r) => `<div class="item mail-item" data-uid="${esc(r.uid)}">
        <div class="t">${esc((r.mdate || '').slice(5, 16))}</div>
        <div class="s" style="white-space:normal">${esc(r.subject || '(无主题)')} <span style="color:var(--ink-3)">· ${esc(r.mfrom)}</span>
          <div class="note" style="margin:2px 0 0;font-size:12px">${esc(r.snippet || '')}</div>
        </div>
      </div>`).join('') : '<div class="note">没搜到。读过的信才会缓存到本机，多读几封再搜。</div>');
    box.querySelectorAll('[data-uid]').forEach((n) => { n.onclick = () => this.open(n.dataset.uid); });
  },

  /* ---------- 读信（含 65 附件 / 66 转待办 / 星标 / 标签） ---------- */

  async open(uid) {
    const el = this.el;
    const panel = el.querySelector('#mailViewPanel');
    const view = el.querySelector('#mailView');
    panel.style.display = '';
    view.innerHTML = '<span class="tag">打开中…</span>';
    el.querySelectorAll('.mail-item').forEach((n) => n.classList.toggle('on', n.dataset.uid === uid));

    const d = await api(`/api/mail/read?uid=${encodeURIComponent(uid)}`);
    if (!d.ok) {
      view.innerHTML = `<span class="tag err">${esc(d.error || '打不开')}</span>`;
      return;
    }
    this.current = d;
    const auto = d.auto_tags || d.tags || '';
    view.innerHTML = `
      <div class="mail-head">
        <div class="mail-subj">${esc(d.subject || '(无主题)')}</div>
        <div class="mail-meta">${esc(d.from || '')}${d.date ? ' · ' + esc(d.date) : ''}</div>
        ${d.to ? `<div class="mail-meta">收件人：${esc(d.to)}</div>` : ''}
        ${auto ? `<div class="mail-meta">自动标签：${esc(auto)}</div>` : ''}
      </div>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
        <button class="btn" id="btnStar" style="height:28px;padding:0 10px;font-size:12px">${d.starred ? '★ 取消星标' : '☆ 星标'}</button>
        <button class="btn" id="btnTodo" style="height:28px;padding:0 10px;font-size:12px">转待办</button>
        ${d.attachments && d.attachments.length ? `<button class="btn" id="btnAtt" style="height:28px;padding:0 10px;font-size:12px">下载附件 (${d.attachments.length})</button>` : ''}
        <input id="mTags" value="${esc(d.my_tags || '')}" placeholder="自定义标签" style="width:130px;height:28px;padding:0 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
        <button class="btn" id="btnTag" style="height:28px;padding:0 10px;font-size:12px">存标签</button>
        <span id="readState"></span>
      </div>
      ${d.from_html ? '<div class="mail-meta" style="margin-bottom:8px">HTML 邮件，已转成纯文本</div>' : ''}
      <div class="mail-body">${esc(d.body || '(这封没有正文)')}</div>
      ${d.attachments && d.attachments.length
        ? `<div class="mail-atts">附件：${d.attachments.map((a) => `<span class="tag">${esc(a)}</span>`).join(' ')}</div>`
        : ''}
      <div id="attOut"></div>`;

    view.querySelector('#btnStar').onclick = () => this.star(d.uid);
    view.querySelector('#btnTodo').onclick = () => this.toTodo();
    view.querySelector('#btnTag').onclick = () => this.saveTags();
    const ba = view.querySelector('#btnAtt');
    if (ba) ba.onclick = () => this.saveAtt(d.uid);
  },

  async star(uid) {
    const d = await post('/api/mail/star', { uid });
    const st = this.el.querySelector('#readState');
    if (d.ok) {
      if (this.current) this.current.starred = d.starred ? 1 : 0;
      const b = this.el.querySelector('#btnStar');
      if (b) b.textContent = d.starred ? '★ 取消星标' : '☆ 星标';
      if (st) st.innerHTML = '<span class="tag ok">星标已更新</span>';
      this.load();
    } else if (st) st.innerHTML = '<span class="tag err">改不了星标</span>';
  },

  /* 66 转待办 */
  async toTodo() {
    const d = this.current;
    const st = this.el.querySelector('#readState');
    if (!d) return;
    const r = await post('/api/today/add', { text: `邮件：${d.subject || '(无主题)'} — ${d.from || ''}` });
    if (st) st.innerHTML = r.ok ? '<span class="tag ok">已加进今日待办</span>'
      : `<span class="tag err">${esc(r.error || '失败')}</span>`;
  },

  /* 65 附件批量下载 */
  async saveAtt(uid) {
    const st = this.el.querySelector('#readState');
    const out = this.el.querySelector('#attOut');
    st.innerHTML = '<span class="tag">下载中…</span>';
    const d = await post('/api/mail/att/save', { uid });
    if (!d.ok) { st.innerHTML = `<span class="tag err">${esc(d.error || '失败')}</span>`; return; }
    st.innerHTML = `<span class="tag ok">已存 ${d.count} 个</span>`;
    out.innerHTML = `<div class="note">存到：${esc(d.dir || '')}</div>`
      + (d.rows || []).map((r) => `<div class="item"><div class="s" style="white-space:normal">${esc(r.name)} <span style="color:var(--ink-3)">${fmtSize(r.size)}</span></div></div>`).join('')
      + (d.failed || []).map((f) => `<div class="note" style="color:var(--err)">${esc(f.name)}：${esc(f.error)}</div>`).join('');
  },

  async saveTags() {
    const uid = this.current && this.current.uid;
    const st = this.el.querySelector('#readState');
    if (!uid) return;
    const tags = this.el.querySelector('#mTags').value.trim();
    const d = await post('/api/mail/tag', { uid, tags });
    if (st) st.innerHTML = d.ok ? '<span class="tag ok">标签已存</span>' : '<span class="tag err">存不了</span>';
    if (d.ok) this.load();
  },

  closeView() {
    this.current = null;
    this.el.querySelector('#mailViewPanel').style.display = 'none';
    this.el.querySelectorAll('.mail-item').forEach((n) => n.classList.remove('on'));
  },

  /* 回复 / 转发：把原信内容带进写信区 */
  reply(forward) {
    const d = this.current;
    if (!d) return;
    const el = this.el;
    const to = forward ? '' : (d.reply_to || '');
    const subj = forward ? `Fwd: ${d.subject || ''}` : `Re: ${d.subject || ''}`;
    const head = forward
      ? `\n\n---------- 转发 ----------\n发件人：${d.from}\n日期：${d.date}\n主题：${d.subject}\n\n${d.body}`
      : `\n\n在 ${d.date}，${d.from} 写道：\n${quote(d.body)}`;

    this.draftId = 0;
    el.querySelector('#mTo').value = to;
    el.querySelector('#mSubj').value = subj;
    const body = el.querySelector('#mBody');
    body.value = head.trim();
    this.tab('compose');
    body.focus();
    body.setSelectionRange(0, 0);
    this.saveLocalDraft();
    toast(forward ? '已带进写信区，填收件人' : (to ? '已带进写信区' : '没解析出对方地址，手填一下'));
  },

  compose() {
    const el = this.el;
    return {
      to: el.querySelector('#mTo').value.trim(),
      subject: el.querySelector('#mSubj').value.trim(),
      body: el.querySelector('#mBody').value,
    };
  },

  /* 本机兜底草稿（防崩），真正的草稿箱是 68 那份 */
  saveLocalDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(this.compose())); } catch (_) { /* 存不了就算了 */ }
  },

  restoreLocalDraft() {
    let d = null;
    try { d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (_) { /* 坏了就当没有 */ }
    if (!d) return;
    const el = this.el;
    el.querySelector('#mTo').value = d.to || '';
    el.querySelector('#mSubj').value = d.subject || '';
    el.querySelector('#mBody').value = d.body || '';
  },

  clearCompose() {
    const el = this.el;
    this.draftId = 0;
    el.querySelector('#mTo').value = '';
    el.querySelector('#mSubj').value = '';
    el.querySelector('#mBody').value = '';
    localStorage.removeItem(DRAFT_KEY);
  },

  async send() {
    const el = this.el;
    const st = el.querySelector('#sendState');
    const c = this.compose();
    if (!c.to) { st.innerHTML = '<span class="tag err">还没填收件人</span>'; return; }
    st.innerHTML = '<span class="tag">发送中…</span>';
    const d = await post('/api/mail/send', c);
    st.innerHTML = d.ok ? '<span class="tag ok">已发送</span>'
      : `<span class="tag err">${esc(d.error || '失败')}</span>`;
    if (d.ok) this.clearCompose();
  },

  /* ---------- 68 草稿箱 ---------- */

  async saveDraftToServer(tell) {
    const c = this.compose();
    if (!c.to && !c.subject && !c.body) { if (tell) toast('内容是空的'); return; }
    const d = await post('/api/mail/draft/save', { id: this.draftId || 0, ...c });
    if (d.ok) {
      this.draftId = d.id;
      if (tell) toast('已存进草稿箱');
    } else if (tell) toast(d.error || '存不了');
  },

  async loadDrafts() {
    const box = this.el.querySelector('#draftList');
    box.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api('/api/mail/drafts');
    const rows = d.rows || [];
    if (!rows.length) { box.innerHTML = '<div class="note">草稿箱是空的</div>'; return; }
    box.innerHTML = rows.map((r) => `<div class="item mail-item" data-draft="${r.id}">
      <div class="t">${esc(fmtAt(r.updated).slice(5, 16))}</div>
      <div class="s">${esc(r.subject || '(无主题)')} <span style="color:var(--ink-3)">· ${esc(r.mto || '未填收件人')}</span>
        <button class="btn" data-deldraft="${r.id}" style="height:24px;padding:0 8px;font-size:11.5px;margin-left:6px">删</button>
      </div>
    </div>`).join('');
    box.querySelectorAll('[data-draft]').forEach((n) => { n.onclick = () => this.openDraft(n.dataset.draft); });
    box.querySelectorAll('[data-deldraft]').forEach((n) => {
      n.onclick = (e) => { e.stopPropagation(); this.delDraft(n.dataset.deldraft); };
    });
  },

  async openDraft(id) {
    const d = await api(`/api/mail/draft?id=${encodeURIComponent(id)}`);
    const r = d.row || {};
    const el = this.el;
    this.draftId = r.id || 0;
    el.querySelector('#mTo').value = r.mto || '';
    el.querySelector('#mSubj').value = r.subject || '';
    el.querySelector('#mBody').value = r.body || '';
    this.tab('compose');
    toast('草稿已载入写信区');
  },

  async delDraft(id) {
    const d = await post('/api/mail/draft/del', { id });
    if (d.ok) { toast('已删除'); this.loadDrafts(); }
  },

  /* ---------- 69 定时发送 ---------- */

  async schedule() {
    const el = this.el;
    const st = el.querySelector('#scheduleState');
    const c = this.compose();
    const v = el.querySelector('#mAt').value;
    if (!c.to) { st.innerHTML = '<span class="tag err">先填收件人</span>'; return; }
    if (!v) { st.innerHTML = '<span class="tag err">选个发送时间</span>'; return; }
    const at = new Date(v).getTime() / 1000;
    if (!at || at <= 0) { st.innerHTML = '<span class="tag err">时间不对</span>'; return; }
    const d = await post('/api/mail/schedule', { ...c, at });
    st.innerHTML = d.ok ? `<span class="tag ok">已排队，${esc(fmtAt(at))} 发</span>`
      : `<span class="tag err">${esc(d.error || '入队失败')}</span>`;
    if (d.ok) { this.loadOutbox(); toast('已加入发件箱'); }
  },

  async loadOutbox() {
    const box = this.el.querySelector('#outboxList');
    box.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api('/api/mail/outbox');
    const rows = d.rows || [];
    const head = `<div class="note">排队中 ${d.pending || 0} 封</div>`;
    if (!rows.length) { box.innerHTML = head + '<div class="note">发件箱是空的</div>'; return; }
    box.innerHTML = head + rows.map((r) => `<div class="item" style="align-items:flex-start">
      <div class="t">${esc(fmtAt(r.at).slice(5))}</div>
      <div class="s" style="white-space:normal">
        ${esc(r.subject || '(无主题)')} <span style="color:var(--ink-3)">· ${esc(r.mto)}</span>
        <span class="tag ${OUT_TAG[r.status] || ''}">${OUT_TEXT[r.status] || esc(r.status)}</span>
        ${r.error ? `<div class="note" style="color:var(--err);margin:2px 0 0">${esc(r.error)}</div>` : ''}
      </div>
      ${r.status === 'pending' ? `<button class="btn" data-oc="${r.id}" style="height:26px;padding:0 8px;font-size:12px">取消</button>` : ''}
    </div>`).join('');
    box.querySelectorAll('[data-oc]').forEach((n) => { n.onclick = () => this.cancelOut(n.dataset.oc); });
  },

  async cancelOut(id) {
    const d = await post('/api/mail/outbox/cancel', { id });
    if (d.ok) { toast('已取消'); this.loadOutbox(); }
  },

  async outboxRun() {
    const d = await post('/api/mail/outbox/run', {});
    toast(`这轮处理了 ${d.processed || 0} 封`);
    this.loadOutbox();
  },

  /* ---------- 64 收件规则 ---------- */

  async loadRules() {
    const box = this.el.querySelector('#ruleList');
    box.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api('/api/mail/rules');
    const rows = d.rows || [];
    if (!rows.length) { box.innerHTML = '<div class="note">还没规则。加一条，比如「发件人包含 noreply 就标为 通知」。</div>'; return; }
    const F = { from: '发件人', subject: '主题', any: '都看' };
    box.innerHTML = rows.map((r) => `<div class="item" style="align-items:center">
      <div class="s" style="white-space:normal">
        <b>${esc(r.name || '(未命名)')}</b>
        <span style="color:var(--ink-3)">— ${esc(F[r.field] || r.field)} 含「${esc(r.contains)}」</span>
        ${r.tag ? ` <span class="tag">${esc(r.tag)}</span>` : ''}
      </div>
      <button class="btn" data-rule="${r.id}" style="height:26px;padding:0 8px;font-size:12px">删</button>
    </div>`).join('');
    box.querySelectorAll('[data-rule]').forEach((n) => { n.onclick = () => this.delRule(n.dataset.rule); });
  },

  async addRule() {
    const el = this.el;
    const name = el.querySelector('#rName').value.trim();
    const contains = el.querySelector('#rContains').value.trim();
    const tag = el.querySelector('#rTag').value.trim();
    const field = el.querySelector('#rField').value;
    if (!contains) { toast('「包含」要填'); return; }
    const d = await post('/api/mail/rules/save', { id: 0, name: name || contains, field, contains, tag });
    if (d.ok) {
      el.querySelector('#rName').value = '';
      el.querySelector('#rContains').value = '';
      el.querySelector('#rTag').value = '';
      toast('规则已加');
      this.loadRules();
      this._inboxLoaded = true;
      this.load();
    } else toast(d.error || '加不了');
  },

  async delRule(id) {
    const d = await post('/api/mail/rules/del', { id });
    if (d.ok) { toast('已删除'); this.loadRules(); }
  },

  commands() {
    return [
      { title: '刷新收件箱', hint: '邮件', run: () => { window.WB.go('mail'); this.tab('inbox'); this._inboxLoaded = true; this.load(); } },
      { title: '写新邮件', hint: '邮件', run: () => { window.WB.go('mail'); this.tab('compose'); } },
      { title: '打开草稿箱', hint: '邮件', run: () => { window.WB.go('mail'); this.tab('drafts'); } },
      { title: '看未读有几封', hint: '邮件', run: () => { api('/api/mail/unread?force=1').then((d) => toast(`未读 ${d.n || 0} 封`)); } },
    ];
  },
};
