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
