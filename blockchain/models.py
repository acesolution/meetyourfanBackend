# blockchain/models.py

from django.db import models
from django.conf import settings

class OnChainBase(models.Model):
    """
    Abstract base capturing:
      - user/campaign linkage
      - mining status + raw tx hash
      - full on‑chain metadata once mined
      - timestamp of record creation
    """
    PENDING   = 'pending'
    COMPLETED = 'completed'
    FAILED    = 'failed'
    STATUS_CHOICES = [
        (PENDING,   'Pending'),
        (COMPLETED, 'Completed'),
        (FAILED,    'Failed'),
    ]

    # ─── Shared linkage ────────────────────────────────────────────────────────
    user      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        help_text="Who initiated this on‑chain TX"
    )
    campaign  = models.ForeignKey(
        'campaign.Campaign',  # string reference avoids the import cycle
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text="Optional campaign FK"
    )

    # ─── Core on‑chain fields ─────────────────────────────────────────────────
    status    = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=PENDING,
        help_text="Pending until mined → completed/failed"
    )
    tx_hash   = models.CharField(
        max_length=66, blank=True, null=True,
        help_text="On‑chain tx hash"
    )

    # ─── Enhanced metadata ─────────────────────────────────────────────────────
    block_number        = models.BigIntegerField(
        null=True, blank=True,
        help_text="Block number in which tx was mined"
    )
    transaction_index   = models.IntegerField(
        null=True, blank=True,
        help_text="Index of tx within its block"
    )
    gas_used            = models.BigIntegerField(
        null=True, blank=True,
        help_text="Actual gas used"
    )
    effective_gas_price = models.BigIntegerField(
        null=True, blank=True,
        help_text="EIP‑1559 effective gas price"
    )
    from_address        = models.CharField(
        max_length=42, null=True, blank=True,
        help_text="EOA that sent this tx"
    )
    to_address          = models.CharField(
        max_length=42, null=True, blank=True,
        help_text="Contract or EOA receiver"
    )
    value               = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True,
        help_text="Wei value sent"
    )
    input_data          = models.TextField(
        null=True, blank=True,
        help_text="Raw input data (hex)"
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this DB record was created"
        # built‑in: auto_now_add stamps current datetime on first save
    )

    class Meta:
        abstract = True

class BalanceSnapshot(models.Model):
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tt_balance     = models.DecimalField(max_digits=30, decimal_places=0)
    credit_balance = models.DecimalField(max_digits=30, decimal_places=0)
    taken_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-taken_at']
        get_latest_by = 'taken_at'

class Transaction(OnChainBase):
    DEPOSIT  = 'deposit'
    WITHDRAW = 'withdraw'
    SPEND    = 'spend'
    TX_TYPES = [
        (DEPOSIT,  'Deposit'),
        (WITHDRAW, 'Withdrawal'),
        (SPEND,    'Spend'),
    ]

    
    tx_type       = models.CharField(
        max_length=66,
        choices=TX_TYPES,
        help_text="deposit/withdraw/spend"
    )
    tt_amount     = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        help_text="Raw TT units moved on‑chain"
    )
    credits_delta = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        help_text="+ for mint/deposit, – for burn/spend"
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="If buyer’s email was verified at time of TX"
    )
    phone_verified = models.BooleanField(
        default=False,
        help_text="If buyer’s phone was verified at time of TX"
    )

    class Meta(OnChainBase.Meta):
        ordering = ['-timestamp']

class InfluencerTransaction(OnChainBase):
    ON_HOLD = 'on_hold'
    RELEASE = 'release'
    REFUND  = 'refund'
    TYPE_CHOICES = [
        (ON_HOLD, 'On Hold'),
        (RELEASE, 'Release'),
        (REFUND,  'Refund'),
    ]

    influencer    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='influencer_txs',
        on_delete=models.CASCADE,
        help_text="Campaign owner receiving or tied to these funds"
    )
    
    transaction_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        help_text="on_hold / release / refund"
    )
    tt_amount     = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        help_text="Raw TT units moved"
    )
    credits_delta = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        help_text="+ credits for release, − for hold/refund"
    )

    class Meta(OnChainBase.Meta):
        ordering = ['-timestamp']

class OnChainAction(OnChainBase):
    USER_REGISTERED     = 'user_registered'
    CAMPAIGN_REGISTERED = 'campaign_registered'
    OTHER_OPERATION     = 'other'
    EVENT_CHOICES = [
        (USER_REGISTERED,     'User Registered'),
        (CAMPAIGN_REGISTERED, 'Campaign Registered'),
        (OTHER_OPERATION,     'Other Operation'),
    ]

    event_type   = models.CharField(
        max_length=32,
        choices=EVENT_CHOICES,
        help_text="Which non‑monetary event occurred"
    )
    
    args         = models.JSONField(
        null=True,
        blank=True,
        help_text="Decoded event parameters"
        # built‑in: JSONField serializes Python dict ↔ JSON automatically
    )

    class Meta(OnChainBase.Meta):
        ordering = ['-timestamp']

class ConversionRate(models.Model):
    # We store the raw Wei integer; if you want decimals, change field type
    rate_wei   = models.BigIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # ensure only one row
        verbose_name = "Conversion Rate"
        verbose_name_plural = "Conversion Rate"

    def __str__(self):
        return f"{self.rate_wei} Wei @ {self.updated_at}"