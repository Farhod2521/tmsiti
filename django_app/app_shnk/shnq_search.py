"""
SHNQ hujjatlari ichidan qidiruv (MySQL FULLTEXT).

Har bir SHNQ ning har bir tildagi oxirgi tahriri bandlarga bo'linib ShnkSearchBlock jadvaliga
yoziladi (tahriri yo'q hujjatlarda — PDF sahifalari). search_text ustuni — matnning
lotin, kichik harf va tutuq belgilarisiz ko'rinishi: "Қурилиш", "Qurilish", "qurilish"
bir xil topiladi. FULLTEXT indeksni `python manage.py shnq_search_index` yaratadi.

    GET /api/shnq/search/?q=yong'in xavfsizligi
"""
import html
import logging
import os
import re

from django.conf import settings
from django.db import connection

from .shnq_docs import _CYR_WORD_RE, _latin_chars

logger = logging.getLogger(__name__)

FULLTEXT_INDEX = "shnq_search_ft"
MIN_TERM = 3          # MySQL innodb_ft_min_token_size (standart 3) dan qisqa so'zlar indekslanmaydi
SNIPPET_BEFORE = 70
SNIPPET_AFTER = 170

_APOSTROPHES = set("'ʻʼ‘’`´")
_TAG_RE = re.compile(r"<[^>]+>")


# ---------------- normallashtirish ----------------
def _norm_chars(text):
    """(normallashgan belgi, asl matndagi indeks) juftliklari."""
    pos = 0
    for m in _CYR_WORD_RE.finditer(text):
        yield from _plain_chars(text, pos, m.start())
        for offset, lat in enumerate(_latin_chars(m.group(0).lower())):
            for ch in lat:
                yield from _plain_chars(ch, 0, 1, m.start() + offset)
        pos = m.end()
    yield from _plain_chars(text, pos, len(text))


def _plain_chars(text, start, end, origin=None):
    for i in range(start, end):
        ch = text[i].lower()
        if ch in _APOSTROPHES:
            continue
        idx = origin if origin is not None else i
        yield (ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else " "), idx


def search_norm(text):
    """Qidiruv kaliti: lotin, kichik harf, faqat [a-z0-9] va bo'shliq."""
    return re.sub(r"\s+", " ", "".join(ch for ch, _ in _norm_chars(text or ""))).strip()


def query_terms(query):
    return [t for t in search_norm(query).split(" ") if t]


def make_snippet(text, terms):
    """Birinchi topilgan joy atrofidagi parcha; topilgan so'zlar <mark> ichida (HTML xavfsiz)."""
    pairs = list(_norm_chars(text))
    norm = "".join(ch for ch, _ in pairs)
    spans = []
    for term in terms:
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(term)}", norm):
            start = pairs[m.start()][1]
            end = pairs[m.end() - 1][1] + 1
            while end < len(text) and text[end].isalnum():  # so'zni oxirigacha belgilaymiz
                end += 1
            spans.append((start, end))
    if not spans:
        return html.escape(text[:SNIPPET_BEFORE + SNIPPET_AFTER])
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))

    first = merged[0][0]
    lo = max(0, first - SNIPPET_BEFORE)
    hi = min(len(text), first + SNIPPET_AFTER)
    if lo > 0:
        lo = text.find(" ", lo, first) + 1 or lo
    if hi < len(text):
        cut = text.rfind(" ", first, hi)
        hi = cut if cut > first else hi

    parts, pos = [], lo
    for s, e in merged:
        if e <= lo or s >= hi:
            continue
        s, e = max(s, lo), min(e, hi)
        parts.append(html.escape(text[pos:s]))
        parts.append(f"<mark>{html.escape(text[s:e])}</mark>")
        pos = e
    parts.append(html.escape(text[pos:hi]))
    return ("…" if lo > 0 else "") + "".join(parts).strip() + ("…" if hi < len(text) else "")


def _html_text(markup):
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", markup or ""))).strip()


# ---------------- indekslash ----------------
def ensure_fulltext_index():
    """MySQL da FULLTEXT indeks bo'lmasa yaratadi. Boshqa bazalarda — hech narsa."""
    from .models import ShnkSearchBlock

    if connection.vendor != "mysql":
        return False
    table = ShnkSearchBlock._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", [FULLTEXT_INDEX])
        if cursor.fetchone():
            return False
        cursor.execute(f"ALTER TABLE `{table}` ADD FULLTEXT INDEX `{FULLTEXT_INDEX}` (`search_text`)")
    return True


def _edition_rows(shnk_id, edition):
    rows, section = [], ""
    for b in edition.blocks or []:
        if b.get("t") == "removed":
            continue
        if b.get("t") == "h":
            section = (b.get("text") or _html_text(b.get("html")))[:300]
        text = _html_text(b.get("html"))
        if not text:
            continue
        rows.append(dict(shnk_id=shnk_id, lang=edition.lang, block=b.get("id", ""), section=section, text=text))
    return rows


