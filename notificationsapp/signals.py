# notificationsapp/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from messagesapp.models import Message, Conversation
from notificationsapp.models import Notification, ConversationMute
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
import logging
from notificationsapp.serializers import ActorUserSerializer

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    if created:
        conversation = instance.conversation
        sender_user = instance.sender
        channel_layer = get_channel_layer()

        actor_data = ActorUserSerializer(sender_user).data  # ← full actor

        for user in conversation.participants.exclude(id=sender_user.id):
            mute_record = ConversationMute.objects.filter(conversation=conversation, user=user).first()
            if mute_record and timezone.now() < mute_record.mute_until:
                continue

            notification = Notification.objects.create(
                actor=sender_user,
                recipient=user,
                verb="sent you a message",
                target=instance,
            )

            async_to_sync(channel_layer.group_send)(
                f"notifications_{user.id}",
                {
                    "type": "send_notification",
                    "notification": {
                        "id": notification.id,
                        "actor": actor_data,
                        "verb": notification.verb,
                        "target": {
                            "type": "message",
                            "message_id": instance.id,
                            "conversation_id": conversation.id,
                            "preview": str(instance)[:140],
                        },
                        "created_at": notification.created_at.isoformat(),
                        "read": notification.read,
                    }
                }
            )
