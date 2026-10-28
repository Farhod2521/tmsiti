"""
SHNQ hujjatlarini lex.uz ko'rinishida ochish va ularni yuklash (admin dashboard) uchun API.

Public:
    GET  /api/shnq/<id>/?lang=uz&edition=<eid>   hujjat + tanlangan tahrir matni
         lang: uz (lotin) | kr (kirill) | ru.  ?prefer=ru,kr,uz — lang berilmasa,
         ro'yxatdagi birinchi mavjud til ochiladi (sayt tiliga qarab)
    POST /api/shnq/<id>/download/                yuklab olishlar sonini oshirish
    GET  /api/shnq/search/?q=...                 hujjatlar ichidan qidiruv (mos bandlar bilan)
         &mode=question&limit=6                  sayt yordamchisi (chat) uchun: savol so'zlari tashlanadi

Admin (X-Admin-Token sarlavhasi bilan):
    POST   /api/shnq-admin/login/                      {"username", "password"} -> {"token", "user"}
    GET    /api/shnq-admin/me/                         joriy xodim
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
import ipaddress
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
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .lex_sync import active_job, invalidate_link_map, law_kind, make_link_rewriter, rewrite_block
from .models import LawDocument, LawEdition, LexSource, LexSyncJob, Shnk, ShnkCounter, ShnkEdition
from .shnq_docs import ALLOWED_EXTENSIONS, LANG_CODES, process_edition, rebuild_chain, resolve_lang
from .shnq_search import MIN_TERM as SEARCH_MIN_TERM, query_terms, search as search_documents

TOKEN_SALT = "shnq-admin"
TOKEN_MAX_AGE = 60 * 60 * 12  # 12 soat
LOGIN_MAX_FAILS = 10
LOGIN_LOCK_SECONDS = 15 * 60
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def _user_fingerprint(user):
    # Parol almashtirilsa, xodim o'chirilsa yoki admin huquqi olinsa — eski tokenlar bekor bo'ladi
    raw = f"{user.pk}:{user.password}:{user.is_active}:{user.is_staff}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def make_admin_token(user):
    return signing.dumps({"u": user.pk, "f": _user_fingerprint(user)}, salt=TOKEN_SALT)


def admin_user_from_token(token):
    """Token to'g'ri va xodim faol bo'lsa — User, aks holda None. (REST va WebSocket uchun umumiy)"""
    from django.contrib.auth import get_user_model

    if not token:
        return None
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    user = get_user_model().objects.filter(pk=data.get("u")).first()
    if not user or not user.is_active or not user.is_staff:
        return None
    if not hmac.compare_digest(str(data.get("f", "")), _user_fingerprint(user)):
        return None
    return user


def _client_ip(request):
    # nginx orqasida: X-Forwarded-For yoki X-Real-IP (aks holda hamma so'rov 127.0.0.1 dan keladi)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (
        forwarded.split(",")[0].strip()
        or request.META.get("HTTP_X_REAL_IP", "").strip()
        or request.META.get("REMOTE_ADDR", "")
    )


