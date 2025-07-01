# campaign/models.py

from django.db import models
from django.conf import settings
from decimal import Decimal
from django.db import transaction
from campaign.utils import select_random_winners
from django.utils import timezone
from blockchain.tasks import release_all_holds_for_campaign_task

class Campaign(models.Model):
    CAMPAIGN_TYPE_CHOICES = [
        ('ticket', 'Ticket'),
        ('media_selling', 'Media Selling'),
        ('meet_greet', 'Meet & Greet'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="base_campaigns"
    )
    title = models.CharField(max_length=200)
    banner_image = models.ImageField(upload_to='campaign_banners/')
    campaign_type = models.CharField(max_length=20, choices=CAMPAIGN_TYPE_CHOICES)
    deadline = models.DateTimeField()
    details = models.TextField()
    ticket_limit_per_fan = models.PositiveIntegerField(blank=True, null=True)
    winner_slots = models.PositiveIntegerField(blank=True, null=True, default=1)
    winners_selected = models.BooleanField(default=False)
    is_public_announcement = models.BooleanField(default=True)
    auto_close_on_goal_met = models.BooleanField(default=False)
    npn_campaign = models.BooleanField(default=False)
    refund_on_deadline = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(blank=True, null=True)  # New field for closing time.
    exclude_previous_winners = models.BooleanField(default=False)  # ✅ New Feature
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        blank=True, 
        related_name="liked_campaigns"
    )
    
    


    def close_campaign(self):
        """Mark the campaign as closed and select winners if required."""
        with transaction.atomic():
            if self.is_closed:
                return
            self.is_closed = True
            self.closed_at = timezone.now()  # Set closing time to current time.
            self.save(update_fields=['is_closed', 'closed_at'])
            
            
            if not self.winners_selected and self.winner_slots > 0:
                select_random_winners(self.id)


    def __str__(self):
        return f"{self.title} - {'Closed' if self.is_closed else 'Active'}"
    
    def specific_campaign(self):
        """Returns the campaign as its correct subclass."""
        if self.campaign_type == 'ticket':
            return TicketCampaign.objects.get(id=self.id)
        elif self.campaign_type == 'media_selling':
            return MediaSellingCampaign.objects.get(id=self.id)
        elif self.campaign_type == 'meet_greet':
            return MeetAndGreetCampaign.objects.get(id=self.id)
        return self  # If it's a base campaign


class TicketCampaign(Campaign):
    ticket_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_tickets = models.PositiveIntegerField()


class MediaSellingCampaign(Campaign):
    media_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_media = models.PositiveIntegerField()
    media_file = models.FileField(upload_to='campaign_media/', blank=True, null=True)


class MeetAndGreetCampaign(Campaign):
    ticket_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_tickets = models.PositiveIntegerField()


class Participation(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('credit_card', 'Credit Card'),
        ('paypal', 'PayPal'),
        ('bank_transfer', 'Bank Transfer'),
        ('balance', 'On-chain Balance'),
        ('wert', 'Wert'),
    ]

    fan = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participations"
    )
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="participations"
    )  # ✅ Linked to base campaign
    tickets_purchased = models.PositiveIntegerField(blank=True, null=True)  # ✅ Only for TicketCampaign & MeetAndGreetCampaign
    media_purchased = models.PositiveIntegerField(blank=True, null=True)  # ✅ Only for MediaSellingCampaign
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # For media selling campaigns, reduce available media count.
        if isinstance(self.campaign, MediaSellingCampaign):
            if self.media_purchased:
                self.campaign.total_media -= self.media_purchased
                self.campaign.save()

        # Save the participation first.
        super().save(*args, **kwargs)

        # --- Auto-close logic for ticket-based or meet & greet campaigns ---
        # Retrieve the specific subclass instance (e.g., TicketCampaign or MeetAndGreetCampaign)
        campaign_specific = self.campaign.specific_campaign()
        
        if campaign_specific.campaign_type in ['ticket', 'meet_greet'] and campaign_specific.auto_close_on_goal_met:
            total_sold = sum(p.tickets_purchased for p in campaign_specific.participations.all())
            if total_sold >= campaign_specific.total_tickets:
                # 1) close in DB
                campaign_specific.close_campaign()

                # 2) schedule the on-chain release in a batch
                seller_id = int(campaign_specific.user.user_id)
                def _dispatch():
                    release_all_holds_for_campaign_task.delay(campaign_specific.id, seller_id)
                transaction.on_commit(_dispatch)


class CampaignWinner(models.Model):
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="winners"
    )
    fan = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="won_campaigns"
    )
    selected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fan.username} won {self.campaign.title}"


class MediaFile(models.Model):
    campaign = models.ForeignKey(
        MediaSellingCampaign, on_delete=models.CASCADE, related_name="media_files"
    )
    file = models.FileField(upload_to='campaign_media/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Media for {self.campaign.title}"


class PurchasedMedia(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='purchased_media'
    )
    media_file = models.ForeignKey(
        'MediaFile',  # or from campaign.models import MediaFile if needed
        on_delete=models.CASCADE, 
        related_name='purchases'
    )
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'media_file')
    
    def __str__(self):
        return f"{self.user.username} purchased {self.media_file}"
    
    
class CreditSpend(models.Model):
    PARTICIPATION = 'participation'
    WITHDRAWAL    = 'withdrawal'
    GAS_FEE       = 'gas_fee'
    SPEND_TYPE_CHOICES = [
        (PARTICIPATION, 'Campaign Participation'),
        (WITHDRAWAL,    'Withdrawal'),
        (GAS_FEE,       'Gas Fee'),
    ]

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    campaign   = models.ForeignKey('campaign.Campaign', on_delete=models.CASCADE, null=True, blank=True)
    spend_type = models.CharField(max_length=32, choices=SPEND_TYPE_CHOICES)
    credits    = models.BigIntegerField(help_text="Credits burned")
    tt_amount  = models.BigIntegerField(help_text="Equivalent TT amount", null=True, blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.user} spent {self.credits} credits on {self.spend_type}"
    
    
class EscrowRecord(models.Model):
    STATUS = [
        ('held',     'Held'),
        ('released', 'Released'),
        ('refunded', 'Refunded'),
    ]
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    campaign   = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    onchain_campaign_id = models.CharField(max_length=64)   # the on-chain campaignId you passed
    tt_amount  = models.BigIntegerField()
    credit_amount = models.BigIntegerField()
    gas_cost_credits = models.BigIntegerField(default=0, help_text="Gas cost in credits")
    gas_cost_tt = models.BigIntegerField(default=0, help_text="Gas cost in TT")
    status     = models.CharField(max_length=10, choices=STATUS)
    tx_hash       = models.CharField(
        max_length=66,    # 0x + 64 hex chars 
        null=True,
        blank=True,
        help_text="On-chain transaction hash"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    task_id    = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery task ID for on-chain registration"
    )
