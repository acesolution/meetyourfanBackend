from django.contrib import admin
from .models import CustomUser, VerificationCode, Profile, SocialMediaLink, ReportGenericIssue

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'date_of_birth', 'created_at', 'updated_at', 'status')
    search_fields = ('user__username', 'user__email',)
    list_filter = ('created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Profile Details', {
            'fields': ('name', 'date_of_birth', 'bio', 'profile_picture', 'cover_photo', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'phone_number', 'is_staff', 'is_active', 'user_id')
    search_fields = ('username', 'email', 'phone_number')
    list_filter = ('is_staff', 'is_active')
    ordering = ('email',)
    
    readonly_fields = ('user_id',)
    
    
    
@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'email_code', 'email_verified', 'email_sent_at',
        'phone_code', 'phone_verified', 'phone_sent_at',
        'withdraw_email_code', 'withdraw_email_verified', 'withdraw_email_sent_at',
        'withdraw_phone_code', 'withdraw_phone_verified', 'withdraw_phone_sent_at',
        'created_at', 'expires_at', 'withdraw_expires_at',
    )
    search_fields = ('user__username', 'user__email',)
    list_filter   = ('email_verified', 'phone_verified',)
    readonly_fields = (
        'created_at',
        'expires_at',
        'withdraw_expires_at',
        # you can also make the “sent_at” timestamps read-only if you like:
        'email_sent_at',
        'phone_sent_at',
        'withdraw_email_sent_at',
        'withdraw_phone_sent_at',
    )

    fieldsets = (
        (None, {
            'fields': ('user',)
        }),
        ('Email Verification', {
            'fields': (
                'email_code',
                'email_verified',
                'email_sent_at',
            )
        }),
        ('Phone Verification', {
            'fields': (
                'phone_code',
                'phone_verified',
                'phone_sent_at',
            )
        }),
        ('Withdrawal via Email', {
            'fields': (
                'withdraw_email_code',
                'withdraw_email_verified',
                'withdraw_email_sent_at',
            )
        }),
        ('Withdrawal via Phone', {
            'fields': (
                'withdraw_phone_code',
                'withdraw_phone_verified',
                'withdraw_phone_sent_at',
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'expires_at',
                'withdraw_expires_at',
            )
        }),
    )

    
@admin.register(SocialMediaLink)
class SocialMediaLinkAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'url', 'created_at', 'updated_at')
    search_fields = ('user__username', 'platform',)
    list_filter = ('platform', 'created_at')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(ReportGenericIssue)
class ReportGenericIssueAdmin(admin.ModelAdmin):
    list_display = ('user', 'issue_category', 'created_at')
    search_fields = ('user__username', 'issue_category', 'details')
    list_filter = ('issue_category', 'created_at')



