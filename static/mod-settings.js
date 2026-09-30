/* 设置：AI 接口、OCR 阅读模型、索引范围、备份、数据概览 */

const { api, post, toast, esc } = window.WB;

export default {
  id: 'settings',
  name: '设置',
  el: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <h3>AI 接口</h3>
          <div class="note" style="margin-bottom:12px">
            OpenAI 兼容格式即可。Ollama 云端填 https://ollama.com/v1，本机 Ollama 填 http://localhost:11434/v1。
            Key 只存在本机 config.json。
          </div>
          <div class="field"><label>名称</label><input id="sLabel"></div>
          <div class="field"><label>Base URL</label><input id="sBase"></div>
          <div class="field"><label>API Key</label><input id="sKey" type="password" placeholder="留空则不改"></div>
          <div class="field"><label>默认模型</label><input id="sModel"></div>
          <button class="btn primary" id="btnSaveAI">保存</button>
        </div>

        <div class="panel">
          <h3>OCR 阅读模型</h3>
          <div class="note" style="margin-bottom:12px">
            读图片里的字，得用<b>视觉模型</b>（能看图的那种），普通文本模型不行。
            <br><b>实测过的结果</b>（2026-09-26，一张图逐个打过去）：
            Ollama 云端 17 个模型里<b>只有 <code>gemma4:31b</code> 能看图</b>，
            其他要么明确报「不支持图片」，要么不在免费额度内。
            <br>所以 Base URL 和 Key <b>留空就行</b>——会自动复用上面的 AI 接口。
            哪天你在本机 <code>ollama pull</code> 了本地视觉模型，再把地址填成
            <code>http://127.0.0.1:11434/v1</code>。
          </div>
          <div class="field"><label>Base URL</label><input id="oBase" placeholder="留空 = 跟 AI 接口一样"></div>
          <div class="field"><label>API Key</label><input id="oKey" placeholder="留空 = 跟 AI 接口一样"></div>
          <div class="field"><label>模型</label>
            <input id="oModel" placeholder="例如 gemma4:31b" style="flex:1">
            <button class="btn" id="btnOcrModels" style="height:34px;padding:0 12px;font-size:12px">拉列表</button>
          </div>
          <div id="ocrPick" style="margin-bottom:8px"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" id="btnSaveOcr">保存</button>
            <button class="btn" id="btnProbeOcr" style="height:34px;padding:0 12px;font-size:12px">实测这个模型能不能看图</button>
          </div>
          <span id="ocrInfo" style="margin-left:2px;font-size:12.5px;color:var(--ink-2)"></span>
        </div>

        <div class="panel">
          <h3>索引</h3>
          <div class="field"><label>扫描根目录</label><input id="sRoots" placeholder="C:\\,D:\\,E:\\"></div>
          <div class="note" style="margin-bottom:12px">
            系统目录、缓存、node_modules 会自动跳过。只读不写，索引留在本机。
          </div>
          <button class="btn" id="btnRescan">重新扫描</button>
          <span id="idxInfo" style="margin-left:10px;font-size:12.5px;color:var(--ink-2)"></span>
        </div>

        <div class="panel">
          <h3>模块管理（拼装你的工作台）</h3>
          <div class="note" style="margin-bottom:10px">
            开关模块、改显示名、调顺序，保存后侧栏立刻变（不用刷新）。
            <b>设置本身不能关</b>——不然就没地方再打开了。
          </div>
          <div id="modMgr" class="note">加载中…</div>
          <div class="field-row" style="margin-top:10px">
            <button class="btn" id="btnModReset">恢复默认布局</button>
            <button class="btn" id="btnModExport">导出布局</button>
            <input type="file" id="modImportFile" accept=".json" style="font-size:12px">
            <button class="btn" id="btnModImport">导入布局</button>
          </div>
        </div>

        <div class="panel">
          <h3>连接器（把工作台接到外部）</h3>
          <div class="note" style="margin-bottom:10px">
            通道即插即用：<b>PushPlus / Server酱</b>（微信推送，token 即用）、
            <b>Webhook</b>（自定义 URL，接任意服务）、<b>SMTP 邮件</b>（自己的邮箱发给自己）。
            停用不必删，每次推送都留日志。
          </div>
          <div id="connList" class="note">加载中…</div>
          <div style="margin-top:10px;border-top:1px solid var(--line-soft);padding-top:10px">
            <div class="field"><label>类型</label>
              <select id="cType" style="height:34px">
                <option value="pushplus">PushPlus（微信服务号）</option>
                <option value="serverchan">Server酱（微信）</option>
                <option value="webhook">Webhook（自定义 URL）</option>
                <option value="smtp">SMTP 邮件</option>
              </select>
            </div>
            <div class="field"><label>名称</label><input id="cName" placeholder="例如 微信推送"></div>
            <div id="cDyn"></div>
            <button class="btn primary" id="btnAddConn">添加并保存</button>
            <button class="btn" id="btnCancelEdit" style="display:none">取消编辑</button>
          </div>
          <div id="connLog" style="margin-top:10px"></div>
        </div>

        <div class="panel">
          <h3>备份</h3>
          <div class="note" style="margin-bottom:10px">
            所有数据都在本机 <code>workbench/data/app.db</code> 这一个文件里。
            它坏了或者你换电脑，这份 JSON 就是唯一的退路 —— 隔段时间导一次。
          </div>
          <div class="field-row">
            <button class="btn primary" id="btnBackup">导出备份</button>
            <input type="file" id="backupFile" accept=".json" style="font-size:12px">
            <button class="btn" id="btnRestore">导回来（追加）</button>
          </div>
          <div id="backupInfo" class="note" style="margin-top:8px"></div>
        </div>

        <div class="panel">
          <h3>数据</h3>
          <div id="counts" class="note"></div>
        </div>
      </div>`;

    el.querySelector('#btnSaveAI').addEventListener('click', async () => {
      const key = el.querySelector('#sKey').value;
      await post('/api/config', {
        ai: {
          label: el.querySelector('#sLabel').value,
          base_url: el.querySelector('#sBase').value,
          model: el.querySelector('#sModel').value,
          ...(key ? { api_key: key } : {}),
        },
        scan_roots: el.querySelector('#sRoots').value.split(',').map((s) => s.trim()).filter(Boolean),
      });
      el.querySelector('#sKey').value = '';
      toast('已保存');
    });

    el.querySelector('#btnOcrModels').addEventListener('click', () => this.loadOcrModels());
    el.querySelector('#btnProbeOcr').addEventListener('click', () => this.probeCurrent());
    el.querySelector('#btnSaveOcr').addEventListener('click', async () => {
      await post('/api/config', {
        ocr: {
          base_url: el.querySelector('#oBase').value.trim(),
          api_key: el.querySelector('#oKey').value.trim(),
          model: el.querySelector('#oModel').value.trim(),
        },
      });
      toast('已保存');
      this.sync();
    });

    el.querySelector('#btnRescan').addEventListener('click', async () => {
      const d = await post('/api/scan', {});
      toast(d.ok ? '开始扫描' : d.error || '启动失败');
    });

    el.querySelector('#btnBackup').addEventListener('click', () => {
      window.location = '/api/backup';
      toast('已开始下载');
    });

    el.querySelector('#btnRestore').addEventListener('click', async () => {
      const f = el.querySelector('#backupFile').files[0];
      const info = el.querySelector('#backupInfo');
      if (!f) { toast('先选一个备份文件'); return; }
      if (!confirm('会把备份里的数据追加进来。现有的不会被删，但可能有重复。继续？')) return;
      try {
        const data = JSON.parse(await f.text());
        const r = await post('/api/backup/import', { data, mode: 'merge' });
        if (!r.ok) { info.textContent = '导不进来：' + (r.error || ''); return; }
        const parts = Object.entries(r.imported || {})
          .filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(' · ');
        info.textContent = '已导入：' + (parts || '（没导入任何行）');
        toast('导回来了');
        window.WB.refresh && window.WB.refresh();
      } catch (e) {
        info.textContent = '这个文件读不了：' + e.message;
      }
    });

    this._editing = null;
    this._modOrder = null;
    this.renderDyn();
    this.loadMods();
    this.loadConns();
    this.loadConnLog();

    el.querySelector('#cType').addEventListener('change', () => this.renderDyn());
    el.querySelector('#btnAddConn').addEventListener('click', () => this.saveConn());
    el.querySelector('#btnCancelEdit').addEventListener('click', () => this.editConn(null));

    el.querySelector('#btnModReset').addEventListener('click', async () => {
      if (!confirm('恢复默认：所有开关、顺序、改名全部还原。继续？')) return;
      const cfg = { order: window.WB.modules.map((m) => m.id), disabled: [], labels: {} };
      await post('/api/kv/set', { k: 'moduleConfig', v: JSON.stringify(cfg) });
      window.WB.applyModuleCfg(cfg);
      toast('已恢复默认布局');
      this.loadMods();
    });

    el.querySelector('#btnModExport').addEventListener('click', () => {
      const blob = new Blob([JSON.stringify(window.WB.readModuleCfg(), null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'workbench-layout.json';
      a.click();
      URL.revokeObjectURL(a.href);
      toast('布局已导出');
    });

    el.querySelector('#btnModImport').addEventListener('click', async () => {
      const f = el.querySelector('#modImportFile').files[0];
      if (!f) { toast('先选一个布局文件'); return; }
      try {
        const cfg = JSON.parse(await f.text());
        if (!Array.isArray(cfg.order) && !Array.isArray(cfg.disabled)) throw new Error('不是布局文件');
        window.WB.applyModuleCfg(cfg);
        await post('/api/kv/set', { k: 'moduleConfig', v: JSON.stringify(cfg) });
        toast('布局已导入并生效');
        this.loadMods();
      } catch (e) {
        toast('导不进来：' + e.message);
      }
    });

    this.sync();
  },

  /* ---- 模块管理：开关 / 改名 / 排序（改完全局立刻生效）---- */

  async readModCfg() {
    const d = await api('/api/kv?k=moduleConfig');
    try {
      const c = JSON.parse((d && d.v) || 'null') || {};
      return {
        order: Array.isArray(c.order) ? c.order : [],
        disabled: Array.isArray(c.disabled) ? c.disabled : [],
        labels: c.labels || {},
      };
    } catch (_) {
      return { order: [], disabled: [], labels: {} };
    }
  },

  async loadMods() {
    const box = this.el.querySelector('#modMgr');
    if (!box) return;
    const mods = window.WB.modules;
    const cfg = await this.readModCfg();
    if (!this._modOrder) {
      this._modOrder = (cfg.order.length ? cfg.order : mods.map((m) => m.id)).slice();
      for (const m of mods) if (!this._modOrder.includes(m.id)) this._modOrder.push(m.id);
    }
    box.innerHTML = this._modOrder.map((id, i) => {
      const m = mods.find((x) => x.id === id);
      if (!m) return '';
      const dis = cfg.disabled.includes(id);
      const locked = id === 'settings';
      return `<div class="mod-row" data-id="${id}" style="display:flex;gap:6px;align-items:center;padding:4px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
        <input type="checkbox" data-en="${id}" ${dis ? '' : 'checked'} ${locked ? 'disabled title="设置不能关"' : ''}>
        <span style="width:70px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis">${esc(id)}</span>
        <input data-lb="${id}" value="${esc((cfg.labels && cfg.labels[id]) || m.name)}" style="flex:1;height:28px">
        <button class="btn" data-up="${i}" style="height:26px;padding:0 8px;font-size:11px" ${i === 0 ? 'disabled' : ''}>↑</button>
        <button class="btn" data-dn="${i}" style="height:26px;padding:0 8px;font-size:11px" ${i === this._modOrder.length - 1 ? 'disabled' : ''}>↓</button>
      </div>`;
    }).join('');

    box.querySelectorAll('[data-en]').forEach((cb) => {
      cb.addEventListener('change', () => this.saveMods());
    });
    box.querySelectorAll('[data-lb]').forEach((inp) => {
      inp.addEventListener('change', () => this.saveMods());
    });
    box.querySelectorAll('[data-up]').forEach((b) => {
      b.onclick = async () => {
        const i = +b.dataset.up;
        [this._modOrder[i - 1], this._modOrder[i]] = [this._modOrder[i], this._modOrder[i - 1]];
        await this.loadMods();   // 先按新顺序重渲染
        this.saveMods();         // 再从新 DOM 收集保存
      };
    });
    box.querySelectorAll('[data-dn]').forEach((b) => {
      b.onclick = async () => {
        const i = +b.dataset.dn;
        [this._modOrder[i + 1], this._modOrder[i]] = [this._modOrder[i], this._modOrder[i + 1]];
        await this.loadMods();
        this.saveMods();
      };
    });
  },

  async saveMods(skipReload) {
    const box = this.el.querySelector('#modMgr');
    const order = [...box.querySelectorAll('.mod-row')].map((r) => r.dataset.id);
    const disabled = [...box.querySelectorAll('[data-en]')]
      .filter((cb) => !cb.checked && !cb.disabled).map((cb) => cb.dataset.en);
    const labels = {};
    box.querySelectorAll('[data-lb]').forEach((inp) => {
      if (inp.value.trim()) labels[inp.dataset.lb] = inp.value.trim();
    });
    const cfg = { order, disabled, labels };
    await post('/api/kv/set', { k: 'moduleConfig', v: JSON.stringify(cfg) });
    window.WB.applyModuleCfg(cfg);
    if (!skipReload) this.loadMods();
  },

  /* ---- 连接器：四类型 + 启停 + 编辑 + 推送日志 ---- */

  dynHtml() {
    // 按类型渲染动态字段（编辑时预填值放在 this._editVals）
    const v = (k, def) => ((this._editVals && this._editVals[k]) != null ? this._editVals[k] : def);
    const t = this.el.querySelector('#cType').value;
    const f = (label, id, val, ph) =>
      `<div class="field"><label>${label}</label><input id="${id}" value="${esc(val || '')}" placeholder="${esc(ph || '')}"></div>`;
    if (t === 'pushplus' || t === 'serverchan') {
      return f('Token', 'cToken', v('token'), t === 'pushplus' ? 'pushplus.plus 上的 token' : 'sendkey，如 SCTxxxx');
    }
    if (t === 'webhook') {
      return f('URL', 'cUrl', v('url'), 'https://…（POST 目标地址）')
        + f('Header（可选）', 'cHeaders', v('headers'), 'JSON，如 {"Authorization":"Bearer x"}')
        + f('Body 模板（可选）', 'cBody', v('body'), 'JSON，可用 {title} {content} {ts}');
    }
    if (t === 'smtp') {
      return f('SMTP 服务器', 'cHost', v('host'), '如 smtp.qq.com')
        + f('端口', 'cPort', v('port', 465), '465 = SSL')
        + f('账号', 'cUser', v('user'), '你的邮箱')
        + f('授权码', 'cPass', v('pass'), '邮箱设置里生成的授权码')
        + f('发给', 'cTo', v('to'), '收件邮箱，默认发给自己');
    }
    return '';
  },

  renderDyn() {
    this.el.querySelector('#cDyn').innerHTML = this.dynHtml();
  },

  collectConnVals(type) {
    const g = (id) => ((this.el.querySelector('#' + id) || {}).value || '').trim();
    if (type === 'pushplus' || type === 'serverchan') return { token: g('cToken') };
    if (type === 'webhook') return { url: g('cUrl'), headers: g('cHeaders'), body: g('cBody') };
    if (type === 'smtp') {
      return { host: g('cHost'), port: g('cPort') || '465', user: g('cUser'), pass: g('cPass'), to: g('cTo') };
    }
    return {};
  },

  connDesc(c) {
    const t = c.type || '';
    if (t === 'pushplus' || t === 'serverchan') {
      return c.token ? 'token ' + c.token.slice(0, 4) + '…' + c.token.slice(-4) : '无 token';
    }
    if (t === 'webhook') return (c.url || '').slice(0, 46) || '无 URL';
    if (t === 'smtp') return (c.user || '未配') + (c.to ? ' → ' + c.to : '');
    return '';
  },

  async saveConn() {
    const type = this.el.querySelector('#cType').value;
    const name = this.el.querySelector('#cName').value.trim() || '我的通道';
    const vals = this.collectConnVals(type);
    if (type === 'pushplus' || type === 'serverchan') {
      if (!vals.token) { toast('先填 token'); return; }
    } else if (type === 'webhook') {
      if (!vals.url) { toast('先填 URL'); return; }
    } else if (type === 'smtp') {
      if (!vals.host || !vals.user || !vals.pass) { toast('SMTP 三样填全：服务器 / 账号 / 授权码'); return; }
    }
    const cons = (await api('/api/connectors')).rows || [];
    if (this._editing) {
      const i = cons.findIndex((x) => x.id === this._editing);
      if (i >= 0) cons[i] = { ...cons[i], type, name, ...vals };
    } else {
      cons.push({ id: 'c' + Date.now(), type, name, enabled: true, ...vals });
    }
    const r = await post('/api/config', { connectors: cons });
    if (r && r.ok) {
      const wasEdit = !!this._editing;
      this.editConn(null);
      toast(wasEdit ? '已更新' : '已添加');
      this.loadConns();
    } else toast('保存失败');
  },

  editConn(id) {
    this._editing = id || null;
    this._editVals = null;
    const cancel = this.el.querySelector('#btnCancelEdit');
    const addBtn = this.el.querySelector('#btnAddConn');
    if (!id) {
      cancel.style.display = 'none';
      addBtn.textContent = '添加并保存';
      this.el.querySelector('#cName').value = '';
      this.el.querySelector('#cType').value = 'pushplus';
      this.renderDyn();
      return;
    }
    cancel.style.display = '';
    addBtn.textContent = '保存修改';
    const cons = this._connRows || [];
    const c = cons.find((x) => x.id === id);
    if (!c) return;
    this.el.querySelector('#cType').value = c.type || 'pushplus';
    this.el.querySelector('#cName').value = c.name || '';
    this._editVals = c;
    this.renderDyn();
  },

  async loadConns() {
    const box = this.el.querySelector('#connList');
    if (!box) return;
    const d = await api('/api/connectors');
    const rows = d.rows || [];
    this._connRows = rows;
    if (!rows.length) {
      box.innerHTML = '<span class="note">还没接任何连接器。下面挑一个类型加上就能推出去。</span>';
      return;
    }
    box.innerHTML = rows.map((c) => `
      <div class="conn-row" data-id="${c.id}" style="display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px;flex-wrap:wrap">
        <input type="checkbox" data-tg="${c.id}" ${c.enabled !== false ? 'checked' : ''} title="启停">
        <span class="tag">${esc(c.type)}</span>
        <b style="font-weight:500">${esc(c.name || c.id)}</b>
        <span class="note" style="flex:1;min-width:120px">${esc(this.connDesc(c))}</span>
        <button class="btn" data-act="edit" style="height:26px;padding:0 9px;font-size:11px">改</button>
        <button class="btn" data-act="test" style="height:26px;padding:0 9px;font-size:11px">测试</button>
        <button class="btn" data-act="del" style="height:26px;padding:0 9px;font-size:11px">删</button>
      </div>`).join('');
    box.querySelectorAll('[data-tg]').forEach((cb) => {
      cb.onchange = async () => {
        const id = cb.dataset.tg;
        const cons = rows.map((x) => ({ ...x, enabled: x.id === id ? cb.checked : (x.enabled !== false) }));
        await post('/api/config', { connectors: cons });
        toast(cb.checked ? '已启用' : '已停用（配置保留）');
        this.loadConns();
      };
    });
    box.querySelectorAll('[data-act]').forEach((b) => {
      b.onclick = async () => {
        const id = b.closest('.conn-row').dataset.id;
        if (b.dataset.act === 'test') {
          const r = await post('/api/connectors/push', { id, title: '工作台连接测试', content: '如果你看到了这条，说明这条通道打通了 🎉' });
          toast(r && r.ok ? '已发测试，去收一下' : '测试失败：' + (r && r.error || ''));
          this.loadConnLog();
        } else if (b.dataset.act === 'edit') {
          this.editConn(id);
        } else if (b.dataset.act === 'del') {
          if (!confirm('删掉这个连接器？')) return;
          const cons = rows.filter((x) => x.id !== id);
          const r = await post('/api/config', { connectors: cons });
          toast(r && r.ok ? '已删除' : '删除失败');
          this.loadConns();
        }
      };
    });
  },

  async loadConnLog() {
    const box = this.el.querySelector('#connLog');
    if (!box) return;
    const d = await api('/api/connectors/log');
    const rows = d.rows || [];
    if (!rows.length) { box.innerHTML = '<div class="note" style="font-size:12px">还没有推送记录</div>'; return; }
    box.innerHTML = '<div class="note" style="font-size:12px;margin-bottom:4px">最近推送：</div>'
      + rows.slice(0, 10).map((r) => `
        <div style="display:flex;gap:8px;font-size:12px;padding:2px 0;color:var(--ink-2)">
          <span class="tag ${r.ok ? 'ok' : 'err'}">${r.ok ? '成功' : '失败'}</span>
          <span>${esc(r.type)}</span>
          <b style="font-weight:500">${esc(r.title || '')}</b>
          <span style="margin-left:auto;color:var(--ink-3)">${esc(window.WB.fmtTime(r.ts))}</span>
          ${r.error ? `<div style="width:100%;color:var(--err,#c0392b);font-size:11px">${esc(String(r.error).slice(0, 120))}</div>` : ''}
        </div>`).join('');
  },

  async loadOcrModels() {
    const info = this.el.querySelector('#ocrInfo');
    const pick = this.el.querySelector('#ocrPick');
    info.textContent = '拉取中…';
    const d = await api('/api/ocr/models');
    if (!d.ok) {
      info.textContent = '拉不到：' + (d.error || '');
      pick.innerHTML = '';
      return;
    }

    const all = []
      .concat((d.cloud || []).map((x) => ({ ...x, tag: '云端' })))
      .concat((d.local || []).map((x) => ({ ...x, tag: '本机' })));

    const err = (d.errors || []).length
      ? `<div class="note" style="margin-top:6px;color:var(--ink-3)">${esc(d.errors.join('；'))}</div>`
      : '';

    if (!all.length) {
      info.textContent = '两个地址都没拉到模型';
      pick.innerHTML = err;
      return;
    }

    info.innerHTML = `共 ${all.length} 个模型（云端 ${d.cloud.length} · 本机 ${d.local.length}），`
      + `<b>${all.filter((x) => x.guess).length}</b> 个像视觉模型。`
      + '名字只能猜，<b>要点「实测」才是准的</b>。';

    pick.innerHTML = '<div class="note" style="margin:6px 0 4px">点名字填进上面，点「测」真发一张图过去验：</div>'
      + all.map((x) => {
        const mark = x.guess ? '<span class="tag ok" style="margin-left:4px">像视觉</span>' : '';
        return `<div style="display:flex;align-items:center;gap:6px;padding:3px 0">
            <button class="chip" data-m="${esc(x.name)}">${esc(x.name)}</button>
            <span style="font-size:11px;color:var(--ink-3)">${esc(x.tag)}</span>
            ${mark}
            <button class="btn" data-probe="${esc(x.name)}" data-base="${esc(x.base)}"
              style="height:24px;padding:0 8px;font-size:11px">测</button>
            <span data-res="${esc(x.name)}" style="font-size:11px;color:var(--ink-3)"></span>
          </div>`;
      }).join('') + err;

    pick.querySelectorAll('[data-m]').forEach((b) => {
      b.onclick = () => {
        this.el.querySelector('#oModel').value = b.dataset.m;
        toast('已填，记得点保存');
      };
    });
    pick.querySelectorAll('[data-probe]').forEach((b) => {
      b.onclick = () => this.probeOne(b.dataset.probe, b.dataset.base, b);
    });
  },

  async probeOne(name, base, btn) {
    const slot = this.el.querySelector(`[data-res="${name}"]`);
    btn.disabled = true;
    slot.textContent = '测中…';
    const d = await post('/api/ocr/probe', { model: name, base_url: base });
    btn.disabled = false;
    if (!d.ok) { slot.textContent = '测失败：' + (d.error || ''); return; }
    slot.innerHTML = d.vision
      ? `<span class="tag ok">能看图</span> <span style="color:var(--ink-3)">${esc(d.note)}</span>`
      : `<span class="tag err">不能看图</span> <span style="color:var(--ink-3)">${esc(d.note)}</span>`;
    if (d.vision) {
      this.el.querySelector('#oModel').value = name;
      toast('能用，已填进模型框');
    }
  },

  async probeCurrent() {
    const name = this.el.querySelector('#oModel').value.trim();
    const info = this.el.querySelector('#ocrInfo');
    if (!name) { toast('先填模型名'); return; }
    info.textContent = '实测中…（真的会发一张图过去）';
    const d = await post('/api/ocr/probe', { model: name, force: 1 });
    info.innerHTML = !d.ok
      ? '测失败：' + esc(d.error || '')
      : (d.vision
        ? `<span class="tag ok">能看图</span> ${esc(d.note)}`
        : `<span class="tag err">不能看图</span> ${esc(d.note)}`);
  },

  sync() {
    const s = window.WB.status();
    if (!s) return;
    const el = this.el;
    if (el.querySelector('#lbAddr')) {
      el.querySelector('#lbAddr').value = localStorage.getItem('wb_local_backend') || '';
      el.querySelector('#lbKey').value = localStorage.getItem('wb_local_key') || '';
    }
    const oc = s.config.ocr || {};
    el.querySelector('#oBase').value = oc.base_url || '';
    el.querySelector('#oKey').value = oc.api_key || '';
    el.querySelector('#oModel').value = oc.model || '';
    el.querySelector('#sLabel').value = s.config.ai.label;
    el.querySelector('#sBase').value = s.config.ai.base_url;
    el.querySelector('#sModel').value = s.config.ai.model;
    el.querySelector('#sRoots').value = (s.config.scan_roots || []).join(',');
    el.querySelector('#idxInfo').textContent = `${s.count.toLocaleString()} 个文件已索引`;
    const c = s.counts || {};
    el.querySelector('#counts').innerHTML = [
      `捕捉 ${c.inbox || 0}`,
      `今日 ${c.today || 0}`,
      `笔记 ${c.notes || 0}`,
      `链接 ${c.links || 0}`,
      `项目 ${c.projects || 0}`,
      `任务 ${c.tasks || 0}`,
      `对话 ${c.chats || 0}`,
      `日程 ${c.events || 0}`,
      `习惯 ${c.habits || 0}`,
    ].join(' · ');
  },

  onShow() {
    this.sync();
    this.loadMods();
    this.loadConns();
    this.loadConnLog();
  },

  commands() {
    return [
      { title: '重新扫描磁盘', hint: '索引', run: () => post('/api/scan', {}) },
    ];
  },
};
