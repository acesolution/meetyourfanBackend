# blockchain/utils.py

import json
from django.conf import settings
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# 1️⃣ Point at your configured provider
w3 = Web3(Web3.HTTPProvider(settings.WEB3_PROVIDER_URL))

# 2️⃣ Inject the PoA middleware so extraData > 32 bytes is OK
w3.middleware_onion.inject(ExtraDataToPOAMiddleware(), layer=0)

# 3️⃣ Load your ABI & instantiate the contract once
with open(settings.CONTRACT_ABI_PATH) as f:
    abi = json.load(f)

contract = w3.eth.contract(address=settings.CONTRACT_ADDRESS, abi=abi)

# 4️⃣ Sanity check at import time
if not w3.is_connected():
    raise RuntimeError("Cannot connect to WEB3_PROVIDER_URL")


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