def _is_proxy(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unix socket va h.k. — so'rov nginx orqali kelgan
    return addr.is_loopback or addr.is_private


def trusted_client_ip(request):
    """
    Admin cheklovi uchun soxtalashtirib bo'lmaydigan IP.
    X-Forwarded-For ning BIRINCHI qiymatini foydalanuvchi o'zi yozib yuborishi mumkin, shuning uchun
    nginx qo'shgan OXIRGI qiymat olinadi ($proxy_add_x_forwarded_for). Sarlavhalar faqat so'rov
    lokal proksidan (nginx) kelgandagina hisobga olinadi.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    if not remote or _is_proxy(remote):
        chain = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if chain:
            return chain[-1]
        real = request.META.get("HTTP_X_REAL_IP", "").strip()
        if real:
            return real
    return remote


class HasShnqAdminToken(BasePermission):
    message = "Avtorizatsiya talab qilinadi"

    def has_permission(self, request, view):
        user = admin_user_from_token(request.headers.get("X-Admin-Token", ""))
        request.admin_user = user
        return user is not None


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
        "kind": law.kind or "boshqa",
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

        # Avval yuklangan qonunlarning turi bir marta aniqlanib saqlanadi
        for law in laws:
            if not law.kind:
                head = LawEdition.objects.filter(law=law).order_by("-lang", "-edition_date").only("raw_blocks").first()
                law.kind = law_kind(law.number, law.title_kr or law.title_uz, head.raw_blocks[:6] if head else [])
                LawDocument.objects.filter(pk=law.pk).update(kind=law.kind)

        langs, files = {}, {}
        for law_id, lang, file in (
            LawEdition.objects.filter(law_id__in=[l.id for l in laws])
            .order_by("edition_date", "id").values_list("law_id", "lang", "source_file")
        ):
            langs.setdefault(law_id, set()).add(lang)
            files.setdefault(law_id, {})[lang] = file  # oxirgi tahrirning Word fayli
        sources = {
            law_id: ids for law_id, ids in LexSource.objects.filter(law_id__in=[l.id for l in laws]).values_list("law_id", "lex_ids")
        }

        def lex_url(law_id):
            ids = sources.get(law_id) or {}
            first = ids.get("kr") or ids.get("uz") or ids.get("ru")
            return f"https://lex.uz/docs/{first}" if first else None

        return Response({
            "count": len(laws),
            "results": [
                dict(
                    _law_brief(l),
                    languages=[x for x in LANG_CODES if x in langs.get(l.id, ())],
                    files=files.get(l.id, {}),
                    url=lex_url(l.id),
                )
                for l in laws
            ],
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


class ShnqSearchAPIView(PublicAPIView):
    """Hujjatlar matni ichidan qidiruv: mos hujjatlar va har biridan 3 tagacha band parchasi."""

    def get(self, request):
        terms = query_terms(request.GET.get("q", ""))
        question = request.GET.get("mode") == "question"
        limit = request.GET.get("limit", "")
        limit = min(int(limit), 80) if limit.isdigit() and int(limit) > 0 else 80
        if not any(len(t) >= SEARCH_MIN_TERM for t in terms):
            return Response({"results": []})
        key = "shnq-search:%s:%s:%s" % (question, limit, hashlib.sha1(" ".join(terms).encode()).hexdigest())
        results = cache.get(key)
        if results is None:
            results = search_documents(" ".join(terms), max_docs=limit, any_term=question)
            # Ro'yxat sahifasidan tashqarida (chat) ham ko'rsatish uchun hujjat nomi va shifri
            meta = {
                s["id"]: s
                for s in Shnk.objects.filter(id__in=[r["id"] for r in results]).values(
                    "id", "designation", "name_uz", "name_ru"
                )
            }
            for r in results:
                r.update({k: v for k, v in meta.get(r["id"], {}).items() if k != "id"})
            cache.set(key, results, 300)
        return Response({"results": results})


class ShnqDownloadHitAPIView(PublicAPIView):
    def post(self, request, pk):
        shnk = get_object_or_404(Shnk, pk=pk)
        counter, _ = ShnkCounter.objects.get_or_create(shnk=shnk)
        ShnkCounter.objects.filter(pk=counter.pk).update(downloads=F("downloads") + 1)
        return Response({"ok": True})


# =====================================================================
#   ADMIN
# =====================================================================
class ShnqAdminAccessAPIView(PublicAPIView):
    """Eski frontend uchun: admin sahifasi endi hamma uchun ochiq, kirish — login/parol bilan."""

    def get(self, request):
        return Response({"ok": True})


class ShnqAdminLoginAPIView(PublicAPIView):
    """
    Django foydalanuvchisi (is_staff) login/paroli bilan kirish.
    Bir IP dan 10 ta, bitta login uchun 30 ta xato urinishdan keyin 15 daqiqa bloklanadi.
    Xodim yaratish: python manage.py shnq_admin_user <login>
    """

    def post(self, request):
        from django.contrib.auth import authenticate

        username = str(request.data.get("username", "")).strip()[:150]
        password = str(request.data.get("password", ""))[:256]
        ip_key = f"shnq_admin_fail_ip_{trusted_client_ip(request)}"
        user_key = f"shnq_admin_fail_user_{hashlib.sha1(username.lower().encode()).hexdigest()}"
        if cache.get(ip_key, 0) >= LOGIN_MAX_FAILS or cache.get(user_key, 0) >= LOGIN_MAX_FAILS * 3:
            return Response(
                {"detail": "Juda ko'p urinish. 15 daqiqadan keyin qayta urinib ko'ring."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, username=username, password=password) if username and password else None
        if user is None or not user.is_staff:
            for key in (ip_key, user_key):
                cache.set(key, cache.get(key, 0) + 1, LOGIN_LOCK_SECONDS)
            return Response({"detail": "Login yoki parol noto'g'ri"}, status=status.HTTP_401_UNAUTHORIZED)

        cache.delete(ip_key)
        cache.delete(user_key)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response({
            "token": make_admin_token(user),
            "expires_in": TOKEN_MAX_AGE,
            "user": {"username": user.get_username(), "name": user.get_full_name() or user.get_username()},
        })


class ShnqAdminMeAPIView(AdminAPIView):
    def get(self, request):
        user = request.admin_user
        return Response({"username": user.get_username(), "name": user.get_full_name() or user.get_username()})


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


class ShnqAdminCoverageAPIView(AdminAPIView):
    """
    Hujjatlar holati: har bir SHNQ saytda qanday ochiladi.
        text  — matn (lex.uz ko'rinishi): xatosiz, bloklari bor tahrir mavjud
        pdf   — matn yo'q, PDF ochiladi
        link  — matn ham, PDF ham yo'q, faqat lex.uz havolasi
        none  — hech narsa yo'q (hujjat ochilmaydi)
    "error" — tahriri bor, lekin o'qishda xato (sayt uni ko'rsatmaydi).
    GET /api/shnq-admin/coverage/?status=active|all
    """

    def get(self, request):
        qs = Shnk.objects.select_related("shnkgroup__subsystem").order_by(
            "shnkgroup__subsystem_id", "shnkgroup_id", "order", "id"
        )
        if request.GET.get("status", "active") == "active":
            qs = qs.filter(status=True)
        docs = list(qs)

        text_langs, errors = {}, {}
        for shnk_id, lang, parse_error, stats in ShnkEdition.objects.filter(
            shnk_id__in=[d.id for d in docs]
        ).values_list("shnk_id", "lang", "parse_error", "stats"):
            if parse_error:
                errors.setdefault(shnk_id, parse_error)
            elif (stats or {}).get("blocks"):
                text_langs.setdefault(shnk_id, set()).add(lang)

        summary = {"total": len(docs), "text": 0, "pdf": 0, "link": 0, "none": 0, "error": 0,
                   "langs": {code: 0 for code in LANG_CODES}}
        subsystems, items = {}, []
        for d in docs:
            langs = text_langs.get(d.id, set())
            has_pdf = bool(d.pdf_uz or d.pdf_ru)
            if langs:
                kind = "text"
            elif has_pdf:
                kind = "pdf"
            elif d.url and "lex.uz" in d.url:
                kind = "link"
            else:
                kind = "none"
            summary[kind] += 1
            for code in langs:
                summary["langs"][code] += 1
            error = errors.get(d.id) if not langs else None
            if error:
                summary["error"] += 1

            group = d.shnkgroup
            sub = group.subsystem if group else None
            sub_key = sub.id if sub else 0
            row = subsystems.setdefault(sub_key, {
                "id": sub_key, "title": sub.title_uz if sub else "Quyi tizimsiz",
                "total": 0, "text": 0, "pdf": 0, "link": 0, "none": 0,
            })
            row["total"] += 1
            row[kind] += 1

            if kind != "text":
                items.append({
                    "id": d.id,
                    "designation": d.designation,
                    "name_uz": d.name_uz,
                    "name_ru": d.name_ru,
                    "status": d.status,
                    "group": group.title_uz if group else None,
                    "subsystem": sub_key,
                    "kind": kind,
                    "pdf_uz": bool(d.pdf_uz),
                    "pdf_ru": bool(d.pdf_ru),
                    "url": d.url,
                    "error": error,
                })
        return Response({"summary": summary, "subsystems": list(subsystems.values()), "items": items})


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
        return "Faqat .doc, .docx, .rtf yoki .html fayl yuklash mumkin"
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
