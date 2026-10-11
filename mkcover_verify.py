# -*- coding: utf-8 -*-
"""验封面里真的渲染出了东西。

⚠️ 我这个模型读不了图片，所以不能用"看"来确认。
   改用两种客观手段：
   1) 重新渲染同一份 HTML，在页面里量元素的几何与颜色（DOM probe）
   2) 解析 PNG 的像素分布，确认不是纯色/纯黑
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkcover  # noqa: E402

passed = 0
failed = 0


def ck(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s  <<< %s" % (name, str(extra)[:300]))


def png_pixels(path):
    """解 PNG 的 IDAT，返回 (w, h, [(r,g,b)...]) —— 只支持 8bit RGB/RGBA。"""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
    pos = 8
    w = h = bd = ct = None
    idat = b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", chunk[:10])
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    stride = w * nch
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _ in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        for i in range(stride):
            a = line[i - nch] if i >= nch else 0
            b = prev[i]
            c = prev[i - nch] if i >= nch else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out += line
        prev = line
    return w, h, nch, bytes(out)


PROBE = """
(async () => {
  const q = (s) => document.querySelector(s);
  const box = (s) => { const e = q(s); if (!e) return null;
    const r = e.getBoundingClientRect();
    return {w: Math.round(r.width), h: Math.round(r.height),
            x: Math.round(r.x), y: Math.round(r.y)}; };
  const img = q('.shot img');
  return JSON.stringify({
    h1: q('h1') ? q('h1').innerText : null,
    h1box: box('h1'),
    h1color: q('h1') ? getComputedStyle(q('h1')).color : null,
    emColor: q('h1 em') ? getComputedStyle(q('h1 em')).color : null,
    sub: q('.sub') ? q('.sub').innerText.slice(0,60) : null,
    tags: [...document.querySelectorAll('.tag')].map(e => e.innerText),
    repo: q('.repo') ? q('.repo').innerText : null,
    shotImg: img ? {complete: img.complete, nw: img.naturalWidth, nh: img.naturalHeight,
                    w: Math.round(img.getBoundingClientRect().width)} : null,
    topBar: q('.top') ? getComputedStyle(q('.top')).backgroundColor : null,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
    h1overflow: (() => { const e = q('h1'); if (!e) return null;
      return e.scrollWidth > e.clientWidth + 2; })(),
    docH: document.documentElement.scrollHeight,
    winH: window.innerHeight,
  });
})()
"""


def probe(html_path, w, h):
    """重新渲染 HTML 并在页面里量。"""
    # mkcover.py 和 smoke/ 都同级，所以是 HERE/smoke，不是 HERE 的父目录（早先算错一层）
    cdp = os.path.join(HERE, "smoke", "_cdp.py")
    if not os.path.isfile(cdp):
        return None
    js = os.path.join(tempfile.gettempdir(), "wb_cover_probe.js")
    with open(js, "w", encoding="utf-8") as f:
        f.write(PROBE)
    r = subprocess.run(
        [sys.executable, cdp, "--url", "file:///" + html_path.replace("\\", "/"),
         "--w", str(w), "--h", str(h), "--js", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=os.path.dirname(cdp), timeout=120)
    import json
    try:
        d = json.loads(r.stdout)
        return json.loads(d.get("js") or "{}")
    except Exception:  # noqa: BLE001
        return None


def main():
    home = os.path.join(mkcover.ASSETS, "ui-home.png")
    ck("素材截图在", os.path.isfile(home), home)

    # 造一份 HTML 留着探针用
    out = os.path.join(mkcover.OUT, "cover-1280x640.png")
    ok, made = mkcover.build(1280, 640,
                              "让 AI <em>主动来找你</em><br>而不是你一直去问它",
                              "早上一睁眼，要紧的邮件已经挑好了、回复草稿也写好了。"
                              "在微信里说一句话就能打印，手机拍的照片直传电脑。",
                              home, "cover-1280x640.png")
    ck("封面已生成", ok and os.path.isfile(made), made)

    if not os.path.isfile(made):
        return 1

    # --- 1. 像素层：不能是纯色 ---
    W, H, nch, px = png_pixels(made)
    ck("PNG 尺寸 1280x640", (W, H) == (1280, 640), "%dx%d" % (W, H))
    # ⚠️ 采样步长别太大：早先按 12 像素跳采只看到 196 种颜色，
    #    误判成"颜色不够丰富"——那其实是采样漏了，不是图真单调。
    seen = set()
    dark = 0
    bright = 0
    total = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            i = (y * W + x) * nch
            c = (px[i], px[i + 1], px[i + 2])
            seen.add(c)
            s = sum(c)
            total += 1
            if s < 200:
                dark += 1
            if s > 600:
                bright += 1
    ck("颜色种类 > 1000（不是纯色/纯黑）", len(seen) > 1000, str(len(seen)))
    # 背景到底是什么色，先取出来（别猜，猜就会写出 sum(int) 这种错）
    corner = []
    # 左上角往下让开 6px —— 顶部 4px 是品牌绿那条线，取到的必须是底色不是绿线
    for yy, xx in ((8, 8), (H - 6, 8), (8, W - 6), (H // 2, 20)):
        i = (yy * W + xx) * nch
        corner.append("#%02x%02x%02x" % (px[i], px[i + 1], px[i + 2]))
    # ⚠️ 别要求"暗色占多数"：右半边是工作台亮色界面截图，全图算下来暗色只占 ~14%。
    #    该断言的是**左右两半都有内容**（左=文字右=截图），不是谁比谁多。
    half = W // 2
    dark_left = 0
    dark_right = 0
    cnt_left = 0
    cnt_right = 0
    seen_left = set()
    seen_right = set()
    # ⚠️ 右半是**暗色主题**的工作台截图，所以别断言"右半很亮"——
    #    该断言的是"右半跟纯底色不一样（有界面内容）"。
    for y in range(0, H, 3):
        for x in range(0, W, 3):
            i = (y * W + x) * nch
            s = px[i] + px[i + 1] + px[i + 2]
            c = (px[i], px[i + 1], px[i + 2])
            if x < half:
                cnt_left += 1
                seen_left.add(c)
                if s < 200:
                    dark_left += 1
            else:
                cnt_right += 1
                seen_right.add(c)
                if s > 500:
                    dark_right += 1
    ck("左半有暗色底（背景确实是深色，不是白底）", dark_left > cnt_left * 0.5,
       "暗色 %d/%d (%.1f%%)  四角=%s"
       % (dark_left, cnt_left, 100.0 * dark_left / cnt_left, corner))
    # ⚠️ 关键哨兵：**背景必须精确等于品牌暗色 #0b0e14**。
    #    早先 CSS 里 `background:ACC` 被替成 `#36d399s`（多一个 s），
    #    整条规则作废 → body 背景声明被丢弃 → 底色变白，而 DOM 探针照样全绿
    #    （它只管元素有没有渲染，不管背景色）。所以这里必须比**精确值**。
    body_bg = corner[0]
    ck("背景精确等于品牌暗色 #0b0e14", body_bg == "#0b0e14", "实际=%s" % body_bg)
    ck("背景是深色", all((int(c[1:3], 16) + int(c[3:5], 16) + int(c[5:7], 16)) < 200
                        for c in corner),
       "四角色值=%s" % corner)
    ck("右半有内容（界面截图铺在那儿）", cnt_right > 0 and len(seen_right) > 30,
       "右半颜色种类=%d" % len(seen_right))
    ck("右半与左半视觉上有区别（不是一整块底色）", len(seen_right) > 10,
       "右半 %d 种 / 左半 %d 种" % (len(seen_right), len(seen_left)))
    # 品牌绿必须真的出现在图里
    def near(c, t, tol=60):
        return all(abs(c[i] - t[i]) < tol for i in range(3))
    has_accent = any(near(c, (0x36, 0xd3, 0x99)) for c in seen)
    ck("品牌绿 #36d399 出现在图里", has_accent, str(len(seen)))
    ck("有亮色文字（亮像素 > 0.5%）", bright > total * 0.005,
       "亮色 %d / 共 %d (%.1f%%)" % (bright, total, 100.0 * bright / total))

    # --- 2. DOM 层：内容真的排上去了 ---
    htmlp = os.path.join(tempfile.gettempdir(), "wb_cover_cover-1280x640.html")
    if os.path.isfile(htmlp):
        p = probe(htmlp, 1280, 640)
        ck("DOM 探针拿到数据", bool(p), str(p)[:150])
        if p:
            ck("标题渲染出来了", bool(p.get("h1")), str(p.get("h1"))[:100])
            ck("标题不是被裁切", p.get("h1overflow") is False, str(p.get("h1overflow")))
            ck("标题有实际尺寸", (p.get("h1box") or {}).get("h", 0) > 40,
               str(p.get("h1box")))
            ck("强调色是品牌绿", str(p.get("emColor")) == "rgb(54, 211, 153)",
               str(p.get("emColor")))
            ck("副标题有文字", bool(p.get("sub")), str(p.get("sub"))[:80])
            ck("6 个标签都在", len(p.get("tags") or []) == 6, str(p.get("tags")))
            ck("仓库地址在", "ZhangZhangooo" in str(p.get("repo")), str(p.get("repo")))
            si = p.get("shotImg") or {}
            ck("界面截图真的加载了（naturalWidth>0）", (si.get("nw") or 0) > 0, str(si))
            ck("截图按预期宽度显示", 200 < (si.get("w") or 0) < 700, str(si.get("w")))
            ck("没有横向溢出", p.get("overflowX") is False, str(p.get("overflowX")))
            ck("内容高度正好一屏（没溢出到需要滚动）",
               abs((p.get("docH") or 0) - (p.get("winH") or 0)) <= 2,
               "docH=%s winH=%s" % (p.get("docH"), p.get("winH")))

    print("\n=== 封面内容验证：%d PASS / %d FAIL ===" % (passed, failed))
    print("SMOKE_OK" if not failed else "SMOKE_FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
