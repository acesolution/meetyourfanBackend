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
from django.db.models import Q

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    if created:
        conversation = instance.conversation
        sender_user = instance.sender
        channel_layer = get_channel_layer()

        actor_data = ActorUserSerializer(sender_user).data  # ← full actor

        for user in conversation.participants.exclude(id=sender_user.id):
            # MUTED if: mute_until is NULL (always) OR in the future
            is_muted = ConversationMute.objects.filter(
                conversation=conversation, user=user
            ).filter(Q(mute_until__isnull=True) | Q(mute_until__gt=timezone.now())).exists()

            if is_muted:
                continue  # skip creating Notification + skip group_send

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
