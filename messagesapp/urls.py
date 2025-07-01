# messageapp/urls.py

from django.urls import path
from messagesapp.views import (
    ConversationListView,
    CreateConversationView,
    MessageListView,
    ConversationParticipantsView,
    DeleteConversationView
)

urlpatterns = [
    path('conversations/', ConversationListView.as_view(), name='conversation-list'),
    path('conversations/create/', CreateConversationView.as_view(), name='create-conversation'),
    path('conversations/<int:conversation_id>/messages/', MessageListView.as_view(), name='message-list'),
    path('conversations/<int:conversation_id>/participants/', ConversationParticipantsView.as_view(), name='conversation-participants'),
    path('conversations/<int:conversation_id>/delete/', DeleteConversationView.as_view(), name='delete-conversation'),
]
