# messagesapp/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Q  # built-in Q objects are used to express WHERE conditions
from campaign.models import Campaign

class Conversation(models.Model):
    CATEGORY_CHOICES = [
        ('winner', 'Winner'),
        ('broadcast', 'Broadcast'),
        ('other', 'Other'),
    ]

    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='conversations'
    )
    # Who initiated/created this conversation (helps dedupe broadcast per-creator)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,            # built-in: cascade delete will remove conversations if creator is deleted
        related_name='created_conversations',
        null=True, blank=True
    )

    # Optional campaign link
    campaign = models.ForeignKey(
        Campaign, null=True, blank=True,
        on_delete=models.SET_NULL,           # built-in: set campaign field to NULL if Campaign is deleted
        related_name='conversations'
    )

    # Stable hash/signature of the full participant set (sorted IDs; see view)
    # We'll store plain signature to keep it human-readable; you can switch to sha256 if you prefer.
    participant_signature = models.CharField(max_length=512, db_index=True, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)  # built-in: auto_now_add sets on first create()
    updated_at = models.DateTimeField(auto_now=True)      # built-in: auto_now updates on each save()
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='other')

    class Meta:
        constraints = [
            # For 1-to-1 chats (non-broadcast), enforce a single conversation per signature
            # regardless of category, which satisfies "doesn't matter the category".
            models.UniqueConstraint(
                fields=['participant_signature'],
                condition=Q(category__in=['winner', 'other']),
                name='uniq_direct_signature_any_category',
            ),
            # For broadcast, enforce uniqueness per creator + exact set of participants.
            models.UniqueConstraint(
                fields=['participant_signature', 'created_by'],
                condition=Q(category='broadcast'),
                name='uniq_broadcast_signature_per_creator',
            ),
        ]
        indexes = [
            models.Index(fields=['category', 'participant_signature']),
            models.Index(fields=['created_by', 'category']),
        ]

    def __str__(self):
        # built-in str: shown in admin/shell
        return f"Conversation({self.category}) by {getattr(self.created_by, 'username', 'N/A')} sig={self.participant_signature}"


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
    deleted_at = models.DateTimeField(default=timezone.now)  # built-in: default callable runs at instance creation

    class Meta:
        unique_together = ('conversation', 'user')  # built-in: enforces (conversation,user) pair uniqueness in DB

    def __str__(self):
        return f"Conversation {self.conversation.id} deleted by {self.user.username} at {self.deleted_at}"


class UserMessagesReport(models.Model):
    """
    Store reports raised from a 1:1 conversation.
    """
    REASON_CHOICES = [
        ('inappropriate', 'Inappropriate Content'),
        ('harassment', 'Harassment or Abuse'),
        ('spam', 'Spam or Misleading'),
        ('impersonation', 'Impersonation'),
        ('ip', 'Intellectual Property Violation'),
        ('other', 'Other'),
    ]
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_made_messages')
    reported_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_received_messages')
    conversation = models.ForeignKey('Conversation', on_delete=models.CASCADE, related_name='message_reports')
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # built-in: set on create()

    class Meta:
        indexes = [
            models.Index(fields=['reported_user', 'created_at']),
        ]
        
        
MEETUP_STATUS_CHOICES = (
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
)

class MeetupSchedule(models.Model):
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name='meetup_schedules'
    )
    influencer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='meetups_created'
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='meetups_received'
    )
    # Combine date and time into a single DateTimeField for simplicity.
    scheduled_datetime = models.DateTimeField()
    location = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=MEETUP_STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Meetup for campaign {self.campaign.id} between {self.influencer.username} and {self.winner.username}"