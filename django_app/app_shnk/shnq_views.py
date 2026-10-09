"""
SHNQ hujjatlarini lex.uz ko'rinishida ochish va ularni yuklash (admin dashboard) uchun API.

Public:
    GET  /api/shnq/<id>/?lang=uz&edition=<eid>   hujjat + tanlangan tahrir matni
         lang: uz (lotin) | kr (kirill) | ru.  ?prefer=ru,kr,uz — lang berilmasa,
         ro'yxatdagi birinchi mavjud til ochiladi (sayt tiliga qarab)
    POST /api/shnq/<id>/download/                yuklab olishlar sonini oshirish

Admin (X-Admin-Token sarlavhasi bilan):
    POST   /api/shnq-admin/login/                      {"password": "..."} -> {"token": "..."}
    GET    /api/shnq-admin/documents/?search=&page=     SHNQ lar ro'yxati
    GET    /api/shnq-admin/documents/<id>/              SHNQ + tahrirlari
    POST   /api/shnq-admin/documents/<id>/editions/     yangi tahrir (multipart: file, lang, edition_date, note)
                                                        lang=auto (yoki bo'sh) — til matndan aniqlanadi
    PATCH  /api/shnq-admin/editions/<eid>/              sana / izoh / til / faylni o'zgartirish
    DELETE /api/shnq-admin/editions/<eid>/              tahrirni o'chirish
    POST   /api/shnq-admin/editions/<eid>/reparse/      faylni qayta o'qish
"""
import datetime
import hashlib
import hmac
import os
import shutil
import subprocess
import sys

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db.models import Count, F, Max, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .lex_sync import active_job, invalidate_link_map, make_link_rewriter, rewrite_block
from .models import LawDocument, LawEdition, LexSource, LexSyncJob, Shnk, ShnkCounter, ShnkEdition
from .shnq_docs import ALLOWED_EXTENSIONS, LANG_CODES, process_edition, rebuild_chain, resolve_lang

TOKEN_SALT = "shnq-admin"
TOKEN_MAX_AGE = 60 * 60 * 12  # 12 soat
LOGIN_MAX_FAILS = 10
LOGIN_LOCK_SECONDS = 15 * 60
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def _admin_password():
    return str(getattr(settings, "SHNQ_ADMIN_PASSWORD", "1212"))


def _password_fingerprint():
    # Parol o'zgarsa eski tokenlar avtomatik bekor bo'ladi
    return hashlib.sha256(_admin_password().encode()).hexdigest()[:16]


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


class HasShnqAdminToken(BasePermission):
    message = "Avtorizatsiya talab qilinadi"

    def has_permission(self, request, view):
        token = request.headers.get("X-Admin-Token", "")
        if not token:
            return False
        try:
            data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
        except signing.BadSignature:
            return False
        return data.get("p") == _password_fingerprint()


class PublicAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class AdminAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasShnqAdminToken]


def _file_name(field):
    return field.name if field else None


def _lang(value, default="uz"):
    return value if value in LANG_CODES else default


def _shnk_brief(shnk):
    group = shnk.shnkgroup
    subsystem = group.subsystem if group else None
    return {
        "id": shnk.id,
        "designation": shnk.designation,
        "name_uz": shnk.name_uz,
        "name_ru": shnk.name_ru,
        "status": shnk.status,
        "change": shnk.change,
        "pdf_uz": _file_name(shnk.pdf_uz),
        "pdf_ru": _file_name(shnk.pdf_ru),
        "url": shnk.url,
        "group": {"id": group.id, "title_uz": group.title_uz, "title_ru": group.title_ru} if group else None,
        "subsystem": {"id": subsystem.id, "title_uz": subsystem.title_uz, "title_ru": subsystem.title_ru}
        if subsystem else None,
    }


def _edition_brief(edition):
    return {
        "id": edition.id,
        "lang": edition.lang,
        "date": edition.edition_date.isoformat(),
        "note": edition.note,
        "file": _file_name(edition.source_file),
        "stats": edition.stats or {},
        "error": edition.parse_error or None,
        "source": edition.source,
        "created_at": edition.created_at.isoformat() if edition.created_at else None,
    }


def _editions_light(owner, model=ShnkEdition):
    return list(
        model.objects.filter(**{model.OWNER_FIELD: owner.pk})
        .defer("raw_blocks", "blocks", "toc")
        .order_by("lang", "edition_date", "id")
    )


