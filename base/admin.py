from django.contrib import admin
from .models import Email

# Register the Email model with customization options
@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'created_at')  # Fields to display in list view
    search_fields = ('email',)  # Add search functionality by email
    list_filter = ('created_at',)  # Filter by creation date

    # Optional: Customize the ordering of displayed entries
    ordering = ('-created_at',)
