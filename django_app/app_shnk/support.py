"""
Saytdagi yordamchi chat (operator bilan) va hujjatlarga takliflar.

Mehmon ro'yxatdan o'tmaydi: birinchi xabarda xona ochiladi, brauzerda faqat maxfiy xona tokeni
saqlanadi va yozishma shu token bilan o'qiladi.
    POST /api/chat/start/                            {page} -> {token}
    GET  /api/chat/<token>/messages/                 yozishma
    POST /api/chat/<token>/messages/                 {text}
    WS   /ws/chat/<token>/                           yangi xabarlar real vaqtda (consumers.py)
Operator (X-Admin-Token):
    GET  /api/shnq-admin/chat/rooms/?search=         xonalar (oxirgi xabar bo'yicha)
    GET  /api/shnq-admin/chat/rooms/<id>/messages/   yozishma (mehmon xabarlari o'qilgan deb belgilanadi)
    POST /api/shnq-admin/chat/rooms/<id>/messages/   {text} javob
    GET  /api/shnq-admin/badges/                     o'qilmagan chat va yangi takliflar soni
    WS   /ws/admin/chat/                             barcha xonalardagi yangi xabarlar
Takliflar:
    POST  /api/suggestions/                          {kind, doc_id, doc_title, block, block_text, type, full_name, phone, text}
    GET   /api/shnq-admin/suggestions/?status=&type=&page=
    PATCH /api/shnq-admin/suggestions/<id>/          {status}

Real vaqt: xabar REST orqali saqlanadi, keyin Channels guruhlariga yuboriladi —
"chat_room_<id>" (mehmon) va "chat_admins" (operatorlar).
"""
import logging
import re
import secrets

from django.core.cache import cache
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from .analytics import UZ_REGIONS, locate_place
from .models import ChatMessage, ChatRoom, DocSuggestion
from .shnq_search import _bmp
from .shnq_views import AdminAPIView, PublicAPIView, trusted_client_ip

logger = logging.getLogger(__name__)

ADMINS_GROUP = "chat_admins"
MAX_MESSAGE = 2000
BLOCK_RE = re.compile(r"^b\d{1,6}$")


def room_group(room_id):
    return f"chat_room_{room_id}"


def _limited(key, limit, seconds):
    """Oddiy hisoblagich: limitdan oshsa True."""
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, seconds)
    return False


def _clean_text(value, limit):
    return _bmp(str(value or "").strip())[:limit]


def _phone_ok(phone):
    return 9 <= len(re.sub(r"\D", "", phone)) <= 15


def _place(request):
    try:
        return locate_place(trusted_client_ip(request))
    except Exception:
        return "", "", ""


# ---------------- JSON ----------------
def room_json(room):
    return {
        "id": room.pk,
        "title": str(room),
        "page": room.page,
        "country": room.country,
        "region": room.region,
        "region_name": UZ_REGIONS.get(room.region, ""),
        "city": room.city,
        "unread": room.unread,
        "last_message": room.last_message,
        "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
        "created_at": room.created_at.isoformat() if room.created_at else None,
    }


def message_json(message, for_admin=False):
    data = {
        "id": message.pk,
        "sender": message.sender,
        "text": message.text,
        "read": message.read,
        "created_at": message.created_at.isoformat(),
    }
    if for_admin:
        data["operator"] = message.operator
    return data


