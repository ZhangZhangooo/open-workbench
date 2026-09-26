"""文档读写：零第三方依赖，只用标准库。

能读：docx / pptx / xlsx（都是 zip + xml）、pdf 的**文本层**、txt / md / csv / 代码
不能读：扫描版 PDF（没有文本层，得先 OCR 成图片再识别）、老式 .doc（二进制 OLE）

写一个原则：解析不出来就老实说「读不了 / 像扫描件」，绝不返回半截乱码当正文。
"""

from __future__ import annotations

import os
import re
import zipfile

MAX_TEXT = 200_000


# ---------- 小工具 ----------

def _xml_text(blob: str, tags: tuple[str, ...]) -> list[str]:
    """抠出指定标签里的文本，按出现顺序。够用就行，不做完整 XML 解析。"""
    out = []
    for m in re.finditer(r"<(?:" + "|".join(tags) + r")(?:\s[^>]*)?>(.*?)</(?:"
                         + "|".join(tags) + r")>", blob, re.S):
        t = m.group(1)
        t = re.sub(r"<[^>]+>", "", t)
        t = (t.replace("&amp;", "&").replace("&lt;", "<")
              .replace("&gt;", ">").replace("&quot;", '"')
              .replace("&apos;", "'"))
        if t.strip():
            out.append(t.strip())
    return out


def _col_idx(ref: str) -> int:
    """'AB12' -> 27（列序号，从 0 开始）。"""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1 if n > 0 else 0


# ---------- docx ----------

def read_docx(path: str) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        return {"ok": False, "error": f"打不开：{e}"}

    # 段落：w:p 是一段，里面的 w:t 拼起来
    paras = []
    for pm in re.finditer(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", xml, re.S):
        ts = _xml_text(pm.group(1), ("w:t",))
        if ts:
            paras.append("".join(ts))
    text = "\n".join(paras)

    # 表格：w:tbl 里的每行 w:tr、每格 w:tc
    tables = []
    for tm in re.finditer(r"<w:tbl(?:\s[^>]*)?>(.*?)</w:tbl>", xml, re.S):
        rows = []
        for rm in re.finditer(r"<w:tr(?:\s[^>]*)?>(.*?)</w:tr>", tm.group(1), re.S):
            cells = []
            for cm in re.finditer(r"<w:tc(?:\s[^>]*)?>(.*?)</w:tc>", rm.group(1), re.S):
                cells.append("".join(_xml_text(cm.group(1), ("w:t",))))
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)

    return {"ok": True, "kind": "docx", "text": text[:MAX_TEXT],
            "tables": tables, "paras": len(paras),
            "note": f"{len(paras)} 段，{len(tables)} 个表"}


# ---------- pptx ----------

def read_pptx(path: str) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            slides = sorted(n for n in z.namelist()
                            if re.match(r"ppt/slides/slide\d+\.xml$", n))
            if not slides:
                return {"ok": False, "error": "里面没有幻灯片"}
            pages = []
            for n in slides:
                xml = z.read(n).decode("utf-8", "replace")
                idx = int(re.search(r"slide(\d+)\.xml", n).group(1))
                ts = _xml_text(xml, ("a:t",))
                if ts:
                    pages.append((idx, "\n".join(ts)))
            pages.sort()
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        return {"ok": False, "error": f"打不开：{e}"}

    text = "\n\n".join(f"— 第 {i} 页 —\n{t}" for i, t in pages)
    return {"ok": True, "kind": "pptx", "text": text[:MAX_TEXT], "tables": [],
            "slides": len(pages), "note": f"{len(pages)} 页"}


# ---------- xlsx ----------

