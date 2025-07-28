# blockchain/admin.py

from django.contrib import admin
from .models import (
    Transaction,
    BalanceSnapshot,
    InfluencerTransaction,
    OnChainAction,
)

# ── Transaction ──────────────────────────────────────────────────────────────
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'campaign',
        'tx_type',
        'tt_amount',
        'credits_delta',
        'status',
        'tx_hash',
        'block_number',
        'gas_used',
        'timestamp',
    )
    list_filter = (
        'tx_type',
        'status',
        'campaign',
    )
    search_fields = (
        'user__username',
        'user__email',
        'tx_hash',
    )
    readonly_fields = (
        'timestamp',
        'block_number',
        'transaction_index',
        'gas_used',
        'effective_gas_price',
        'from_address',
        'to_address',
        'value',
        'input_data',
    )
    raw_id_fields = (
        'user',
        'campaign',
    )
    ordering = ('-timestamp',)


# ── BalanceSnapshot ──────────────────────────────────────────────────────────
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


# ── InfluencerTransaction ────────────────────────────────────────────────────
@admin.register(InfluencerTransaction)
class InfluencerTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'influencer',
        'campaign',
        'transaction_type',
        'tt_amount',
        'credits_delta',
        'status',
        'tx_hash',
        'block_number',
        'gas_used',
        'timestamp',
    )
    list_filter = (
        'transaction_type',
        'status',
        'campaign',
    )
    search_fields = (
        'user__username',
        'influencer__username',
        'tx_hash',
    )
    readonly_fields = (
        'timestamp',
        'block_number',
        'transaction_index',
        'gas_used',
        'effective_gas_price',
        'from_address',
        'to_address',
        'value',
        'input_data',
    )
    raw_id_fields = (
        'user',
        'influencer',
        'campaign',
    )
    ordering = ('-timestamp',)


# ── OnChainAction ────────────────────────────────────────────────────────────
@admin.register(OnChainAction)
class OnChainActionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'event_type',
        'user',
        'campaign',
        'status',
        'tx_hash',
        'block_number',
        'timestamp',
    )
    list_filter = (
        'event_type',
        'status',
        'campaign',
    )
    search_fields = (
        'user__username',
        'tx_hash',
    )
    readonly_fields = (
        'timestamp',
        'block_number',
        'transaction_index',
        'gas_used',
        'effective_gas_price',
        'from_address',
        'to_address',
        'value',
        'input_data',
        'args',
    )
    raw_id_fields = (
        'user',
        'campaign',
    )
    ordering = ('-timestamp',)
