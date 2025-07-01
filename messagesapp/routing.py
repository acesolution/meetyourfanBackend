#messagesapp/routing.py

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/conversations/(?P<conversation_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    # New endpoint for global conversation updates.
    re_path(r'ws/conversation-updates/$', consumers.ConversationUpdatesConsumer.as_asgi()),
]
