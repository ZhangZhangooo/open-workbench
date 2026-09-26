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
          <h3>连接器（把工作台接到外部）</h3>
          <div class="note" style="margin-bottom:10px">
            接上就能把待办、OpenClaw 结果、快速捕捉推到手机。第一个支持：
            <b>PushPlus</b>（微信服务号推送，去 pushplus.plus 拿个 token 填上即可，
            单向、不碰逆向协议、不封号）。以后邮件 / 日历 / RSS 都按这套拼进来。
          </div>
          <div id="connList" class="note">加载中…</div>
          <div style="margin-top:10px;border-top:1px solid var(--line-soft);padding-top:10px">
            <div class="note" style="margin-bottom:6px">添加 PushPlus：</div>
            <div class="field"><label>名称</label><input id="cName" placeholder="例如 微信推送"></div>
            <div class="field"><label>Token</label><input id="cToken" placeholder="pushplus.plus 上的 token"></div>
            <button class="btn primary" id="btnAddConn">添加并保存</button>
          </div>
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

    this.loadConns();
    el.querySelector('#btnAddConn').addEventListener('click', async () => {
      const name = el.querySelector('#cName').value.trim() || '微信推送';
      const token = el.querySelector('#cToken').value.trim();
      if (!token) { toast('先填 token'); return; }
      const cons = (await api('/api/connectors')).rows || [];
      cons.push({ id: 'c' + Date.now(), type: 'pushplus', name, token, enabled: true });
      const r = await post('/api/config', { connectors: cons });
      if (r && r.ok) {
        el.querySelector('#cName').value = '';
        el.querySelector('#cToken').value = '';
        toast('已添加');
        this.loadConns();
      } else toast('保存失败');
    });

    this.sync();
  },

  async loadConns() {
    const box = this.el.querySelector('#connList');
    if (!box) return;
    const d = await api('/api/connectors');
    const rows = d.rows || [];
    if (!rows.length) {
      box.innerHTML = '<span class="note">还没接任何连接器。上面加一个 PushPlus 就能推到微信。</span>';
      return;
    }
    box.innerHTML = rows.map((c) => `
      <div class="conn-row" data-id="${c.id}" style="display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line-soft);font-size:12.5px">
        <span class="tag">${esc(c.type)}</span>
        <b style="font-weight:500">${esc(c.name || c.id)}</b>
        <span class="note">${c.token ? 'token ' + esc(c.token.slice(0, 4)) + '…' + esc(c.token.slice(-4)) : '无 token'}</span>
        <button class="btn" data-act="test" style="height:26px;padding:0 9px;font-size:11px;margin-left:auto">测试</button>
        <button class="btn" data-act="del" style="height:26px;padding:0 9px;font-size:11px">删</button>
      </div>`).join('');
    box.querySelectorAll('[data-act]').forEach((b) => {
      b.onclick = async () => {
        const id = b.closest('.conn-row').dataset.id;
        const c = rows.find((x) => x.id === id);
        if (b.dataset.act === 'test') {
          const r = await post('/api/connectors/push', { id, title: '工作台连接测试', content: '如果你在微信里看到这条，说明打通了 🎉' });
          toast(r && r.ok ? '已发测试，去看微信' : '测试失败：' + (r && r.error || ''));
        } else if (b.dataset.act === 'del') {
          const cons = rows.filter((x) => x.id !== id);
          const r = await post('/api/config', { connectors: cons });
          toast(r && r.ok ? '已删除' : '删除失败');
          this.loadConns();
        }
      };
    });
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
  },

  commands() {
    return [
      { title: '重新扫描磁盘', hint: '索引', run: () => post('/api/scan', {}) },
    ];
  },
};
