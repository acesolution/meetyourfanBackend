# messagesapp/admin.py
from django.contrib import admin
from messagesapp.models import Conversation, Message

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'participant_list', 'created_at', 'updated_at')
    search_fields = ('participants__username',)
    list_filter = ('created_at', 'updated_at')

    def participant_list(self, obj):
        # Display participants' usernames, separated by commas
        return ", ".join([user.username for user in obj.participants.all()])
    participant_list.short_description = "Participants"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation_id', 'sender', 'created_at', 'preview')
    search_fields = ('sender__username', 'content')
    list_filter = ('created_at',)

    def conversation_id(self, obj):
        return obj.conversation.id
    conversation_id.short_description = "Conversation ID"

    def preview(self, obj):
        return obj.content[:50] + ("..." if len(obj.content) > 50 else "")
    preview.short_description = "Content Preview"
