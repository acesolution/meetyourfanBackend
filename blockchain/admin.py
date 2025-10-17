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
    GuestOrder,
    TransactionIssueReport,
    IssueAttachment,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

class ReadOnlyCreatedUpdatedMixin:
    readonly_fields = getattr(admin.ModelAdmin, "readonly_fields", tuple()) + (
        "created_at",
        "updated_at",
    )

# ─────────────────────────────────────────────────────────────────────────────
# Transactions
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "campaign",
        "tx_type",
        "tt_amount",
        "credits_delta",
        "status",
        "tx_hash",
        "block_number",
        "gas_used",
        "timestamp",
    )
    list_filter = ("tx_type", "status", "campaign")
    search_fields = ("user__username", "user__email", "tx_hash")
    readonly_fields = (
        "timestamp",
        "block_number",
        "transaction_index",
        "gas_used",
        "effective_gas_price",
        "from_address",
        "to_address",
        "value",
        "input_data",
        "tt_amount_wei",
        "credits_delta_wei",
    )
    raw_id_fields = ("user", "campaign")
    ordering = ("-timestamp",)
    list_per_page = 50


@admin.register(BalanceSnapshot)
class BalanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "tt_balance", "credit_balance", "taken_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user", "tt_balance", "credit_balance", "taken_at")
    raw_id_fields = ("user",)
    ordering = ("-taken_at",)
    date_hierarchy = "taken_at"
    list_per_page = 50


@admin.register(InfluencerTransaction)
class InfluencerTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "influencer",
        "campaign",
        "tx_type",
        "tt_amount",
        "credits_delta",
        "status",
        "tx_hash",
        "block_number",
        "gas_used",
        "timestamp",
    )
    list_filter = ("tx_type", "status", "campaign")
    search_fields = ("user__username", "influencer__username", "tx_hash")
    readonly_fields = (
        "timestamp",
        "block_number",
        "transaction_index",
        "gas_used",
        "effective_gas_price",
        "from_address",
        "to_address",
        "value",
        "input_data",
        "tt_amount_wei",
        "credits_delta_wei",
    )
    raw_id_fields = ("user", "influencer", "campaign")
    ordering = ("-timestamp",)
    list_per_page = 50


@admin.register(OnChainAction)
class OnChainActionAdmin(admin.ModelAdmin):
    list_display = ("id", "tx_type", "user", "campaign", "status", "tx_hash", "block_number", "timestamp")
    list_filter = ("tx_type", "status", "campaign")
    search_fields = ("user__username", "tx_hash")
    readonly_fields = (
        "timestamp",
        "block_number",
        "transaction_index",
        "gas_used",
        "effective_gas_price",
        "from_address",
        "to_address",
        "value",
        "input_data",
        "args",
    )
    raw_id_fields = ("user", "campaign")
    ordering = ("-timestamp",)
    list_per_page = 50

# ─────────────────────────────────────────────────────────────────────────────
# Conversion rate (singleton)
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(ConversionRate)
class ConversionRateAdmin(admin.ModelAdmin):
    list_display = ("id", "rate_wei", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not ConversionRate.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

# ─────────────────────────────────────────────────────────────────────────────
# Wert webhook & sync models
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(WertOrder)
class WertOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_id",
        "click_id",
        "status",
        "fiat_currency",
        "fiat_amount",
        "token_symbol",
        "token_network",
        "token_amount_wei",
        "tx_id",
        "updated_at",
    )
    list_filter = ("status", "token_symbol", "token_network", "fiat_currency")
    search_fields = ("order_id", "click_id", "tx_id", "ref", "user__username", "user__email")
    raw_id_fields = ("user", "campaign")
    readonly_fields = ("raw", "created_at", "updated_at")
    ordering = ("-updated_at",)
    date_hierarchy = "updated_at"
    list_per_page = 50
    fieldsets = (
        ("Identifiers", {"fields": ("order_id", "click_id", "ref", "status")}),
        ("Joins", {"fields": ("user", "campaign", "entries")}),
        ("Amounts", {"fields": ("fiat_currency", "fiat_amount", "token_symbol", "token_network", "token_amount_wei")}),
        ("Chain", {"fields": ("tx_id",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
        ("Raw Payload (read-only)", {"classes": ("collapse",), "fields": ("raw",)}),
    )


@admin.register(WertSyncCursor)
class WertSyncCursorAdmin(admin.ModelAdmin):
    list_display = ("name", "last_synced_at")
    search_fields = ("name",)
    ordering = ("name",)

# ─────────────────────────────────────────────────────────────────────────────
# Guest orders (pre-Wert flow / guest checkout)
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(GuestOrder)
class GuestOrderAdmin(admin.ModelAdmin):
    list_display = ("click_id", "status", "amount", "token_decimals", "user", "campaign", "entries", "order_id", "tx_hash")
    list_filter = ("status",)
    search_fields = ("ref", "click_id", "order_id", "tx_hash", "user__username", "user__email")
    raw_id_fields = ("user", "campaign")
    list_per_page = 50
    ordering = ("-order_id",)

# ─────────────────────────────────────────────────────────────────────────────
# Issue reports + attachments
# ─────────────────────────────────────────────────────────────────────────────

class IssueAttachmentInline(admin.TabularInline):
    model = IssueAttachment
    extra = 0
    fields = ("file",)
    can_delete = True


@admin.register(TransactionIssueReport)
class TransactionIssueReportAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "transaction_hash", "content_type", "object_id", "created_at")
    search_fields = ("transaction_hash", "user__username", "user__email", "object_id")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    inlines = [IssueAttachmentInline]
    ordering = ("-created_at",)