def read_xlsx(path: str, sheet: str = "") -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                sx = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                for sm in re.finditer(r"<si>(.*?)</si>", sx, re.S):
                    shared.append("".join(_xml_text(sm.group(1), ("t",))))

            sheets = [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
            if not sheets:
                return {"ok": False, "error": "没有工作表"}
            target = sheet if sheet in names else sorted(
                sheets, key=lambda s: int(re.search(r"sheet(\d+)", s).group(1)))[0]
            xml = z.read(target).decode("utf-8", "replace")
            sheet_names = _sheet_names(z)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        return {"ok": False, "error": f"打不开：{e}"}

    rows: dict[int, dict[int, str]] = {}
    for cm in re.finditer(r'<c\b([^>]*)>(.*?)</c>|<c\b([^>]*)/>', xml, re.S):
        attrs = cm.group(1) or cm.group(3) or ""
        inner = cm.group(2) or ""
        ref = re.search(r'r="([A-Z]+\d+)"', attrs)
        if not ref:
            continue
        r_i = int(re.search(r"\d+", ref.group(1)).group(0)) - 1
        c_i = _col_idx(ref.group(1))
        t = re.search(r'\bt="([^"]+)"', attrs)
        if t and t.group(1) == "s":
            vm = re.search(r"<v>(.*?)</v>", inner, re.S)
            if vm:
                try:
                    val = shared[int(vm.group(1))]
                except (ValueError, IndexError):
                    val = ""
            else:
                val = ""
        elif t and t.group(1) == "inlineStr":
            val = "".join(_xml_text(inner, ("t",)))
        else:
            vm = re.search(r"<v>(.*?)</v>", inner, re.S)
            val = vm.group(1).strip() if vm else ""
        if val:
            rows.setdefault(r_i, {})[c_i] = val

    if not rows:
        return {"ok": True, "kind": "xlsx", "rows": [], "text": "",
                "note": "表是空的", "sheets": sheet_names}

    max_r = max(rows)
    max_c = max(max(v) for v in rows.values())
    grid = [[rows.get(r, {}).get(c, "") for c in range(max_c + 1)]
            for r in range(max_r + 1)]
    # 掐掉全空的尾巴
    grid = [g for g in grid if any(x for x in g)]

    text = "\n".join("\t".join(g) for g in grid)
    return {"ok": True, "kind": "xlsx", "rows": grid, "text": text[:MAX_TEXT],
            "sheets": sheet_names, "note": f"{len(grid)} 行 × {max_c + 1} 列"}


def _sheet_names(z: zipfile.ZipFile) -> list[str]:
    try:
        wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
    except KeyError:
        return []
    out = []
    for m in re.finditer(r'<sheet\b[^>]*name="([^"]*)"', wb):
        out.append(m.group(1))
    return out


# ---------- pdf（只抽文本层）----------

_TJ = re.compile(r"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>")


def _cmaps(raw: bytes) -> dict[int, str]:
    """从 PDF 里抠出 ToUnicode 映射表（中文 PDF 基本都靠它才能解出字）。

    CID 编码的 PDF，字模里存的是字形编号而不是 Unicode，
    必须查这张表才能变回汉字。没有这张表就只能解出乱码。
    """
    import zlib
    table: dict[int, str] = {}

    blobs: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            blobs.append(zlib.decompress(m.group(1)).decode("latin-1", "replace"))
        except zlib.error:
            continue
    blobs.append(raw.decode("latin-1", "replace"))   # 有些 CMap 没压缩

    for b in blobs:
        if "beginbfchar" not in b and "beginbfrange" not in b:
            continue
        for block in re.findall(r"beginbfchar(.*?)endbfchar", b, re.S):
            for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                try:
                    code = int(src, 16)
                    ub = bytes.fromhex(dst if len(dst) % 2 == 0 else dst[:-1])
                    table[code] = ub.decode("utf-16-be", "replace")
                except (ValueError, UnicodeDecodeError):
                    continue
        for block in re.findall(r"beginbfrange(.*?)endbfrange", b, re.S):
            for a, z, dst in re.findall(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                try:
                    lo, hi = int(a, 16), int(z, 16)
                    base = int(dst, 16)
                    for i in range(min(hi - lo, 65535) + 1):
                        try:
                            table[lo + i] = chr(base + i)
                        except ValueError:
                            break
                except ValueError:
                    continue
            # 有些 bfrange 的目标是数组 [ <xx> <yy> ... ]
            for m in re.finditer(
                    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
                try:
                    lo = int(m.group(1), 16)
                    for i, d in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", m.group(3))):
                        ub = bytes.fromhex(d if len(d) % 2 == 0 else d[:-1])
                        table[lo + i] = ub.decode("utf-16-be", "replace")
                except (ValueError, UnicodeDecodeError):
                    continue
    return table


def _readable_ratio(s: str) -> float:
    """能看的比例。用来判断抽出来的到底是文字还是一坨乱码。"""
    if not s:
        return 0.0
    good = 0
    for ch in s:
        o = ord(ch)
        if ch in " \t\n\r":
            good += 1
        elif 0x20 <= o < 0x7F:          # 半角
            good += 1
        elif 0x3000 <= o <= 0x9FFF:     # 中日韩
            good += 1
        elif 0xFF00 <= o <= 0xFFEF:     # 全角
            good += 1
    return good / len(s)


def read_pdf(path: str) -> dict:
    """只抽文本层。扫描件和 CID 解不开的，都如实说读不了。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "error": f"读不了：{e}"}

    import zlib
    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            data = zlib.decompress(m.group(1))
        except zlib.error:
            continue
        if b"Tj" not in data and b"TJ" not in data:
            continue
        chunks.append(data.decode("latin-1", "replace"))

    if not chunks:
        return {"ok": False, "kind": "pdf", "error": "这个 PDF 里没有文字层，"
                "大概率是扫描件。要读它得先装视觉模型做 OCR"}

    cmap = _cmaps(raw)

    def hexs_to_text(h: str) -> str:
        """CID：一般是 2 字节一个字，查 ToUnicode 表变回汉字。"""
        h = re.sub(r"\s+", "", h)
        if len(h) % 4:      # 凑不到 2 字节对齐就按 4 位一组试
            pass
        out = []
        for i in range(0, len(h) - 1, 4):
            try:
                code = int(h[i:i + 4], 16)
            except ValueError:
                continue
            if code in cmap:
                out.append(cmap[code])
            else:
                # 表里没有：2 字节直接当 UTF-16BE 解，解出来是控制字符就丢弃
                try:
                    ch = bytes.fromhex(h[i:i + 4]).decode("utf-16-be", "replace")
                except ValueError:
                    continue
                if ch and ord(ch[0]) >= 0x20:
                    out.append(ch)
        return "".join(out)

    parts = []
    for c in chunks:
        for tm in re.finditer(r"\((?:\\.|[^\\()])*\)\s*Tj|<([0-9A-Fa-f\s]+)>\s*Tj"
                              r"|\[(.*?)\]\s*TJ", c, re.S):
            if tm.group(1):                       # <hex> Tj
                parts.append(hexs_to_text(tm.group(1)))
            elif tm.group(2) is not None:         # [ ... ] TJ
                inner = tm.group(2) or ""
                buf = []
                for x in _TJ.findall(inner):
                    if x.startswith("<"):
                        buf.append(hexs_to_text(x[1:-1]))
                    elif x.startswith("("):
                        buf.append(_unescape(x))
                    else:
                        buf.append(" ")
                parts.append("".join(buf))
            elif tm.group(0).startswith("("):     # (str) Tj
                parts.append(_unescape(tm.group(0)[:-2].strip()))

    text = re.sub(r"[ \t]+", " ", "".join(parts)).strip()
    ratio = _readable_ratio(text)

    if len(text) < 20:
        return {"ok": False, "kind": "pdf",
                "error": f"只抽出 {len(text)} 个字符，像是扫描件或纯图 PDF"}
    if ratio < 0.6:
        return {"ok": False, "kind": "pdf",
                "error": f"抽出来了但大部分是乱码（可读率 {ratio:.0%}）"
                         "—— 这个 PDF 用了我没解开的字体编码，"
                         "别拿它去总结，会得出一堆胡话"}

    return {"ok": True, "kind": "pdf", "text": text[:MAX_TEXT], "tables": [],
            "note": f"抽出 {len(text)} 字符（文本层，可读率 {ratio:.0%}）"}


def _unescape(s: str) -> str:
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    s = (s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
          .replace("\\n", "\n").replace("\\r", "").replace("\\t", "\t"))
    # PDF 的 UTF-16BE（带 BOM）在 latin-1 下会显示为 \xfe\xff 之类
    if s.startswith("\xfe\xff"):
        try:
            return s.encode("latin-1").decode("utf-16-be", "replace")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


# ---------- 纯文本 ----------

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css",
            ".log", ".ini", ".cfg", ".yml", ".yaml", ".xml", ".sql", ".sh", ".bat",
            ".java", ".go", ".rs", ".c", ".cpp", ".h"}


def read_text(path: str) -> dict:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                t = f.read(MAX_TEXT)
            return {"ok": True, "kind": "text", "text": t, "tables": [],
                    "note": f"{len(t)} 字符（{enc}）"}
        except (UnicodeDecodeError, OSError):
            continue
    return {"ok": False, "error": "这个文件的编码我解不开"}


def pdf_render(path: str, max_pages: int = None, dpi: int = 150) -> dict:
    """把 PDF 的每一页渲染成 PNG，给扫描件走 OCR 用。

    max_pages 留 None（默认）= 渲染整份 PDF；传数字则只渲染前 N 页。
    pymupdf 是**可选**依赖（本项目主体零第三方依赖，这个只在这一条路上用）。
    没装就老实说装不了，不假装成功。
    """
    try:
        try:
            import pymupdf as M            # 1.24+ 的新包名
        except ImportError:
            import fitz as M               # noqa: N813  老包名
    except ImportError:
        return {"ok": False, "error": "没装 pymupdf，先把 PDF 渲染成图片才能 OCR。"
                                      "终端跑：pip install pymupdf"}
    try:
        doc = M.open(path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"这个 PDF 打不开：{e}"}

    n = doc.page_count
    take = min(n, max_pages) if max_pages else n
    pages = []
    for i in range(take):
        try:
            pix = doc[i].get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"第 {i + 1} 页渲染失败：{e}"}
    doc.close()
    return {"ok": True, "pages": pages, "total": n, "rendered": take}


# ---------- 统一入口 ----------

READERS = {
    ".docx": read_docx,
    ".pptx": read_pptx,
    ".xlsx": read_xlsx,
    ".xlsm": read_xlsx,
    ".pdf": read_pdf,
}


def read_any(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "文件不存在"}
    ext = os.path.splitext(path)[1].lower()
    fn = READERS.get(ext)
    if fn:
        r = fn(path)
    elif ext in TEXT_EXT:
        r = read_text(path)
    else:
        return {"ok": False, "error": f"{ext} 这种格式我读不了"}
    r.setdefault("path", path)
    r.setdefault("name", os.path.basename(path))
    if not r.get("ok"):
        r.setdefault("kind", ext.lstrip("."))
    return r
