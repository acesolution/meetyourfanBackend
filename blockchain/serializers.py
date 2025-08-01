# blockchain/serializers.py

from rest_framework import serializers
from .models import Transaction, InfluencerTransaction

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'tx_hash', 'tx_type', 'tt_amount', 'credits_delta',
            'status', 'block_number', 'transaction_index',
            'gas_used', 'effective_gas_price',
            'from_address', 'to_address', 'value', 'input_data',
            'timestamp',
        ]

class InfluencerTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfluencerTransaction
        fields = [
            'id', 'tx_hash', 'tx_type', 'tt_amount', 'credits_delta',
            'status', 'block_number', 'transaction_index',
            'gas_used', 'effective_gas_price',
            'from_address', 'to_address', 'value', 'input_data',
            'timestamp',
        ]
