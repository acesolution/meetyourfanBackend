# blockchain/serializers.py

from rest_framework import serializers
from .models import Transaction, InfluencerTransaction

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
            "timestamp", "campaign",
        ]
