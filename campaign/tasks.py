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
