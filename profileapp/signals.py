# profileapp/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from api.models import Profile  # Import the Profile model from the same app
from profileapp.models import Follower, FollowRequest
from messagesapp.models import Conversation, Message
from notificationsapp.models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

logger = logging.getLogger(__name__)

def push_notification(actor, recipient, verb, target):
    
    channel_layer = get_channel_layer()
    
    # Create the notification record
    notification = Notification.objects.create(
        actor=actor,
        recipient=recipient,
        verb=verb,
        target=target
    )
    logger.info(f"Notification created for {recipient.username}: {actor.username} {verb}")
    
    # Manually build actor data with profile
    actor_data = {
        "id": actor.id,
        "username": actor.username,
        "email": actor.email,
        "profile": {
            "id": actor.profile.id if hasattr(actor, "profile") and actor.profile else None,
            "name": actor.profile.name if hasattr(actor, "profile") and actor.profile else None,
            "profile_picture": actor.profile.profile_picture.url if hasattr(actor, "profile") and actor.profile and actor.profile.profile_picture else None,
        }
    }
    
    # Alternatively, if you want to use the serializer:
    # actor_data = ActorUserSerializer(actor).data

    payload = {
        "id": notification.id,
        "actor": actor_data,
        "verb": notification.verb,
        "target": str(target),
        "created_at": notification.created_at.isoformat(),
        "read": notification.read,
    }
    
    async_to_sync(channel_layer.group_send)(
        f"notifications_{recipient.id}",
        {
            "type": "send_notification",
            "notification": payload
        }
    )
    return notification

# ------------------------------
# Direct Follow Notification
# ------------------------------
@receiver(post_save, sender=Follower)
def notify_direct_follow(sender, instance, created, **kwargs):
    if created:
        # When a new Follower record is created, notify the followed user.
        # instance.follower is the user who initiated the follow.
        # instance.user is the user being followed.
        push_notification(
            actor=instance.follower,
            recipient=instance.user,
            verb="started following you",
            target=instance  # You can change this to a string like instance.follower.username if desired
        )

# ------------------------------
# Follow Request Notification (When Sent)
# ------------------------------
@receiver(post_save, sender=FollowRequest)
def notify_follow_request(sender, instance, created, **kwargs):
    if created:
        # When a follow request is created, notify the receiver.
        push_notification(
            actor=instance.sender,
            recipient=instance.receiver,
            verb="sent you a follow request",
            target=instance
        )

# ------------------------------
# Follow Request Accepted Notification
# ------------------------------
@receiver(post_save, sender=FollowRequest)
def notify_follow_request_accepted(sender, instance, created, **kwargs):
    # We only want to act on an update (not creation) when the status changes to 'accepted'
    if not created and instance.status == "accepted":
        # Notify the sender that their follow request was accepted.
        push_notification(
            actor=instance.receiver,
            recipient=instance.sender,
            verb="accepted your follow request",
            target=instance
        )
        
        
# @receiver(post_save, sender=MeetupSchedule)
# def notify_meetup_scheduled(sender, instance, created, **kwargs):
#     if created:
#         # ------------------------------
#         # 1. Send a Notification
#         # ------------------------------
#         # Use the existing push_notification function

#         # Notify the winner that the influencer has scheduled a meetup.
#         push_notification(
#             actor=instance.influencer,      # The influencer schedules the meetup
#             recipient=instance.winner,        # The winner should be notified
#             verb="scheduled a meetup with you",  # Customize the message as needed
#             target=instance.campaign        # You can set target as the campaign or even instance if you want more details
#         )
#         logger.info(f"Notification sent for MeetupSchedule id {instance.id}")

#         # ------------------------------
#         # 2. Optionally, Create an Automatic Message
#         # ------------------------------
#         try:
#             # Find the conversation between influencer and winner.
#             # This example assumes that if a conversation exists with exactly these two participants, it should be used.
#             conversation = Conversation.objects.filter(
#                 participants=instance.influencer
#             ).filter(
#                 participants=instance.winner
#             ).first()

#             if conversation:
#                 # Create the message content.
#                 message_content = (
#                     f"Meetup scheduled on {instance.scheduled_datetime.strftime('%Y-%m-%d %H:%M')} at {instance.location}."
#                 )
#                 # Create a new message from the influencer.
#                 message = Message.objects.create(
#                     conversation=conversation,
#                     sender=instance.influencer,
#                     content=message_content
#                 )

#                 # Use the channels layer to broadcast this message to the conversation.
#                 channel_layer = get_channel_layer()
#                 async_to_sync(channel_layer.group_send)(
#                     f"conversation_{conversation.id}",  # group name based on conversation id
#                     {
#                         "type": "chat_message",          # this should match your consumer's method name
#                         "message": message_content,
#                         "user_id": instance.influencer.id,
#                         "username": instance.influencer.username,
#                         "status": message.status,        # Typically "sent"
#                         "message_id": message.id,
#                     }
#                 )
#                 logger.info(f"Automatic message sent in conversation {conversation.id}")
#             else:
#                 logger.warning(
#                     f"No conversation found between {instance.influencer.username} and {instance.winner.username}."
#                 )
#         except Exception as e:
#             logger.error(f"Error while sending automatic message: {str(e)}")