def _lex_ids(owner, field):
    source = LexSource.objects.filter(**{field: owner}).only("lex_ids").first()
    return [v for v in (source.lex_ids or {}).values()] if source else []


def document_content(request, owner, model, self_lex_ids):
    """
    Hujjat tahrirlari va tanlangan tahrir matni (SHNQ va qonunlar uchun umumiy).
    ?lang=uz|kr|ru  ?prefer=ru,kr,uz  ?edition=<id>
    """
    lang = request.GET.get("lang")
    if lang not in LANG_CODES:
        lang = None
    prefer = [l for l in (request.GET.get("prefer") or "").split(",") if l in LANG_CODES]
    prefer += [l for l in LANG_CODES if l not in prefer]

    editions = [e for e in _editions_light(owner, model) if not e.parse_error and (e.stats or {}).get("blocks")]
    chosen = None
    edition_id = request.GET.get("edition")
    if edition_id and edition_id.isdigit():
        chosen = next((e for e in editions if e.id == int(edition_id)), None)
    if chosen is None:
        available = {e.lang for e in editions}
        target = lang if lang in available else next((l for l in prefer if l in available), None)
        pool = [e for e in editions if e.lang == target]
        chosen = pool[-1] if pool else None

    content = None
    if chosen is not None:
        full = model.objects.only("blocks", "toc").get(pk=chosen.id)
        latest_in_lang = [e for e in editions if e.lang == chosen.lang][-1]
        # lex.uz havolalari: bizda bor hujjat bo'lsa — sayt ichida, bo'lmasa — lex.uz
        rewrite = make_link_rewriter(self_lex_ids, chosen.lang)
        content = {
            "edition": _edition_brief(chosen),
            "is_latest": latest_in_lang.id == chosen.id,
            "blocks": [rewrite_block({k: v for k, v in b.items() if k != "key"}, rewrite) for b in full.blocks],
            "toc": full.toc,
        }
    return {
        "languages": [l for l in LANG_CODES if any(e.lang == l for e in editions)],
        "editions": [_edition_brief(e) for e in editions],
        "content": content,
    }


# =====================================================================
#   PUBLIC
# =====================================================================
class ShnqDocumentAPIView(PublicAPIView):
    def get(self, request, pk):
        shnk = get_object_or_404(Shnk.objects.select_related("shnkgroup__subsystem"), pk=pk)

        counter, _ = ShnkCounter.objects.get_or_create(shnk=shnk)
        ShnkCounter.objects.filter(pk=counter.pk).update(views=F("views") + 1)

        related = list(
            Shnk.objects.filter(shnkgroup_id=shnk.shnkgroup_id, status=True)
            .exclude(pk=shnk.pk)
            .order_by("order")
            .values("id", "designation", "name_uz", "name_ru")[:6]
        )

        data = _shnk_brief(shnk)
        data.update({
            "kind": "shnq",
            "titles": {"uz": shnk.name_uz, "kr": shnk.name_uz, "ru": shnk.name_ru},
            "views": counter.views + 1,
            "downloads": counter.downloads,
            "related": related,
        })
        data.update(document_content(request, shnk, ShnkEdition, _lex_ids(shnk, "shnk")))
        return Response(data)


def _law_brief(law):
    return {
        "id": law.id,
        "titles": {"uz": law.title_uz, "kr": law.title_kr, "ru": law.title_ru},
        "number": law.number,
        "doc_date": law.doc_date.isoformat() if law.doc_date else None,
        "status": law.status,
    }


class LawListAPIView(PublicAPIView):
    def get(self, request):
        qs = LawDocument.objects.filter(editions__isnull=False).distinct()
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(title_uz__icontains=search) | Q(title_kr__icontains=search)
                | Q(title_ru__icontains=search) | Q(number__icontains=search)
            )
        laws = list(qs.order_by("-doc_date", "id")[:500])
        langs = {}
        for law_id, lang in LawEdition.objects.filter(law_id__in=[l.id for l in laws]).values_list("law_id", "lang").distinct():
            langs.setdefault(law_id, set()).add(lang)
        return Response({
            "count": len(laws),
            "results": [dict(_law_brief(l), languages=[x for x in LANG_CODES if x in langs.get(l.id, ())]) for l in laws],
        })


