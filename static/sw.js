/* OpenWorkbench 的 Service Worker。
 *
 * 只干两件事：
 *   1) 让浏览器认这是个「可安装的应用」（Chrome 装到主屏要求有 SW + manifest）；
 *   2) 断网时还能看见壳（页面、样式、脚本、图标），而不是一只恐龙。
 *
 * 刻意用 network-first，不搞 cache-first：
 *   本地服务的前端是一天改八遍的，缓存优先等于把「改了不生效」变成家常便饭。
 *   这个坑真踩过 —— 上次是另一个旧进程抢了端口，排查耗了半天。
 *   所以这里的原则是：有网就以网上的为准，缓存只当断网时的垫背。
 *
 * /api/* 一律不碰：数据必须每次都是新的，缓存住会出大问题。
 */

const CACHE = 'wb-shell-v2';
const SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/style.css',
  '/static/core.js',
  '/static/icon.svg',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // 单个文件 404 不该让整个安装失败，所以一个个来、各自吞错
    await Promise.all(SHELL.map((u) => c.add(u).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

const cacheable = (p) => p === '/' || p === '/manifest.webmanifest' || p.startsWith('/static/');

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  let u;
  try { u = new URL(req.url); } catch (_) { return; }
  if (u.origin !== self.location.origin) return;   // CDN 之类的外部请求不管
  if (u.pathname.startsWith('/api/')) return;      // 数据永远走网络
  if (!cacheable(u.pathname)) return;

  e.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    } catch (_) {
      const hit = await caches.match(req);
      if (hit) return hit;
      const shell = await caches.match('/');
      if (shell) return shell;
      return new Response('离线了，而且这份还没缓存过。', {
        status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }
  })());
});
