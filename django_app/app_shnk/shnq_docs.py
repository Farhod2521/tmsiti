"""
SHNQ hujjatlarini lex.uz ko'rinishida ko'rsatish uchun yordamchi modul.

1. parse_document()  — .docx faylni bloklar ro'yxatiga aylantiradi
   (paragraf, sarlavha, jadval, rasm). Lex.uz dan olingan Word fayldagi
   "(... tahririda)" izohlari oldingi bandga biriktiriladi, ishlamaydigan
   "Oldingi tahrirga qarang" yozuvlari olib tashlanadi.
2. rebuild_chain()   — bitta SHNQ ning bitta tildagi barcha tahrirlarini sana
   bo'yicha tartiblab, har birini oldingisi bilan solishtiradi va o'zgargan
   bandlarga tarix (hist) yozadi: qachon, qaysi hujjat bilan, oldingi matn.

Blok tuzilishi:
    {
        "id": "b12",
        "t": "p" | "h" | "table" | "removed",
        "html": "...",                  # xavfsiz, server o'zi yasagan HTML
        "align": "left|center|right|justify",
        "lvl": 1 | 2,                   # faqat sarlavhalar uchun
        "text": "...",                  # faqat sarlavhalar uchun (mundarija)
        "notes": ["(... tahririda)"],   # Word fayldagi izohlar
        "lexprev": true,                # Word faylda "Oldingi tahrirga qarang" bo'lgan
        "hist": [{"e", "date", "note", "kind": changed|added|removed, "prev"}],
        "key": "..."                    # solishtirish kaliti (API ga berilmaydi)
    }
Rasm manzillari HTML ichida "{{MEDIA}}FILES/..." ko'rinishida saqlanadi,
frontend uni MEDIA_URL bilan almashtiradi.
"""
import hashlib
import html
import os
import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

ALLOWED_EXTENSIONS = (".docx", ".doc", ".htm", ".html")
MEDIA_PLACEHOLDER = "{{MEDIA}}"

M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
A_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
V_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

WEB_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"}

_APOS = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'", "´": "'"})

PREV_LINK_RE = re.compile(
    r"^(oldingi tahrirga qarang|олдинги таҳрирга қаранг|см\.? предыдущую редакцию)\.?$"
)
NOTE_KEYWORDS_RE = re.compile(
    r"tahririda|таҳририда|редакци|to'ldirilgan|тўлдирилган|дополнен|chiqarilgan|чиқарилган|"
    r"исключен|o'zgartirilgan|ўзгартирилган|изменен|kuchini yo'qotgan|кучини йўқотган|утратил"
)
CHAPTER_RE = re.compile(
    r"^("
    r"(\d+|[ivxlc]+)\s*[-‑–]?\s*(bob|боб|bo'lim|бўлим|qism|қисм|глава|раздел|часть)\b"
    r"|(глава|раздел|часть|bob|боб)\s+(\d+|[ivxlc]+)\b"
    r"|(\d+\s*[-‑–]?\s*)?(ilova|илова|приложение)\b"
    r")"
)
HEADING_STYLE_RE = re.compile(r"^(heading|заголовок)\s*(\d)")


LANG_CODES = ("uz", "kr", "ru")
_LATIN_RE = re.compile(r"[a-z]")
_CYR_RE = re.compile(r"[а-яёўқғҳ]")
_UZ_CYR_RE = re.compile(r"[ўқғҳ]")
_RU_ONLY_RE = re.compile(r"[ыщ]")


def detect_lang(blocks):
    """
    Matn tilini aniqlaydi: "uz" (o'zbek lotin), "kr" (o'zbek kirill) yoki "ru".
    Kirillda o'zbekcha uchun ў/қ/ғ/ҳ, ruscha uchun ы/щ harflari hal qiladi.
    """
    text = " ".join(b.get("key", "") for b in blocks)[:300000]
    latin = len(_LATIN_RE.findall(text))
    cyr = len(_CYR_RE.findall(text))
    if latin > cyr:
        return "uz"
    return "kr" if len(_UZ_CYR_RE.findall(text)) > len(_RU_ONLY_RE.findall(text)) else "ru"


