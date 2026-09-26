"""文档生成：把 Markdown 变成 docx / pptx。零第三方依赖，纯手写 OOXML。

为什么用 Markdown 当中转：
  1) 模型输出 Markdown 比输出 JSON 稳得多，不容易出格式错；
  2) 用户自己写的笔记、OpenClaw 的产出也都是 Markdown，一条路打通。

生成的 .docx / .pptx 能被 WPS 文字 / WPS 演示直接打开。
"""

from __future__ import annotations

import os
import re
import zipfile

# ---------- 公共小工具 ----------

def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _col(n: int) -> str:
    """1 -> A, 27 -> AA"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_EMPH = re.compile(r"(\*\*|__)(.+?)\1")


def _runs(text: str, bold: bool = False) -> str:
    """把 **加粗** 转成 word/ppt 的 rPr 分段。返回 <w:r>/<a:r> 片段。"""
    parts: list[str] = []
    pos = 0
    for m in _EMPH.finditer(text):
        if m.start() > pos:
            parts.append((text[pos:m.start()], bold))
        parts.append((m.group(2), True))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], bold))
    return [(t, b) for t, b in parts if t]


# ---------- Markdown -> 结构化块 ----------

def md_to_blocks(md: str) -> list[dict]:
    """支持：# ## ### 标题、- / * / 1. 列表、| 表格、空行分段。"""
    blocks: list[dict] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush():
        nonlocal para
        if para:
            blocks.append({"type": "p", "text": " ".join(para).strip()})
            para = []

    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()

        if not s:
            flush()
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            flush()
            rows = []
            for j in range(i, len(lines)):
                t = lines[j].strip()
                if not t.startswith("|"):
                    break
                cells = [c.strip() for c in t.strip("|").split("|")]
                if re.match(r"^[\s:|-]+$", "".join(cells)):
                    continue          # 跳过 |---|---| 分隔行
                rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            i = j
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush()
            lv = min(len(m.group(1)), 3)
            blocks.append({"type": f"h{lv}", "text": m.group(2).strip()})
            i += 1
            continue

        m = re.match(r"^([-*+])\s+(.*)$", s)
        if m:
            flush()
            blocks.append({"type": "bullet", "text": m.group(2).strip()})
            i += 1
            continue

        m = re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            flush()
            blocks.append({"type": "bullet", "text": m.group(1).strip()})
            i += 1
            continue

        para.append(s)
        i += 1

    flush()
    return blocks


def md_to_slides(md: str) -> list[dict]:
    """# 是整副标题页，## 开始一页，页内 - 是要点，其余是正文段。"""
    lines = md.replace("\r\n", "\n").split("\n")
    deck_title = ""
    slides: list[dict] = []
    cur: dict | None = None

    def flush():
        if cur and (cur["title"] or cur["bullets"] or cur["body"]):
            slides.append(cur)

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = re.match(r"^#\s+(.*)$", s)
        if m:
            if cur is None:
                deck_title = m.group(1).strip()
                continue
            s = "## " + m.group(1)     # 正文里的 # 当二级标题处理
        m = re.match(r"^##\s+(.*)$", s)
        if m:
            flush()
            cur = {"title": m.group(1).strip(), "bullets": [], "body": []}
            continue
        if cur is None:
            cur = {"title": "", "bullets": [], "body": []}
        mm = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
        if mm:
            cur["bullets"].append(mm.group(2).strip())
        else:
            cur["body"].append(s)

    flush()
    if deck_title:
        slides.insert(0, {"title": deck_title, "bullets": [], "body": []})
    return slides


def md_title(md: str, fallback: str = "未命名") -> str:
    for ln in md.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^#{1,2}\s+(.*)$", ln.strip())
        if m:
            return m.group(1).strip()[:60]
    for ln in md.replace("\r\n", "\n").split("\n"):
        if ln.strip():
            return ln.strip()[:60]
    return fallback


# ---------- DOCX ----------

