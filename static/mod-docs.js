/* 文档：导入并读懂（pdf/docx/pptx/xlsx/txt/md）+ WPS 全套生成（Word/PPT/Excel）
 *
 * 两条链路：
 *   读：选文件 → 后端抽文字 → 喂模型（总结 / 出报告 / 挑毛病）→ 存成 Word 或存进资料
 *   写：说一句要什么（或自己写 Markdown）→ 落成 docx / pptx / xlsx → 用 WPS 打开
 */

const { api, post, toast, esc } = window.WB;

const KINDS = [
  { id: 'word', label: 'Word', app: 'wps', ph: '例如：一份无人机竞赛班的家长说明，含选拔流程和时间安排' },
  { id: 'ppt', label: 'PPT', app: 'wpp', ph: '例如：5 页的无人机竞赛班选拔说明，给家长看的' },
  { id: 'excel', label: 'Excel', app: 'et', ph: '例如：期末复习计划表，列：科目、章节、截止日期、状态' },
];

const MODES = [
  { id: 'summary', label: '总结', hint: '通读全文，给要点 + 概述' },
  { id: 'report', label: '出报告', hint: '表格数据 → 汇总报告 + 建议' },
  { id: 'fix', label: '挑毛病', hint: '找出空值、重复、异常值并给改法' },
];

const TEMPLATES = [
  {
    name: '复习计划',
    prompt: '生成一张期末复习计划表，列：科目、章节、截止日期、完成状态，给我 8 行示例',
    header: ['科目', '章节', '截止日期', '状态'],
    rows: [
      ['高等数学', '第三章 积分', '', '未开始'],
      ['高等数学', '第四章 级数', '', '未开始'],
      ['数据结构', '树与图', '', '未开始'],
      ['数据结构', '排序算法', '', '未开始'],
      ['英语', '词汇 List5-8', '', '未开始'],
    ],
  },
  {
    name: '月度预算',
    prompt: '生成一张大学生月度预算表，列：项目、预算金额、实际金额、差额，给我 10 行',
    header: ['项目', '预算', '实际', '差额'],
    rows: [
      ['伙食', '800', '', ''], ['交通', '100', '', ''],
      ['话费网费', '80', '', ''], ['学习资料', '150', '', ''],
      ['娱乐', '200', '', ''], ['其他', '100', '', ''],
    ],
  },
  {
    name: '设备清单',
    prompt: '生成一张房间设备清单表，列：设备、位置、供电方式、备注，给我 10 行',
    header: ['设备', '位置', '供电', '备注'],
    rows: [
      ['台式机', '书桌', '插座A', ''], ['显示器', '书桌', '插座A', ''],
      ['路由器', '书架', '插座B', ''], ['手机充电', '床头', '插座C', ''],
      ['台灯', '书桌', 'USB', ''],
    ],
  },
];

