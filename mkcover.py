# -*- coding: utf-8 -*-
"""生成宣传封面（1280x640，GitHub 社交预览标准尺寸）。

⚠️ 纯标准库，零依赖。PNG 编码手写（zlib + struct 就有），
   字体靠 Chrome 渲染后截屏 —— 不用 PIL，不装任何东西。

为什么不用 PIL：项目铁律是「clone 就能跑」，加个图片库就破功了。
为什么要 Chrome 渲染文字：手写 PNG 光栅化器要处理字形，太重；
让浏览器排版再截屏，字体/间距/换行全是对的。

用法：
    python mkcover.py            # 生成 3 张：封面 / 手机版 / 竖版
"""
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 素材目录和本脚本同级（宣传素材/），不是 ROOT 下 —— 之前算错成 ROOT/宣传素材
ASSETS = os.path.join(HERE, "宣传素材")
OUT = HERE

CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

# 品牌色（跟工作台暗色主题一致：#0b0e14 底 / #36d399 强调）
INK = "#0b0e14"
ACCENT = "#36d399"
TEXT = "#e8ecf1"
MUTED = "#8b97a8"
PANEL = "#141a24"
LINE = "#232c3a"


def find_chrome():
    for p in CHROME:
        if os.path.isfile(p):
            return p
    raise SystemExit("没找到 Chrome")


def png_size(path):
    with open(path, "rb") as f:
        b = f.read(32)
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", b[16:24])
    return w, h


def shot(url, out_png, w, h):
    """用 Chrome headless 截图指定尺寸。"""
    chrome = find_chrome()
    prof = tempfile.mkdtemp(prefix="wb_cover_")
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=%d,%d" % (w, h),
        "--user-data-dir=" + prof,
        "--screenshot=" + out_png,
        "--virtual-time-budget=3000",
        url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=90)
    try:
        import shutil
        shutil.rmtree(prof, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return os.path.isfile(out_png)


HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:WPXpx;height:HPXpx;overflow:hidden}
body{
  background:INKC;color:TX;
  font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
  display:flex;flex-direction:column;
}
/* 顶部一条品牌线 */
.top{height:4px;background:ACC;flex:0 0 auto}
.body{flex:1;display:flex;padding:0}
.left{flex:1;display:flex;flex-direction:column;justify-content:center;padding:0 0 0 64px}
.right{width:SHOTWpx;display:flex;align-items:center;justify-content:center;
  padding-right:56px;flex:0 0 auto}

.brand{display:flex;align-items:center;gap:10px;margin-bottom:26px}
.brand b{font-size:15px;letter-spacing:2.5px;font-weight:600;color:ACC}
.brand span{font-size:12px;letter-spacing:1px;color:MUT}

h1{font-size:H1px;font-weight:600;line-height:1.28;margin-bottom:18px;letter-spacing:-.5px}
h1 em{font-style:normal;color:ACC}
.sub{font-size:SUBpx;line-height:1.6;color:MUT;margin-bottom:28px;max-width:SUBWpx}

.tags{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:30px;max-width:TAGWpx}
.tag{font-size:12px;padding:5px 11px;border:1px solid LN;border-radius:6px;color:TX;
  background:PN}
.tag.hi{border-color:ACC;color:ACC}

.repo{font-size:13px;color:MUT;font-family:"Cascadia Code",Consolas,monospace}
.repo b{color:TX;font-weight:500}

.shot{border:1px solid LN;border-radius:10px;overflow:hidden;
  box-shadow:0 18px 50px rgba(0,0,0,.55);background:PN}
.shot img{display:block;width:100%}
.shotbar{height:26px;background:#0f151e;display:flex;align-items:center;gap:6px;
  padding:0 10px;border-bottom:1px solid LN}
