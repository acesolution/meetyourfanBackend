# api/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin  # Django built-in admin for AbstractUser
from django.utils.html import format_html        # format_html: Django built-in safe HTML builder
from django.utils.translation import gettext_lazy as _  # _(): i18n helper (Django built-in)

from .models import (
    CustomUser,
    Profile,
    VerificationCode,
    SocialMediaLink,
    ReportGenericIssue,
    UsernameResetToken,
    DeletedAccount,
)

# ──────────────────────────────────────────────────────────────────────────────
# CustomUser admin (best: extend UserAdmin so permissions/groups/etc just work)
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    UserAdmin: Django built-in — provides a full-featured admin for user models.
    We extend it to add your custom fields (user_type, phone_number, wallet_address, user_id).
    """
    model = CustomUser

    list_display = (
        "id",
        "email",
        "username",
        "user_type",
        "phone_number",
        "wallet_address",
        "is_staff",
        "is_active",
        "user_id",
        "date_joined",
        "last_login",
    )
    list_filter = ("user_type", "is_staff", "is_active", "is_superuser", "groups")
    search_fields = ("email", "username", "phone_number", "wallet_address", "user_id")
    ordering = ("email",)

    readonly_fields = ("user_id", "last_login", "date_joined")

    # fieldsets: Django admin built-in — controls layout of fields on the change page
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("username", "first_name", "last_name", "phone_number")}),
        (_("MYF Details"), {"fields": ("user_type", "wallet_address", "user_id")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # add_fieldsets: Django admin built-in — controls fields when creating user in admin
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "user_type", "phone_number", "password1", "password2", "is_staff", "is_active"),
        }),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Profile admin
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "name",
        "status",
        "instagram_verified",
        "is_online",
        "last_seen",
        "created_at",
        "updated_at",
    )
    search_fields = ("user__email", "user__username", "name")
    list_filter = ("status", "instagram_verified", "is_online", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    # Optional: small preview thumbnails in admin
    def profile_picture_thumb(self, obj):
        url = getattr(obj.profile_picture, "url", None)  # getattr: Python built-in — safe attribute read
        if not url:
            return "-"
        return format_html('<img src="{}" style="height:40px;width:40px;object-fit:cover;border-radius:8px;" />', url)

    profile_picture_thumb.short_description = "Avatar"  # admin label

    def cover_photo_thumb(self, obj):
        url = getattr(obj.cover_photo, "url", None)
        if not url:
            return "-"
        return format_html('<img src="{}" style="height:40px;width:80px;object-fit:cover;border-radius:8px;" />', url)

    cover_photo_thumb.short_description = "Cover"

    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Profile", {"fields": (
            "name",
            "date_of_birth",
            "bio",
            "status",
            "instagram_verified",
            "profile_picture",
            "cover_photo",
            "cover_focal_x",
            "cover_focal_y",
        )}),
        ("Presence", {"fields": ("is_online", "last_seen")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

# ──────────────────────────────────────────────────────────────────────────────
# VerificationCode admin
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "email_code",
        "email_verified",
        "email_sent_at",
        "phone_code",
        "phone_verified",
        "phone_sent_at",
        "withdraw_email_code",
        "withdraw_email_verified",
        "withdraw_email_sent_at",
        "withdraw_phone_code",
        "withdraw_phone_verified",
        "withdraw_phone_sent_at",
        "created_at",
        "expires_at",
        "withdraw_expires_at",
    )
    search_fields = ("user__email", "user__username")
    list_filter = ("email_verified", "phone_verified", "withdraw_email_verified", "withdraw_phone_verified")
    readonly_fields = (
        "created_at",
        "expires_at",
        "withdraw_expires_at",
        "email_sent_at",
        "phone_sent_at",
        "withdraw_email_sent_at",
        "withdraw_phone_sent_at",
    )

    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Email Verification", {"fields": ("email_code", "email_verified", "email_sent_at")}),
        ("Phone Verification", {"fields": ("phone_code", "phone_verified", "phone_sent_at")}),
        ("Withdrawal via Email", {"fields": ("withdraw_email_code", "withdraw_email_verified", "withdraw_email_sent_at")}),
        ("Withdrawal via Phone", {"fields": ("withdraw_phone_code", "withdraw_phone_verified", "withdraw_phone_sent_at")}),
        ("Timestamps", {"fields": ("created_at", "expires_at", "withdraw_expires_at")}),
    )

# ──────────────────────────────────────────────────────────────────────────────
# SocialMediaLink admin
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(SocialMediaLink)
class SocialMediaLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "url", "created_at", "updated_at")
    search_fields = ("user__email", "user__username", "platform", "url")
    list_filter = ("platform", "created_at")
    readonly_fields = ("created_at", "updated_at")

# ──────────────────────────────────────────────────────────────────────────────
# Generic issue reports
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(ReportGenericIssue)
class ReportGenericIssueAdmin(admin.ModelAdmin):
    list_display = ("user", "issue_category", "created_at")
    search_fields = ("user__email", "user__username", "issue_category", "details")
    list_filter = ("issue_category", "created_at")

# ──────────────────────────────────────────────────────────────────────────────
# Username reset tokens
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(UsernameResetToken)
class UsernameResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "used", "created_at")
    search_fields = ("user__email", "user__username", "token")
    list_filter = ("used", "created_at")
    readonly_fields = ("created_at",)

# ──────────────────────────────────────────────────────────────────────────────
# Deleted accounts snapshot (audit/support)
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(DeletedAccount)
class DeletedAccountAdmin(admin.ModelAdmin):
    list_display = ("deleted_at", "email", "username", "user_type", "user_id", "user_pk", "reason")
    search_fields = ("email", "username", "user_id", "reason")
    list_filter = ("user_type", "deleted_at")
    readonly_fields = ("deleted_at", "user_pk", "user_id", "username", "email", "user_type", "name", "reason")

    # Make it immutable in admin (optional safety)
    def has_add_permission(self, request):
        return False  # Django admin built-in permission hook

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
