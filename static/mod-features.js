// 功能清单与进度板：每一项都在代码里有出处，不编愿望单
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
async function getJSON(path) {
  const r = await fetch(path, { headers: { 'Accept': 'application/json' } });
  return r.ok ? r.json() : null;
}

export default {
  id: 'features',
  name: '功能清单',
  icon: '📋',

  GROUPS: [
    { name: '核心引擎', items: [
      { n: '模块系统（侧栏导航 + 懒加载）', s: 'done' },
      { n: '⌘K 命令面板', s: 'done' },
      { n: '明暗主题切换', s: 'done' },
      { n: '统一数据流（今日 / 快速捕捉 / 资料库 / 活动流）', s: 'done' },
      { n: '设置与配置持久化（config.json）', s: 'done' },
      { n: '连接器框架（外接通道统一契约）', s: 'done' },
    ]},
    { name: 'AI 与 OpenClaw', items: [
      { n: 'AI 对话（流式输出，已去掉思考过程）', s: 'done' },
      { n: 'OpenClaw 真干活（读文件 / 跑命令 / 查系统）', s: 'done' },
      { n: '结果写回工作台 / 一键推到微信', s: 'done' },
      { n: '提示词库', s: 'done' },
      { n: '对话导出 Markdown', s: 'done' },
      { n: '文档（Office 读写，OpenClaw 内标签）', s: 'done' },
      { n: '多模型对比模式', s: 'done' },
    ]},
    { name: '外接通道', items: [
      { n: '微信推送（PushPlus 连接器）', s: 'done' },
      { n: '邮件（企业微信 / Agent Mail 连接器）', s: 'done' },
      { n: '日历 / 会议同步（企业微信 + 腾讯会议）', s: 'done' },
      { n: '企业微信双向（在微信里指挥工作台）', s: 'plan' },
    ]},
    { name: '项目与资料', items: [
      { n: '项目进度', s: 'done' },
      { n: '任务清单', s: 'done' },
      { n: '快速捕捉（收件箱）', s: 'done' },
      { n: '笔记', s: 'done' },
      { n: '知识库', s: 'done' },
      { n: '文件管理', s: 'done' },
      { n: '资料库（在线文档）', s: 'done' },
      { n: '看板 / 里程碑 / xlsx 导出', s: 'plan' },
    ]},
    { name: '生活与赚钱', items: [
      { n: '收入看板（自动汇总）', s: 'done' },
      { n: '设备清单', s: 'done' },
      { n: '购物预算', s: 'done' },
      { n: '灵感池（捕捉）', s: 'done' },
    ]},
    { name: '房间布置', items: [
      { n: '20㎡ 房间画布（家具 / 方案 / 尺寸）', s: 'done' },
    ]},
    { name: '专注与效率', items: [
      { n: '番茄钟（计时 + 今日统计）', s: 'done' },
      { n: '习惯打卡（连续天数）', s: 'done' },
      { n: '每日日志（自动保存）', s: 'done' },
      { n: '剪贴板历史', s: 'done' },
      { n: '定时提醒', s: 'done' },
      { n: '小工具盒（时间戳 / 密码 / Base64 / 哈希 / 去重）', s: 'done' },
    ]},
    { name: '系统', items: [
      { n: '内置终端（本机命令）', s: 'done' },
      { n: '备份 / 索引重建', s: 'done' },
    ]},
    { name: '规划中（还没做）', items: [
      { n: '首页卡片化（信息 + 动作卡片，可增删排序）', s: 'plan' },
      { n: 'RSS 订阅（进今日 / 捕捉）', s: 'plan' },
      { n: '课程表 / 考试倒计时（学生刚需）', s: 'plan' },
    ]},
  ],

  mount(el) {
    this.el = el;
    el.innerHTML = `
      <div class="stack">
        <div class="panel">
          <h3>功能清单与进度</h3>
          <div id="fSummary" class="note" style="margin:6px 0 10px"></div>
          <div id="fGroups"></div>
          <div id="fLive" class="note" style="margin-top:12px;color:var(--ink-3)"></div>
        </div>
      </div>`;
    this.renderGroups();
    this.renderLive();
  },

  renderGroups() {
    const wrap = this.el.querySelector('#fGroups');
    let total = 0, done = 0, plan = 0;
    const html = this.GROUPS.map((g) => {
      const d = g.items.filter((i) => i.s === 'done').length;
      const p = g.items.filter((i) => i.s === 'plan').length;
      total += g.items.length; done += d; plan += p;
      const rows = g.items.map((i) => {
        const tag = i.s === 'done'
          ? '<span class="tag ok">已能用</span>'
          : '<span class="tag">规划中</span>';
        return `<div style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px solid var(--line-soft)">`
          + `<span style="flex:1">${esc(i.n)}</span>${tag}</div>`;
      }).join('');
      const head = p
        ? `<b>${esc(g.name)}</b> <span class="tag" style="margin-left:6px">${d}/${g.items.length} 已能用</span>`
        : `<b>${esc(g.name)}</b> <span class="tag ok" style="margin-left:6px">${d}/${g.items.length}</span>`;
      return `<div style="margin-bottom:14px"><div style="margin-bottom:4px">${head}</div>${rows}</div>`;
    }).join('');
    wrap.innerHTML = html;
    this.el.querySelector('#fSummary').innerHTML =
      `共 <b>${this.GROUPS.length}</b> 个域、<b>${total}</b> 项功能 · `
      + `<span class="tag ok">已能用 ${done}</span> `
      + `<span class="tag">规划中 ${plan}</span>`;
  },

  async renderLive() {
    const box = this.el.querySelector('#fLive');
    box.textContent = '正在读取真实数据…';
    try {
      const [proj, inbox, tasks, life] = await Promise.all([
        getJSON('/api/projects'), getJSON('/api/inbox'),
        getJSON('/api/tasks?project_id=0'), getJSON('/api/life'),
      ]);
      const pN = (proj && proj.rows ? proj.rows.length : 0);
      const iN = (inbox && inbox.rows ? inbox.rows.length : 0);
      const tN = (tasks && tasks.rows ? tasks.rows.length : 0);
      const lN = (life && life.rows ? life.rows.length : 0);
      box.innerHTML = `当前真实数据：项目 <b>${pN}</b> · 任务 <b>${tN}</b> · `
        + `快速捕捉 <b>${iN}</b> · 生活条目 <b>${lN}</b>`
        + (iN === 0 ? '（捕捉空着——这块还没真正用起来）' : '');
    } catch (e) {
      box.textContent = '真实数据读取失败：' + e.message;
    }
  },
};
