# campaign/utils.py

from django.conf import settings
from django.db import transaction
import numpy as np
from django.db.models import Sum, Count, Q
from PIL import Image, ImageDraw, ImageFont, ImageOps
from django.db.utils import IntegrityError
import random
import boto3
from io import BytesIO
from pathlib import Path
from django.core.files.base import ContentFile


def select_random_winners(campaign_id):
    from campaign.models import Campaign, Participation, CampaignWinner

    campaign = Campaign.objects.get(id=campaign_id)
    participants = list(Participation.objects.filter(campaign=campaign))

    # 1) optional: exclude prior winners
    if campaign.exclude_previous_winners:
        past = set(
            CampaignWinner.objects
            .filter(campaign__user=campaign.user)
            .values_list('fan_id', flat=True)
        )
        participants = [p for p in participants if p.fan_id not in past]

    if not participants:
        return []

    # 2) build fans & weights
    fans    = []
    weights = []
    for p in participants:
        fans.append(p.fan)
        if campaign.campaign_type == 'media_selling':
            w = p.media_purchased or 1
        else:
            w = p.tickets_purchased or 1
        weights.append(w)

    # 3) sample without replacement, weighted
    k = campaign.winner_slots or 1
    if len(fans) <= k:
        chosen = fans
    else:
        probs = np.array(weights) / sum(weights)
        idxs  = np.random.choice(len(fans), size=k, replace=False, p=probs)
        chosen = [fans[i] for i in idxs]

    # 4) atomically mark winners
    winners = []
    with transaction.atomic():
        campaign.winners_selected = True
        campaign.save(update_fields=['winners_selected'])

        for fan in chosen:
            cw, created = CampaignWinner.objects.get_or_create(
                campaign=campaign, fan=fan
            )
            if created:
                winners.append(fan)

    return winners



def get_or_create_winner_conversation(influencer, winner):
    from messagesapp.models import Conversation
    
    """
    Checks if any conversation exists between the influencer and the winner.
    If a conversation exists but its category is not 'winner', update its category.
    Otherwise, create a new conversation with category 'winner' and add both as participants.
    """
    # Find conversations that include both influencer and winner,
    # and annotate the number of participants in each conversation.
    conversation = Conversation.objects.filter(
        Q(participants=influencer) & Q(participants=winner)
    ).annotate(num_participants=Count('participants')).filter(num_participants=2).first()
    
    if conversation:
        if conversation.category != 'winner':
            conversation.category = 'winner'
            conversation.save(update_fields=['category'])
    else:
        conversation = Conversation.objects.create(category='winner')
        conversation.participants.add(influencer, winner)
    return conversation



def assign_media_to_user(campaign, user, quantity: int):
    """
    Give the user up to `quantity` random media files from the given campaign that they don't already own.
    Multiple users can own the same media_file, but a user can't get duplicates of the same file.
    """
    from .models import MediaAccess, MediaFile
    # 1) Filter all media for this campaign that the user doesn’t already have
    available_qs = (
        MediaFile.objects
        .filter(campaign=campaign)
        .exclude(accesses__user=user)
    )

    # 2) Shuffle and pick up to `quantity` IDs
    media_ids = list(available_qs.values_list("id", flat=True))
    random.shuffle(media_ids)

    assigned = []
    for media_id in media_ids[:quantity]:
        with transaction.atomic():
            media = MediaFile.objects.select_for_update().get(pk=media_id)
            # get_or_create prevents duplicates per user due to unique_together
            ma, created = MediaAccess.objects.get_or_create(
                user=user,
                media_file=media
            )
            if created:
                assigned.append(media)
    return assigned




def generate_presigned_s3_url(key: str, expires_in: int = 3600):
    """
    Built-in boto3.client(‘s3’).generate_presigned_url()
    returns a time-limited URL to GET a private object.
    """
    client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': key},
        ExpiresIn=expires_in,
    )
    
    

def watermark_image(uploaded_file, text="meetyourfan.io", opacity=0.15):
    """Place a single semi-transparent purple text watermark on the image.

    The watermark is rendered once in the bottom-right corner to avoid
    obscuring the underlying image content.
    """
    im = Image.open(uploaded_file)
    fmt = im.format  # preserve original format before conversion
    im = ImageOps.exif_transpose(im)  # respect camera EXIF orientation
    im = im.convert("RGBA")

    # pick a font size ~10% of min dimension
    base = min(im.size)
    size = max(16, int(base * 0.10))
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()

    # build watermark layer
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # text size
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    alpha = int(255 * opacity)

    # position watermark in bottom-right with a small margin
    margin = max(5, int(size * 0.5))
    x = im.width - tw - margin
    y = im.height - th - margin

    draw.text((x, y), text, font=font, fill=(128, 0, 128, alpha))

    out = Image.alpha_composite(im, layer)

    buf = BytesIO()

    fmt = fmt if fmt in ["JPEG", "PNG"] else "JPEG"

    if fmt != "PNG":
        out = out.convert("RGB")
        out.save(buf, format=fmt, quality=90, optimize=True)
    else:
        out.save(buf, format=fmt)
    buf.seek(0)
    ext = "jpg" if fmt == "JPEG" else "png"
    name = Path(getattr(uploaded_file, "name", "upload")).stem + f"_wm.{ext}"
    return ContentFile(buf.read(), name=name)
