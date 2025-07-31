# blockchain/management/commands/watch_rate.py

import time
from django.core.management.base import BaseCommand
from blockchain.models import ConversionRate
from blockchain.utils import contract_http, get_ws_contract  # reuse centralized setup

class Command(BaseCommand):
    help = "Watch for ConversionRateUpdated events and keep DB in sync."

    def handle(self, *args, **opts):
        # ── Initial seed from on-chain via shared HTTP contract ─────────
        try:
            onchain_rate = contract_http.functions.conversionRate().call()
            obj, _ = ConversionRate.objects.get_or_create(
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

        # ── Event watching via WebSocket-backed contract ───────────────
        w3_ws, contract_ws = get_ws_contract()

        try:
            event_cls = contract_ws.events.ConversionRateUpdated
        except AttributeError:
            self.stderr.write("Event ConversionRateUpdated not found in ABI.")
            return

        event_filter = event_cls.createFilter(fromBlock="latest")
        self.stdout.write("Listening for ConversionRateUpdated events…")

        while True:
            try:
                entries = event_filter.get_new_entries()
                for ev in entries:
                    self.stdout.write(f"Raw event args: {ev.args}")
                    old_rate = getattr(ev.args, "oldRate", None)
                    new_rate = getattr(ev.args, "newRate", None)
                    if new_rate is None:
                        self.stderr.write(f"Unexpected event shape, skipping: {ev.args}")
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
                # try to recover the filter so we don't permanently miss events
                try:
                    current_block = w3_ws.eth.block_number
                    event_filter = event_cls.createFilter(fromBlock=max(0, current_block - 5))
                    self.stderr.write("[watch loop] recreated filter")
                except Exception as inner:
                    self.stderr.write(f"[watch loop] failed to recreate filter: {inner}")
            time.sleep(2)
