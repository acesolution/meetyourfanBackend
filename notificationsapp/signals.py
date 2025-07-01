# notificationsapp/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from messagesapp.models import Message, Conversation
from notificationsapp.models import Notification, ConversationMute
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    if created:
        conversation = instance.conversation
        sender_user = instance.sender
        channel_layer = get_channel_layer()
        
        # Loop through all participants except the sender
        for user in conversation.participants.exclude(id=sender_user.id):
            # Check if notifications for this conversation are muted for the recipient.
            mute_record = ConversationMute.objects.filter(conversation=conversation, user=user).first()
            if mute_record and timezone.now() < mute_record.mute_until:
                logger.info(
                    f"Skipping push notification for {user.username} for conversation {conversation.id} because notifications are muted until {mute_record.mute_until}."
                )
                # Optionally, you can still create the Notification record in the database here if you want it available via the API.
                continue

            # Otherwise, create a notification record in the database
            notification = Notification.objects.create(
                actor=sender_user,
                recipient=user,
                verb="sent you a message",
                target=instance,
            )
            logger.info(f"Notification created for {user.username} about message {instance.id}")
            
            # Push the notification via the channel layer to the recipient's group
            async_to_sync(channel_layer.group_send)(
                f"notifications_{user.id}",
                {
                    "type": "send_notification",
                    "notification": {
                        "id": notification.id,
                        "actor": sender_user.username,
                        "verb": notification.verb,
                        "target": str(instance),
                        "created_at": notification.created_at.isoformat(),
                        "read": notification.read,
                    }
                }
            )
