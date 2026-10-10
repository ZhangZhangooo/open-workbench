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
  // ⚠️ 第一次碰到这个节点时**必须把中文原文存进 expando**（node[ORIG]）。
  //    只读不写的话，第二遍扫描拿到的"原文"已经是英文，
  //    含中文判断直接 return —— 表现为「切到英文能翻，切回中文永远翻不回来」（踩过）。
  let zh = node[ORIG];
  if (zh == null) {
    if (!/[\u4e00-\u9fff]/.test(raw)) return;    // 本来就没中文，不用记
    zh = raw;
    node[ORIG] = raw;
  }
  const trimmed = String(zh).trim();
  if (!trimmed) return;
  const out = t(zh);
  if (out !== raw) node.nodeValue = out;
}

const ATTRS = ['placeholder', 'title', 'aria-label', 'alt', 'data-empty'];

function swapAttrs(el) {
  // 语言切换按钮自己管显示，别让它的 title 走翻译（会叠加成两遍）
  if (el.hasAttribute('data-wb-lang')) return;
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const key = ORIG + '-' + a;
    let orig = el[key];
    if (orig == null) {
      orig = el.getAttribute(a);
      // 没有中文的属性（图标 alt 之类）不值得存，每次重扫时直接跳过
      if (!orig || !/[\u4e00-\u9fff]/.test(orig)) continue;
      el[key] = orig;
    }
    // ⚠️ 别写成「el[key] 存过就 continue」——那样从英文切回中文时属性永远停在英文
    //（文本节点走 swapText 能还原，属性不能，这是真踩过的坑）
    const want = t(orig);
    if (el.getAttribute(a) !== want) el.setAttribute(a, want);
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
    if (wb && typeof wb.rerender === 'function') wb.rerender();
  } catch (e) { /* 忽略 */ }
  try { window.dispatchEvent(new CustomEvent('wb:lang', { detail: current })); } catch (e) { /* 忽略 */ }
  paintSwitchers();
  return current;
}

/** 回到「跟随系统」：清掉本地覆盖，重新按 navigator 判断 */
function follow() {
  try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* 忽略 */ }
  return apply(null);
}

/** 在支持的语言之间轮换（顶栏那个按钮用） */
function toggle() {
  return apply(current === 'zh' ? 'en' : 'zh');
}

/* ---------- 切换入口的自我显示 ----------
   按钮上要写「当前是什么语言」，但这段文字/提示本身不能被翻译器再翻一遍：
   swapAttrs 只认 data-wb-zh-* 这类属性，看不见 data-wb-lang，所以 title 会被
   当成待译文案处理，出现「…（点击切换到 English）（点击切换）」这种叠加（踩过）。
   所以带 data-wb-lang 的元素在 swapAttrs 里整个跳过。 */

const LABELS = { zh: 'ZH', en: 'EN' };
const TITLES = {
  zh: '界面语言：中文（点击切换到 English）',
  en: 'Interface language: English (click to switch to 中文)',
};

function paintSwitchers() {
  document.querySelectorAll('[data-wb-lang]').forEach((b) => {
    b.classList.toggle('on', b.dataset.wbLang === current);
    b.textContent = LABELS[current] || current;
    b.title = TITLES[current] || current;
  });
}

/** 语言包词条统计（设置页显示进度用） */
function stats() {
  const out = {};
  for (const l of SUPPORTED) out[l] = Object.keys(PACKS[l] || {}).length;
  // 覆盖率以中文包为分母（中文是恒等的，条数 = 应翻总数）
  const base = out.zh || 0;
  out.pct = base ? Math.round(((out.en || 0) / base) * 100) : 0;
  return out;
}

const api = {
  load,
  t,
  renderPattern,
  apply,
  follow,
  toggle,
  detect,
  stats,
  paintSwitchers,
  get lang() { return current; },
  get supported() { return SUPPORTED.slice(); },
  LABELS,
  STORAGE_KEY,
};

if (typeof window !== 'undefined') window.WBi18n = api;
export default api;