.dot{width:8px;height:8px;border-radius:50%;background:#2c3644}
.dot.a{background:#e05c5c}.dot.b{background:#e0b25c}.dot.c{background:#5cbe7a}
.url{flex:1;margin-left:8px;font-size:10px;color:#5a6675;
  font-family:"Cascadia Code",Consolas,monospace}
</style></head><body>
<div class="top"></div>
<div class="body">
  <div class="left">
    <div class="brand"><b>OPENWORKBENCH</b><span>v2.0 · MIT</span></div>
    <h1>TITLEGOESHERE</h1>
    <div class="sub">SUBGOESHERE</div>
    <div class="tags">
      <span class="tag hi">零第三方依赖</span>
      <span class="tag">Python 标准库</span>
      <span class="tag">数据不出本机</span>
      <span class="tag">MCP 标准接口</span>
      <span class="tag">手机可用</span>
      <span class="tag">中英双语</span>
    </div>
    <div class="repo">github.com/<b>ZhangZhangooo</b>/open-workbench</div>
  </div>
  <div class="right">
    <div class="shot">
      <div class="shotbar"><span class="dot a"></span><span class="dot b"></span>
        <span class="dot c"></span><span class="url">127.0.0.1:8777</span></div>
      <img src="file:///SHOTPATH">
    </div>
  </div>
</div>
</body></html>
"""


def build(W, H, title, sub, shot_png, out_name, h1=46, sub_size=17, shot_scale=1.0):
    shot_w = int((H * 0.66) * shot_scale)
    # ⚠️ 用 str.replace 不用 % 格式化：CSS 里有 width:100% / border-radius:50%，
    #    跟 %-占位符打架（实测 TypeError: not enough arguments for format string）。
    # ⚠️ 占位符必须**全部**在下面列出来。早先漏了 WPX/HPX/INKC 三个，
    #    页面里留下 %(W)d 这种字面量；再加上 ACC 被替成 "#36d399s"（多一个 s）
    #    把整条 CSS 规则搞坏，**body 背景声明被丢弃 → 底色变白**，封面看着像白底卡片。
    html = (HTML
            .replace("INKC", INK)
            .replace("ACC", ACCENT).replace("MUT", MUTED)
            .replace("TX", TEXT).replace("PN", PANEL).replace("LN", LINE)
            .replace("WPXpx", "%dpx" % W).replace("HPXpx", "%dpx" % H)
            .replace("H1px", "%dpx" % h1).replace("SUBpx", "%dpx" % sub_size)
            .replace("SUBWpx", "%dpx" % int(W * 0.44))
            .replace("TAGWpx", "%dpx" % int(W * 0.44))
            .replace("SHOTWpx", "%dpx" % shot_w)
            .replace("TITLEGOESHERE", title)
            .replace("SUBGOESHERE", sub)
            .replace("SHOTPATH", shot_png.replace("\\", "/")))
    # 自检：占位符没被替换干净就别往下走（留给 verify 的哨兵，这里先自保）
    left = [k for k in ("%(W)", "%(H)", "GOESHERE", "SHOTPATH", ":ACC;", ":PN}",
                        ":LN}", ":TX;", ":MUT") if k in html]
    if left:
        raise SystemExit("模板占位符没替换干净：%s" % left)
    hp = os.path.join(tempfile.gettempdir(), "wb_cover_%s.html" % out_name.replace(".png", ""))
    with open(hp, "w", encoding="utf-8") as f:
        f.write(html)
    out = os.path.join(OUT, out_name)
    ok = shot("file:///" + hp.replace("\\", "/"), out, W, H)
    return ok, out


def selftest():
    ok = 0
    bad = 0

    def ck(name, cond, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s  <<< %s" % (name, str(extra)[:200]))

    ck("能找到 Chrome", os.path.isfile(find_chrome()))
    shots = [os.path.join(ASSETS, n) for n in
             ("ui-home.png", "ui-printer.png", "ui-mobile-transfer.png")]
    for s in shots:
        ck("素材截图存在 " + os.path.basename(s), os.path.isfile(s), s)
        if os.path.isfile(s):
            ck("  是合法 PNG " + os.path.basename(s), png_size(s) is not None)

    # 真生成一张，验尺寸与 PNG 结构
    home = shots[0]
    made, out = build(1280, 640,
                      "让 AI <em>主动来找你</em><br>而不是你一直去问它",
                      "早上一睁眼，要紧的邮件已经挑好了、回复草稿也写好了。"
                      "在微信里说一句话就能打印，手机拍的照片直传电脑。",
                      home, "cover-1280x640.png")
    ck("封面生成成功", made and os.path.isfile(out), out)
    if os.path.isfile(out):
        sz = png_size(out)
        ck("封面尺寸 1280x640", sz == (1280, 640), str(sz))
        ck("封面不是空白（>30KB）", os.path.getsize(out) > 30000,
           str(os.path.getsize(out)))

    print("\n=== 封面生成自检：%d PASS / %d FAIL ===" % (ok, bad))
    print("SMOKE_OK" if not bad else "SMOKE_FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    home = os.path.join(ASSETS, "ui-home.png")
    print(build(1280, 640,
                "让 AI <em>主动来找你</em><br>而不是你一直去问它",
                "早上一睁眼，要紧的邮件已经挑好了、回复草稿也写好了。"
                "在微信里说一句话就能打印，手机拍的照片直传电脑。",
                home, "cover-1280x640.png"))
