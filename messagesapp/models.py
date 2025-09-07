# messagesapp/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from campaign.models import Campaign
# Create your models here.
class Conversation(models.Model):
    CATEGORY_CHOICES = [
        ('winner', 'Winner'),
        ('broadcast', 'Broadcast'),
        ('other', 'Other'),
    ]

    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='conversations'
    )
    # NEW: link the conversation to a campaign (optional)
    campaign = models.ForeignKey(
        Campaign, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='conversations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='other')  # Add category field

    def __str__(self):
        return f"Conversation ({self.category}) between {', '.join([user.username for user in self.participants.all()])}"


class Message(models.Model):
    
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages'
    )
    content = models.TextField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10,
        choices=[
            ('sent', 'Sent'),
            ('delivered', 'Delivered'),
            ('read', 'Read')
        ],
        default='sent'
    )
    
    class Meta:
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'status']),
        ]
    
    def __str__(self):
        return f"Message from {self.sender.username}: {self.content[:30]}"
    
    

    
class ConversationDeletion(models.Model):
    conversation = models.ForeignKey('Conversation', on_delete=models.CASCADE, related_name='deletions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversation_deletions')
    deleted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('conversation', 'user')

    def __str__(self):
        return f"Conversation {self.conversation.id} deleted by {self.user.username} at {self.deleted_at}"