def resolve_lang(chosen, raw_blocks):
    """
    Admin tanlagan til bilan matndan aniqlangan tilni solishtiradi.
    "auto" yoki noma'lum bo'lsa — aniqlangani. O'zbekcha tanlanib, yozuvi (lotin/kirill)
    noto'g'ri bo'lsa ham aniqlangani olinadi; ruscha/o'zbekcha tanlovi esa hurmat qilinadi.
    """
    detected = detect_lang(raw_blocks)
    if chosen not in LANG_CODES:
        return detected
    if chosen in ("uz", "kr") and detected in ("uz", "kr"):
        return detected
    return chosen


def normalize(text):
    return re.sub(r"\s+", " ", (text or "").translate(_APOS)).strip().lower()


def _esc(text):
    return html.escape(text, quote=False)


def _flag(rpr, tag):
    """w:b, w:i kabi bayroq: True/False, yoki belgilanmagan bo'lsa None."""
    if rpr is None:
        return None
    el = rpr.find(qn(tag))
    if el is None:
        return None
    return el.get(qn("w:val")) not in ("0", "false", "off", "none")


class _Out:
    """Paragraf ichidagi bo'laklar: (format, html) va statistikasi."""

    def __init__(self):
        self.segs = []
        self.plain = []
        self.bold_chars = 0
        self.total_chars = 0

    def add_text(self, fmt, text):
        if not text:
            return
        self.segs.append((fmt, _esc(text)))
        self.plain.append(text)
        n = len(text.strip())
        self.total_chars += n
        if fmt and fmt[0]:
            self.bold_chars += n

    def add_raw(self, raw_html, plain=""):
        self.segs.append((None, raw_html))
        if plain:
            self.plain.append(plain)

    def extend(self, other):
        self.segs.extend(other.segs)
        self.plain.extend(other.plain)
        self.bold_chars += other.bold_chars
        self.total_chars += other.total_chars

    def render(self):
        # Bir xil formatdagi qo'shni bo'laklarni birlashtiramiz
        merged = []
        for fmt, piece in self.segs:
            if merged and merged[-1][0] == fmt and fmt is not None:
                merged[-1] = (fmt, merged[-1][1] + piece)
            else:
                merged.append((fmt, piece))
        parts = []
        for fmt, piece in merged:
            if fmt:
                bold, italic, underline, strike, valign = fmt
                if valign == "superscript":
                    piece = f"<sup>{piece}</sup>"
                elif valign == "subscript":
                    piece = f"<sub>{piece}</sub>"
                if strike:
                    piece = f"<s>{piece}</s>"
                if underline:
                    piece = f"<u>{piece}</u>"
                if italic:
                    piece = f"<i>{piece}</i>"
                if bold:
                    piece = f"<b>{piece}</b>"
            parts.append(piece)
        return "".join(parts).strip()

    @property
    def text(self):
        return re.sub(r"\s+", " ", "".join(self.plain)).strip()


