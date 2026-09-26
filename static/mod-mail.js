/* 邮件：直连 IMAP/SMTP（网易邮箱大师没有开放 API，直接走标准协议） */

const { api, post, toast, esc } = window.WB;

const PRESETS = {
  '163': ['imap.163.com', 993, 'smtp.163.com', 465],
  '126': ['imap.126.com', 993, 'smtp.126.com', 465],
  'qq': ['imap.qq.com', 993, 'smtp.qq.com', 465],
  'gmail': ['imap.gmail.com', 993, 'smtp.gmail.com', 465],
};

const DRAFT_KEY = 'wb_mail_draft';

/* 引用原文：每行前加 > */
function quote(text, prefix = '> ') {
  return (text || '')
    .split('\n')
    .map((l) => prefix + l)
    .join('\n');
}

export default {
  id: 'mail',
  name: '邮件',
  el: null,
  current: null,   // 正在看的那封

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <h3>邮箱设置</h3>
          <div class="note" style="margin-bottom:12px">
            邮箱大师本身没有开放接口，所以这里直连 IMAP/SMTP。
            密码那一栏填<b>授权码</b>，不是登录密码 —— 要去邮箱网页版设置里开启 IMAP/SMTP 服务后生成。
          </div>
          <div style="display:flex;gap:6px;margin-bottom:10px">
            ${Object.keys(PRESETS).map((k) => `<button class="btn" data-preset="${k}" style="height:28px;padding:0 10px;font-size:12px">${k}</button>`).join('')}
          </div>
          <div class="field"><label>邮箱</label><input id="mUser" placeholder="you@163.com"></div>
          <div class="field"><label>授权码</label><input id="mPass" type="password" placeholder="留空则不改"></div>
          <div class="field"><label>IMAP</label><input id="mImap" placeholder="imap.163.com"></div>
          <div class="field"><label>IMAP 端口</label><input id="mImapPort" value="993"></div>
          <div class="field"><label>SMTP</label><input id="mSmtp" placeholder="smtp.163.com"></div>
          <div class="field"><label>SMTP 端口</label><input id="mSmtpPort" value="465"></div>
          <button class="btn primary" id="btnSaveMail">保存并测试</button>
          <span id="mailCfgState" style="margin-left:10px"></span>
        </div>

        <div class="panel">
          <h3>收件箱</h3>
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
            <button class="btn" id="btnRefresh" style="height:30px;padding:0 12px;font-size:12px">刷新</button>
            <label style="font-size:12.5px;color:var(--ink-2);display:flex;gap:6px;align-items:center">
              <input type="checkbox" id="mUnseen"> 只看未读
            </label>
            <input id="mSearch" placeholder="搜主题或发件人" style="flex:1;min-width:140px;height:30px;padding:0 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink);font-size:12px">
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

        <div class="panel">
          <h3>写邮件</h3>
          <div class="field"><label>收件人</label><input id="mTo" placeholder="someone@example.com"></div>
          <div class="field"><label>主题</label><input id="mSubj"></div>
          <div class="field">
            <label>正文</label>
            <textarea id="mBody" rows="8" placeholder="正文，可以直接换行。Ctrl + Enter 发送"></textarea>
          </div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <button class="btn primary" id="btnSendMail">发送</button>
            <button class="btn" id="btnDraft" style="height:32px;padding:0 12px;font-size:12px">存草稿</button>
            <button class="btn" id="btnClearMail" style="height:32px;padding:0 12px;font-size:12px">清空</button>
            <span id="sendState"></span>
          </div>
        </div>
      </div>`;

    el.querySelectorAll('[data-preset]').forEach((b) => {
      b.onclick = () => {
        const [ih, ip, sh, sp] = PRESETS[b.dataset.preset];
        el.querySelector('#mImap').value = ih;
        el.querySelector('#mImapPort').value = ip;
        el.querySelector('#mSmtp').value = sh;
        el.querySelector('#mSmtpPort').value = sp;
      };
    });

    el.querySelector('#btnSaveMail').onclick = () => this.save();
    el.querySelector('#btnRefresh').onclick = () => this.load();
    el.querySelector('#mUnseen').onchange = () => this.load();
    el.querySelector('#mSearch').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.load();
    });
    el.querySelector('#btnSendMail').onclick = () => this.send();
    el.querySelector('#btnDraft').onclick = () => this.saveDraft(true);
    el.querySelector('#btnClearMail').onclick = () => this.clearCompose();
    el.querySelector('#btnReply').onclick = () => this.reply(false);
    el.querySelector('#btnForward').onclick = () => this.reply(true);
    el.querySelector('#btnCloseMail').onclick = () => this.closeView();

    el.querySelector('#mBody').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.send();
      }
    });

    // 草稿自动存，写一半关掉页面不至于丢
    ['#mTo', '#mSubj', '#mBody'].forEach((sel) => {
      el.querySelector(sel).addEventListener('input', () => this.saveDraft(false));
    });

    this.restoreDraft();
    this.sync();
  },

  sync() {
    const s = window.WB.status();
    if (!s) return;
    const m = s.config.mail || {};
    const el = this.el;
    if (!el.querySelector('#mUser').value && m.user) el.querySelector('#mUser').value = m.user;
    if (!el.querySelector('#mImap').value && m.imap_host) el.querySelector('#mImap').value = m.imap_host;
    if (!el.querySelector('#mSmtp').value && m.smtp_host) el.querySelector('#mSmtp').value = m.smtp_host;
  },

  async save() {
    const el = this.el;
    const pass = el.querySelector('#mPass').value;
    const body = {
      mail: {
        user: el.querySelector('#mUser').value.trim(),
        imap_host: el.querySelector('#mImap').value.trim(),
        imap_port: el.querySelector('#mImapPort').value.trim(),
        smtp_host: el.querySelector('#mSmtp').value.trim(),
        smtp_port: el.querySelector('#mSmtpPort').value.trim(),
        ...(pass ? { password: pass } : {}),
      },
    };
    await post('/api/config', body);
    el.querySelector('#mPass').value = '';
    const st = el.querySelector('#mailCfgState');
    st.innerHTML = '<span class="tag">正在测试连接…</span>';
    const r = await post('/api/mail/test', {});
    st.innerHTML = this.diagHTML(r);
    if (r.ok) this.load();
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

  async load() {
    const el = this.el;
    const q = el.querySelector('#mSearch').value.trim();
    const unseen = el.querySelector('#mUnseen').checked;
    const box = el.querySelector('#mailList');
    box.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api(`/api/mail/list?limit=40&unseen=${unseen ? 1 : 0}&q=${encodeURIComponent(q)}`);
    if (!d.ok) {
      box.innerHTML = `<span class="tag err">${esc(d.error || '读取失败')}</span>
        <div class="note" style="margin-top:8px">点上面「保存并测试」，能看到卡在哪一步</div>`;
      return;
    }
    if (!d.rows.length) {
      box.innerHTML = '<div class="note">没有邮件</div>';
      return;
    }
    box.innerHTML = d.rows
      .map((r) => `<div class="item mail-item${this.current && this.current.uid === r.uid ? ' on' : ''}" data-uid="${esc(r.uid)}">
        <div class="t">${esc(r.date)}</div>
        <div class="s">${esc(r.subject || '(无主题)')} <span style="color:var(--ink-3)">· ${esc(r.from)}</span></div>
      </div>`)
      .join('');
    box.querySelectorAll('[data-uid]').forEach((n) => {
      n.onclick = () => this.open(n.dataset.uid);
    });
  },

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
    view.innerHTML = `
      <div class="mail-head">
        <div class="mail-subj">${esc(d.subject || '(无主题)')}</div>
        <div class="mail-meta">${esc(d.from || '')}${d.date ? ' · ' + esc(d.date) : ''}</div>
        ${d.to ? `<div class="mail-meta">收件人：${esc(d.to)}</div>` : ''}
      </div>
      ${d.from_html ? '<div class="mail-meta" style="margin-bottom:8px">HTML 邮件，已转成纯文本</div>' : ''}
      <div class="mail-body">${esc(d.body || '(这封没有正文)')}</div>
      ${d.attachments && d.attachments.length
        ? `<div class="mail-atts">附件：${d.attachments.map((a) => `<span class="tag">${esc(a)}</span>`).join(' ')}</div>`
        : ''}`;
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

    el.querySelector('#mTo').value = to;
    el.querySelector('#mSubj').value = subj;
    const body = el.querySelector('#mBody');
    body.value = head.trim();
    body.focus();
    body.setSelectionRange(0, 0);
    this.saveDraft(false);
    window.WB.toast(forward ? '已带进写信区，填收件人' : (to ? '已带进写信区' : '没解析出对方地址，手填一下'));
  },

  compose() {
    const el = this.el;
    return {
      to: el.querySelector('#mTo').value.trim(),
      subject: el.querySelector('#mSubj').value.trim(),
      body: el.querySelector('#mBody').value,
    };
  },

  saveDraft(tell) {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(this.compose()));
    } catch (_) { /* 存不了就算了 */ }
    if (tell) window.WB.toast('草稿已存（在本机浏览器里）');
  },

  restoreDraft() {
    let d = null;
    try {
      d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
    } catch (_) { /* 坏了就当没有 */ }
    if (!d) return;
    const el = this.el;
    el.querySelector('#mTo').value = d.to || '';
    el.querySelector('#mSubj').value = d.subject || '';
    el.querySelector('#mBody').value = d.body || '';
  },

  clearCompose() {
    const el = this.el;
    el.querySelector('#mTo').value = '';
    el.querySelector('#mSubj').value = '';
    el.querySelector('#mBody').value = '';
    localStorage.removeItem(DRAFT_KEY);
  },

  async send() {
    const el = this.el;
    const st = el.querySelector('#sendState');
    const c = this.compose();
    if (!c.to) {
      st.innerHTML = '<span class="tag err">还没填收件人</span>';
      return;
    }
    st.innerHTML = '<span class="tag">发送中…</span>';
    const d = await post('/api/mail/send', c);
    st.innerHTML = d.ok
      ? '<span class="tag ok">已发送</span>'
      : `<span class="tag err">${esc(d.error || '失败')}</span>`;
    if (d.ok) this.clearCompose();
  },

  onShow() {
    this.sync();
  },

  commands() {
    return [
      { title: '刷新收件箱', hint: '邮件', run: () => this.load() },
    ];
  },
};