class LawDocumentAPIView(PublicAPIView):
    def get(self, request, pk):
        law = get_object_or_404(LawDocument, pk=pk)
        lex_ids = _lex_ids(law, "law")
        data = _law_brief(law)
        data.update({
            "kind": "law",
            "designation": law.number,
            "url": f"https://lex.uz/docs/{lex_ids[0]}" if lex_ids else None,
        })
        data.update(document_content(request, law, LawEdition, lex_ids))
        return Response(data)


class ShnqDownloadHitAPIView(PublicAPIView):
    def post(self, request, pk):
        shnk = get_object_or_404(Shnk, pk=pk)
        counter, _ = ShnkCounter.objects.get_or_create(shnk=shnk)
        ShnkCounter.objects.filter(pk=counter.pk).update(downloads=F("downloads") + 1)
        return Response({"ok": True})


# =====================================================================
#   ADMIN
# =====================================================================
class ShnqAdminLoginAPIView(PublicAPIView):
    def post(self, request):
        key = f"shnq_admin_fail_{_client_ip(request)}"
        fails = cache.get(key, 0)
        if fails >= LOGIN_MAX_FAILS:
            return Response(
                {"detail": "Juda ko'p urinish. 15 daqiqadan keyin qayta urinib ko'ring."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        password = str(request.data.get("password", ""))
        if not hmac.compare_digest(password.encode(), _admin_password().encode()):
            cache.set(key, fails + 1, LOGIN_LOCK_SECONDS)
            return Response({"detail": "Parol noto'g'ri"}, status=status.HTTP_401_UNAUTHORIZED)

        cache.delete(key)
        token = signing.dumps({"p": _password_fingerprint()}, salt=TOKEN_SALT)
        return Response({"token": token, "expires_in": TOKEN_MAX_AGE})


class ShnqAdminDocumentListAPIView(AdminAPIView):
    def get(self, request):
        qs = Shnk.objects.select_related("shnkgroup").annotate(
            editions_count=Count("editions", distinct=True),
            last_edition=Max("editions__edition_date"),
        )
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(
                Q(designation__icontains=search) | Q(name_uz__icontains=search) | Q(name_ru__icontains=search)
            )
        has_text = request.GET.get("has_text")
        if has_text == "1":
            qs = qs.filter(editions_count__gt=0)
        elif has_text == "0":
            qs = qs.filter(editions_count=0)
        qs = qs.order_by("shnkgroup__subsystem_id", "shnkgroup_id", "order", "id")

        try:
            page = max(1, int(request.GET.get("page", 1)))
            page_size = min(100, max(5, int(request.GET.get("page_size", 30))))
        except ValueError:
            page, page_size = 1, 30
        total = qs.count()
        items = list(qs[(page - 1) * page_size: page * page_size])
        langs = {}
        for shnk_id, lang in (
            ShnkEdition.objects.filter(shnk_id__in=[s.id for s in items]).values_list("shnk_id", "lang").distinct()
        ):
            langs.setdefault(shnk_id, set()).add(lang)

        summary = {
            "documents": Shnk.objects.count(),
            "with_text": Shnk.objects.filter(editions__isnull=False).distinct().count(),
            "editions": ShnkEdition.objects.count(),
            "views": ShnkCounter.objects.aggregate(s=Sum("views"))["s"] or 0,
        }
        return Response({
            "count": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size,
            "summary": summary,
            "results": [
                {
                    "id": s.id,
                    "designation": s.designation,
                    "name_uz": s.name_uz,
                    "name_ru": s.name_ru,
                    "status": s.status,
                    "group": s.shnkgroup.title_uz if s.shnkgroup else None,
                    "pdf": bool(s.pdf_uz or s.pdf_ru),
                    "editions_count": s.editions_count,
                    "languages": [l for l in LANG_CODES if l in langs.get(s.id, ())],
                    "last_edition": s.last_edition.isoformat() if s.last_edition else None,
                }
                for s in items
            ],
        })


class ShnqAdminDocumentDetailAPIView(AdminAPIView):
    def get(self, request, pk):
        shnk = get_object_or_404(Shnk.objects.select_related("shnkgroup__subsystem"), pk=pk)
        data = _shnk_brief(shnk)
        data["editions"] = [_edition_brief(e) for e in _editions_light(shnk)]
        source = LexSource.objects.filter(shnk=shnk).first()
        data["lex"] = {
            "status": source.status, "status_label": source.get_status_display(), "message": source.message,
            "lex_ids": source.lex_ids, "synced_at": source.synced_at.isoformat() if source.synced_at else None,
        } if source else None
        return Response(data)


def _validate_file(upload):
    if upload is None:
        return "Fayl tanlanmagan"
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return "Faqat .doc, .docx yoki .html fayl yuklash mumkin"
    if upload.size > MAX_UPLOAD_SIZE:
        return "Fayl hajmi 50 MB dan oshmasligi kerak"
    return None


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class ShnqAdminEditionCreateAPIView(AdminAPIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        shnk = get_object_or_404(Shnk, pk=pk)
        upload = request.FILES.get("file")
        error = _validate_file(upload)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        edition_date = _parse_date(request.data.get("edition_date"))
        if edition_date is None:
            return Response({"detail": "Tahrir sanasini kiriting (YYYY-MM-DD)"}, status=status.HTTP_400_BAD_REQUEST)

        chosen_lang = request.data.get("lang") or "auto"
        edition = ShnkEdition.objects.create(
            shnk=shnk,
            lang=_lang(chosen_lang),
            edition_date=edition_date,
            note=(request.data.get("note") or "").strip()[:1000],
            source_file=upload,
        )
        try:
            raw = process_edition(edition)
        except ValueError as exc:
            edition.source_file.delete(save=False)
            edition.delete()
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        edition.lang = resolve_lang(chosen_lang, raw)
        edition.save(update_fields=["lang", "updated_at"])
        rebuild_chain(shnk.id, edition.lang)
        edition.refresh_from_db()
        data = _edition_brief(edition)
        data["lang_corrected"] = chosen_lang in LANG_CODES and chosen_lang != edition.lang
        return Response(data, status=status.HTTP_201_CREATED)


class ShnqAdminEditionAPIView(AdminAPIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, pk):
        edition = get_object_or_404(ShnkEdition, pk=pk)
        old_lang = edition.lang
        fields = []

        if "edition_date" in request.data:
            edition_date = _parse_date(request.data.get("edition_date"))
            if edition_date is None:
                return Response({"detail": "Sana noto'g'ri"}, status=status.HTTP_400_BAD_REQUEST)
            edition.edition_date = edition_date
            fields.append("edition_date")
        if "note" in request.data:
            edition.note = (request.data.get("note") or "").strip()[:1000]
            fields.append("note")
        if "lang" in request.data:
            edition.lang = _lang(request.data.get("lang"), edition.lang)
            fields.append("lang")
        if fields:
            edition.save(update_fields=fields + ["updated_at"])

        upload = request.FILES.get("file")
        if upload is not None:
            error = _validate_file(upload)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
            old_file = edition.source_file.name
            edition.source_file = upload
            edition.save(update_fields=["source_file", "updated_at"])
            try:
                raw = process_edition(edition)
            except ValueError as exc:
                edition.source_file.delete(save=False)
                edition.source_file.name = old_file
                edition.save(update_fields=["source_file", "updated_at"])
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            edition.lang = resolve_lang(edition.lang, raw)
            edition.save(update_fields=["lang", "updated_at"])
            if old_file and old_file != edition.source_file.name:
                edition.source_file.storage.delete(old_file)

        rebuild_chain(edition.shnk_id, edition.lang)
        if old_lang != edition.lang:
            rebuild_chain(edition.shnk_id, old_lang)
        edition.refresh_from_db()
        return Response(_edition_brief(edition))

    def delete(self, request, pk):
        edition = get_object_or_404(ShnkEdition, pk=pk)
        shnk_id, lang = edition.shnk_id, edition.lang
        edition.source_file.delete(save=False)
        edition.delete()
        rebuild_chain(shnk_id, lang)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShnqAdminEditionReparseAPIView(AdminAPIView):
    def post(self, request, pk):
        edition = get_object_or_404(ShnkEdition, pk=pk)
        old_lang = edition.lang
        try:
            raw = process_edition(edition)
        except ValueError as exc:
            edition.parse_error = str(exc)
            edition.save(update_fields=["parse_error", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        edition.lang = resolve_lang(edition.lang, raw)
        edition.save(update_fields=["lang", "updated_at"])
        rebuild_chain(edition.shnk_id, edition.lang)
        if old_lang != edition.lang:
            rebuild_chain(edition.shnk_id, old_lang)
        edition.refresh_from_db()
        return Response(_edition_brief(edition))


# =====================================================================
#   lex.uz AVTOMATIK IMPORT
#   GET  /api/shnq-admin/lex-sync/          oxirgi jarayon, holatlar, muammoli hujjatlar
#   POST /api/shnq-admin/lex-sync/start/    {"scope": "all|missing|failed", "mode": "update|replace",
#                                            "laws": true, "shnk_ids": [12]}
#   POST /api/shnq-admin/lex-sync/stop/
# =====================================================================
def _job_dict(job):
    if job is None:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "status_label": job.get_status_display(),
        "params": job.params,
        "total": job.total,
        "done": job.done,
        "counters": job.counters or {},
        "current": job.current,
        "log": (job.log or "").splitlines()[-200:],
        "stop_requested": job.stop_requested,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _spawn_job(job):
    """lex_sync buyrug'ini web-serverdan mustaqil alohida jarayonda ishga tushiradi."""
    python = getattr(settings, "LEX_SYNC_PYTHON", "") or sys.executable
    if "python" not in os.path.basename(python).lower():  # uwsgi va h.k. ostida
        python = shutil.which("python3") or shutil.which("python") or "python3"
    base_dir = str(settings.BASE_DIR)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    with open(os.path.join(base_dir, "lex_sync.log"), "ab") as out:
        subprocess.Popen(
            [python, os.path.join(base_dir, "manage.py"), "lex_sync", "--job", str(job.pk)],
            cwd=base_dir, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=os.environ.copy(), **kwargs,
        )


class LexSyncStatusAPIView(AdminAPIView):
    def get(self, request):
        active_job()
        job = LexSyncJob.objects.order_by("-id").first()
        counts = dict(
            LexSource.objects.filter(shnk__isnull=False).values_list("status").annotate(n=Count("id")).order_by()
        )
        problems = (
            LexSource.objects.filter(shnk__isnull=False, status__in=["mismatch", "error", "stub"])
            .select_related("shnk").order_by("status", "shnk__designation")[:300]
        )
        with_link = sum(
            1 for url in Shnk.objects.exclude(url__isnull=True).exclude(url="").values_list("url", flat=True)
            if "lex.uz" in url and "/docs/" in url
        )
        return Response({
            "job": _job_dict(job),
            "running": bool(job and job.status in ("queued", "running")),
            "summary": {
                "with_lex_link": with_link,
                "statuses": counts,
                "laws": LawDocument.objects.filter(editions__isnull=False).distinct().count(),
            },
            "problems": [
                {
                    "shnk_id": p.shnk_id,
                    "designation": p.shnk.designation,
                    "name": p.shnk.name_uz,
                    "url": p.shnk.url,
                    "status": p.status,
                    "status_label": p.get_status_display(),
                    "message": p.message,
                    "synced_at": p.synced_at.isoformat() if p.synced_at else None,
                }
                for p in problems
            ],
        })


class LexSyncStartAPIView(AdminAPIView):
    parser_classes = [JSONParser]

    def post(self, request):
        if active_job():
            return Response({"detail": "Import allaqachon ishlab turibdi"}, status=status.HTTP_409_CONFLICT)
        shnk_ids = [int(i) for i in (request.data.get("shnk_ids") or []) if str(i).isdigit()]
        params = {
            "scope": request.data.get("scope") if request.data.get("scope") in ("all", "missing", "failed") else "all",
            "mode": "replace" if request.data.get("mode") == "replace" else "update",
            "laws": bool(request.data.get("laws", True)),
            "shnk_ids": shnk_ids,
            "source": "admin",
        }
        job = LexSyncJob.objects.create(params=params, heartbeat=timezone.now())
        try:
            _spawn_job(job)
        except Exception as exc:
            job.status, job.log = "failed", f"Jarayonni ishga tushirib bo'lmadi: {exc}"
            job.save(update_fields=["status", "log"])
            return Response({"detail": job.log}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(_job_dict(job), status=status.HTTP_201_CREATED)


class LexSyncStopAPIView(AdminAPIView):
    def post(self, request):
        updated = LexSyncJob.objects.filter(status__in=["queued", "running"]).update(stop_requested=True)
        return Response({"ok": bool(updated)})
