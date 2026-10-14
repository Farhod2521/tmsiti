"""
ASGI: oddiy HTTP (Django) + WebSocket (Channels — sayt yordamchisi chati).

WebSocket uchun alohida jarayon (gunicorn HTTP ni boshqarishda davom etadi):
    DJANGO_ENV=production uvicorn config.asgi:application --host 127.0.0.1 --port 8001
nginx: /ws/ -> 127.0.0.1:8001 (Upgrade sarlavhalari bilan).
"""
import os

env = os.getenv("DJANGO_ENV", "development")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env}")

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

from django_app.app_shnk import consumers  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter([
        path("ws/chat/<str:token>/", consumers.VisitorChatConsumer.as_asgi()),
        path("ws/admin/chat/", consumers.AdminChatConsumer.as_asgi()),
    ]),
})
