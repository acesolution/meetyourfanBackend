# notificationsapp/admin.py

from django.contrib import admin
from notificationsapp.models import Notification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'actor', 'recipient', 'verb', 'target_display', 'created_at', 'read')
    list_filter = ('read', 'created_at')
    search_fields = ('actor__username', 'recipient__username', 'verb')
    ordering = ('-created_at',)

    def target_display(self, obj):
        """
        Returns a string representation of the target object, if available.
        """
        return str(obj.target) if obj.target else '-'
    target_display.short_description = 'Target'
