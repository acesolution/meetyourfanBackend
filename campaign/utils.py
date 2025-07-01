# campaign/utils.py

from django.conf import settings
from django.db import transaction
import numpy as np
from django.db.models import Sum, Count, Q


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
