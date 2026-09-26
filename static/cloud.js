/* 多设备云同步层
 * - 仅在「已发布域名 + 已登录」时激活；本地 Flask 版（localhost）完全不受影响。
 * - 把 tasks/projects/reminders/today/kv 这几个集合的读写翻译成云数据库（wb_docs 表）。
 * - 设备本地功能（文件/系统/邮件/AI/终端）在云模式下安全降级，不会崩。
 * publicConfig 的 publishableKey 是客户端公开值，可安全打包进前端。
 */
(function () {
  'use strict';

  const PUBLIC = {
    endpoint: 'https://manman-workbench-37493.app.workbuddy.host',
    publishableKey: 'wbpk_UtmULpzXBWZRDM5c3BqqAm_KeCuhcjW64Hi2ROmGADACR72Vmgd2Yh1',
  };

  // 走云端的集合
  const SYNC = ['tasks', 'projects', 'reminders', 'today', 'kv'];

  const isPublished = () => {
    const h = location.hostname;
    return h !== 'localhost' && h !== '127.0.0.1' && h !== '0.0.0.0';
  };

  let cloud = null;          // WorkBuddyCloud 实例
  let active = false;        // 是否处于云模式（已发布域名）
  let ready = false;         // 是否已登录、可服务云端请求
  let user = null;           // 当前用户
  let lastSync = 0;          // 上次同步时间戳
  const listeners = new Set();

  function emit() { listeners.forEach((f) => { try { f(state()); } catch (_) {} }); }
  function state() {
    return { active, ready, user, lastSync, published: isPublished() };
  }
  function onSyncChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

  function newId() {
    // 数值 id（模块用 +id 还原），避免碰撞
    return Date.now() % 1000000000000 * 1000 + Math.floor(Math.random() * 1000);
  }

  /* ---------- 云文档存储（wb_docs：collection + doc_id 主键，payload 为整行） ---------- */

  const db = {
    async list(col) {
      const { data, error } = await cloud.database
        .from('wb_docs').select('payload').eq('collection', col);
      if (error) throw error;
      return (data || []).map((r) => r.payload);
    },
    async get(col, docId) {
      const { data, error } = await cloud.database
        .from('wb_docs').select('payload').eq('collection', col).eq('doc_id', String(docId)).maybeSingle();
      if (error) throw error;
      return data ? data.payload : null;
    },
    async upsert(col, docId, payload) {
      const { error } = await cloud.database.from('wb_docs').upsert({
        collection: col, doc_id: String(docId), payload,
        updated_at: new Date().toISOString(),
      });
      if (error) throw error;
    },
    async merge(col, docId, patch) {
      const cur = await db.get(col, docId) || {};
      await db.upsert(col, docId, Object.assign({}, cur, patch, { id: cur.id != null ? cur.id : Number(docId) }));
    },
    async remove(col, docId) {
      const { error } = await cloud.database
        .from('wb_docs').delete().eq('collection', col).eq('doc_id', String(docId));
      if (error) throw error;
    },
  };

  /* ---------- 路由：/api/<col> 是否由云端接管 ---------- */

  function parse(path) {
    const u = new URL(path, location.origin);
    const col = u.pathname.replace(/^\/api\//, '').split('/')[0];
    return { u, col, q: u.searchParams };
  }

  function canServe(path) {
    if (!ready) return false;
    const { col } = parse(path);
    return SYNC.includes(col);
  }

  async function serveApi(path) {
    const { col, q } = parse(path);
    if (col === 'kv') {
      const k = q.get('k');
      const doc = k ? await db.get('kv', k) : null;
      return { v: doc ? doc.v : null };
    }
    let rows = await db.list(col);
    if (col === 'tasks') {
      const pid = q.get('project_id');
      if (pid && pid !== '0') rows = rows.filter((r) => String(r.project_id) === String(pid));
    }
    if (col === 'today') {
      const d = q.get('day');
      if (d) rows = rows.filter((r) => r.day === d);
    }
    return { rows };
  }

  async function servePost(path, obj) {
    const { col } = parse(path);
    const seg = path.split('/');
    const action = seg[2]; // save/state/del/due/add/done/toggle/set
    if (col === 'kv') { await db.upsert('kv', obj.k, { k: obj.k, v: obj.v }); lastSync = Date.now(); emit(); return { ok: true }; }
    if (action === 'save') {
      const id = obj.id != null ? obj.id : newId();
      await db.upsert(col, String(id), Object.assign({}, obj, { id }));
      lastSync = Date.now(); emit(); return { ok: true, id };
    }
    if (action === 'add') { // reminders.add {at,text}
      const id = newId();
      await db.upsert(col, String(id), { id, at: obj.at, text: obj.text, done: 0, created: Date.now() / 1000 });
      lastSync = Date.now(); emit(); return { ok: true, id };
    }
    if (action === 'state') { await db.merge(col, String(obj.id), { state: obj.state }); lastSync = Date.now(); emit(); return { ok: true }; }
    if (action === 'due') { await db.merge(col, String(obj.id), { due: obj.due }); lastSync = Date.now(); emit(); return { ok: true }; }
    if (action === 'done') { await db.merge(col, String(obj.id), { done: obj.done }); lastSync = Date.now(); emit(); return { ok: true }; }
    if (action === 'del') { await db.remove(col, String(obj.id)); lastSync = Date.now(); emit(); return { ok: true }; }
    if (action === 'toggle') {
      const cur = await db.get(col, String(obj.id));
      const done = cur ? (cur.done ? 0 : 1) : 1;
      await db.merge(col, String(obj.id), { done });
      lastSync = Date.now(); emit(); return { ok: true };
    }
    throw new Error('unsupported cloud op ' + path);
  }

  // 云模式下本机功能：若用户配了"本机后端地址"（自托管 / 内网穿透），真去打本机；否则安全降级占位
  async function localOnlyApi(path) {
    const base = (localStorage.getItem('wb_local_backend') || '').trim().replace(/\/+$/, '');
    if (base) {
      const key = (localStorage.getItem('wb_local_key') || '').trim();
      try {
        const r = await fetch(base + path, { headers: key ? { 'X-Access-Key': key } : {} });
        if (r.ok) return await r.json();
        if (r.status === 401) return { rows: [], _localOnly: true, _needKey: true };
        return { rows: [], _localOnly: true, _err: 'HTTP ' + r.status };
      } catch (e) { return { rows: [], _localOnly: true, _err: e.message }; }
    }
    if (/\/api\/(tasks|projects|reminders|today|kv)/.test(path)) return null;
    return { rows: [], _localOnly: true };
  }
  async function localOnlyPost(path, obj) {
    const base = (localStorage.getItem('wb_local_backend') || '').trim().replace(/\/+$/, '');
    if (base) {
      const key = (localStorage.getItem('wb_local_key') || '').trim();
      try {
        const r = await fetch(base + path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Access-Key': key } : {}) },
          body: JSON.stringify(obj || {}),
        });
        if (r.ok) return await r.json();
        return { ok: false, _localOnly: true, _err: 'HTTP ' + r.status };
      } catch (e) { return { ok: false, _localOnly: true, _err: e.message }; }
    }
    return { ok: false, _localOnly: true };
  }

  /* ---------- 初始化（仅发布域名） ---------- */

  async function init() {
    if (!isPublished()) return false;        // 本地版不激活
    active = true;                            // 发布域名即进入云模式（即使 SDK 没加载也走降级，避免 404 崩模块）
    if (typeof window.WorkBuddyCloud === 'undefined') {
      console.warn('[cloud] SDK 未加载，云同步不可用');
      ready = false;
      emit();
      return true;
    }
    cloud = window.WorkBuddyCloud.createWorkBuddyCloud({
      endpoint: PUBLIC.endpoint,
      publishableKey: PUBLIC.publishableKey,
    });
    cloud.auth.onAuthStateChange((_event, session) => {
      user = session && session.user ? session.user : null;
      ready = !!user;
      emit();
      if (ready) renderGate(false);
    });
    const { data: sess } = await cloud.auth.getSession();
    user = sess && sess.user ? sess.user : null;
    ready = !!user;
    emit();
    return true;
  }

  /* ---------- 登录界面 ---------- */

  function ensureModal() {
    if (document.getElementById('cloudGate')) return document.getElementById('cloudGate');
    const d = document.createElement('div');
    d.id = 'cloudGate';
    d.className = 'cloud-gate';
    d.innerHTML = `<div class="cg-box">
      <div class="cg-title">登录以同步工作台</div>
      <div class="cg-sub">用同一账号在台式机和手机打开，数据自动共享</div>
      <div class="cg-tabs">
        <button class="cg-tab on" data-t="pw">密码登录</button>
        <button class="cg-tab" data-t="otp">验证码登录</button>
        <button class="cg-tab" data-t="up">注册</button>
      </div>
      <input id="cgEmail" class="cg-in" placeholder="邮箱" autocomplete="email">
      <input id="cgPw" class="cg-in" placeholder="密码（注册时填）" type="password" autocomplete="off">
      <input id="cgOtp" class="cg-in" placeholder="邮箱验证码" style="display:none" autocomplete="off">
      <button id="cgSendOtp" class="cg-send" style="display:none">发送验证码</button>
      <div id="cgMsg" class="cg-msg"></div>
      <button id="cgGo" class="btn primary cg-go">登录</button>
      <button id="cgForgot" class="cg-link" style="display:none">忘记密码？</button>
      <div class="cg-note">验证码会发到你的邮箱；本地版（台式机 Flask）不需要登录。</div>
    </div>`;
    document.body.appendChild(d);

    let tab = 'pw';
    let otpCtx = null;       // sendOtp 返回的 { verificationId, isExistingUser }
    let sendTimer = null;
    const email = () => d.querySelector('#cgEmail').value.trim();
    const pw = () => d.querySelector('#cgPw').value;
    const otp = () => d.querySelector('#cgOtp').value.trim();
    const msg = (t, err) => { d.querySelector('#cgMsg').textContent = t; d.querySelector('#cgMsg').style.color = err ? 'var(--err,#c0392b)' : 'var(--ink-3)'; };
    function resetSend() {
      otpCtx = null;
      if (sendTimer) { clearInterval(sendTimer); sendTimer = null; }
      const b = d.querySelector('#cgSendOtp');
      if (b) { b.disabled = false; b.textContent = '发送验证码'; }
    }

    d.querySelectorAll('.cg-tab').forEach((b) => b.onclick = () => {
      tab = b.dataset.t;
      d.querySelectorAll('.cg-tab').forEach((x) => x.classList.toggle('on', x === b));
      d.querySelector('#cgPw').style.display = (tab === 'otp') ? 'none' : '';
      // 注册(up)和验证码登录(otp)都填验证码框，且都要先点「发送验证码」
      d.querySelector('#cgOtp').style.display = (tab === 'otp' || tab === 'up') ? '' : 'none';
      d.querySelector('#cgSendOtp').style.display = (tab === 'otp' || tab === 'up') ? '' : 'none';
      d.querySelector('#cgForgot').style.display = (tab === 'pw') ? '' : 'none';
      d.querySelector('#cgGo').textContent = tab === 'up' ? '注册并登录' : '登录';
      resetSend();
      msg('');
    });

    d.querySelector('#cgSendOtp').onclick = async () => {
      const e = email();
      if (!e) { msg('先填邮箱', true); return; }
      msg('发送中…');
      try {
        const sent = await cloud.auth.sendOtp({ email: e });
        if (sent.error) { msg(sent.error.message || '发送失败', true); return; }
        otpCtx = sent.data; // { verificationId, isExistingUser }
        msg('验证码已发到 ' + e + '（收不到看垃圾箱）');
        let n = 60;
        const b = d.querySelector('#cgSendOtp');
        b.disabled = true;
        b.textContent = n + 's 后可重发';
        sendTimer = setInterval(() => {
          n--;
          if (n <= 0) { clearInterval(sendTimer); sendTimer = null; b.disabled = false; b.textContent = '重新发送'; }
          else b.textContent = n + 's 后可重发';
        }, 1000);
      } catch (err) { msg(err.message || '发送失败', true); }
    };

    d.querySelector('#cgGo').onclick = async () => {
      msg('处理中…');
      try {
        if (tab === 'pw') {
          const { error } = await cloud.auth.signInWithPassword({ email: email(), password: pw() });
          if (error) { msg('账号或密码不对', true); return; }
          msg('登录成功');
        } else { // otp 登录 / up 注册：都必须先点「发送验证码」拿到 otpCtx
          if (!otpCtx) { msg('请先点「发送验证码」', true); return; }
          const v = await cloud.auth.verifyOtp({
            verificationId: otpCtx.verificationId, token: otp(),
            email: email(), isExistingUser: otpCtx.isExistingUser, password: otpCtx.isExistingUser ? undefined : pw(),
          });
          if (v.error) { msg(v.error.message || (tab === 'up' ? '注册失败' : '验证码不对'), true); return; }
          msg(tab === 'up' ? '注册成功' : '登录成功');
        }
        // onAuthStateChange 会关掉弹窗
      } catch (e) { msg(e.message || '出错了', true); }
    };

    d.querySelector('#cgForgot').onclick = async () => {
      msg('发送重置邮件…');
      const r = await cloud.auth.resetPasswordForEmail(email());
      if (r.error) msg(r.error.message || '发送失败', true);
      else msg('重置链接已发到邮箱');
    };
    return d;
  }

  function renderGate(show) {
    if (!active) return;
    if (show && !ready) { ensureModal().style.display = 'flex'; }
    else { const m = document.getElementById('cloudGate'); if (m) m.style.display = 'none'; }
  }

  function showLogin() { renderGate(true); }

  window.CloudSync = {
    init, canServe, serveApi, servePost,
    active: () => active, ready: () => ready, state, onSyncChange,
    showLogin, newId,
    localOnlyApi, localOnlyPost,
    get user() { return user; },
  };
})();
