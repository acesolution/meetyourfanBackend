# notificationsapp/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from messagesapp.models import Conversation

class Notification(models.Model):
    # Who triggers the notification
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications_sent'
    )
    # Who receives the notification
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    verb = models.CharField(max_length=255)
    # Optional: a target object (e.g., a campaign, a message, etc.)
    target_content_type = models.ForeignKey(
        'contenttypes.ContentType',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    target_object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey('target_content_type', 'target_object_id')

    created_at = models.DateTimeField(default=timezone.now)
    read = models.BooleanField(default=False)
    
    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.actor} {self.verb} {self.recipient} ({self.created_at})"



class ConversationMute(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='mutes'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversation_mutes'
    )
    mute_until = models.DateTimeField()  # Time until which notifications are muted
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('conversation', 'user')

    def __str__(self):
        return f"Conversation {self.conversation.id} muted for {self.user.username} until {self.mute_until}"