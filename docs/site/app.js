/* OpenWorkbench 官网交互
 *
 * 对齐 openclaw.ai 的实测行为：
 *   - 573 个元素带 transition（它几乎所有能变的都给了过渡）
 *   - IntersectionObserver 进场动画
 *   - scroll-behavior: smooth
 *   - 导航滚动态（滚动后加边框/底色）
 *   - 卡片 hover 抬升
 * 纯原生 JS，零依赖、零构建。
 */
(function () {
  'use strict';

  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. 进场动画 ----------
     给每个要动的块加 .reveal，滚进视口时加 .in。
     ⚠️ 必须用 IntersectionObserver 的 threshold 0.12 —— 太大（比如 0.5）
     会导致"元素比视口高时永远触发不了"，长卡片尤其明显。 */
  function setupReveal() {
    var targets = document.querySelectorAll(
      '.card, .sup, .why, .step, .pills li, figure, .reqs, ' +
      '.table-wrap, section > .wrap > h2, section > .wrap > .kicker'
    );
    if (!targets.length) return;

    if (REDUCED || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(targets, function (el) { el.classList.add('in'); });
      return;
    }

    Array.prototype.forEach.call(targets, function (el) { el.classList.add('reveal'); });

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add('in');
        io.unobserve(e.target);          // 只动一次，别来回抖
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });

    Array.prototype.forEach.call(targets, function (el) { io.observe(el); });
  }

  /* ---------- 2. 导航滚动态 ---------- */
  function setupNav() {
    var nav = document.getElementById('nav');
    if (!nav) return;
    var mark = function () {
      if (window.scrollY > 12) nav.classList.add('scrolled');
      else nav.classList.remove('scrolled');
    };
    mark();
    window.addEventListener('scroll', mark, { passive: true });
  }

  /* ---------- 3. 数字滚动 ----------
     「25 个模块」「3 种协议」这种数字，滚到时从 0 数上去。 */
  function setupCount() {
    var nums = document.querySelectorAll('[data-count]');
    if (!nums.length) return;
    if (REDUCED || !('IntersectionObserver' in window)) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        var end = parseFloat(el.getAttribute('data-count')) || 0;
        var t0 = null;
        var dur = 900;
        function step(ts) {
          if (!t0) t0 = ts;
          var p = Math.min((ts - t0) / dur, 1);
          // easeOutExpo：开头快、尾巴慢，读起来更有"落定感"
          var k = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
          el.textContent = Math.round(end * k);
          if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
        io.unobserve(el);
      });
    }, { threshold: 0.5 });

    Array.prototype.forEach.call(nums, function (el) { io.observe(el); });
  }

  /* ---------- 4. 高亮当前导航项 ---------- */
  function setupSpy() {
    var links = document.querySelectorAll('[data-spy]');
    if (!links.length) return;
    var secs = [];
    Array.prototype.forEach.call(links, function (a) {
      var id = a.getAttribute('href');
      if (id && id.charAt(0) === '#') {
        var s = document.querySelector(id);
        if (s) secs.push([s, a]);
      }
    });
    if (!secs.length) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        secs.forEach(function (p) { p[1].classList.remove('on'); });
        e.target.querySelectorAll('a').forEach(function (a) { a.classList.add('on'); });
      });
    }, { threshold: 0.2, rootMargin: '-72px 0px -60% 0px' });

    secs.forEach(function (p) { io.observe(p[0]); });
  }

  /* ---------- 5. 平台表：手机端逐行高亮（用 details 折叠代替横向滚动） ---------- */
  function setupTable() {
    var t = document.querySelector('table');
    if (!t) return;
    // 宽屏隐藏这个提示，窄屏才显示
    var hint = document.querySelector('.table-hint');
    if (hint) {
      var check = function () { hint.style.display = window.innerWidth < 720 ? 'block' : 'none'; };
      check();
      window.addEventListener('resize', check);
    }
  }

  /* ---------- 6. 复制命令 ---------- */
  function setupCopy() {
    var btns = document.querySelectorAll('[data-copy]');
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener('click', function () {
        var txt = b.getAttribute('data-copy') || '';
        var done = function () {
          var old = b.getAttribute('data-label') || b.textContent;
          b.setAttribute('data-label', old);
          b.textContent = '已复制';
          b.classList.add('ok');
          setTimeout(function () {
            b.textContent = old;
            b.classList.remove('ok');
          }, 1400);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(done, done);
        } else {
          var ta = document.createElement('textarea');
          ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta); ta.select();
          try { document.execCommand('copy'); } catch (e) {}
          document.body.removeChild(ta);
          done();
        }
      });
    });
  }

  /* ---------- 7. 顶栏菜单（窄屏抽屉） ---------- */
  function setupBurger() {
    var burger = document.getElementById('burger');
    var panel = document.getElementById('navPanel');
    if (!burger || !panel) return;
    var close = function () {
      panel.classList.remove('on');
      burger.classList.remove('on');
      burger.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('nav-lock');
    };
    burger.addEventListener('click', function () {
      var on = panel.classList.toggle('on');
      burger.classList.toggle('on', on);
      burger.setAttribute('aria-expanded', on ? 'true' : 'false');
      document.body.classList.toggle('nav-lock', on);
    });
    panel.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  function boot() {
    setupNav();
    setupReveal();
    setupCount();
    setupSpy();
    setupTable();
    setupCopy();
    setupBurger();
    document.documentElement.classList.add('js-ready');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
