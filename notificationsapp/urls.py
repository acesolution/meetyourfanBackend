# notificationsapp/urls.py
from django.urls import path
from notificationsapp.views import (
    NotificationListView,
    MarkNotificationReadView,
    MuteConversationView,
)

urlpatterns = [
    # GET endpoint for listing notifications
    path('', NotificationListView.as_view(), name='notification-list'),
    
    # POST endpoint for marking a notification as read; expects a notification_id parameter
    path('<int:notification_id>/read/', MarkNotificationReadView.as_view(), name='notification-read'),
    
    # POST endpoint for muting notifications for a specific conversation;
    # expects a conversation_id parameter and a 'mute_duration' in the request body.
    path('conversations/<int:conversation_id>/mute/', MuteConversationView.as_view(), name='mute-conversation'),
]
