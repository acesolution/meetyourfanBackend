#meetyourfanBackend/asgi

import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "meetyourfanBackend.settings")

# Initialize Django's ASGI application early to prevent "Apps aren't loaded yet."
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from messagesapp.routing import websocket_urlpatterns as messages_patterns
from notificationsapp.routing import websocket_urlpatterns as notifications_patterns
from .middleware import JWTAuthMiddlewareStack  # Import your custom middleware

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': JWTAuthMiddlewareStack(
        URLRouter(
            messages_patterns + notifications_patterns
        )
    )
})