class DocxParser:
    def __init__(self, path, image_saver):
        self.doc = Document(path)
        self.part = self.doc.part
        self.image_saver = image_saver
        self.styles = {}
        for style in self.doc.styles:
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                self.styles[style.style_id] = style
        try:
            self.default_style = self.doc.styles.default(WD_STYLE_TYPE.PARAGRAPH)
        except Exception:
            self.default_style = None
        self._style_cache = {}

    # ---------- uslublar ----------
    def _style_info(self, style_id):
        if style_id in self._style_cache:
            return self._style_cache[style_id]
        style = self.styles.get(style_id) if style_id else self.default_style
        name, bold, align = "", False, None
        if style is not None:
            name = (style.name or "").lower()
            s = style
            while s is not None:
                if s.font.bold is not None:
                    bold = bool(s.font.bold)
                    break
                s = s.base_style
            s = style
            while s is not None:
                if s.paragraph_format.alignment is not None:
                    align = s.paragraph_format.alignment
                    break
                s = s.base_style
        info = (name, bold, align)
        self._style_cache[style_id] = info
        return info

    # ---------- rasm ----------
    def _image(self, rid, out):
        if not rid or rid not in self.part.related_parts:
            return
        img_part = self.part.related_parts[rid]
        ext = os.path.splitext(str(img_part.partname))[1].lstrip(".").lower()
        if ext not in WEB_IMAGE_EXT:
            return  # EMF/WMF brauzerda ko'rinmaydi
        blob = img_part.blob
        digest = hashlib.sha1(blob).hexdigest()[:12]
        name = self.image_saver(blob, ext, digest)
        out.add_raw(f'<img src="{MEDIA_PLACEHOLDER}{_esc(name)}" alt="" loading="lazy">', f"[img:{digest}]")

    def _images_in(self, el, out):
        for blip in el.iter(A_BLIP):
            self._image(blip.get(R_EMBED), out)
        for imd in el.iter(V_IMAGEDATA):
            self._image(imd.get(R_ID), out)

    # ---------- matn ----------
    def _run(self, r, para_bold, out):
        rpr = r.find(qn("w:rPr"))
        bold = _flag(rpr, "w:b")
        if bold is None:
            bold = para_bold
        valign = None
        if rpr is not None:
            va = rpr.find(qn("w:vertAlign"))
            if va is not None:
                valign = va.get(qn("w:val"))
        fmt = (
            bool(bold),
            bool(_flag(rpr, "w:i")),
            bool(_flag(rpr, "w:u")),
            bool(_flag(rpr, "w:strike") or _flag(rpr, "w:dstrike")),
            valign if valign in ("superscript", "subscript") else None,
        )
        for ch in r:
            tag = ch.tag
            if tag == qn("w:t"):
                out.add_text(fmt, ch.text or "")
            elif tag == qn("w:tab"):
                out.add_text(fmt, " ")
            elif tag in (qn("w:br"), qn("w:cr")):
                if ch.get(qn("w:type")) != "page":
                    out.add_raw("<br>", " ")
            elif tag == qn("w:noBreakHyphen"):
                out.add_text(fmt, "-")
            elif tag == qn("w:sym"):
                code = ch.get(qn("w:char"))
                try:
                    out.add_text(fmt, chr(int(code, 16)))
                except (TypeError, ValueError):
                    pass
            elif tag in (qn("w:drawing"), qn("w:pict"), qn("w:object")) or tag.endswith("AlternateContent"):
                self._images_in(ch, out)

    def _math(self, el, out):
        text = "".join(t.text or "" for t in el.iter(f"{M_NS}t"))
        if text:
            out.add_raw(f'<span class="math">{_esc(text)}</span>', text)

    def _inline(self, el, para_bold, out):
        for ch in el:
            tag = ch.tag
            if tag == qn("w:r"):
                self._run(ch, para_bold, out)
            elif tag == qn("w:hyperlink"):
                sub = _Out()
                self._inline(ch, para_bold, sub)
                href = None
                rid = ch.get(R_ID)
                if rid and rid in self.part.rels:
                    rel = self.part.rels[rid]
                    if rel.is_external:
                        href = rel.target_ref
                inner = sub.render()
                if href and href.startswith(("http://", "https://")) and inner:
                    sub.segs = [(None, f'<a href="{html.escape(href)}" target="_blank" rel="noopener noreferrer">{inner}</a>')]
                out.extend(sub)
            elif tag in (f"{M_NS}oMath", f"{M_NS}oMathPara"):
                self._math(ch, out)
            elif tag in (
                qn("w:ins"), qn("w:smartTag"), qn("w:customXml"), qn("w:sdt"),
                qn("w:sdtContent"), qn("w:fldSimple"),
            ):
                self._inline(ch, para_bold, out)

    def _paragraph(self, p):
        ppr = p.find(qn("w:pPr"))
        style_id, jc = None, None
        if ppr is not None:
            ps = ppr.find(qn("w:pStyle"))
            if ps is not None:
                style_id = ps.get(qn("w:val"))
            j = ppr.find(qn("w:jc"))
            if j is not None:
                jc = j.get(qn("w:val"))
        style_name, style_bold, style_align = self._style_info(style_id)

        if jc in ("center",):
            align = "center"
        elif jc in ("right", "end"):
            align = "right"
        elif jc in ("both", "distribute", "lowKashida", "mediumKashida", "highKashida"):
            align = "justify"
        elif jc in ("left", "start"):
            align = "left"
        elif style_align == WD_ALIGN_PARAGRAPH.CENTER:
            align = "center"
        elif style_align == WD_ALIGN_PARAGRAPH.RIGHT:
            align = "right"
        elif style_align in (WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.DISTRIBUTE):
            align = "justify"
        else:
            align = "left"

        out = _Out()
        self._inline(p, style_bold, out)
        return {
            "t": "p",
            "html": out.render(),
            "plain": out.text,
            "align": align,
            "bold": (out.bold_chars / out.total_chars) if out.total_chars else 0,
            "style": style_name,
        }

    # ---------- jadval ----------
    def _cell_html(self, tc):
        parts = []
        for ch in tc:
            if ch.tag == qn("w:p"):
                b = self._paragraph(ch)
                if b["html"]:
                    parts.append(f'<p data-align="{b["align"]}">{b["html"]}</p>')
            elif ch.tag == qn("w:tbl"):
                parts.append(self._table(ch)["html"])
            elif ch.tag == qn("w:sdt"):
                content = ch.find(qn("w:sdtContent"))
                if content is not None:
                    parts.append(self._cell_html(content))
        return "".join(parts)

    def _table(self, tbl):
        rows = []
        for tr in tbl.iter(qn("w:tr")):
            if tr.getparent() is not tbl:
                continue
            cells, col = [], 0
            for tc in tr.findall(qn("w:tc")):
                tcpr = tc.find(qn("w:tcPr"))
                span, vmerge = 1, None
                if tcpr is not None:
                    gs = tcpr.find(qn("w:gridSpan"))
                    if gs is not None:
                        try:
                            span = max(1, int(gs.get(qn("w:val"))))
                        except (TypeError, ValueError):
                            span = 1
                    vm = tcpr.find(qn("w:vMerge"))
                    if vm is not None:
                        vmerge = vm.get(qn("w:val")) or "continue"
                cells.append({"col": col, "span": span, "vmerge": vmerge, "tc": tc})
                col += span
            rows.append(cells)

        html_rows, plain = [], []
        for r_idx, cells in enumerate(rows):
            tds = []
            for cell in cells:
                if cell["vmerge"] == "continue":
                    continue
                rowspan = 1
                if cell["vmerge"] == "restart":
                    for nxt in rows[r_idx + 1:]:
                        if any(c["col"] == cell["col"] and c["vmerge"] == "continue" for c in nxt):
                            rowspan += 1
                        else:
                            break
                content = self._cell_html(cell["tc"])
                plain.append(re.sub(r"<[^>]+>", " ", content))
                attrs = ""
                if cell["span"] > 1:
                    attrs += f' colspan="{cell["span"]}"'
                if rowspan > 1:
                    attrs += f' rowspan="{rowspan}"'
                tds.append(f"<td{attrs}>{content}</td>")
            html_rows.append(f"<tr>{''.join(tds)}</tr>")
        return {
            "t": "table",
            "html": f"<table><tbody>{''.join(html_rows)}</tbody></table>",
            "plain": re.sub(r"\s+", " ", " ".join(plain)).strip(),
            "align": "left",
        }

    # ---------- butun hujjat ----------
    def _body_items(self, container):
        for ch in container:
            if ch.tag == qn("w:p"):
                yield self._paragraph(ch)
            elif ch.tag == qn("w:tbl"):
                yield self._table(ch)
            elif ch.tag == qn("w:sdt"):
                content = ch.find(qn("w:sdtContent"))
                if content is not None:
                    yield from self._body_items(content)

    def parse(self):
        items = [b for b in self._body_items(self.doc.element.body) if b["html"]]
        return _postprocess(items)


