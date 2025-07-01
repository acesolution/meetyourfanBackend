# blockchain/admin.py

from django.contrib import admin
from .models import Transaction, BalanceSnapshot

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'tx_type',
        'tt_amount',
        'credits_delta',
        'email_verified',
        'phone_verified',
        'tx_hash',
        'timestamp',
    )
    list_filter = (
        'tx_type',
        'email_verified',
        'phone_verified',
    )
    search_fields = (
        'user__username',
        'user__email',
        'tx_hash',
    )
    readonly_fields = (
        'timestamp',
    )
    raw_id_fields = ('user',)
    ordering = ('-timestamp',)


@admin.register(BalanceSnapshot)
class BalanceSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'tt_balance',
        'credit_balance',
        'taken_at',
    )
    search_fields = (
        'user__username',
        'user__email',
    )
    readonly_fields = (
        'user',
        'tt_balance',
        'credit_balance',
        'taken_at',
    )
    raw_id_fields = ('user',)
    ordering = ('-taken_at',)
    date_hierarchy = 'taken_at'
