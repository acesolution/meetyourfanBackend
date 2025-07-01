# blockchain/models.py

from django.db import models
from django.conf import settings

class Transaction(models.Model):
    DEPOSIT    = 'deposit'
    WITHDRAW   = 'withdraw'
    SPEND      = 'spend'     # e.g. spent credits in‐platform
    TX_TYPES   = [(DEPOSIT,'Deposit'), (WITHDRAW,'Withdrawal'), (SPEND,'Spend')]

    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tx_type       = models.CharField(max_length=10, choices=TX_TYPES)
    tt_amount     = models.DecimalField(max_digits=30, decimal_places=0)  # raw TT units
    credits_delta = models.DecimalField(max_digits=30, decimal_places=0)  # + for mint, – for burn/spend
    tx_hash       = models.CharField(max_length=66, blank=True, null=True)
    timestamp     = models.DateTimeField(auto_now_add=True)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-timestamp']


class BalanceSnapshot(models.Model):
    user           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tt_balance     = models.DecimalField(max_digits=30, decimal_places=0)
    credit_balance = models.DecimalField(max_digits=30, decimal_places=0)
    taken_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-taken_at']
        get_latest_by = 'taken_at'
