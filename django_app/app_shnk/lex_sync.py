"""
lex.uz dan hujjatlarni avtomatik yuklash va hujjat ichidagi havolalarni sayt ichiga yo'naltirish.

lex.uz qoidalari (tekshirilgan):
    * hujjat tili raqam bilan belgilanadi: /docs/N — o'zbek (kirill), /docs/-N — o'zbek (lotin),
      ruscha variant — boshqa raqam. Sahifadagi "Рус / Ўзб / O'zb" tugmalarida hamma raqamlar bor.
    * /uz/, /ru/ prefiksi faqat sayt interfeysi tili, hujjat matniga ta'sir qilmaydi.
    * Word fayl: /docs/<id>?type=doc — bu HTML (LexHtmlParser o'qiydi).
    * Hujjat ichidagi havola: https://lex.uz/docs/<id>#<band_id>; lotin va kirill band raqamlari
      faqat ishorasi bilan farq qiladi.

Jarayon (run_job):
    1. lex.uz havolasi bor har bir SHNQ: sahifa -> til raqamlari -> shifr tekshiruvi ->
       zip/bo'sh hujjat bo'lsa o'tkazib yuboriladi (PDF qoladi) -> har bir til yuklanadi.
    2. Matn o'zgarmagan bo'lsa hech narsa qilinmaydi; o'zgargan bo'lsa yangi tahrir qo'shiladi
       ("Oldingi tahrirga qarang" avtomatik paydo bo'ladi); avvalgi matn butunlay boshqa hujjat
       bo'lsa (admin adashib yuklagan) — almashtiriladi.
    3. SHNQ matnlarida havola qilingan, lekin bazada yo'q hujjatlar "Qonunlar" bo'limiga yuklanadi.
"""
import datetime
import hashlib
import html as html_lib
import re
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import close_old_connections
from django.utils import timezone

from .shnq_docs import LANG_CODES, LexHtmlParser, _sniff_bytes, content_hash, detect_lang, rebuild_chain

LEX_BASE = "https://lex.uz"
USER_AGENT = "Mozilla/5.0 (compatible; TMSITI-sync/1.0; +https://tmsiti.uz)"
REQUEST_DELAY = 2.0  # lex.uz ni ortiqcha yuklamaslik uchun so'rovlar orasidagi pauza (soniya)
LINK_MAP_CACHE_KEY = "lex_link_map_v1"
LOG_KEEP_LINES = 400

LEX_DOC_RE = re.compile(r"lex\.uz/(?:[a-z]{2}/)?docs/(-?\d+)", re.I)
LEX_HREF_RE = re.compile(
    r'<a href="https?://(?:www\.)?lex\.uz/(?:[a-z]{2}/)?docs/(-?\d+)(?:#(-?\d+))?"[^>]*>', re.I
)
FILE_LINK_RE = re.compile(r'href="(?:https?://(?:www\.)?lex\.uz)?/files/[^"]+\.(?:zip|rar|7z|pdf|docx?|xlsx?)"', re.I)
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
AMENDMENT_RE = re.compile(r"ўзгартириш|қўшимча|o['‘ʻ’]zgartirish|qo['‘ʻ’]shimcha|изменени|дополнени", re.I)

# Hujjatning matni shundan qisqa bo'lsa (va ichida fayl havolasi bo'lsa) — "matn yo'q", PDF qoladi
STUB_TEXT_WITH_FILE = 1500
STUB_TEXT_MIN = 300
# Til varianti eng uzun variantning shuncha qismidan qisqa bo'lsa — to'liq tarjima emas, import qilinmaydi
SHORT_LANG_RATIO = 0.25
SHORT_LANG_MAX = 6000


class LexError(Exception):
    pass


class StopRequested(Exception):
    pass


