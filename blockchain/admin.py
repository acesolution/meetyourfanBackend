# blockchain/admin.py

from django.contrib import admin
from .models import (
    Transaction,
    BalanceSnapshot,
    InfluencerTransaction,
    OnChainAction,
    ConversionRate,
    WertSyncCursor,
    WertOrder,
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
        'tx_type',
        'user',
        'campaign',
        'status',
        'tx_hash',
        'block_number',
        'timestamp',
    )
    list_filter = (
        'tx_type',
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



# ── ConversionRate (singleton) ───────────────────────────────────────────────
@admin.register(ConversionRate)
class ConversionRateAdmin(admin.ModelAdmin):
    list_display = ('id', 'rate_wei', 'updated_at')
    readonly_fields = ('updated_at',)  # updated_at is maintained automatically
    # built-in: prevent creating more than one row (singleton pattern)
    def has_add_permission(self, request):
        if ConversionRate.objects.exists():
            return False
        return super().has_add_permission(request)

    # built-in: disable deletion so the singleton stays present
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WertOrder)
class WertOrderAdmin(admin.ModelAdmin):
    list_display  = ("order_id","click_id","status","fiat_amount","token_symbol","token_amount_wei","tx_id","updated_at")
    list_filter   = ("status","token_symbol","token_network")
    search_fields = ("order_id","click_id","tx_id","ref")

admin.site.register(WertSyncCursor)