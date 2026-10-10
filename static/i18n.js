/* 极简 i18n —— 语言包 + 运行时 DOM 替换。
 *
 * 为什么不用「把每个 title="打印机" 改成 t('printer')」这种常规做法：
 * 26 个前端文件、几千处硬编码中文，改一遍极易漏，而且以后每加一个模块都得记得包 t()。
 * 这里走另一条路：**语言包 = 中文原文 -> 译文** 的映射表，跑起来扫 DOM 做精确匹配替换。
 * 好处是模块代码一行不动、覆盖率反而更高（连拼接不出来的长说明句都能翻）。
 *
 * 三个必须知道的取舍：
 *  1. 只认**精确匹配**。「已删除 3 项」这种带变量的拼不出来的原文匹配不到，
 *     所以语言包里另留 DYNAMIC 段，用 {0} {1} 占位，走 renderPattern() 插值。
 *  2. 替换时把原文存进 data-wb-zh，切回中文时从那里还原 —— 否则改一次就永久变了。
 *  3. **默认跟随系统语言**（navigator.language），不是用户手选；
 *     设置页可以覆盖并存 localStorage，测试和「我想看另一种语言」时用。
 *
 * 用法（模块里）：
 *   const { t } = window.WBi18n;      el.innerHTML = t('打印机');
 *   不改模块的话什么都不用做，apply() 会自动扫。
 */

const STORAGE_KEY = 'wb_lang';

/** 语言包在 load() 时动态载入（静态字面量改成运行时填充） */
const PACKS = {};
const DYNAMIC = {};
let SUPPORTED = [];

/** 载入语言包。必须在 apply() 之前 await 它。 */
async function load(which) {
  const langs = which && which.length ? which : ['zh', 'en'];
  await Promise.all(langs.map(async (l) => {
    try {
      const m = await import(`./i18n/${l}.js`);
      PACKS[l] = m.default || m[l.toUpperCase()] || {};
    } catch (e) {
      PACKS[l] = {};              // 语言包缺失不应让整个应用起不来
    }
  }));
  SUPPORTED = Object.keys(PACKS).filter((l) => Object.keys(PACKS[l]).length);
  return SUPPORTED;
}

let current = 'zh';

function normalize(list) {
  const out = {};
  for (const l of list || []) {
    const k = String(l || '').toLowerCase();
    if (k.startsWith('zh')) return 'zh';
    if (k.startsWith('en')) return 'en';
  }
  return 'zh';
}

/** 语言决策顺序：本地覆盖 > 系统语言 > 兜底中文 */
function detect() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED.includes(saved)) return saved;
  } catch (e) { /* 隐私模式下 localStorage 可能不可用 */ }
  if (!SUPPORTED.length) return 'zh';
  return normalize(navigator.languages || [navigator.language || 'zh-CN']);
}

function dict(lang) {
  return PACKS[lang] || {};
}

/** 查译文；查不到就回原文（中文包里是恒等的，所以永远有值） */
function t(text) {
  if (text == null) return '';
  const s = String(text);
  if (current === 'zh') return s;
  const d = dict(current);
  return Object.prototype.hasOwnProperty.call(d, s) ? d[s] : s;
}

/** 拼接型文案：把原文里的 {0} {1} ... 换成实参 */
function renderPattern(zhText, ...args) {
  const s = String(zhText);
  if (current !== 'zh' && Object.prototype.hasOwnProperty.call(DYNAMIC, s)) {
    return DYNAMIC[s].replace(/\{(\d+)\}/g, (m, i) => (args[i] != null ? args[i] : m));
  }
  return s.replace(/\{(\d+)\}/g, (m, i) => (args[i] != null ? args[i] : m));
}

/** 文本节点替换：先记住中文原文，方便切回来 */
const ORIG = 'data-wb-zh';

function swapText(node) {
  const raw = node.nodeValue;
  if (!raw) return;
  const zh = node[ORIG] != null ? node[ORIG] : raw;
  const trimmed = zh.trim();
  if (!trimmed) return;
  // 整段精确匹配才翻；一整段里只含标点的（"·"）之类不动
  if (!/[\u4e00-\u9fff]/.test(trimmed)) return;
  const out = t(zh);
  if (out !== raw) node.nodeValue = out;
}

const ATTRS = ['placeholder', 'title', 'aria-label', 'alt', 'data-empty'];

function swapAttrs(el) {
  if (el[ORIG] == null) {
    el[ORIG] = '';                       // 标记已处理
  }
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const key = ORIG + '-' + a;
    if (el[key] != null) continue;
    const v = el.getAttribute(a);
    if (!v || !/[\u4e00-\u9fff]/.test(v)) continue;
    el[key] = v;
    const nv = t(v);
    if (nv !== v) el.setAttribute(a, nv);
  }
}

function walk(root) {
  if (!root) return;
  // ⚠️ 顺序不能反：文本节点是 3 不是 1，先判 `!== 1` 会把它们全挡掉，
  // 后面那个 `nodeType === 3` 的分支就成了死代码（踩过：apply() 什么都不换）。
  if (root.nodeType === 3) { swapText(root); return; }
  if (root.nodeType !== 1) return;
  swapAttrs(root);
  const kids = root.childNodes;
  for (let i = 0; i < kids.length; i++) walk(kids[i]);
}

let observer = null;

function observe() {
  if (observer || typeof MutationObserver === 'undefined') return;
  observer = new MutationObserver((muts) => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1 || n.nodeType === 3) walk(n);
      }
    }
  });
  try {
    observer.observe(document.body, { childList: true, subtree: true });
  } catch (e) { /* body 还没就绪 */ }
}

/** 把整页刷成当前语言。lang 省略则自动检测。 */
function apply(lang, root) {
  if (lang) {
    current = SUPPORTED.includes(lang) ? lang : detect();
    try { localStorage.setItem(STORAGE_KEY, current); } catch (e) { /* 忽略 */ }
  } else {
    current = detect();
  }
  const target = root || document.body;
  if (!target) return current;
  walk(target);
  observe();
  document.documentElement.setAttribute('lang', current === 'zh' ? 'zh-CN' : 'en');
  // 让模块自己有机会重绘（badge、时钟这类不是静态文本）
  try {
    const wb = window.WB;
    if (wb && Array.isArray(wb.modules) && typeof wb.rerender === 'function') wb.rerender();
  } catch (e) { /* 忽略 */ }
  try { window.dispatchEvent(new CustomEvent('wb:lang', { detail: current })); } catch (e) { /* 忽略 */ }
  return current;
}

const api = {
  load,
  t,
  renderPattern,
  apply,
  detect,
  get lang() { return current; },
  get supported() { return SUPPORTED.slice(); },
  STORAGE_KEY,
};

if (typeof window !== 'undefined') window.WBi18n = api;
export default api;