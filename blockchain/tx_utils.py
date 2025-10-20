# blockchain/tx_utils.py
from django.conf import settings
from blockchain.utils import w3  # your existing web3 instance

def build_and_send(fn, tx_params):
    """
    Sign & broadcast any contract function call.

    Built-ins used:
    - dict access: tx_params[...] → get values from the dict the same way you'd index a list, but by key.
    - .hex(): bytes → hex string prefixed with '0x' (human-readable transaction hash).
    """
    tx = fn.build_transaction(tx_params)                          # web3: build tx dict
    signed = w3.eth.account.sign_transaction(                     # built-in method on web3 account; signs bytes
        tx, private_key=settings.PRIVATE_KEY
    )
    raw = w3.eth.send_raw_transaction(signed.raw_transaction)     # sends bytes to the node mempool
    return raw.hex()                                              # built-in .hex(): bytes→"0x..."