# =====================================================================
#   lex.uz bilan aloqa
# =====================================================================
class LexClient:
    def __init__(self, delay=REQUEST_DELAY):
        self.delay = delay
        self._last = 0.0

    def get(self, path):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = path if path.startswith("http") else LEX_BASE + path
        last_exc = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read(60 * 1024 * 1024)
                self._last = time.monotonic()
                return data
            except urllib.error.HTTPError as exc:
                self._last = time.monotonic()
                if exc.code == 404:
                    raise LexError(f"lex.uz da topilmadi (404): {url}")
                last_exc = exc
            except Exception as exc:  # tarmoq xatosi — qayta urinamiz
                self._last = time.monotonic()
                last_exc = exc
            time.sleep(5 * (attempt + 1))
        raise LexError(f"lex.uz ga ulanib bo'lmadi: {last_exc}")

    def page(self, lex_id):
        return self.get(f"/docs/{lex_id}").decode("utf-8", errors="replace")

    def export(self, lex_id):
        return self.get(f"/docs/{lex_id}?type=doc&s527=0&s1089=0&s1104=0")


def parse_lex_id(url):
    m = LEX_DOC_RE.search(url or "")
    return int(m.group(1)) if m else None


_LANG_BTN_RE = re.compile(
    r'<div class="docContentHeader__item-link([^"]*)"\s*'
    r"(?:onclick=\"openUrl\('[^']*?/docs/(-?\d+)'\)\"\s*)?"
    r'title="([^"]*)"\s*>',
)


def _btn_lang(title):
    t = title.lower()
    if "рус" in t:
        return "ru"
    if "ўзбек" in t:
        return "kr"
    if re.search(r"o['‘ʻ’]zbek", t):
        return "uz"
    return None


def page_info(html, lex_id):
    """lex.uz hujjat sahifasidan: sarlavha, til raqamlari, raqami va sanasi."""
    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = html_lib.unescape(title_m.group(1)) if title_m else ""
    title = re.sub(r"\s+", " ", title.replace("\xa0", " ")).strip()

    ids = {}
    for cls, other_id, btn_title in _LANG_BTN_RE.findall(html):
        lang = _btn_lang(btn_title)
        if not lang or lang in ids:
            continue
        if other_id:
            ids[lang] = int(other_id)
        elif "active" in cls:
            ids[lang] = lex_id

    date_m = DATE_RE.search(title)
    doc_date = None
    if date_m:
        try:
            doc_date = datetime.date(int(date_m.group(3)), int(date_m.group(2)), int(date_m.group(1)))
        except ValueError:
            doc_date = None
    # Sarlavha: "ЎРҚ-674-сон 22.02.2021. Ўзбекистон ..." — raqam sanadan oldin turadi
    number_m = re.match(r"^\s*(.{1,80}?)\s*\d{2}\.\d{2}\.\d{4}", title)

    clean_title = re.sub(r"^.*?\d{2}\.\d{2}\.\d{4}\.?\s*", "", title) if date_m else title
    return {
        "title": clean_title or title,
        "raw_title": title,
        "ids": ids,
        "doc_date": doc_date,
        "number": number_m.group(1).strip(" ,.") if number_m else "",
    }