/* 极简 Markdown 渲染：够看就行，不引第三方库 */
function mdHtml(s) {
  const lines = esc(s || '').split('\n');
  const out = [];
  let inList = false;
  for (const ln of lines) {
    const t = ln.trim();
    if (/^([-*+]|\d+[.)])\s+/.test(t)) {
      if (!inList) { out.push('<ul style="margin:6px 0;padding-left:20px">'); inList = true; }
      out.push('<li style="margin:3px 0">' + t.replace(/^([-*+]|\d+[.)])\s+/, '') + '</li>');
      continue;
    }
    if (inList) { out.push('</ul>'); inList = false; }
    if (!t) { out.push('<div style="height:8px"></div>'); continue; }
    let h = t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    const m = h.match(/^(#{1,4})\s+(.*)$/);
    if (m) {
      const lv = Math.min(m[1].length, 3);
      h = `<div style="font-weight:600;font-size:${18 - lv * 2}px;margin:12px 0 6px">${m[2]}</div>`;
    }
    out.push('<div style="margin:4px 0;line-height:1.7">' + h + '</div>');
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

export default {
  id: 'docs',
  name: '文档',
  el: null,
  kind: 'word',
  mode: 'summary',
  curPath: '',
  lastText: '',
  lastFile: null,

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">

        <div class="panel">
          <h3>导入文件，让 Ollama 读</h3>
          <div class="note" style="margin-bottom:8px">
            文档 <b>pdf / docx / pptx / xlsx / txt / md / csv</b> —— 有文字层的直接抽文字，
            抽不出来会直说，不会拿乱码糊弄你。
            <br>图片 <b>png / jpg / webp / bmp</b> —— 走 OCR（视觉模型 <code>gemma4:31b</code>）读字。
          </div>
          <div style="display:flex;gap:6px">
            <input id="docPath" placeholder="文件路径，或点右边从已索引的文件里挑" style="flex:1">
            <button class="btn" id="btnPick" style="height:34px;padding:0 12px">挑文件</button>
          </div>
          <div id="picker" style="display:none;margin-top:8px;
               border:1px solid var(--line-soft);border-radius:8px;padding:8px">
            <div style="display:flex;gap:6px">
              <input id="pickQ" placeholder="搜文档名，空着就列出最近的" style="flex:1;height:30px">
              <button class="btn" id="btnPickGo" style="height:30px;padding:0 12px;font-size:12px">搜</button>
              <button class="btn" id="btnPickX" style="height:30px;padding:0 12px;font-size:12px">收起</button>
            </div>
            <div id="pickList" style="max-height:240px;overflow:auto;margin-top:8px"></div>
          </div>
          <div id="readInfo" style="margin-top:10px"></div>
        </div>

        <div class="panel" id="panelRead" style="display:none">
          <h3>怎么读它</h3>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
            ${MODES.map((m, i) => `<button class="btn mode-btn${i === 0 ? ' primary' : ''}"
               data-mode="${m.id}" style="height:30px;padding:0 12px;font-size:12px"
               title="${esc(m.hint)}">${esc(m.label)}</button>`).join('')}
          </div>
          <div class="field"><input id="extra" placeholder="补充要求（可留空），例如：只讲第三章、用表格输出"></div>
          <button class="btn primary" id="btnRead">开始读</button>
          <span id="readState" style="margin-left:10px"></span>
          <div id="sumOut" style="margin-top:12px"></div>
        </div>

        <div class="panel">
          <h3>生成文档（WPS 全套）</h3>
          <div style="display:flex;gap:6px;margin-bottom:8px">
            ${KINDS.map((k, i) => `<button class="btn kind-btn${i === 0 ? ' primary' : ''}"
               data-kind="${k.id}" style="height:30px;padding:0 14px;font-size:12px">${esc(k.label)}</button>`).join('')}
          </div>
          <div class="field"><input id="genPrompt" placeholder="${esc(KINDS[0].ph)}"></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn primary" id="btnGen">AI 写并生成</button>
            <button class="btn" id="btnTpl">表格式模板</button>
            <button class="btn" id="btnMd">自己写 Markdown</button>
          </div>
          <div id="mdBox" style="display:none;margin-top:8px">
            <textarea id="genMd" rows="9" placeholder="# 标题&#10;## 一节&#10;- 要点&#10;&#10;Excel 的话只写 Markdown 表格：&#10;| 列1 | 列2 |&#10;|---|---|&#10;| a | b |"
              style="width:100%;font-family:ui-monospace,Consolas,monospace;font-size:12.5px"></textarea>
            <div class="field" style="margin-top:6px"><input id="genTitle" placeholder="文件名（留空自动取标题）"></div>
            <button class="btn primary" id="btnMake" style="margin-top:2px">直接生成</button>
          </div>
          <span id="genState" style="margin-left:2px"></span>
          <div id="mkOut" style="margin-top:12px"></div>
        </div>

        <div class="panel">
          <h3>用 WPS 打开</h3>
          <div class="note" id="wpsInfo">检测中…</div>
        </div>

      </div>`;

    // 类型切换
    el.querySelectorAll('.kind-btn').forEach((b) => {
      b.onclick = () => {
        this.kind = b.dataset.kind;
        el.querySelectorAll('.kind-btn').forEach((x) => x.classList.remove('primary'));
        b.classList.add('primary');
        const k = KINDS.find((x) => x.id === this.kind);
        el.querySelector('#genPrompt').placeholder = k.ph;
      };
    });

    // 读法切换
    el.querySelectorAll('.mode-btn').forEach((b) => {
      b.onclick = () => {
        this.mode = b.dataset.mode;
        el.querySelectorAll('.mode-btn').forEach((x) => x.classList.remove('primary'));
        b.classList.add('primary');
      };
    });

    el.querySelector('#btnPick').onclick = () => {
      const p = el.querySelector('#picker');
      p.style.display = p.style.display === 'none' ? '' : 'none';
      if (p.style.display === '') this.pick('');
    };
    el.querySelector('#btnPickX').onclick = () => { el.querySelector('#picker').style.display = 'none'; };
    el.querySelector('#btnPickGo').onclick = () => this.pick(el.querySelector('#pickQ').value.trim());
    el.querySelector('#pickQ').onkeydown = (e) => {
      if (e.key === 'Enter') this.pick(el.querySelector('#pickQ').value.trim());
    };

    el.querySelector('#docPath').onchange = () => this.probe();
    el.querySelector('#btnRead').onclick = () => this.read();

    el.querySelector('#btnGen').onclick = () => this.gen();
    el.querySelector('#btnMake').onclick = () => this.make();
    el.querySelector('#btnMd').onclick = () => {
      const b = el.querySelector('#mdBox');
      b.style.display = b.style.display === 'none' ? '' : 'none';
    };
    el.querySelector('#btnTpl').onclick = () => this.tplFill();

    this.checkWps();
  },

  // ---------- 挑文件 ----------

  async pick(q) {
    const box = this.el.querySelector('#pickList');
    box.innerHTML = '<div class="note">搜中…</div>';
    let rows = [];
    for (const ext of ['docx', 'pptx', 'xlsx', 'pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp']) {
      const d = await api(`/api/search?q=${encodeURIComponent(q)}&ext=${ext}&min_size=0&limit=40&offset=0`);
      rows = rows.concat(d.rows || []);
      if (rows.length > 60) break;
    }
    if (!rows.length) {
      box.innerHTML = '<div class="note">没搜到。索引里没有就先去「文件」页建索引。</div>';
      return;
    }
    box.innerHTML = rows.slice(0, 60).map((r) => {
      const p = r.path || r.p || '';
      const n = p.split(/[\\/]/).pop();
      const sz = r.size ? `${(r.size / 1024).toFixed(0)}K` : '';
      return `<div class="pick-row" data-p="${esc(p)}" style="padding:5px 6px;cursor:pointer;
              border-radius:6px;font-size:12.5px">${esc(n)}
              <span style="color:var(--ink-3);font-size:11px;margin-left:6px">${sz}</span>
              <div style="color:var(--ink-3);font-size:11px;word-break:break-all">${esc(p)}</div></div>`;
    }).join('');
    box.querySelectorAll('.pick-row').forEach((d) => {
      d.onmouseenter = () => { d.style.background = 'var(--bg-soft)'; };
      d.onmouseleave = () => { d.style.background = ''; };
      d.onclick = () => {
        this.el.querySelector('#docPath').value = d.dataset.p;
        this.el.querySelector('#picker').style.display = 'none';
        this.probe();
      };
    });
  },

  // ---------- 读文件 ----------

  isImage(p) {
    return /\.(png|jpe?g|webp|bmp|gif)$/i.test(p || '');
  },

  async probe() {
    const p = this.el.querySelector('#docPath').value.trim();
    const info = this.el.querySelector('#readInfo');
    const panel = this.el.querySelector('#panelRead');
    const out = this.el.querySelector('#sumOut');
    if (!p) { info.innerHTML = ''; panel.style.display = 'none'; out.innerHTML = ''; return; }

    // 图片走 OCR，文档走抽文字 —— 两条路，别混
    if (this.isImage(p)) {
      info.innerHTML = '<span class="tag">OCR 识别中，十几秒…</span>';
      const d = await post('/api/ocr/read', { path: p });
      if (!d.ok) {
        info.innerHTML = `<span class="tag err">${esc(d.error)}</span>`;
        panel.style.display = 'none';
        this.curPath = '';
        return;
      }
      this.curPath = '';
      this.lastText = d.text;
      panel.style.display = 'none';        // 图不走「总结/报告/挑毛病」，那套是给文档和表格的
      info.innerHTML = `<span class="tag ok">OCR 读出来了</span>
        <span style="font-size:12px;color:var(--ink-3);margin-left:6px">
          ${esc(d.model)} · ${(d.bytes / 1024).toFixed(0)}KB 的图</span>`;
      this.showText(d.text, `OCR：${d.name}`, 'ocr');
      return;
    }

    info.innerHTML = '<span class="tag">读取中…</span>';
    const d = await api('/api/docs/read?path=' + encodeURIComponent(p));
    if (!d.ok) {
      // 扫描版 / 乱码 PDF 抽不出文字 —— 给一条 OCR 的活路，别让人卡在这
      const isPdf = /\.pdf$/i.test(p);
      info.innerHTML = `<span class="tag err">${esc(d.error)}</span>`
        + (isPdf ? `<div style="margin-top:8px">
             <button class="btn primary" id="btnOcrPdf" style="height:30px;padding:0 12px;font-size:12px">
               改用 OCR 读这个 PDF</button>
             <span style="font-size:12px;color:var(--ink-3);margin-left:6px">
               会渲染整份 PDF 的每一页，逐页发给视觉模型识别。现在支持<b>一次性读完整份</b>，不用你填页数。</span>
             <span id="ocrPdfN" style="margin-left:6px"></span>
           </div>` : '');
      panel.style.display = 'none';
      this.curPath = '';
      const ob = this.el.querySelector('#btnOcrPdf');
      if (ob) ob.onclick = () => this.ocrPdf(p);
      return;
    }
    this.curPath = p;
    const prev = (d.text || '').slice(0, 220).replace(/\n+/g, ' / ');
    info.innerHTML = `<span class="tag ok">读到了</span>
      <span style="font-size:12px;color:var(--ink-3);margin-left:6px">${esc(d.note || '')}</span>
      <div style="margin-top:6px;font-size:12px;color:var(--ink-3);line-height:1.6">${esc(prev)}…</div>`;
    panel.style.display = '';
  },

  async ocrPdf(p) {
    const slot = this.el.querySelector('#ocrPdfN');
    slot.innerHTML = '<span class="tag">整份 PDF 逐页识别中…（会显示进度）</span>';
    // 走 SSE：后端边逐页识别边推进度，最后推完整文本。整份一次喂，不用填页数。
    let res;
    try {
      res = await fetch('/api/docs/ocr-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p }),
      });
    } catch (e) {
      slot.innerHTML = `<span class="tag err">请求失败：${esc(e.message)}</span>`;
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let finalMeta = null, err = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const pp of parts) {
        const s = pp.trim();
        if (!s.startsWith('data:')) continue;
        let o;
        try { o = JSON.parse(s.slice(5).trim()); } catch (_) { continue; }
        if (o.type === 'start') {
          slot.innerHTML = `<span class="tag">整份识别中：共 ${o.total} 页 · 0%</span>`;
        } else if (o.type === 'progress') {
          const pct = o.total ? Math.round((o.page / o.total) * 100) : 0;
          slot.innerHTML = `<span class="tag">识别中：第 ${o.page}/${o.total} 页（${pct}%）</span>`;
        } else if (o.type === 'done') {
          finalMeta = o;
        } else if (o.type === 'error') {
          err = o.error;
        }
      }
    }
    if (err) { slot.innerHTML = `<span class="tag err">${esc(err)}</span>`; return; }
    if (!finalMeta) { slot.innerHTML = '<span class="tag err">没收到识别结果</span>'; return; }
    const d = finalMeta;
    const warn = (d.rendered && d.total && d.rendered < d.total
      ? `<div class="note" style="margin-bottom:8px">只渲染了前 ${d.rendered} 页（共 ${d.total} 页）。</div>` : '')
      + (d.failed && d.failed.length
        ? `<div class="note" style="margin-bottom:8px">有 ${d.failed.length} 页没识别出来：${esc(d.failed.join('、'))}</div>` : '');
    slot.innerHTML = `<span class="tag ok">整份读完：共 ${d.total} 页</span>`;
    this.showText(d.text, `OCR：${d.name}`, '文档', warn);
  },

  /* OCR / 总结的结果都走这里：渲染 + 三个出口 */
  showText(text, title, tag, warn) {
    const out = this.el.querySelector('#sumOut');
    this.lastText = text;
    out.innerHTML = (warn || '') + `
      <div style="border:1px solid var(--line-soft);border-radius:8px;padding:12px;font-size:13.5px">
        ${mdHtml(text)}
      </div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <button class="btn" id="btnToWord2">存成 Word</button>
        <button class="btn" id="btnToNote2">存进资料</button>
        <button class="btn" id="btnCopy2">复制</button>
      </div>`;
    this.el.querySelector('#btnToWord2').onclick = async () => {
      const r = await post('/api/docs/make', { kind: 'word', md: `# ${title}\n\n${text}`, title });
      if (!r.ok) { toast(r.error || '失败'); return; }
      toast('已生成 Word');
      this.showFile(r, 'wps');
    };
    this.el.querySelector('#btnToNote2').onclick = async () => {
      const r = await post('/api/notes/save', { title, body: text, tags: tag });
      toast(r.ok ? '已存进资料' : r.error || '失败');
      if (r.ok) window.WB.refresh();
    };
    this.el.querySelector('#btnCopy2').onclick = () => {
      navigator.clipboard.writeText(text);
      toast('已复制');
    };
  },

  async read() {
    if (!this.curPath) return;
    const el = this.el;
    const st = el.querySelector('#readState');
    const out = el.querySelector('#sumOut');
    const btn = el.querySelector('#btnRead');
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = '读中…';
    st.innerHTML = '<span class="tag">模型在读，十几秒到一分钟</span>';
    out.innerHTML = '';

    const d = await post('/api/docs/summarize', {
      path: this.curPath,
      mode: this.mode,
      extra: el.querySelector('#extra').value.trim(),
    });
    btn.disabled = false;
    btn.textContent = old;

    if (!d.ok) {
      st.innerHTML = `<span class="tag err">${esc(d.error || '失败')}</span>`;
      return;
    }
    const label = MODES.find((m) => m.id === d.mode).label;
    const warn = d.truncated
      ? `<div class="note" style="margin-bottom:8px">材料太长，只取了前 ${d.chunks} 段（共 ${d.src_chars.toLocaleString()} 字）来读，结论可能不完整。</div>`
      : '';
    st.innerHTML = `<span class="tag ok">读完</span>
      <span style="font-size:12px;color:var(--ink-3);margin-left:6px">${esc(d.model || '')} · ${d.src_chars.toLocaleString()} 字</span>`;
    this.showText(d.text, `${label}：${d.name}`, '文档', warn);
  },

  // ---------- 生成 ----------

  tplFill() {
    const t = TEMPLATES[0];
    this.kind = 'excel';
    this.el.querySelectorAll('.kind-btn').forEach((x) =>
      x.classList.toggle('primary', x.dataset.kind === 'excel'));
    this.el.querySelector('#genPrompt').value = t.prompt;
    this.el.querySelector('#genPrompt').placeholder = KINDS[2].ph;
  },

  async gen() {
    const el = this.el;
    const prompt = el.querySelector('#genPrompt').value.trim();
    if (!prompt) { toast('先说要写什么'); return; }
    const st = el.querySelector('#genState');
    const btn = el.querySelector('#btnGen');
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = '写中…';
    st.innerHTML = '<span class="tag">模型在写，稍等</span>';
    el.querySelector('#mkOut').innerHTML = '';

    const d = await post('/api/docs/ai-doc', { kind: this.kind, prompt });
    btn.disabled = false;
    btn.textContent = old;
    if (!d.ok) {
      st.innerHTML = `<span class="tag err">${esc(d.error || '失败')}</span>`;
      if (d.raw) st.innerHTML += `<div class="note" style="margin-top:6px">${esc(d.raw)}</div>`;
      return;
    }
    st.innerHTML = `<span class="tag ok">${esc(d.note || '已生成')}</span>`;
    this.showFile(d, (KINDS.find((k) => k.id === this.kind) || KINDS[0]).app);
  },

  async make() {
    const el = this.el;
    const md = el.querySelector('#genMd').value;
    if (!md.trim()) { toast('Markdown 是空的'); return; }
    const st = el.querySelector('#genState');
    st.innerHTML = '<span class="tag">生成中…</span>';
    const d = await post('/api/docs/make', {
      kind: this.kind,
      md,
      title: el.querySelector('#genTitle').value.trim(),
    });
    if (!d.ok) {
      st.innerHTML = `<span class="tag err">${esc(d.error || '失败')}</span>`;
      return;
    }
    st.innerHTML = `<span class="tag ok">${esc(d.note || '已生成')}</span>`;
    this.showFile(d, (KINDS.find((k) => k.id === this.kind) || KINDS[0]).app);
  },

  showFile(d, app) {
    this.lastFile = { file: d.file, app };
    const box = this.el.querySelector('#mkOut');
    box.innerHTML = `
      <div style="border:1px solid var(--line-soft);border-radius:8px;padding:12px">
        <div style="font-size:13.5px;font-weight:500">${esc(d.title || d.file)}</div>
        <div style="font-size:12px;color:var(--ink-3);margin-top:4px">${esc(d.file)} · ${esc(d.note || '')}</div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <button class="btn" id="btnDl">下载</button>
          <button class="btn primary" id="btnWps">用 WPS 打开</button>
          <button class="btn" id="btnInWb">在文件页定位</button>
        </div>
      </div>`;
    box.querySelector('#btnDl').onclick = () => { window.location = d.url; };
    box.querySelector('#btnWps').onclick = async () => {
      const r = await post('/api/docs/open', { file: d.file, app });
      toast(r.ok ? '已交给 WPS' : r.error || '打开失败');
    };
    box.querySelector('#btnInWb').onclick = () => {
      window.WB.go('files', { q: d.file });
    };
  },

  async checkWps() {
    const d = await api('/api/docs/wps');
    this.el.querySelector('#wpsInfo').innerHTML = d.et
      ? `<span class="tag ok">WPS 已找到</span>
         <span style="color:var(--ink-3);font-size:12px;margin-left:6px">${esc(d.et)}</span>
         <div style="font-size:12px;color:var(--ink-3);margin-top:6px">
           生成的 docx / pptx / xlsx 都能直接双击用 WPS 打开。</div>`
      : '<span class="tag warn">没找到 WPS</span>';
  },

  commands() {
    return [
      { title: '导入一个文件让 Ollama 读', hint: '文档', run: () => window.WB.go('claw', { tab: 'docs' }) },
      { title: 'OCR 读一张图片里的字', hint: '文档', run: () => window.WB.go('claw', { tab: 'docs' }) },
      { title: '让 AI 写一份 Word', hint: '文档', run: () => window.WB.go('claw', { tab: 'docs' }) },
      { title: '让 AI 做一份 PPT', hint: '文档', run: () => window.WB.go('claw', { tab: 'docs' }) },
    ];
  },
};
