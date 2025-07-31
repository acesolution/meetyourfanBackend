# blockchain/utils.py

import json
from django.conf import settings
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from blockchain.models import ConversionRate

# 1️⃣ Point at your configured provider
w3 = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))

# 2️⃣ Inject the PoA middleware so extraData > 32 bytes is OK
w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)

# 3️⃣ Load your ABI & instantiate the contract once
with open(settings.CONTRACT_ABI_PATH) as f:
    abi = json.load(f)

contract = w3.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)

contract_http = contract  # alias; modules importing contract_http expect this to exist


# 4️⃣ Sanity check at import time
if not w3.is_connected():
    raise RuntimeError("Cannot connect to WEB3_PROVIDER_URL")


def get_ws_contract():
    """
    Returns (w3_ws, contract_ws) using a WebSocket-backed connection so watchers can listen
    to events. Falls back to LegacyWebSocketProvider if WebsocketProvider isn't present.
    Assumes settings.WEB3_PROVIDER_URL is ws:// or wss://; if it's HTTP you need a separate WS URL.
    """
    ws_url = settings.WEB3_PROVIDER_URL
    if not ws_url.startswith(("ws://", "wss://")):
        raise RuntimeError(f"WEB3_PROVIDER_URL for websocket must be ws:// or wss://, got {ws_url!r}")

    # Try the newer provider if present, else fallback to legacy
    provider_cls = getattr(Web3, "WebsocketProvider", None) or getattr(Web3, "LegacyWebSocketProvider", None)
    if provider_cls is None:
        raise RuntimeError("No WebSocket provider class available on Web3 (neither WebsocketProvider nor LegacyWebSocketProvider)")

    # Instantiate websocket-backed Web3 and inject same middleware
    w3_ws = Web3(provider_cls(ws_url))
    w3_ws.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)

    if not w3_ws.is_connected():
        raise RuntimeError(f"Failed to connect over websocket to {ws_url}")

    contract_ws = w3_ws.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)
    return w3_ws, contract_ws


def fetch_tx_details(tx_hash: str) -> dict:
    """
    Fetch on-chain receipt + original tx fields for the given hash.
    Raises:
      - TransactionNotFound: if the tx isn't yet mined.
    Returns a dict of the metadata we care about.
    """
    # ─── Receipt ────────────────────────────────────────────────────────────────
    # w3.eth.get_transaction_receipt blocks until the tx is mined,
    # then returns a receipt object with gasUsed, blockNumber, etc.
    receipt = w3.eth.get_transaction_receipt(tx_hash)

    # ─── Original TX ────────────────────────────────────────────────────────────
    # w3.eth.get_transaction returns the original tx dict:
    #   'from', 'to', 'value', 'input', etc.
    txn = w3.eth.get_transaction(tx_hash)

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
    """
    Always returns the latest on-chain rate (in Wei) from the DB singleton.
    """
    # built-in: Query for pk=1 row
    return ConversionRate.objects.get(pk=1).rate_wei