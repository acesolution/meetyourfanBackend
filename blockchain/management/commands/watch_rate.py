# blockchain/management/commands/watch_rate.py
import time
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware  # reuse the working one
from blockchain.models import ConversionRate

class Command(BaseCommand):
    help = "Watch for conversion rate change events and keep DB in sync."

    def handle(self, *args, **opts):
        # ── Wire up WebSocket + middleware ───────────────────────────────
        w3 = Web3(Web3.WebsocketProvider(settings.WEB3_PROVIDER_URL))
        # If your chain is PoA-like (e.g., BSC, some private chains), inject middleware:
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)

        # ── Load ABI & contract ────────────────────────────────────────
        with open(settings.CONTRACT_ABI_PATH) as f:
            abi = json.load(f)
        contract = w3.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)

        # ── Initial seed: fetch current rate on-chain so DB is never empty ──
        try:
            # Replace `conversionRate` with the actual getter name if different
            onchain_rate = contract.functions.conversionRate().call()
            obj, created = ConversionRate.objects.get_or_create(
                pk=1, defaults={"rate_wei": onchain_rate}
            )
            if obj.rate_wei != onchain_rate:
                obj.rate_wei = onchain_rate
                obj.save(update_fields=["rate_wei"])
                self.stdout.write(f"Initial sync: rate updated to {onchain_rate}")
            else:
                self.stdout.write(f"Initial sync: rate already {obj.rate_wei}")
        except Exception as e:
            self.stderr.write(f"[startup] failed to fetch initial rate: {e}")

        # ── Set up event filter ───────────────────────────────────────
        # Ensure this name matches the actual Solidity event
        EVENT_NAME = "ConversionRateUpdated"  # or "ConversionRateUpdated" as per your contract
        try:
            event_cls = getattr(contract.events, EVENT_NAME)
        except AttributeError:
            self.stderr.write(f"Event {EVENT_NAME} not found in ABI.")
            return

        event_filter = event_cls.createFilter(fromBlock="latest")

        self.stdout.write(f"Listening for {EVENT_NAME} events…")
        while True:
            try:
                entries = event_filter.get_new_entries()
                for ev in entries:
                    # adjust arg names if contract uses different ones
                    old_rate = getattr(ev.args, "conversionRate", None)
                    new_rate = getattr(ev.args, "newRate", None)
                    if new_rate is None:
                        self.stderr.write(f"Event missing expected newRate arg: {ev}")
                        continue

                    obj, _ = ConversionRate.objects.get_or_create(
                        pk=1, defaults={"rate_wei": new_rate}
                    )
                    if obj.rate_wei != new_rate:
                        obj.rate_wei = new_rate
                        obj.save(update_fields=["rate_wei"])
                        self.stdout.write(f"Updated rate: {old_rate} → {new_rate}")
            except Exception as e:
                self.stderr.write(f"[watch loop] error: {e}")
                # attempt to recreate filter from current block so we don't miss new ones
                try:
                    current_block = w3.eth.block_number
                    event_filter = event_cls.createFilter(fromBlock=current_block)
                    self.stderr.write("[watch loop] recreated filter")
                except Exception as inner:
                    self.stderr.write(f"[watch loop] failed to recreate filter: {inner}")
            time.sleep(2)