# ---------------- lex.uz HTML (.doc) ----------------
# lex.uz "Word formatida yuklab olish" aslida HTML fayl beradi:
#   <div id="divCont"><div class="ACT_TEXT"><a id="6655917">matn</a></div>...</div>
LEX_HEADING_CLASSES = {"TEXT_HEADER_DEFAULT", "TEXT_HEADER_AFTER_SRC", "ACT_TITLE_APPL"}
LEX_CLAUSE_CLASSES = {"CLAUSE_DEFAULT", "CLAUSE_AFTER_SRC"}
LEX_NOTE_CLASSES = {"CHANGES_ORIGINS"}
LEX_CLASS_STYLE = {
    "ACCEPTING_BODY": ("center", "title"),
    "ACT_FORM": ("center", "title"),
    "ACT_FORM_LAW": ("center", "title"),
    "ACT_TITLE": ("center", "title"),
    "DEPARTMENTAL": ("center", "bold"),
    "EXTRACT": ("center", "bold"),
    "TEXT_BOLD": ("justify", "bold"),
    "TEXT_BOLD_CENTER": ("center", "bold"),
    "TEXT_BOLD_RIGHT": ("right", "bold"),
    "TEXT_CENTER": ("center", None),
    "TEXT_RIGHT": ("right", None),
    "TEXT_ITALIC": ("justify", "italic"),
    "SIGNATURE": ("right", "bold"),
    "SIGNATURE_WITH_BOLD": ("right", "bold"),
    "ACT_ESSENTIAL_ELEMENTS": ("left", "small"),
    "ACT_ESSENTIAL_ELEMENTS_NUM": ("left", "small"),
    "APPL_BANNER_LANDSCAPE_TITLE": ("right", "banner"),
    "APPL_BANNER_LANDSCAPE_TEXT": ("right", "banner"),
    "APPL_BANNER_PORTRAIT_TITLE": ("right", "banner"),
    "APPL_BANNER_PORTRAIT_TEXT": ("right", "banner"),
    "GRIF_PARLAMENT": ("right", "banner"),
    "COMMENT": ("justify", "comment"),
    "COMMENT_FOR_WARNING": ("justify", "comment"),
    "EXPLANATION": ("justify", "comment"),
    "FOOTNOTE": ("justify", "footnote"),
    "PUBLICATION_ORIGIN": ("left", "source"),
    "OFFICIAL_SOUR_TEXT": ("left", "source"),
    "INDEXES_ON_REF": ("left", "source"),
    "ACT_TEXT": ("justify", "indent"),
}
LEX_RENAME = {"strong": "b", "em": "i", "strike": "s", "del": "s"}
LEX_KEEP = {"b", "i", "u", "s", "sup", "sub"}
LEX_DROP = {"script", "style", "xml", "head", "title", "meta", "label", "o:p"}


