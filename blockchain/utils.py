# blockchain/utils.py

import json
from django.conf import settings
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from blockchain.models import ConversionRate

# ── Shared HTTP client & contract for reads / bootstrap ───────────
w3_http = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))
# built-in: some chains (Clique/PoA) need this so logs / extraData work
w3_http.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)

with open(settings.CONTRACT_ABI_PATH) as f:
    abi = json.load(f)

contract_http = w3_http.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)

if not w3_http.is_connected():
    raise RuntimeError("Cannot connect to WEB3_PROVIDER_URL")

# ── Factory for WebSocket-backed contract (for event listening) ───
def get_ws_contract():
    """
    Returns (w3_ws, contract_ws) using WebSocketProvider so watchers can listen to events.
    """
    w3_ws = Web3(Web3.WebsocketProvider(settings.WEB3_PROVIDER_URL))
    # same middleware as HTTP version; adjust if your chain requires something else
    w3_ws.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)
    contract_ws = w3_ws.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)
    return w3_ws, contract_ws


# ── Helpers ───────────────────────────────────────────────────────
def fetch_tx_details(tx_hash: str) -> dict:
    receipt = w3_http.eth.get_transaction_receipt(tx_hash)
    txn = w3_http.eth.get_transaction(tx_hash)
    return {
        "block_number":        receipt.blockNumber,
        "transaction_index":   receipt.transactionIndex,
        "gas_used":            receipt.gasUsed,
        "effective_gas_price": receipt.effectiveGasPrice,
        "from_address":        txn["from"],
        "to_address":          txn["to"],
        "value":               txn["value"],
        "input_data":          txn["input"],
    }


def get_current_rate_wei() -> int:
    # built-in: resilient get_or_create so missing singleton doesn't blow up
    obj, _ = ConversionRate.objects.get_or_create(pk=1, defaults={"rate_wei": 10})
    return obj.rate_wei