def _broadcast(groups_events):
    """[(guruh, ma'lumot)] — Channels orqali yuborish. WebSocket ishlamasa ham REST ishlayveradi."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        return
    layer = get_channel_layer()
    if layer is None:
        return
    for group, data in groups_events:
        try:
            async_to_sync(layer.group_send)(group, {"type": "chat.event", "data": data})
        except Exception:
            logger.warning("Chat xabarini %s guruhiga yuborib bo'lmadi", group, exc_info=True)


def _save_message(room, sender, text, operator=""):
    message = ChatMessage.objects.create(room=room, sender=sender, text=text, operator=operator)
    updates = {"last_message": text[:300], "last_message_at": message.created_at}
    if sender == "visitor":
        updates["unread"] = F("unread") + 1
    ChatRoom.objects.filter(pk=room.pk).update(**updates)
    room.refresh_from_db()
    _broadcast([
        (room_group(room.pk), {"event": "message", "message": message_json(message)}),
        (ADMINS_GROUP, {"event": "message", "room": room_json(room), "message": message_json(message, True)}),
    ])
    return message


# =====================================================================
#   Mehmon
# =====================================================================
class ChatStartAPIView(PublicAPIView):
    def post(self, request):
        if _limited(f"chat-start:{trusted_client_ip(request)}", 10, 3600):
            return Response({"detail": "Juda ko'p so'rov"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        country, region, city = _place(request)
        room = ChatRoom.objects.create(
            token=secrets.token_urlsafe(24),
            page=str(request.data.get("page", ""))[:500],
            country=country,
            region=region,
            city=city,
        )
        return Response({"token": room.token}, status=status.HTTP_201_CREATED)


class ChatMessagesAPIView(PublicAPIView):
    def get(self, request, token):
        room = get_object_or_404(ChatRoom, token=token)
        # Mehmon ochdi — operator javoblari o'qilgan
        if room.messages.filter(sender="operator", read=False).update(read=True):
            _broadcast([(ADMINS_GROUP, {"event": "seen", "room": room.pk})])
        return Response({"messages": [message_json(m) for m in room.messages.all()]})

    def post(self, request, token):
        room = get_object_or_404(ChatRoom, token=token)
        text = _clean_text(request.data.get("text"), MAX_MESSAGE)
        if not text:
            return Response({"detail": "Xabar bo'sh"}, status=status.HTTP_400_BAD_REQUEST)
        if _limited(f"chat-msg:{room.pk}", 20, 60):
            return Response({"detail": "Juda tez yozyapsiz, biroz kuting"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        message = _save_message(room, "visitor", text)
        return Response(message_json(message), status=status.HTTP_201_CREATED)


# =====================================================================
#   Operator
# =====================================================================
class AdminChatRoomsAPIView(AdminAPIView):
    def get(self, request):
        qs = ChatRoom.objects.filter(last_message_at__isnull=False)
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(messages__text__icontains=search) | Q(city__icontains=search))
            qs = qs.distinct()
        return Response({"rooms": [room_json(r) for r in qs[:200]]})


class AdminChatMessagesAPIView(AdminAPIView):
    def get(self, request, pk):
        room = get_object_or_404(ChatRoom, pk=pk)
        if room.unread or room.messages.filter(sender="visitor", read=False).exists():
            room.messages.filter(sender="visitor", read=False).update(read=True)
            ChatRoom.objects.filter(pk=room.pk).update(unread=0)
            room.unread = 0
            _broadcast([
                (ADMINS_GROUP, {"event": "read", "room": room.pk}),
                (room_group(room.pk), {"event": "read"}),
            ])
        return Response({
            "room": room_json(room),
            "messages": [message_json(m, True) for m in room.messages.all()],
        })

    def post(self, request, pk):
        room = get_object_or_404(ChatRoom, pk=pk)
        text = _clean_text(request.data.get("text"), MAX_MESSAGE)
        if not text:
            return Response({"detail": "Xabar bo'sh"}, status=status.HTTP_400_BAD_REQUEST)
        user = request.admin_user
        message = _save_message(room, "operator", text, operator=user.get_username())
        return Response(message_json(message, True), status=status.HTTP_201_CREATED)


class AdminBadgesAPIView(AdminAPIView):
    def get(self, request):
        return Response({
            "chat_unread": ChatRoom.objects.aggregate(n=Sum("unread"))["n"] or 0,
            "suggestions_new": DocSuggestion.objects.filter(status="new").count(),
        })


# =====================================================================
#   Takliflar
# =====================================================================
def suggestion_json(s):
    return {
        "id": s.id,
        "kind": s.kind,
        "doc_id": s.doc_id,
        "doc_title": s.doc_title,
        "block": s.block,
        "block_text": s.block_text,
        "type": s.type,
        "type_label": s.get_type_display(),
        "full_name": s.full_name,
        "phone": s.phone,
        "text": s.text,
        "country": s.country,
        "region": s.region,
        "region_name": UZ_REGIONS.get(s.region, ""),
        "city": s.city,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
    }


class SuggestionCreateAPIView(PublicAPIView):
    def post(self, request):
        data = request.data
        kind = data.get("kind") if data.get("kind") in ("shnq", "law") else "shnq"
        doc_id = str(data.get("doc_id", ""))
        stype = data.get("type")
        full_name = _clean_text(data.get("full_name"), 200)
        phone = str(data.get("phone", "")).strip()[:30]
        text = _clean_text(data.get("text"), 5000)
        block = str(data.get("block", ""))
        errors = {}
        if not doc_id.isdigit():
            errors["doc_id"] = "Hujjat ko'rsatilmagan"
        if stype not in dict(DocSuggestion.TYPES):
            errors["type"] = "Taklif turini tanlang"
        if len(full_name) < 3:
            errors["full_name"] = "Ism-familiyani kiriting"
        if not _phone_ok(phone):
            errors["phone"] = "Telefon raqamini to'g'ri kiriting"
        if len(text) < 5:
            errors["text"] = "Taklif matnini yozing"
        if errors:
            return Response({"detail": next(iter(errors.values())), "errors": errors},
                            status=status.HTTP_400_BAD_REQUEST)
        if _limited(f"suggestion:{trusted_client_ip(request)}", 10, 3600):
            return Response({"detail": "Juda ko'p taklif yuborildi. Birozdan keyin urinib ko'ring"},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        country, region, city = _place(request)
        item = DocSuggestion.objects.create(
            kind=kind,
            doc_id=int(doc_id),
            doc_title=_clean_text(data.get("doc_title"), 500),
            block=block if BLOCK_RE.match(block) else "",
            block_text=_clean_text(data.get("block_text"), 2000),
            type=stype,
            full_name=full_name,
            phone=phone,
            text=text,
            country=country,
            region=region,
            city=city,
        )
        _broadcast([(ADMINS_GROUP, {"event": "suggestion", "id": item.id})])
        return Response({"id": item.id}, status=status.HTTP_201_CREATED)


class AdminSuggestionListAPIView(AdminAPIView):
    PAGE_SIZE = 30

    def get(self, request):
        qs = DocSuggestion.objects.all()
        if request.GET.get("status") in dict(DocSuggestion.STATUSES):
            qs = qs.filter(status=request.GET["status"])
        if request.GET.get("type") in dict(DocSuggestion.TYPES):
            qs = qs.filter(type=request.GET["type"])
        search = request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(phone__icontains=search)
                           | Q(text__icontains=search) | Q(doc_title__icontains=search))
        total = qs.count()
        page = request.GET.get("page", "1")
        page = max(int(page), 1) if page.isdigit() else 1
        start = (page - 1) * self.PAGE_SIZE
        counts = {code: DocSuggestion.objects.filter(status=code).count() for code, _ in DocSuggestion.STATUSES}
        return Response({
            "results": [suggestion_json(s) for s in qs[start:start + self.PAGE_SIZE]],
            "total": total,
            "page": page,
            "pages": max((total + self.PAGE_SIZE - 1) // self.PAGE_SIZE, 1),
            "counts": counts,
        })


class AdminSuggestionAPIView(AdminAPIView):
    def patch(self, request, pk):
        item = get_object_or_404(DocSuggestion, pk=pk)
        new_status = request.data.get("status")
        if new_status not in dict(DocSuggestion.STATUSES):
            return Response({"detail": "Noto'g'ri holat"}, status=status.HTTP_400_BAD_REQUEST)
        item.status = new_status
        item.save(update_fields=["status"])
        return Response(suggestion_json(item))

    def delete(self, request, pk):
        get_object_or_404(DocSuggestion, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