class LexHtmlParser:
    def __init__(self, raw_bytes, image_saver):
        import lxml.html

        text = None
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw_bytes.decode("utf-8", errors="replace")
        self.root = lxml.html.fromstring(text)
        self.image_saver = image_saver
        self._img_cache = {}

    def _image_src(self, src):
        src = (src or "").strip()
        if not src or src.startswith("data:"):
            return None
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("/"):
            src = "https://lex.uz" + src
        if not src.startswith(("http://", "https://")):
            return None
        if src in self._img_cache:
            return self._img_cache[src]
        result = src.replace("http://", "https://", 1)
        try:
            import urllib.request

            req = urllib.request.Request(result, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                blob = resp.read(15 * 1024 * 1024)
                ctype = (resp.headers.get("Content-Type") or "").lower()
            ext = {"image/png": "png", "image/gif": "gif", "image/webp": "webp", "image/svg+xml": "svg",
                   "image/bmp": "bmp"}.get(ctype.split(";")[0].strip(), "jpg")
            if blob:
                digest = hashlib.sha1(blob).hexdigest()[:12]
                result = MEDIA_PLACEHOLDER + self.image_saver(blob, ext, digest)
        except Exception:
            pass  # yuklab bo'lmasa lex.uz dagi manzilni qoldiramiz
        self._img_cache[src] = result
        return result

    def _render_children(self, el):
        parts = [_esc(el.text or "")]
        for ch in el:
            parts.append(self._render(ch))
            parts.append(_esc(ch.tail or ""))
        return "".join(parts)

    def _render(self, el):
        if not isinstance(el.tag, str):
            return ""  # izoh (comment) va h.k.
        tag = el.tag.lower()
        if tag in LEX_DROP:
            return ""
        tag = LEX_RENAME.get(tag, tag)
        if tag == "br":
            return "<br>"
        if tag == "img":
            src = self._image_src(el.get("src"))
            return f'<img src="{html.escape(src)}" alt="" loading="lazy">' if src else ""

        inner = self._render_children(el)
        if tag == "a":
            href = el.get("href") or ""
            m = re.search(r"scrollText\((-?\d+)\)", href)
            if m:
                return f'<a href="#l{m.group(1)}" data-anchor="{m.group(1)}">{inner}</a>'
            if href.startswith(("http://", "https://")):
                href = re.sub(r"^http://(www\.)?lex\.uz", "https://lex.uz", href)
                return f'<a href="{html.escape(href)}" target="_blank" rel="noopener noreferrer">{inner}</a>'
            return inner
        if tag in ("td", "th"):
            attrs = ""
            for name in ("colspan", "rowspan"):
                val = (el.get(name) or "").strip()
                if val.isdigit() and int(val) > 1:
                    attrs += f' {name}="{val}"'
            return f"<{tag}{attrs}>{inner}</{tag}>"
        if tag in ("table", "thead", "tbody", "tr"):
            return f"<{tag}>{inner}</{tag}>"
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            align = (el.get("align") or "").lower()
            if not align:
                m = re.search(r"text-align\s*:\s*(\w+)", el.get("style") or "", re.I)
                align = m.group(1).lower() if m else "left"
            if align not in ("left", "center", "right", "justify"):
                align = "left"
            return f'<p data-align="{align}">{inner}</p>' if inner.strip() else ""
        if tag in LEX_KEEP:
            return f"<{tag}>{inner}</{tag}>" if inner else ""
        return inner  # span, font va boshqalar — faqat ichidagi matn

    def parse(self):
        cont = self.root.get_element_by_id("divCont", None)
        if cont is None:
            cont = self.root.find(".//body")
        if cont is None:
            cont = self.root
        items = []
        for div in cont:
            if not isinstance(div.tag, str) or div.tag.lower() != "div":
                continue
            cls = (div.get("class") or "").strip().split(" ")[0].upper()
            # Asosiy matn <a id="..."> (eski eksport) yoki <div id="..."> (yangi eksport) ichida bo'ladi
            anchor_el = None
            for ch in div:
                if isinstance(ch.tag, str) and ch.tag.lower() in ("a", "div") and ch.get("id"):
                    anchor_el = ch
                    break
            body = self._render_children(anchor_el) if anchor_el is not None else self._render_children(div)
            if anchor_el is not None and len(div) > 1:
                body += "".join(self._render(ch) + _esc(ch.tail or "") for ch in div if ch is not anchor_el)
            body = re.sub(r"(<br>\s*)+$", "", body.strip())
            body = re.sub(r"\s*(</?(?:table|tbody|thead|tr|td|th|p)\b[^>]*>)\s*", r"\1", body)
            plain = re.sub(r"\s+", " ", div.text_content()).strip()
            if not body or (not plain and "<img" not in body and "<table" not in body):
                continue
            if "<img" in body and not plain:
                plain = "[img:" + hashlib.sha1(body.encode()).hexdigest()[:12] + "]"

            item = {"html": body, "plain": plain, "fixed": True}
            if anchor_el is not None:
                item["anchor"] = anchor_el.get("id")
            align, style = LEX_CLASS_STYLE.get(cls, ("justify", None))
            if "<table" in body:
                item.update(t="table", align="left")
            elif cls in LEX_NOTE_CLASSES:
                item.update(t="p", align="justify", kind="note")
            elif cls in LEX_HEADING_CLASSES:
                is_para = re.match(r"^\d+\s*[-‑–]?\s*§|^§", plain)
                item.update(t="h", align="center", lvl=2 if is_para else 1)
            elif cls in LEX_CLAUSE_CLASSES:
                item.update(t="h", align="left", lvl=2)
            else:
                item.update(t="p", align=align)
                if style:
                    item["cls"] = style
            items.append(item)
        return _postprocess(items)


def _sniff(path):
    with open(path, "rb") as f:
        return _sniff_bytes(f.read(2048))


def _sniff_bytes(data):
    head = data[:2048]
    if head.startswith(b"PK"):
        return "docx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "word97"
    probe = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if probe.startswith((b"<html", b"<!doctype", b"<?xml", b"<head", b"<div", b"<meta")) or b"<html" in probe:
        return "html"
    return "unknown"


def _is_note(norm_text):
    if len(norm_text) > 1500 or not norm_text.startswith("("):
        return False
    if not norm_text.rstrip(".;").endswith(")"):
        return False
    return bool(NOTE_KEYWORDS_RE.search(norm_text))


def _postprocess(items):
    blocks = []
    pending_lexprev = False
    for item in items:
        n = normalize(item["plain"])
        if item["t"] == "p":
            if PREV_LINK_RE.match(n):
                pending_lexprev = True
                continue
            if blocks and (item.get("kind") == "note" or _is_note(n)):
                blocks[-1].setdefault("notes", []).append(item["html"])
                continue
        block = dict(item)
        block.pop("kind", None)
        block["key"] = n
        if pending_lexprev:
            block["lexprev"] = True
            pending_lexprev = False
        blocks.append(block)

    # Sarlavhalarni aniqlash (lex.uz fayllarida sinflar bo'yicha allaqachon aniqlangan)
    candidates = []
    has_chapters = any(b.get("fixed") for b in blocks)
    for idx, b in enumerate(blocks):
        if b["t"] != "p" or b.get("fixed"):
            continue
        plain = b["plain"]
        m = HEADING_STYLE_RE.match(b.get("style", ""))
        if m:
            b["t"], b["lvl"] = "h", 1 if m.group(2) == "1" else 2
        elif CHAPTER_RE.match(b["key"]) and len(plain) < 300 and (b["bold"] > 0.6 or b["align"] == "center"):
            b["t"], b["lvl"] = "h", 1
            has_chapters = True
        elif (
            b["align"] == "center" and b["bold"] > 0.8 and len(plain) < 250
            and not plain.endswith((";", ",", ":"))
        ):
            candidates.append(idx)

    if has_chapters:
        first_chapter = next((i for i, b in enumerate(blocks) if b.get("lvl") == 1 and b["t"] == "h"), len(blocks))
    else:
        # Hujjat boshidagi markazlashgan qalin qatorlar — sarlavha (buyruq nomi), bo'lim emas
        first_chapter = 0
        while first_chapter < len(blocks) and first_chapter in candidates:
            first_chapter += 1
    for idx in candidates:
        if idx >= first_chapter:
            blocks[idx]["t"], blocks[idx]["lvl"] = "h", 2

    for b in blocks:
        if b["t"] == "h":
            b["text"] = b["plain"][:300]
        for k in ("plain", "bold", "style", "fixed"):
            b.pop(k, None)
    return blocks


# ---------------- .doc -> .docx ----------------
def _find_soffice():
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    for path in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ):
        if os.path.exists(path):
            return path
    return None