_CT_DOCX = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W_NS}>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:cs="Microsoft YaHei"/>
<w:sz w:val="22"/><w:szCs w:val="22"/>
</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>
<w:spacing w:line="360" w:lineRule="auto"/>
</w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:before="0" w:after="240"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="300" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="100"/><w:outlineLvl w:val="2"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:pPr><w:ind w:left="420"/><w:spacing w:after="60"/></w:pPr></w:style>
</w:styles>"""


def _w_runs(text: str, base_bold: bool = False) -> str:
    out = []
    for t, b in _runs(text, base_bold):
        pr = "<w:rPr><w:b/><w:bCs/></w:rPr>" if b else ""
        out.append(f'<w:r>{pr}<w:t xml:space="preserve">{_esc(t)}</w:t></w:r>')
    return "".join(out)


def _docx_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    width = max(1200, int(9000 / ncol))
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(ncol))
    bd = ('<w:tblBorders>'
          + "".join(f'<w:{k} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                    for k in ("top", "left", "bottom", "right", "insideH", "insideV"))
          + "</w:tblBorders>")
    body = []
    for ri, row in enumerate(rows):
        cells = []
        for ci in range(ncol):
            v = row[ci] if ci < len(row) else ""
            shd = '<w:shd w:val="clear" w:fill="F2F2F2"/>' if ri == 0 else ""
            pr = f'<w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shd}</w:tcPr>'
            cells.append(f'<w:tc>{pr}<w:p>{_w_runs(v, ri == 0)}</w:p></w:tc>')
        trpr = '<w:trPr><w:tblHeader/></w:trPr>' if ri == 0 else ""
        body.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    return (f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/>{bd}</w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl>")


def write_docx(path: str, md: str, title: str = "") -> dict:
    blocks = md_to_blocks(md)
    if not blocks:
        return {"ok": False, "error": "没有可写的内容"}

    body: list[str] = []
    if title:
        body.append(f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>{_w_runs(title, True)}</w:p>')

    for b in blocks:
        t = b["type"]
        if t == "table":
            body.append(_docx_table(b["rows"]))
            body.append("<w:p/>")          # 表格后必须跟一个空段，否则 Word 报修复
        elif t in ("h1", "h2", "h3"):
            st = {"h1": "Heading1", "h2": "Heading2", "h3": "Heading3"}[t]
            body.append(f'<w:p><w:pPr><w:pStyle w:val="{st}"/></w:pPr>{_w_runs(b["text"], True)}</w:p>')
        elif t == "bullet":
            body.append(f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>'
                        f'{_w_runs("· " + b["text"])}</w:p>')
        else:
            body.append(f'<w:p>{_w_runs(b["text"])}</w:p>')

    body.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>')

    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f"<w:document {W_NS}><w:body>{''.join(body)}</w:body></w:document>")

    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_esc(title or "文档")}</dc:title>'
            '<dc:creator>OpenClaw</dc:creator><cp:lastModifiedBy>OpenClaw</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified>'
            '</cp:coreProperties>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>OpenClaw</Application></Properties>')

    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CT_DOCX)
            z.writestr("_rels/.rels", _ROOT_RELS)
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", _STYLES)
    except OSError as e:
        return {"ok": False, "error": f"写文件失败：{e}"}

    return {"ok": True, "kind": "docx", "path": path,
            "note": f"{len(blocks)} 个内容块"}


# ---------- PPTX ----------

P_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')

_THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="OpenClaw">'
          '<a:themeElements>'
          '<a:clrScheme name="Clr">'
          '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
          '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
          '<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
          '<a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
          '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
          '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
          '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
          '</a:clrScheme>'
          '<a:fontScheme name="Fnt">'
          '<a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/>'
          '<a:cs typeface="Microsoft YaHei"/></a:majorFont>'
          '<a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/>'
          '<a:cs typeface="Microsoft YaHei"/></a:minorFont>'
          '</a:fontScheme>'
          '<a:fmtScheme name="Fmt">'
          '<a:fillStyleLst>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '</a:fillStyleLst>'
          '<a:lnStyleLst>'
          '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
          '<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
          '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
          '</a:lnStyleLst>'
          '<a:effectStyleLst>'
          '<a:effectStyle><a:effectLst/></a:effectStyle>'
          '<a:effectStyle><a:effectLst/></a:effectStyle>'
          '<a:effectStyle><a:effectLst/></a:effectStyle>'
          '</a:effectStyleLst>'
          '<a:bgFillStyleLst>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '</a:bgFillStyleLst>'
          '</a:fmtScheme></a:themeElements></a:theme>')

_SLD_SZ = ('<p:sldSz cx="12192000" cy="6858000"/>'
           '<p:notesSz cx="6858000" cy="9144000"/>')


def _sp_tree(extra: str) -> str:
    return ('<p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + extra + '</p:spTree></p:cSld>')


def _textbox(sid: int, name: str, x: int, y: int, cx: int, cy: int,
             paras: list[tuple[str, int, bool]]) -> str:
    """paras: [(文本, 字号, 是否加粗)]"""
    ps = []
    for text, sz, bold in paras:
        rs = []
        for t, b in _runs(text, bold):
            battr = ' b="1"' if b else ""
            rs.append(f'<a:r><a:rPr lang="zh-CN" sz="{sz}"{battr} dirty="0">'
                      f'<a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:rPr>'
                      f'<a:t>{_esc(t)}</a:t></a:r>')
        ps.append(f'<a:p><a:pPr algn="l"/>{''.join(rs)}</a:p>')
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_esc(name)}"/>'
            '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            '<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>'
            f'{''.join(ps)}</p:txBody></p:sp>')


def _slide_xml(sl: dict, first: bool) -> str:
    paras: list[tuple[str, int, bool]] = []
    if first:
        cy = 1600000
        y = 2400000
        if sl["title"]:
            paras.append((sl["title"], 4000, True))
        for b in sl["body"][:2]:
            paras.append((b, 1800, False))
        inner = _textbox(2, "Title", 900000, y, 10400000, cy, paras)
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {P_NS}>'
                + _sp_tree(inner) + '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')

    paras = []
    if sl["title"]:
        paras.append((sl["title"], 2800, True))
    for b in sl["bullets"]:
        paras.append(("• " + b, 1800, False))
    for b in sl["body"]:
        paras.append((b, 1600, False))
    if not paras:
        paras = [("", 1800, False)]
    inner = _textbox(2, "Content", 800000, 700000, 10600000, 5400000, paras)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {P_NS}>'
            + _sp_tree(inner) + '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def write_pptx(path: str, md: str, title: str = "") -> dict:
    slides = md_to_slides(md)
    if not slides:
        return {"ok": False, "error": "没有可写的内容"}

    n = len(slides)
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    for k in range(1, n + 1):
        ct.append(f'<Override PartName="/ppt/slides/slide{k}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    ct.append("</Types>")

    pres_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>',
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>']
    sld_ids = []
    for k in range(1, n + 1):
        rid = f"rId{10 + k}"
        pres_rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{k}.xml"/>')
        sld_ids.append(f'<p:sldId id="{255 + k}" r:id="{rid}"/>')
    pres_rels.append("</Relationships>")

    presentation = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {P_NS}>'
                    '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                    f'<p:sldIdLst>{"".join(sld_ids)}</p:sldIdLst>{_SLD_SZ}</p:presentation>')

    master = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster {P_NS}>'
              + _sp_tree("")
              + '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
              'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
              'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
              '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
              '</p:sldMaster>')
    layout = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout {P_NS} '
              'type="blank" preserve="1">' + _sp_tree("")
              + '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')

    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_esc(title or "演示文稿")}</dc:title>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
            '</cp:coreProperties>')

    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", "".join(ct))
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                       '</Relationships>')
            z.writestr("docProps/core.xml", core)
            z.writestr("ppt/presentation.xml", presentation)
            z.writestr("ppt/_rels/presentation.xml.rels", "".join(pres_rels))
            z.writestr("ppt/theme/theme1.xml", _THEME)
            z.writestr("ppt/slideMasters/slideMaster1.xml", master)
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                       '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
                       '</Relationships>')
            z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
                       '</Relationships>')
            for k in range(1, n + 1):
                z.writestr(f"ppt/slides/slide{k}.xml", _slide_xml(slides[k - 1], k == 1))
                z.writestr(f"ppt/slides/_rels/slide{k}.xml.rels",
                           '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                           '</Relationships>')
    except OSError as e:
        return {"ok": False, "error": f"写文件失败：{e}"}

    return {"ok": True, "kind": "pptx", "path": path, "note": f"{n} 页"}


def write_any(path: str, kind: str, md: str, title: str = "") -> dict:
    kind = (kind or "").lower().lstrip(".")
    if kind in ("docx", "word", "doc"):
        return write_docx(path, md, title)
    if kind in ("pptx", "ppt", "演示"):
        return write_pptx(path, md, title)
    return {"ok": False, "error": f"{kind} 这种还不会写"}


def ext_of(kind: str) -> str:
    kind = (kind or "").lower().lstrip(".")
    if kind in ("word", "doc", "docx"):
        return ".docx"
    if kind in ("ppt", "pptx", "演示"):
        return ".pptx"
    if kind in ("excel", "xlsx", "表格"):
        return ".xlsx"
    return "." + (kind or "txt")


def safe_name(title: str, kind: str) -> str:
    """文件名里不能有的字符全部换掉，空标题给个默认名。"""
    t = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (title or "").strip())[:40]
    return (t or "未命名") + ext_of(kind)
