# blockchain/apps.py

from django.apps import AppConfig

class BlockchainConfig(AppConfig):
    name = 'blockchain'
    def ready(self):
        import blockchain.signals  # noqa