def parse_document(path, image_saver):
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Faqat .doc, .docx yoki .html fayl yuklash mumkin")
    kind = _sniff(path)
    if kind == "html":
        with open(path, "rb") as f:
            return LexHtmlParser(f.read(), image_saver).parse()
    if kind == "docx":
        return DocxParser(path, image_saver).parse()
    if kind != "word97":
        raise ValueError("Fayl formati tanilmadi. lex.uz dan yuklangan .doc yoki Word .docx fayl yuklang")

    soffice = _find_soffice()
    if not soffice:
        raise ValueError(
            ".doc formatini o'qish uchun serverda LibreOffice o'rnatilmagan. "
            "Faylni Word'da ochib .docx qilib saqlang va qayta yuklang."
        )
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, path],
            check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        converted = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".docx")
        if not os.path.exists(converted):
            raise ValueError(".doc faylni .docx ga o'girib bo'lmadi")
        return DocxParser(converted, image_saver).parse()


# ---------------- tahrirlarni solishtirish ----------------
def block_outer_html(block):
    if block["t"] == "table" or block["t"] == "removed":
        inner = block["html"]
    else:
        tag = "h4" if block["t"] == "h" else "p"
        inner = f'<{tag} data-align="{block.get("align", "left")}">{block["html"]}</{tag}>'
    notes = "".join(f'<p class="note">{n}</p>' for n in block.get("notes", []))
    return inner + notes