def _pdf_rows(shnk):
    import fitz  # PyMuPDF

    rows = []
    for lang, field in (("uz", shnk.pdf_uz), ("ru", shnk.pdf_ru)):
        if not field:
            continue
        path = os.path.join(settings.MEDIA_ROOT, field.name)
        if not os.path.exists(path):
            continue
        try:
            with fitz.open(path) as pdf:
                for number, page in enumerate(pdf, start=1):
                    text = re.sub(r"\s+", " ", page.get_text("text")).strip()
                    if text:
                        rows.append(dict(shnk_id=shnk.pk, lang=lang, page=number, text=text))
        except Exception as exc:  # buzilgan yoki shifrlangan PDF
            logger.warning("PDF o'qilmadi (SHNQ %s, %s): %s", shnk.pk, path, exc)
    return rows


def index_shnk(shnk_id):
    """Bitta SHNQ ning qidiruv bandlarini qaytadan yozadi. Qaytaradi: bandlar soni."""
    from .models import Shnk, ShnkEdition, ShnkSearchBlock

    shnk = Shnk.objects.filter(pk=shnk_id).first()
    ShnkSearchBlock.objects.filter(shnk_id=shnk_id).delete()
    if shnk is None:
        return 0

    rows = []
    editions = (
        ShnkEdition.objects.filter(shnk_id=shnk_id, parse_error="")
        .defer("raw_blocks")
        .order_by("lang", "edition_date", "id")
    )
    latest = {}
    for edition in editions:
        if (edition.stats or {}).get("blocks"):
            latest[edition.lang] = edition
    for edition in latest.values():
        rows += _edition_rows(shnk_id, edition)
    if not rows:  # matni yuklanmagan hujjat — PDF dan
        rows = _pdf_rows(shnk)

    ShnkSearchBlock.objects.bulk_create(
        [ShnkSearchBlock(position=i, search_text=search_norm(r["text"]), **r) for i, r in enumerate(rows)],
        batch_size=500,
    )
    return len(rows)


def safe_index_shnk(shnk_id):
    """Yuklash/tahrirlash jarayonini buzmaslik uchun: xato bo'lsa faqat log."""
    try:
        index_shnk(shnk_id)
    except Exception:
        logger.exception("SHNQ %s qidiruv indeksini yangilab bo'lmadi", shnk_id)


# ---------------- qidiruv ----------------
def search(query, max_docs=80, hits_per_doc=3, max_rows=3000):
    """
    Natija: [{"id", "count", "hits": [{"lang", "block", "page", "section", "snippet"}]}]
    — eng mos hujjat birinchi. Bitta hujjatdan faqat bitta til (lotin/kirill nusxalari takrorlanmasin).
    """
    from .models import ShnkSearchBlock

    terms = query_terms(query)
    long_terms = [t for t in terms if len(t) >= MIN_TERM]
    if not long_terms:
        return []

    qs = ShnkSearchBlock.objects.filter(shnk__status=True)
    if connection.vendor == "mysql":
        table = ShnkSearchBlock._meta.db_table
        match = f"MATCH(`{table}`.`search_text`) AGAINST (%s IN BOOLEAN MODE)"
        against = " ".join(f"+{t}*" for t in long_terms)
        qs = qs.extra(select={"score": match}, select_params=[against], where=[match], params=[against])
        qs = qs.order_by("-score", "position")
    else:  # sqlite (lokal ishlab chiqish)
        for t in long_terms:
            qs = qs.filter(search_text__contains=t)
        qs = qs.order_by("shnk_id", "position")

    rows = qs.values("shnk_id", "lang", "block", "page", "section", "text", "search_text")[:max_rows]

    docs = {}
    for row in rows:
        # Qisqa so'zlar (2 harf) FULLTEXT da hisobga olinmaydi — shu yerda tekshiramiz
        padded = f" {row['search_text']}"
        if not all(f" {t}" in padded for t in terms):
            continue
        if row["shnk_id"] not in docs and len(docs) >= max_docs:
            continue
        doc = docs.setdefault(row["shnk_id"], {"id": row["shnk_id"], "lang": row["lang"], "count": 0, "hits": []})
        if row["lang"] != doc["lang"]:
            continue
        doc["count"] += 1
        if len(doc["hits"]) < hits_per_doc:
            doc["hits"].append({
                "lang": row["lang"],
                "block": row["block"] or None,
                "page": row["page"],
                "section": row["section"],
                "snippet": make_snippet(row["text"], terms),
            })
    return [{k: v for k, v in d.items() if k != "lang"} for d in docs.values()]
