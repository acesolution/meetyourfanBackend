# sociallogins/admin.py
from django.contrib import admin
from .models import SocialProfile


@admin.register(SocialProfile)
class SocialProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "ig_username",
        "ig_user_id",
        "instagram_verified",
        "token_expires",
    )
    search_fields = (
        "user__email",
        "user__username",
        "ig_username",
        "ig_user_id",
    )
    list_filter = ("ig_token_expires_at",)

    def instagram_verified(self, obj):
        # use the @property on your model
        return obj.is_instagram_verified
    instagram_verified.boolean = True
    instagram_verified.short_description = "IG verified"

    def token_expires(self, obj):
        return obj.ig_token_expires_at
    token_expires.admin_order_field = "ig_token_expires_at"
