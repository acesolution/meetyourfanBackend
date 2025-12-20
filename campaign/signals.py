# campaign/signals.py

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from campaign.models import Participation, Campaign, CampaignWinner, MediaFile
from notificationsapp.models import Notification
from messagesapp.models import Conversation, Message  # if needed for target info
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from django.db.models import Count
from .utils import get_or_create_winner_conversation
from PIL import Image, ImageFilter
from io import BytesIO
from django.core.files.base import ContentFile
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

User = get_user_model()

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Campaign, dispatch_uid="campaign_closed_state_tracker_v1")
def _track_campaign_is_closed(sender, instance: Campaign, **kwargs):
    """
    Track the old value of is_closed BEFORE saving.

    Why:
    - post_save runs AFTER save (so you can't easily know if is_closed changed)
    - We'll store the previous value on the instance to detect a transition.
    """
    if not instance.pk:
        # New campaign (no DB row yet)
        instance._was_closed = False
        return

    # built-in: .values_list("field", flat=True) returns a list-like of that field only
    # built-in: .first() returns first row or None (no exception)
    old_val = sender.objects.filter(pk=instance.pk).values_list("is_closed", flat=True).first()
    instance._was_closed = bool(old_val)
    
    

def push_notification(actor, recipient, verb, target):
    """
    Creates a Notification record and pushes it via the channel layer,
    including the actor’s profile data in the payload.
    """
    # 👇 Don’t notify soft-deleted / inactive accounts
    if hasattr(recipient, "is_active") and not recipient.is_active:
        return None
    
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
                "target": (
                {"type": "campaign", "campaign_id": target.id, "title": getattr(target, "title", None)}
                    if hasattr(target, "id") else
                    {"type": "text", "text": str(target)}
                ),
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
        for participation in campaign.participations.exclude(fan=actor).filter(
            fan__is_active=True
        ):
            push_notification(
                actor=actor,
                recipient=participation.fan,
                verb="also participated in the campaign",
                target=campaign
            )

# ------------------------------
# When a Campaign is closed
# ------------------------------
@receiver(post_save, sender=Campaign, dispatch_uid="campaign_closed_notify_v2")
def notify_campaign_closed(sender, instance: Campaign, created, **kwargs):
    """
    Notify participants exactly once when the campaign transitions from open -> closed.
    Also dedupe at DB-level to be safe even if this runs twice.
    """
    if created:
        return

    # Only notify when it JUST became closed (False -> True)
    was_closed = getattr(instance, "_was_closed", False)
    if was_closed:
        return
    if not instance.is_closed:
        return

    campaign = instance
    actor = campaign.user

    # ✅ Notify unique fans only (not per participation row)
    participant_ids = (
        campaign.participations
        .filter(fan__is_active=True)
        .values_list("fan_id", flat=True)
        .distinct()
    )

    # Optional but very good: DB-level dedupe so even if signal runs twice,
    # we won't insert duplicate "has closed the campaign" notifications.
    ct = ContentType.objects.get_for_model(Campaign)

    existing_recipient_ids = set(
        Notification.objects.filter(
            actor=actor,
            verb="has closed the campaign",
            target_content_type=ct,
            target_object_id=campaign.id,
            recipient_id__in=participant_ids,
        ).values_list("recipient_id", flat=True)
    )

    def _after_commit():
        # built-in: set(...) membership is O(1) average
        for fan in User.objects.filter(id__in=participant_ids).only("id", "username", "email"):
            if fan.id in existing_recipient_ids:
                continue

            push_notification(
                actor=actor,
                recipient=fan,
                verb="has closed the campaign",
                target=campaign
            )

        # Optional self-notification
        push_notification(
            actor=actor,
            recipient=campaign.user,
            verb="your campaign is now closed",
            target=campaign
        )

    # built-in: transaction.on_commit() runs after DB commit succeeds (prevents “ghost” notifs on rollback)
    transaction.on_commit(_after_commit)

@receiver(post_save, sender=CampaignWinner, dispatch_uid="campaign_winner_notify_v1")
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

        # Make sure the actual messaging runs only after the row commits:
        def _after_commit():
            # Ensure a 1:1 exists (no seed text here to avoid double-send)
            conv, _ = get_or_create_winner_conversation(
                influencer=influencer,
                winner=winner,
                campaign=campaign,
                seed_text=None,              # important: prevent helper from also sending
            )

            # Send exactly one DM for this newly-created winner
            text = getattr(campaign, "winner_dm_template", None) \
                or f"Congratulations! You won the campaign: {campaign.title}"
            Message.objects.create(conversation=conv, sender=influencer, content=text)

        transaction.on_commit(_after_commit)


@receiver(post_save, sender=MediaFile)
def create_blurred_preview(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        with instance.file.open('rb') as f:      
            original = Image.open(f)
            original.thumbnail((400, 400))         # built-in: create a thumbnail
            blurred = original.filter(
                ImageFilter.GaussianBlur(radius=12)  # built-in: blur filter
            )

            # convert RGBA→RGB so we can save as JPEG
            if blurred.mode in ("RGBA", "LA"):
                blurred = blurred.convert("RGB")  # built-in: drop alpha layer

            buffer = BytesIO()
            blurred.save(buffer, format="JPEG", quality=50)
            buffer.seek(0)

            instance.preview_image.save(
                f"preview_{instance.file.name.split('/')[-1]}.jpg",
                ContentFile(buffer.read()),
                save=False                           # built-in: don’t auto-save here
            )
            instance.save(update_fields=["preview_image"])  # built-in: save only the preview field

    except Exception as e:
        # now this should only fire on truly unexpected errors
        logger.exception("Failed to create blurred preview: %s", e)