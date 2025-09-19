# profileapp/admin.py

from django.contrib import admin
from profileapp.models import BlockedUsers, Follower, FollowRequest, UserReport

@admin.register(BlockedUsers)
class BlockedUsersAdmin(admin.ModelAdmin):
    list_display = ('id', 'blocker', 'blocked', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('blocker__username', 'blocked__username')
    ordering = ('-created_at',)

@admin.register(Follower)
class FollowerAdmin(admin.ModelAdmin):
    list_display = ('id', 'follower', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('follower__username', 'user__username')
    ordering = ('-created_at',)

@admin.register(FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('sender__username', 'receiver__username', 'status')
    ordering = ('-created_at',)

@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'reported', 'category', 'created_at')
    list_filter = ('category', 'created_at')
    search_fields = ('reporter__username', 'reported__username', 'category')
    ordering = ('-created_at',)