def _entry(edition, kind, prev_html=None):
    return {
        "e": edition.id,
        "date": edition.edition_date.isoformat(),
        "note": edition.note or "",
        "kind": kind,
        "prev": prev_html,
    }


def diff_blocks(prev, raw, edition):
    """prev — oldingi tahrir bloklari (hist bilan), raw — yangi tahrirning toza bloklari."""
    a = [b["key"] for b in prev]
    b_keys = [b["key"] for b in raw]
    sm = SequenceMatcher(None, a, b_keys, autojunk=False)
    out = []
    counts = {"changed": 0, "added": 0, "removed": 0}

    def new_block(j, hist):
        nb = dict(raw[j])
        nb["hist"] = hist
        out.append(nb)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                new_block(j1 + k, list(prev[i1 + k].get("hist", [])))
        elif tag == "insert":
            for j in range(j1, j2):
                new_block(j, [_entry(edition, "added")])
                counts["added"] += 1
        elif tag == "delete":
            old_html = "".join(block_outer_html(b) for b in prev[i1:i2])
            out.append({
                "t": "removed", "html": old_html, "align": "left", "key": "",
                "hist": [_entry(edition, "removed", old_html)],
            })
            counts["removed"] += 1
        else:  # replace
            old, new_range = prev[i1:i2], range(j1, j2)
            if len(old) == len(new_range):
                for o, j in zip(old, new_range):
                    new_block(j, list(o.get("hist", [])) + [_entry(edition, "changed", block_outer_html(o))])
                    counts["changed"] += 1
            else:
                old_html = "".join(block_outer_html(o) for o in old)
                for n, j in enumerate(new_range):
                    if n == 0:
                        new_block(j, list(old[0].get("hist", [])) + [_entry(edition, "changed", old_html)])
                        counts["changed"] += 1
                    else:
                        new_block(j, [_entry(edition, "added")])
                        counts["added"] += 1
    return out, counts


