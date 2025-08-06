# campaign/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from campaign.models import Participation, Campaign, CampaignWinner, MediaFile
from notificationsapp.models import Notification
from messagesapp.models import Conversation, Message  # if needed for target info
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from django.db.models import Count
from .views import get_or_create_winner_conversation
from PIL import Image, ImageFilter
from io import BytesIO
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

def push_notification(actor, recipient, verb, target):
    """
    Creates a Notification record and pushes it via the channel layer,
    including the actor’s profile data in the payload.
    """
    channel_layer = get_channel_layer()
    # Create the notification record in the database
    notification = Notification.objects.create(
        actor=actor,
        recipient=recipient,
        verb=verb,
        target=target
    )
    logger.info(f"Notification created for {recipient.username} about {verb} on {target}")
    
    # Build the actor data manually with profile info
    actor_data = {
        "id": actor.id,
        "username": actor.username,
        "email": actor.email,
        "profile": {
            "id": actor.profile.id if hasattr(actor, "profile") and actor.profile else None,
            "name": actor.profile.name if hasattr(actor, "profile") and actor.profile else None,
            "profile_picture": (actor.profile.profile_picture.url 
                                if hasattr(actor, "profile") and actor.profile and actor.profile.profile_picture 
                                else None)
        }
    }
    
    # Push the notification in real time
    async_to_sync(channel_layer.group_send)(
        f"notifications_{recipient.id}",
        {
            "type": "send_notification",
            "notification": {
                "id": notification.id,
                "actor": actor_data,  # Now includes full profile data
                "verb": notification.verb,
                "target": str(target),  # Customize as needed (e.g., campaign title or message preview)
                "created_at": notification.created_at.isoformat(),
                "read": notification.read,
            }
        }
    )
    return notification

# ------------------------------
# When a Participation is created
# ------------------------------
@receiver(post_save, sender=Participation)
def notify_participation(sender, instance, created, **kwargs):
    if created:
        campaign = instance.campaign
        actor = instance.fan  # The fan who participated
        # Notify the campaign influencer (creator)
        push_notification(
            actor=actor,
            recipient=campaign.user,
            verb="participated in your campaign",
            target=campaign
        )
        # Optionally, notify other participants (excluding the one who just participated)
        for participation in campaign.participations.exclude(fan=actor):
            push_notification(
                actor=actor,
                recipient=participation.fan,
                verb="also participated in the campaign",
                target=campaign
            )

# ------------------------------
# When a Campaign is closed
# ------------------------------
@receiver(post_save, sender=Campaign)
def notify_campaign_closed(sender, instance, **kwargs):
    if instance.is_closed:
        campaign = instance
        actor = campaign.user  # Use the influencer as the actor (or use a system user if preferred)
        # Notify all participants about the campaign closure
        for participation in campaign.participations.all():
            push_notification(
                actor=actor,
                recipient=participation.fan,
                verb="has closed the campaign",
                target=campaign
            )
        # Optionally, notify the influencer (self-notification might be optional)
        push_notification(
            actor=actor,
            recipient=campaign.user,
            verb="your campaign is now closed",
            target=campaign
        )

@receiver(post_save, sender=CampaignWinner)
def notify_winner_selection(sender, instance, created, **kwargs):
    if created:
        campaign = instance.campaign
        influencer = campaign.user
        winner = instance.fan

        # Push notifications
        push_notification(
            actor=winner,
            recipient=influencer,
            verb="a winner was selected for your campaign",
            target=campaign
        )
        push_notification(
            actor=influencer,
            recipient=winner,
            verb="you won the campaign",
            target=campaign
        )

        # --- Conversation Setup ---
        # Use the helper function to get (or update) the conversation regardless of its current category.
        conversation = get_or_create_winner_conversation(influencer, winner)

        # Create an initial congratulatory message.
        Message.objects.create(
            conversation=conversation,
            sender=influencer,
            content=f"Congratulations! You have been selected as a winner for the campaign: {campaign.title}"
        )



@receiver(post_save, sender=MediaFile)
def create_blurred_preview(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        # Use instance.file.open() for remote storage
        with instance.file.open('rb') as f:
            original = Image.open(f)
            original.thumbnail((400, 400))  # small size
            blurred = original.filter(ImageFilter.GaussianBlur(radius=12))

            buffer = BytesIO()
            blurred.save(buffer, format="JPEG", quality=50)
            buffer.seek(0)
            instance.preview_image.save(
                f"preview_{instance.file.name.split('/')[-1]}.jpg",
                ContentFile(buffer.read()),
                save=False
            )
            instance.save(update_fields=["preview_image"])
    except Exception as e:
        # log but do not break upload
        logger.exception("Failed to create blurred preview: %s", e)