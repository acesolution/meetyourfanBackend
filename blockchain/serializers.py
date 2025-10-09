# blockchain/serializers.py

from rest_framework import serializers
from .models import Transaction, InfluencerTransaction, TransactionIssueReport, IssueAttachment

class BaseOnChainSerializer(serializers.ModelSerializer):
    campaign = serializers.SerializerMethodField()

    def get_campaign(self, obj):
        if not obj.campaign:
            return None
        c = obj.campaign
        data = {"id": c.id}
        if hasattr(c, "title"):
            data["title"] = c.title
        if hasattr(c, "slug"):
            data["slug"] = c.slug
        return data


class TransactionSerializer(BaseOnChainSerializer):
    class Meta:
        model = Transaction
        fields = [
            "id", "tx_hash", "tx_type", "tt_amount", "credits_delta",
            "status", "block_number", "transaction_index",
            "gas_used", "effective_gas_price",
            "from_address", "to_address", "value", "input_data",
            "timestamp", "campaign",
        ]


class InfluencerTransactionSerializer(BaseOnChainSerializer):
    class Meta:
        model = InfluencerTransaction
        fields = [
            "id", "tx_hash", "tx_type", "tt_amount", "credits_delta",
            "status", "block_number", "transaction_index",
            "gas_used", "effective_gas_price",
            "from_address", "to_address", "value", "input_data",
            "timestamp", "campaign","viewer_role", 
        ]
        
    def get_viewer_role(self, obj):
        request = self.context.get("request")
        # built-in getattr(): safe attribute access with default
        if request and getattr(request, "user", None):
            return "owner" if obj.influencer_id == request.user.id else "buyer"
        return None



class IssueAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueAttachment
        fields = ["id", "file"]

class TransactionInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "tx_hash", "credits_delta", "tt_amount", "status", "timestamp", "campaign"]

class InfluencerTransactionInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfluencerTransaction
        fields = ["id", "tx_hash", "credits_delta", "tt_amount", "status", "timestamp", "campaign"]

class TransactionIssueReportSerializer(serializers.ModelSerializer):
    attachments = IssueAttachmentSerializer(many=True, read_only=True)
    transaction = serializers.SerializerMethodField()

    class Meta:
        model = TransactionIssueReport
        fields = [
            "id",
            "user",
            "transaction_hash",
            "transaction",
            "description",
            "attachments",
            "created_at",
        ]
        read_only_fields = ["user", "created_at"]

    def get_transaction(self, obj):
        if not obj.content_type or not obj.object_id:
            return None
        model_cls = obj.content_type.model_class()
        try:
            instance = model_cls.objects.get(pk=obj.object_id)
        except Exception:
            return None

        if isinstance(instance, Transaction):
            return TransactionInlineSerializer(instance).data
        if isinstance(instance, InfluencerTransaction):
            return InfluencerTransactionInlineSerializer(instance).data
        return None