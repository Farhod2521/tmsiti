"""
WebSocket (Django Channels): chatdagi yangi xabarlarni real vaqtda yetkazish.

    /ws/chat/<token>/   mehmon — faqat o'z xonasi
    /ws/admin/chat/     operator — ulangandan keyin {"type": "auth", "token": "<admin token>"} yuboradi

Xabarlar REST orqali yoziladi (support.py), bu yerda faqat tinglanadi.
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import ChatRoom
from .support import ADMINS_GROUP, room_group


class _ChatConsumer(AsyncJsonWebsocketConsumer):
    group = None

    async def join(self, group):
        self.group = group
        await self.channel_layer.group_add(group, self.channel_name)

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"event": "pong"})

    async def chat_event(self, event):
        await self.send_json(event["data"])


class VisitorChatConsumer(_ChatConsumer):
    async def connect(self):
        token = self.scope["url_route"]["kwargs"]["token"]
        room_id = await database_sync_to_async(
            lambda: ChatRoom.objects.filter(token=token).values_list("id", flat=True).first()
        )()
        if not room_id:
            await self.close(code=4404)
            return
        await self.join(room_group(room_id))
        await self.accept()


class AdminChatConsumer(_ChatConsumer):
    # Token URL da emas, birinchi xabarda keladi (server loglarida qolmasligi uchun)
    async def connect(self):
        await self.accept()

    async def receive_json(self, content, **kwargs):
        if self.group is None:
            from .shnq_views import admin_user_from_token

            user = await database_sync_to_async(admin_user_from_token)(str(content.get("token", "")))
            if content.get("type") != "auth" or user is None:
                await self.close(code=4401)
                return
            await self.join(ADMINS_GROUP)
            await self.send_json({"event": "ready"})
            return
        await super().receive_json(content, **kwargs)
