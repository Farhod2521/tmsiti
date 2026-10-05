"""
SHNQ hujjatlarini lex.uz ko'rinishida ochish va ularni yuklash (admin dashboard) uchun API.

Public:
    GET  /api/shnq/<id>/?lang=uz&edition=<eid>   hujjat + tanlangan tahrir matni
    POST /api/shnq/<id>/download/                yuklab olishlar sonini oshirish

Admin (X-Admin-Token sarlavhasi bilan):
    POST   /api/shnq-admin/login/                      {"password": "..."} -> {"token": "..."}
    GET    /api/shnq-admin/documents/?search=&page=     SHNQ lar ro'yxati
    GET    /api/shnq-admin/documents/<id>/              SHNQ + tahrirlari
    POST   /api/shnq-admin/documents/<id>/editions/     yangi tahrir (multipart: file, lang, edition_date, note)
    PATCH  /api/shnq-admin/editions/<eid>/              sana / izoh / til / faylni o'zgartirish
    DELETE /api/shnq-admin/editions/<eid>/              tahrirni o'chirish
    POST   /api/shnq-admin/editions/<eid>/reparse/      faylni qayta o'qish
"""
import datetime
import hashlib
import hmac
import os

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db.models import Count, F, Max, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Shnk, ShnkCounter, ShnkEdition
from .shnq_docs import ALLOWED_EXTENSIONS, process_edition, rebuild_chain

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
    return value if value in ("uz", "ru") else default


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
        "created_at": edition.created_at.isoformat() if edition.created_at else None,
    }


def _editions_light(shnk):
    return list(
        ShnkEdition.objects.filter(shnk=shnk)
        .defer("raw_blocks", "blocks", "toc")
        .order_by("lang", "edition_date", "id")
    )


# =====================================================================
#   PUBLIC
# =====================================================================
class ShnqDocumentAPIView(PublicAPIView):
    def get(self, request, pk):
        shnk = get_object_or_404(Shnk.objects.select_related("shnkgroup__subsystem"), pk=pk)
        lang = _lang(request.GET.get("lang"))

        editions = [e for e in _editions_light(shnk) if not e.parse_error and (e.stats or {}).get("blocks")]
        chosen = None
        edition_id = request.GET.get("edition")
        if edition_id and edition_id.isdigit():
            chosen = next((e for e in editions if e.id == int(edition_id)), None)
        if chosen is None:
            same_lang = [e for e in editions if e.lang == lang]
            pool = same_lang or editions
            chosen = pool[-1] if pool else None

        content = None
        if chosen is not None:
            full = ShnkEdition.objects.only("blocks", "toc").get(pk=chosen.id)
            latest_in_lang = [e for e in editions if e.lang == chosen.lang][-1]
            content = {
                "edition": _edition_brief(chosen),
                "is_latest": latest_in_lang.id == chosen.id,
                "blocks": [{k: v for k, v in b.items() if k != "key"} for b in full.blocks],
                "toc": full.toc,
            }

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
            "views": counter.views + 1,
            "downloads": counter.downloads,
            "languages": sorted({e.lang for e in editions}),
            "editions": [_edition_brief(e) for e in editions],
            "content": content,
            "related": related,
        })
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
        items = qs[(page - 1) * page_size: page * page_size]

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

        edition = ShnkEdition.objects.create(
            shnk=shnk,
            lang=_lang(request.data.get("lang")),
            edition_date=edition_date,
            note=(request.data.get("note") or "").strip()[:1000],
            source_file=upload,
        )
        try:
            process_edition(edition)
        except ValueError as exc:
            edition.source_file.delete(save=False)
            edition.delete()
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        rebuild_chain(shnk.id, edition.lang)
        edition.refresh_from_db()
        return Response(_edition_brief(edition), status=status.HTTP_201_CREATED)


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
                process_edition(edition)
            except ValueError as exc:
                edition.source_file.delete(save=False)
                edition.source_file.name = old_file
                edition.save(update_fields=["source_file", "updated_at"])
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
        try:
            process_edition(edition)
        except ValueError as exc:
            edition.parse_error = str(exc)
            edition.save(update_fields=["parse_error", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        rebuild_chain(edition.shnk_id, edition.lang)
        edition.refresh_from_db()
        return Response(_edition_brief(edition))
