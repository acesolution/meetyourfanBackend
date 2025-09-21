# messagesapp/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import (
    Conversation,
    Message,
    ConversationDeletion,
    UserMessagesReport,
    MeetupSchedule,
)


# ---------- Inlines ----------

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("created_at", "sender", "status", "short_content")
    readonly_fields = ("created_at", "sender", "status", "short_content")
    show_change_link = True

    def short_content(self, obj):
        txt = obj.content or ""
        return (txt[:80] + "…") if len(txt) > 80 else txt
    short_content.short_description = "Content"


class ConversationDeletionInline(admin.TabularInline):
    model = ConversationDeletion
    extra = 0
    fields = ("user", "deleted_at")
    readonly_fields = ("user", "deleted_at")


# ---------- Conversation ----------

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """
    Conversations:
    - Optimized queryset with prefetch to avoid N+1 on participants
    - Handy columns and filters
    - Read-only system fields (timestamps/signature)
    """
    list_display = (
        "id",
        "category",
        "created_by",
        "campaign_display",
        "participants_count",
        "participants_preview",
        "created_at",
        "updated_at",
    )
    list_filter = ("category", "created_at", "updated_at", "created_by")
    search_fields = (
        "participant_signature",
        "participants__username",
        "participants__profile__name",
        "campaign__title",
    )
    ordering = ("-updated_at",)
    date_hierarchy = "created_at"
    raw_id_fields = ("participants", "created_by", "campaign")
    filter_horizontal = ()  # keep empty to avoid rendering a huge M2M selector
    inlines = (MessageInline, ConversationDeletionInline)
    readonly_fields = ("created_at", "updated_at", "participant_signature")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("created_by", "campaign").prefetch_related("participants")

    def participants_count(self, obj):
        return obj.participants.count()
    participants_count.short_description = "Members"
    participants_count.admin_order_field = "id"  # harmless fallback

    def participants_preview(self, obj):
        users = list(obj.participants.all()[:4])
        names = [getattr(u, "username", "user") for u in users]
        more = obj.participants.count() - len(users)
        tail = f" +{more}" if more > 0 else ""
        return ", ".join(names) + tail
    participants_preview.short_description = "Participants"

    def campaign_display(self, obj):
        if not obj.campaign_id:
            return "-"
        # Show title if available (avoids admin URL reverse dependency)
        title = getattr(obj.campaign, "title", f"Campaign #{obj.campaign_id}")
        return title
    campaign_display.short_description = "Campaign"


# ---------- Message ----------

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation_link",
        "sender",
        "status",
        "created_at_local",
        "preview",
    )
    list_filter = ("status", "created_at", "conversation__category")
    search_fields = ("content", "sender__username", "sender__profile__name")
    ordering = ("-id",)
    date_hierarchy = "created_at"
    raw_id_fields = ("conversation", "sender")
    list_select_related = ("conversation", "sender")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("conversation", "sender")

    def conversation_link(self, obj):
        return f"{obj.conversation_id} ({obj.conversation.category})"
    conversation_link.short_description = "Conversation"

    def created_at_local(self, obj):
        return localtime(obj.created_at).strftime("%Y-%m-%d %H:%M")
    created_at_local.short_description = "Created (local)"

    def preview(self, obj):
        txt = obj.content or ""
        return (txt[:80] + "…") if len(txt) > 80 else txt
    preview.short_description = "Content Preview"


# ---------- ConversationDeletion ----------

@admin.register(ConversationDeletion)
class ConversationDeletionAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "user", "deleted_at_local")
    list_filter = ("deleted_at",)
    search_fields = ("user__username", "conversation__participant_signature")
    raw_id_fields = ("conversation", "user")
    date_hierarchy = "deleted_at"
    ordering = ("-deleted_at",)

    def deleted_at_local(self, obj):
        return localtime(obj.deleted_at).strftime("%Y-%m-%d %H:%M")
    deleted_at_local.short_description = "Deleted (local)"


# ---------- UserMessagesReport ----------

@admin.register(UserMessagesReport)
class UserMessagesReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "reporter",
        "reported_user",
        "conversation",
        "reason",
        "created_at_local",
        "short_text",
    )
    list_filter = ("reason", "created_at")
    search_fields = (
        "reporter__username",
        "reported_user__username",
        "conversation__participant_signature",
        "text",
    )
    raw_id_fields = ("reporter", "reported_user", "conversation")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def created_at_local(self, obj):
        return localtime(obj.created_at).strftime("%Y-%m-%d %H:%M")
    created_at_local.short_description = "Created (local)"

    def short_text(self, obj):
        t = obj.text or ""
        return (t[:80] + "…") if len(t) > 80 else t
    short_text.short_description = "Details"


# ---------- MeetupSchedule ----------

@admin.action(description="Mark selected meetups as ACCEPTED")
def accept_meetups(modeladmin, request, queryset):
    updated = queryset.filter(status="pending").update(status="accepted")
    modeladmin.message_user(request, f"{updated} meetup(s) marked as accepted.")

@admin.action(description="Reject & DELETE selected pending meetups")
def reject_and_delete_meetups(modeladmin, request, queryset):
    qs = queryset.filter(status="pending")
    count = qs.count()
    qs.delete()
    modeladmin.message_user(request, f"{count} pending meetup(s) rejected and deleted.")


@admin.register(MeetupSchedule)
class MeetupScheduleAdmin(admin.ModelAdmin):
    """
    Meetups:
    - Enforces your business rules via actions matching API behavior:
      * Accept → keep row
      * Reject → delete row
    - Rich filters & search to find collisions quickly
    """
    list_display = (
        "id",
        "campaign_display",
        "influencer",
        "winner",
        "scheduled_local",
        "location_short",
        "status",
        "created_at_local",
        "updated_at_local",
    )
    list_filter = (
        "status",
        ("campaign", admin.RelatedOnlyFieldListFilter),
        ("influencer", admin.RelatedOnlyFieldListFilter),
        ("winner", admin.RelatedOnlyFieldListFilter),
        "scheduled_datetime",
        "created_at",
    )
    search_fields = (
        "campaign__title",
        "influencer__username",
        "influencer__profile__name",
        "winner__username",
        "winner__profile__name",
        "location",
    )
    raw_id_fields = ("campaign", "influencer", "winner")
    date_hierarchy = "scheduled_datetime"
    ordering = ("-scheduled_datetime", "-id")
    actions = (accept_meetups, reject_and_delete_meetups)
    list_select_related = ("campaign", "influencer", "winner")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("campaign", "influencer", "winner")

    def campaign_display(self, obj):
        if not obj.campaign_id:
            return "-"
        title = getattr(obj.campaign, "title", f"Campaign #{obj.campaign_id}")
        return title
    campaign_display.short_description = "Campaign"

    def scheduled_local(self, obj):
        return localtime(obj.scheduled_datetime).strftime("%Y-%m-%d %H:%M")
    scheduled_local.short_description = "Scheduled (local)"

    def created_at_local(self, obj):
        return localtime(obj.created_at).strftime("%Y-%m-%d %H:%M")
    created_at_local.short_description = "Created (local)"

    def updated_at_local(self, obj):
        return localtime(obj.updated_at).strftime("%Y-%m-%d %H:%M")
    updated_at_local.short_description = "Updated (local)"

    def location_short(self, obj):
        loc = obj.location or ""
        return (loc[:40] + "…") if len(loc) > 40 else loc
    location_short.short_description = "Location"
