# blockchain/management/commands/watch_rate.py
import time
from django.core.management.base import BaseCommand
from web3 import Web3
from meetyourfanBackend.settings import WEB3_PROVIDER_URL, CONTRACT_ADDRESS, CONTRACT_ABI
from blockchain.models import ConversionRate

class Command(BaseCommand):
    help = "Watch for ConversionRateChanged events and update the database."

    def handle(self, *args, **opts):
        w3 = Web3(Web3.WebsocketProvider(WEB3_PROVIDER_URL))
        contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

        # built‑in: createFilter(fromBlock="latest") watches only new logs
        event_filter = contract.events.ConversionRateUpdated.createFilter(fromBlock="latest")

        self.stdout.write("Listening for ConversionRateChanged…")
        while True:
            for ev in event_filter.get_new_entries():
                old = ev.args.oldRate
                new = ev.args.newRate

                # built‑in: get_or_create ensures we always have one row
                obj, _ = ConversionRate.objects.get_or_create(pk=1, defaults={"rate_wei": new})
                if obj.rate_wei != new:
                    obj.rate_wei = new
                    obj.save(update_fields=["rate_wei"])
                    self.stdout.write(f"Updated rate: {old} → {new}")
            time.sleep(2)