def content_hash(raw_blocks):
    return hashlib.sha1("\n".join(b.get("key", "") for b in raw_blocks).encode("utf-8")).hexdigest()


def rebuild_chain(owner_id, lang, model=None):
    """
    Hujjatning bitta tildagi barcha tahrirlarini qaytadan solishtirib chiqadi.
    model — ShnkEdition (standart) yoki LawEdition; owner_id — shnk_id / law_id.
    """
    if model is None:
        from .models import ShnkEdition as model

    editions = model.objects.filter(**{model.OWNER_FIELD: owner_id}, lang=lang).order_by("edition_date", "id")
    prev = None
    for edition in editions:
        raw = edition.raw_blocks or []
        if not raw:
            edition.blocks, edition.toc = [], []
            edition.stats = {"blocks": 0}
            edition.save(update_fields=["blocks", "toc", "stats", "updated_at"])
            continue

        if prev is None:
            blocks = [dict(b, hist=[]) for b in raw]
            counts = {"changed": 0, "added": 0, "removed": 0}
            is_original = True
        else:
            blocks, counts = diff_blocks(prev, raw, edition)
            is_original = False

        toc = []
        for idx, b in enumerate(blocks):
            b["id"] = f"b{idx}"
            if b["t"] == "h":
                toc.append({"id": b["id"], "text": b.get("text", ""), "lvl": b.get("lvl", 1)})

        edition.blocks = blocks
        edition.toc = toc
        edition.stats = dict(counts, blocks=len(blocks), headings=len(toc), original=is_original)
        edition.save(update_fields=["blocks", "toc", "stats", "updated_at"])
        prev = [b for b in blocks if b["t"] != "removed"]


def process_edition(edition):
    """Yuklangan faylni o'qib raw_blocks ga yozadi. Xato bo'lsa ValueError."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    folder = f"FILES/shnq_editions/{edition.media_folder()}/img"

    def save_image(blob, ext, digest):
        name = f"{folder}/{digest}.{ext}"
        if not default_storage.exists(name):
            name = default_storage.save(name, ContentFile(blob))
        return name

    try:
        raw = parse_document(edition.source_file.path, save_image)
    except ValueError:
        raise
    except Exception as exc:  # buzilgan fayl va h.k.
        raise ValueError(f"Faylni o'qib bo'lmadi: {exc}") from exc
    if not raw:
        raise ValueError("Faylda matn topilmadi")

    edition.raw_blocks = raw
    edition.content_hash = content_hash(raw)
    edition.parse_error = ""
    edition.save(update_fields=["raw_blocks", "content_hash", "parse_error", "updated_at"])
    return raw
