# messageapp/urls.py

from django.urls import path
from messagesapp.views import (
    ConversationListView,
    CreateConversationView,
    MessageListView,
    ConversationParticipantsView,
    DeleteConversationView,
    MuteConversationView,          
    BlockPeerView,                 
    UnblockPeerView,               
    ReportUserView,                
)

urlpatterns = [
    path('conversations/', ConversationListView.as_view(), name='conversation-list'),
    path('conversations/create/', CreateConversationView.as_view(), name='create-conversation'),

    path('conversations/<int:conversation_id>/', DeleteConversationView.as_view(), name='conversation-delete-root'),  # DELETE supported
    path('conversations/<int:conversation_id>/delete/', DeleteConversationView.as_view(), name='delete-conversation'),

    path('conversations/<int:conversation_id>/messages/', MessageListView.as_view(), name='message-list'),
    path('conversations/<int:conversation_id>/participants/', ConversationParticipantsView.as_view(), name='conversation-participants'),

    path('conversations/<int:conversation_id>/mute/', MuteConversationView.as_view(), name='conversation-mute'),
    path('conversations/<int:conversation_id>/block/', BlockPeerView.as_view(), name='conversation-block'),
    path('conversations/<int:conversation_id>/unblock/', UnblockPeerView.as_view(), name='conversation-unblock'),

    path('reports/', ReportUserView.as_view(), name='report-user'),
]
