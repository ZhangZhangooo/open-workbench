# -*- coding: utf-8 -*-
"""一次生成全部尺寸的封面：GitHub/社交预览 1280x640、小红书 1080x1440、手机 1080x1080。

用法：python mkcover_all.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkcover  # noqa: E402

CN_TITLE = "让 AI <em>主动来找你</em><br>而不是你一直去问它"
CN_SUB = ("早上一睁眼，要紧的邮件已经挑好了、回复草稿也写好了。"
          "在微信里说一句话就能打印，手机拍的照片直传电脑。")
EN_TITLE = "Let the AI <em>come to you</em><br>instead of you always asking"
EN_SUB = ("It flags the emails that need you and drafts the replies before you "
          "open the app. Prints from WeChat. Your phone's photos land on your "
          "computer raw, EXIF intact. Zero dependencies.")

JOBS = [
    # (宽, 高, 标题, 副标题, 素材, 输出名, h1字号, sub字号, 截图占比)
    (1280, 640, CN_TITLE, CN_SUB, "ui-home.png", "cover-1280x640.png", 46, 17, 1.0),
    (1280, 640, EN_TITLE, EN_SUB, "ui-home.png", "cover-en-1280x640.png", 44, 16, 1.0),
    (1080, 1440, CN_TITLE, CN_SUB, "ui-home.png", "cover-1080x1440.png", 62, 22, 1.35),
    (1080, 1080, CN_TITLE, CN_SUB, "ui-mobile-transfer.png",
     "cover-mobile-1080.png", 54, 20, 1.5),
]


def main():
    made = []
    for W, H, title, sub, asset, out, h1, sub_size, scale in JOBS:
        shot = os.path.join(mkcover.ASSETS, asset)
        if not os.path.isfile(shot):
            print("  跳过 %s（素材缺失：%s）" % (out, asset))
            continue
        # 竖版/方版缩窄左栏时，截图得留够宽度，否则会被挤扁
        if H > W:
            scale = max(scale, 1.2)
        ok, path = mkcover.build(W, H, title, sub, shot, out,
                                 h1=h1, sub_size=sub_size, shot_scale=scale)
        sz = os.path.getsize(path) if ok and os.path.isfile(path) else 0
        print("  %s  %dx%d  %.1f KB" % ("OK " if sz > 20000 else "?? ",
                                       W, H, sz / 1024.0))
        if sz > 20000:
            made.append(path)
    print("\n生成 %d 张：" % len(made))
    for p in made:
        print("  " + os.path.basename(p))
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
