# campaign/tasks.py

from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from .models import Campaign
from blockchain.tasks import (
    release_all_holds_for_campaign_task,
    refund_all_holds_for_campaign_task,
)
from campaign.utils import select_random_winners
from django.db.models import Sum
import boto3
from campaign.models import MediaFile
import subprocess, tempfile, os, uuid

OWNER = settings.OWNER_ADDRESS

@shared_task
def close_expired_campaigns():
    """
    Runs every minute (or however often you schedule it).
    For each campaign whose deadline passed:
      - mark it closed
      - if refund_on_deadline and goal not met → refund
      - otherwise → release
    """
    now = timezone.now()
    expired = Campaign.objects.filter(deadline__lt=now, is_closed=False)

    for c in expired:
        # 1) Close in your DB
        c.is_closed = True
        c.closed_at = now
        c.save(update_fields=['is_closed', 'closed_at'])

        # 2) Figure out sold vs. goal
        specific = c.specific_campaign()
        if specific.campaign_type in ('ticket', 'meet_greet'):
            sold = specific.participations.aggregate(sum_t=Sum('tickets_purchased'))['sum_t'] or 0
            goal = specific.total_tickets
        elif specific.campaign_type == 'media_selling':
            sold = specific.participations.aggregate(sum_m=Sum('media_purchased'))['sum_m'] or 0
            goal = specific.total_media
        else:
            sold = 0
            goal = 0

        seller_id = int(c.user.user_id)

        # 3) Decide refund vs. release
        if c.refund_on_deadline and sold < goal:
            refund_all_holds_for_campaign_task.delay(c.id, seller_id)
        else:
            release_all_holds_for_campaign_task.delay(c.id, seller_id)

        # 4) If you still need winners (for ticket/meet_greet),
        #    you can dispatch that here, too:
        if not c.winners_selected and c.winner_slots > 0 and sold >= goal:
            select_random_winners(c.id)
            c.winners_selected = True
            c.save(update_fields=['winners_selected'])


@shared_task
def watermark_video(media_file_id: int, watermark_s3_key: str = None):
    mf = MediaFile.objects.get(pk=media_file_id)
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    s3 = boto3.client("s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )

    # temp files
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        dst = os.path.join(tmp, "out.mp4")
        wm  = os.path.join(tmp, "wm.png")

        # download input
        s3.download_file(bucket, mf.file.name, src)

        # watermark image (optional) – if you keep one in S3 like "brand/watermark.png"
        if watermark_s3_key:
            s3.download_file(bucket, watermark_s3_key, wm)
            filtergraph = f"movie={wm}[wm];[in][wm]overlay=W-w-20:H-h-20[out]"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src,
                "-filter_complex",
                filtergraph,
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "medium",
                "-movflags",
                "+faststart",
                "-c:a",
                "copy",
                dst,
            ]
        else:
            # text watermark example
            # requires ffmpeg built with libfreetype; adjust fontfile
            draw = (
                "drawtext=text='meetyourfan.io':"
                "fontcolor=0x800080@0.15:fontsize=h*0.1:"
                "x=W-tw-20:y=H-th-20"
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src,
                "-vf",
                draw,
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "medium",
                "-movflags",
                "+faststart",
                "-c:a",
                "copy",
                dst,
            ]

        subprocess.check_call(cmd)

        # upload back (replace or write a new key)
        new_key = mf.file.name  # overwrite
        s3.upload_file(
            dst, bucket, new_key, ExtraArgs={"ContentType": "video/mp4"}
        )
