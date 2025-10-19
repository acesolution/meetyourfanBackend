# blockchain/models.py

from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

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
        decimal_places=2,
        help_text="Raw TT units moved on‑chain"
    )
    credits_delta = models.DecimalField(
        max_digits=30,
        decimal_places=2,
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
    # (optional but recommended) exact on-chain integers for audit/recalc
    tt_amount_wei     = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)
    credits_delta_wei = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)

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
    
    tx_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        help_text="on_hold / release / refund"
    )
    tt_amount     = models.DecimalField(
        max_digits=30,
        decimal_places=2,
        help_text="Raw TT units moved"
    )
    credits_delta = models.DecimalField(
        max_digits=30,
        decimal_places=2,
        help_text="+ credits for release, − for hold/refund"
    )
    
    # (optional but recommended) exact on-chain integers for audit/recalc
    tt_amount_wei     = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)
    credits_delta_wei = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)

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

    tx_type   = models.CharField(
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
    
    
class TransactionIssueReport(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    transaction_hash = models.CharField(max_length=100, blank=True)  # keep for convenience / indexing
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=255, null=True, blank=True)
    transaction = GenericForeignKey("content_type", "object_id")
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"IssueReport for {self.transaction_hash} by {self.user}"

class IssueAttachment(models.Model):
    report = models.ForeignKey(TransactionIssueReport, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="issue_reports/%Y/%m/")
    
    
class GuestOrder(models.Model):
    class Status(models.TextChoices):
        CREATED   = "created",   "Created"
        PENDING   = "pending",   "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED    = "failed",    "Failed"
        CLAIMED   = "claimed",   "Claimed"

    click_id   = models.UUIDField(unique=True)
    ref        = models.CharField(max_length=66)  # 0x... keccak(click_id)
    email      = models.EmailField(null=True, blank=True)
    status     = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREATED,
    )
    amount         = models.DecimalField(max_digits=78, decimal_places=0)
    token_decimals = models.IntegerField(default=18)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    campaign   = models.ForeignKey('campaign.Campaign', null=True, blank=True, on_delete=models.SET_NULL)
    entries    = models.IntegerField(null=True, blank=True)
    order_id   = models.CharField(max_length=64, null=True, blank=True)
    tx_hash    = models.CharField(max_length=66, null=True, blank=True)

# --- WERT INTEGRATION MODELS ---

class WertOrder(models.Model):
    STATUS_CHOICES = [
        ("created", "Created"),     # when widget config returned
        ("pending", "Pending"),     # webhook “payment.pending”
        ("confirmed", "Confirmed"), # webhook “payment.confirmed”
        ("failed", "Failed"),       # webhook “payment.failed”
        ("claimed", "Claimed"),     # after claimPending on-chain (optional)
    ]
    order_id      = models.CharField(max_length=80, unique=True, null=True, blank=True)
    click_id      = models.CharField(max_length=80, db_index=True, null=True, blank=True)
    ref           = models.CharField(max_length=66, db_index=True, null=True, blank=True)  # 0x… keccak(click_id)
    status        = models.CharField(max_length=16, choices=STATUS_CHOICES, default="created")

    # amounts: keep both if helpful (fiat for reconciliation; token wei for exactness)
    fiat_currency = models.CharField(max_length=8, null=True, blank=True)
    fiat_amount   = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    token_symbol  = models.CharField(max_length=16, null=True, blank=True)  # e.g., TT
    token_network = models.CharField(max_length=16, null=True, blank=True)  # e.g., bsc
    token_amount_wei = models.DecimalField(max_digits=78, decimal_places=0, null=True, blank=True)

    tx_id         = models.CharField(max_length=66, null=True, blank=True)  # chain tx hash
    raw           = models.JSONField(null=True, blank=True)                 # last webhook/API payload

    # helpful joins for your flow (optional)
    user          = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    campaign      = models.ForeignKey('campaign.Campaign', null=True, blank=True, on_delete=models.SET_NULL)
    entries       = models.IntegerField(null=True, blank=True)

    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["updated_at"])]

    def __str__(self):
        return f"{self.order_id or self.click_id} [{self.status}]"


class WertSyncCursor(models.Model):
    name          = models.CharField(max_length=32, unique=True, default="default")
    last_synced_at= models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"WertSyncCursor({self.name}) @ {self.last_synced_at}"