def designation_core(designation):
    """'ШНҚ 1.01.06-23' -> ('1.01.06', '23')"""
    m = re.search(r"(\d+(?:\.\d+)+)\s*[-‑–]?\s*(\d+)?", designation or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def designation_matches(designation, title):
    core, year = designation_core(designation)
    if not core:
        return True  # tekshirib bo'lmaydi
    compact = re.sub(r"\s+", "", title)
    for m in re.finditer(re.escape(core) + r"(?:[-‑–](\d+))?", compact):
        found_year = m.group(1)
        if not year or not found_year or found_year[-2:] == year[-2:]:
            return True
    return False


# =====================================================================
#   Havolalarni sayt ichiga yo'naltirish
# =====================================================================
def build_link_map():
    """abs(lex raqami) -> ("shnq" | "law", bizdagi id)"""
    from .models import LexSource, Shnk

    mapping = {}
    for shnk_id, url in Shnk.objects.exclude(url__isnull=True).exclude(url="").values_list("id", "url"):
        lex_id = parse_lex_id(url)
        if lex_id:
            mapping[abs(lex_id)] = ("shnq", shnk_id)
    for shnk_id, law_id, ids in LexSource.objects.values_list("shnk_id", "law_id", "lex_ids"):
        target = ("shnq", shnk_id) if shnk_id else ("law", law_id)
        for value in (ids or {}).values():
            try:
                mapping[abs(int(value))] = target
            except (TypeError, ValueError):
                continue
    return mapping


def get_link_map():
    mapping = cache.get(LINK_MAP_CACHE_KEY)
    if mapping is None:
        mapping = build_link_map()
        cache.set(LINK_MAP_CACHE_KEY, mapping, 600)
    return mapping


def invalidate_link_map():
    cache.delete(LINK_MAP_CACHE_KEY)


def make_link_rewriter(self_ids, lang):
    """
    Hujjat HTML idagi lex.uz havolalarini almashtiruvchi funksiya qaytaradi.
    self_ids — joriy hujjatning lex raqamlari (abs); lang — o'qilayotgan til (ochiladigan hujjat ham shu tilda).
    """
    mapping = get_link_map()
    self_ids = {abs(int(i)) for i in self_ids}

    def repl(m):
        doc_id, anchor = abs(int(m.group(1))), m.group(2)
        if doc_id in self_ids:
            if anchor:
                return f'<a href="#l{anchor}" data-anchor="{anchor}">'
            return '<a href="#" data-self="1">'
        target = mapping.get(doc_id)
        if target:
            kind, obj_id = target
            path = f"/shnq/{obj_id}" if kind == "shnq" else f"/qonunlar/{obj_id}"
            suffix = f"#l{anchor}" if anchor else ""
            return f'<a href="{path}?lang={lang}{suffix}" data-doc="{kind}">'
        return m.group(0).replace("<a ", '<a class="lex-ext" ', 1)

    def rewrite(html):
        return LEX_HREF_RE.sub(repl, html) if html and "lex.uz" in html else html

    return rewrite


def rewrite_block(block, rewrite):
    out = dict(block)
    out["html"] = rewrite(block.get("html", ""))
    if block.get("notes"):
        out["notes"] = [rewrite(n) for n in block["notes"]]
    if block.get("hist"):
        out["hist"] = [dict(h, prev=rewrite(h["prev"])) if h.get("prev") else h for h in block["hist"]]
    return out


def collect_lex_ids(raw_blocks):
    found = set()
    for b in raw_blocks:
        for html in [b.get("html", "")] + list(b.get("notes", [])):
            for m in LEX_DOC_RE.finditer(html or ""):
                found.add(abs(int(m.group(1))))
    return found


# =====================================================================
#   Import
# =====================================================================
def _text_len(raw):
    return sum(len(b.get("key", "")) for b in raw)


def _strip(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _newest_change(prev_raw, raw):
    """Yangi matnda paydo bo'lgan eng so'nggi "(... tahririda)" izohi va undagi sana."""
    old = {_strip(n) for b in prev_raw for n in b.get("notes", [])}
    best = None
    for b in raw:
        for n in b.get("notes", []):
            text = _strip(n)
            if text in old:
                continue
            dates = []
            for d, m, y in DATE_RE.findall(text):
                try:
                    dates.append(datetime.date(int(y), int(m), int(d)))
                except ValueError:
                    pass
            when = max(dates) if dates else None
            if best is None or (when and (best[1] is None or when > best[1])):
                best = (text.strip("() "), when)
    return best or ("", None)


class Importer:
    def __init__(self, job=None, mode="update", client=None, log=print):
        self.job = job
        self.mode = mode
        self.client = client or LexClient()
        self.log = log
        self.today = timezone.localdate()

    # ---------- bitta til ----------
    def _parse_export(self, blob, folder):
        if _sniff_bytes(blob) != "html":
            raise LexError("lex.uz kutilgan formatda fayl bermadi")

        def save_image(data, ext, digest):
            name = f"FILES/shnq_editions/{folder}/img/{digest}.{ext}"
            if not default_storage.exists(name):
                name = default_storage.save(name, ContentFile(data))
            return name

        return LexHtmlParser(blob, save_image).parse()

    def _apply(self, model, owner, lang, lex_id, blob, raw, doc_date):
        owner_filter = {model.OWNER_FIELD: owner.pk}
        h = content_hash(raw)
        existing = list(model.objects.filter(**owner_filter, lang=lang).order_by("edition_date", "id"))
        latest = existing[-1] if existing else None
        replace = self.mode == "replace"
        if latest and not replace and (latest.content_hash or content_hash(latest.raw_blocks or [])) == h:
            return "unchanged"

        if latest and not replace:
            old_keys = [b.get("key", "") for b in latest.raw_blocks or []]
            new_keys = [b.get("key", "") for b in raw]
            if SequenceMatcher(None, old_keys, new_keys, autojunk=False).quick_ratio() < 0.3:
                replace = True  # avvalgi matn butunlay boshqa hujjat — adashib yuklangan
                self.log(f"   [{lang}] mavjud matn bu hujjatga mos emas — almashtirildi")
        if replace and existing:
            for e in existing:
                e.source_file.delete(save=False)
                e.delete()
            existing, latest = [], None

        if latest is None:
            edition_date, note = doc_date or self.today, ""
            result = "replaced" if replace else "created"
        else:
            note, when = _newest_change(latest.raw_blocks or [], raw)
            edition_date = when if when and when > latest.edition_date else self.today
            note = note or "lex.uz dagi yangilanish"
            result = "updated"

        edition = model(**{model.OWNER_FIELD: owner.pk}, lang=lang, edition_date=edition_date,
                        note=note[:1000], source="lex", raw_blocks=raw, content_hash=h)
        edition.source_file.save(f"lex_{lex_id}.doc", ContentFile(blob), save=False)
        edition.save()
        rebuild_chain(owner.pk, lang, model)
        return result

    # ---------- bitta hujjat ----------
    def sync(self, kind, owner, lex_id):
        """kind: "shnq" | "law". Natija: (status, link_ids)"""
        from .models import LawEdition, LexSource, ShnkEdition

        model = ShnkEdition if kind == "shnq" else LawEdition
        source, _ = LexSource.objects.get_or_create(**{"shnk" if kind == "shnq" else "law": owner})

        def finish(status, message, ids=None):
            source.status, source.message, source.synced_at = status, message, timezone.now()
            if ids is not None:
                source.lex_ids = ids
            source.save()
            return status

        try:
            info = page_info(self.client.page(lex_id), lex_id)
            ids = info["ids"] or {}
            if lex_id not in ids.values():
                ids.setdefault("kr" if lex_id > 0 else "uz", lex_id)

            if kind == "shnq" and not designation_matches(owner.designation, info["raw_title"]):
                msg = f"lex.uz dagi hujjat boshqa: «{info['title'][:150]}»"
                self.log(f"   ✗ shifr mos emas — {msg}")
                return finish("mismatch", msg, ids), set()


            folder = str(owner.pk) if kind == "shnq" else f"law_{owner.pk}"
            parsed = {}
            for lang in LANG_CODES:
                if lang not in ids:
                    continue
                self.check_stop()
                blob = self.client.export(ids[lang])
                raw = self._parse_export(blob, folder)
                size = _text_len(raw)
                # Matn o'rniga zip/pdf biriktirilgan yoki deyarli bo'sh hujjat — import qilinmaydi, PDF qoladi
                has_file = bool(FILE_LINK_RE.search(blob.decode("utf-8", errors="ignore")))
                if size < STUB_TEXT_MIN or (has_file and size < STUB_TEXT_WITH_FILE):
                    self.log(f"   ○ [{lang}] lex.uz da matn yo'q" + (" (fayl biriktirilgan)" if has_file else ""))
                    continue
                if raw:
                    parsed[lang] = (blob, raw)
                    detected = detect_lang(raw)
                    if detected != lang:
                        self.log(f"   ! [{lang}] matn tili {detected} ga o'xshaydi")

            if not parsed:
                # Avval lex.uz dan yuklangan matn bo'lsa olib tashlanadi — saytda PDF ko'rsatiladi
                stale = list(model.objects.filter(**{model.OWNER_FIELD: owner.pk}, source="lex"))
                for e in stale:
                    e.source_file.delete(save=False)
                    e.delete()
                for lang in {e.lang for e in stale}:
                    rebuild_chain(owner.pk, lang, model)
                return finish("stub", "lex.uz da matn o'rniga fayl (zip/pdf) biriktirilgan yoki matn yo'q — PDF ko'rsatiladi", ids), set()

            longest = max(_text_len(raw) for _, raw in parsed.values())
            results, links = [], set()
            for lang, (blob, raw) in parsed.items():
                size = _text_len(raw)
                if size < longest * SHORT_LANG_RATIO and size < SHORT_LANG_MAX:
                    results.append(f"{lang}: qisqa variant, o'tkazildi")
                    continue
                res = self._apply(model, owner, lang, ids[lang], blob, raw, info["doc_date"])
                results.append(f"{lang}: {RESULT_LABELS[res]}")
                links |= collect_lex_ids(raw)
                if res != "unchanged":
                    self.count(res)

            if kind == "law":
                titles = {}
                for lang in parsed:
                    titles[lang] = info["title"] if ids.get(lang) == lex_id else page_info(
                        self.client.page(ids[lang]), ids[lang])["title"]
                owner.title_uz = titles.get("uz", owner.title_uz)[:1000]
                owner.title_kr = titles.get("kr", owner.title_kr)[:1000]
                owner.title_ru = titles.get("ru", owner.title_ru)[:1000]
                owner.number = info["number"][:200] or owner.number
                owner.doc_date = info["doc_date"] or owner.doc_date
                owner.save()

            message = "; ".join(results)
            if kind == "shnq" and AMENDMENT_RE.search(info["raw_title"]):
                message += " (diqqat: lex.uz havolasi o'zgartirish hujjatiga olib boradi)"
            self.log("   ✓ " + message)
            return finish("ok", message, ids), links
        except StopRequested:
            raise
        except LexError as exc:
            self.log(f"   ✗ {exc}")
            return finish("error", str(exc)), set()
        except Exception as exc:  # kutilmagan xato — keyingi hujjatga o'tamiz
            self.log(f"   ✗ kutilmagan xato: {exc}")
            return finish("error", f"Kutilmagan xato: {exc}"), set()

    # ---------- job bilan bog'liq ----------
    def check_stop(self):
        if self.job is not None:
            from .models import LexSyncJob

            if LexSyncJob.objects.filter(pk=self.job.pk, stop_requested=True).exists():
                raise StopRequested()

    def count(self, key, n=1):
        if self.job is not None:
            self.job.counters[key] = self.job.counters.get(key, 0) + n


RESULT_LABELS = {
    "created": "yuklandi",
    "replaced": "qaytadan yuklandi",
    "updated": "yangi tahrir qo'shildi",
    "unchanged": "o'zgarmagan",
}


def run_job(job_id):
    """LexSyncJob ni bajaradi (lex_sync management buyrug'i chaqiradi)."""
    from .models import LawDocument, LexSource, LexSyncJob, Shnk, ShnkEdition

    close_old_connections()
    job = LexSyncJob.objects.get(pk=job_id)
    params = job.params or {}
    lines = job.log.splitlines() if job.log else []

    def log(text):
        stamp = timezone.localtime().strftime("%H:%M:%S")
        lines.append(f"{stamp} {text}")
        del lines[:-LOG_KEEP_LINES]

    def save(**fields):
        job.log = "\n".join(lines)
        job.heartbeat = timezone.now()
        for k, v in fields.items():
            setattr(job, k, v)
        LexSyncJob.objects.filter(pk=job.pk).update(
            log=job.log, heartbeat=job.heartbeat, counters=job.counters, done=job.done,
            total=job.total, current=job.current, status=job.status,
            started_at=job.started_at, finished_at=job.finished_at,
        )

    job.status, job.started_at = "running", timezone.now()
    job.counters = job.counters or {}
    importer = Importer(job=job, mode=params.get("mode", "update"), client=LexClient(params.get("delay", REQUEST_DELAY)), log=log)

    try:
        # ---- 1. SHNQ lar ----
        qs = Shnk.objects.exclude(url__isnull=True).exclude(url="").order_by("id")
        if params.get("shnk_ids"):
            qs = qs.filter(id__in=params["shnk_ids"])
        targets = [(s, parse_lex_id(s.url)) for s in qs]
        skipped = [s for s, lex_id in targets if not lex_id]
        targets = [(s, lex_id) for s, lex_id in targets if lex_id]
        scope = params.get("scope", "all")
        if scope == "missing":
            with_text = set(ShnkEdition.objects.values_list("shnk_id", flat=True))
            targets = [(s, i) for s, i in targets if s.id not in with_text]
        elif scope == "failed":
            bad = set(LexSource.objects.filter(status__in=["error", "pending"], shnk__isnull=False)
                      .values_list("shnk_id", flat=True))
            targets = [(s, i) for s, i in targets if s.id in bad]

        job.total = len(targets)
        log(f"Boshlandi: {len(targets)} ta SHNQ (lex.uz havolasi to'g'ri bo'lmagan {len(skipped)} ta o'tkazildi)")
        save()

        discovered = set()
        for shnk, lex_id in targets:
            importer.check_stop()
            job.current = f"{shnk.designation} — {(shnk.name_uz or '')[:80]}"
            log(f"▶ {shnk.designation} (lex.uz/docs/{lex_id})")
            save()
            status, links = importer.sync("shnq", shnk, lex_id)
            importer.count(status)
            discovered |= links
            job.done += 1
            save()

        # ---- 2. Qonunlar ----
        #   a) avval yuklangan qonunlar — lex.uz dagi o'zgarishlar tekshiriladi ("Matni yo'qlar" rejimida emas)
        #   b) SHNQ matnlarida havola qilingan, bazada hali yo'q hujjatlar — yangi qonun sifatida yuklanadi
        if params.get("laws", True) and not params.get("shnk_ids"):
            law_sources = list(LexSource.objects.filter(law__isnull=False).select_related("law"))
            refresh = []
            if scope != "missing":
                for src in law_sources:
                    if scope == "failed" and src.status not in ("error", "pending"):
                        continue
                    ids = [int(v) for v in (src.lex_ids or {}).values()]
                    if ids:
                        refresh.append((src.law, ids[0]))

            invalidate_link_map()
            known = set(build_link_map().keys())
            candidates = sorted(discovered - known)
            limit = int(params.get("max_laws", 300))
            if len(candidates) > limit:
                log(f"Qonunlar: {len(candidates)} ta yangi topildi, birinchi {limit} tasi yuklanadi")
                candidates = candidates[:limit]
            job.total += len(refresh) + len(candidates)
            log(f"Qonunlar bosqichi: {len(refresh)} ta mavjud qonun tekshiriladi, {len(candidates)} ta yangi qonun")
            save()

            def sync_law(law, lex_id):
                nonlocal known
                job.current = f"Qonun: {law.title[:80] or f'lex.uz/docs/{lex_id}'}"
                log(f"▶ Qonun: {law.title[:80] or f'lex.uz/docs/{lex_id}'}")
                save()
                status, _ = importer.sync("law", law, lex_id)
                source = LexSource.objects.get(law=law)
                known |= {abs(int(v)) for v in (source.lex_ids or {}).values()}
                if status != "ok" and not law.editions.exists():
                    law.delete()  # matnsiz qonun bo'limda turmasin
                elif status == "ok":
                    importer.count("laws")
                job.done += 1
                save()

            for law, lex_id in refresh:
                importer.check_stop()
                sync_law(law, lex_id)

            for lex_id in candidates:
                importer.check_stop()
                if lex_id in known:  # boshqa tili orqali allaqachon yuklangan
                    job.done += 1
                    continue
                sync_law(LawDocument.objects.create(), lex_id)

        log("Tugadi.")
        save(status="done", finished_at=timezone.now(), current="")
    except StopRequested:
        log("To'xtatildi (admin so'rovi bilan).")
        save(status="stopped", finished_at=timezone.now(), current="")
    except Exception as exc:
        log(f"Jarayon xato bilan to'xtadi: {exc}")
        save(status="failed", finished_at=timezone.now())
        raise
    finally:
        invalidate_link_map()
