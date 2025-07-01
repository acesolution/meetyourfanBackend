from django.contrib import admin
from campaign.models import (
    Campaign, 
    TicketCampaign, 
    MediaSellingCampaign, 
    MeetAndGreetCampaign, 
    Participation, 
    CampaignWinner,
    MediaFile,  # <-- Added MediaFile
    PurchasedMedia,
    EscrowRecord,
    CreditSpend
)

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'title', 
        'campaign_type', 
        'user', 
        'deadline', 
        'is_closed', 
        'winners_selected', 
        'created_at', 
        'updated_at'
    )
    list_filter = ('campaign_type', 'is_closed', 'winners_selected', 'created_at')
    search_fields = ('title', 'user__username', 'user__email')
    ordering = ('-created_at',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user').prefetch_related('likes', 'participations')


@admin.register(TicketCampaign)
class TicketCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'title', 
        'ticket_cost', 
        'total_tickets', 
        'is_closed', 
        'winners_selected', 
        'created_at'
    )
    list_filter = ('is_closed', 'winners_selected', 'created_at')
    search_fields = ('title', 'user__username')
    ordering = ('-created_at',)


@admin.register(MediaSellingCampaign)
class MediaSellingCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'title', 
        'media_cost', 
        'total_media', 
        'is_closed', 
        'created_at'
    )
    list_filter = ('is_closed', 'created_at')
    search_fields = ('title', 'user__username')
    ordering = ('-created_at',)


@admin.register(MeetAndGreetCampaign)
class MeetAndGreetCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'title', 
        'ticket_cost', 
        'total_tickets', 
        'is_closed', 
        'created_at'
    )
    list_filter = ('is_closed', 'created_at')
    search_fields = ('title', 'user__username')
    ordering = ('-created_at',)


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'campaign', 
        'fan', 
        'tickets_purchased', 
        'media_purchased', 
        'payment_method', 
        'amount', 
        'created_at'
    )
    list_filter = ('payment_method', 'created_at')
    search_fields = ('campaign__title', 'fan__username', 'fan__email')
    ordering = ('-created_at',)


@admin.register(CampaignWinner)
class CampaignWinnerAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'campaign', 
        'fan', 
        'selected_at'
    )
    list_filter = ('selected_at',)
    search_fields = ('campaign__title', 'fan__username')
    ordering = ('-selected_at',)


@admin.register(MediaFile)
class MediaFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign', 'file', 'uploaded_at')
    list_filter = ('campaign', 'uploaded_at')
    search_fields = ('campaign__title',)


@admin.register(PurchasedMedia)
class PurchasedMediaAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'media_file', 'purchased_at')
    list_filter = ('purchased_at', 'user')
    search_fields = ('user__username', 'media_file__file')
    
    
    
@admin.register(EscrowRecord)
class EscrowRecordAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'campaign', 'campaign_id',
        'tt_amount', 'credit_amount', 'status', 'tx_hash', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'campaign_id', 'tx_hash')
    ordering = ('-created_at',)
    
    
@admin.register(CreditSpend)
class CreditSpendAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'campaign',
        'spend_type',
        'credits',
        'tt_amount',
        'description',
        'timestamp',
    )
    list_filter = ('spend_type', 'timestamp', 'user')
    search_fields = ('user__username', 'campaign__title', 'spend_type')
    ordering = ('-timestamp',)