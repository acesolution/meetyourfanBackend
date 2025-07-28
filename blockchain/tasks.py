# blockchain/tasks.py

from celery import shared_task
from django.conf import settings
from blockchain.utils import w3, contract
from web3.exceptions import ContractLogicError, TimeExhausted
from rest_framework.response import Response
from decimal import Decimal
from web3 import Web3
import logging
from .models import Transaction, InfluencerTransaction, OnChainAction
from typing import Optional
from web3.exceptions import TransactionNotFound

logger = logging.getLogger(__name__)

OWNER          = settings.OWNER_ADDRESS
PK             = settings.PRIVATE_KEY
GAS_LIMIT      = 200_000
GAS_PRICE_GWEI = "50"
BATCH_SIZE = 50

def _build_and_send(fn, tx_params):
    tx     = fn.build_transaction(tx_params)
    signed = w3.eth.account.sign_transaction(tx, private_key=PK)
    raw    = w3.eth.send_raw_transaction(signed.raw_transaction)
    return raw.hex()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def register_user_on_chain(self, user_id):
    try:
        chain_id = w3.eth.chain_id
        nonce    = w3.eth.get_transaction_count(OWNER)
        tx_params= {
            "chainId":  chain_id,
            "from":     OWNER,
            "nonce":    nonce,
            "gas":      GAS_LIMIT,
            "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
        }
        return _build_and_send(contract.functions.registerUser(user_id), tx_params)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def release_all_holds_for_campaign_task(self, campaign_id, seller_id):
    """
    Break a big campaign’s holds into BATCH_SIZE chunks
    and call releaseHoldsBatch(campaign, seller, start, end) for each.
    """
    campaign_id = int(campaign_id)
    seller_id   = int(seller_id)

    try:
        # ─── Step 1: fetch the full buyer list ───────────────────────────────
        buyers = contract.functions.getCampaignBuyers(campaign_id).call({'from': OWNER})
        total  = len(buyers)
        if total == 0:
            return f"No holders to release for campaign {campaign_id}"

        # ─── Step 2: loop over chunks ────────────────────────────────────────
        tx_hashes = []
        base_nonce = w3.eth.get_transaction_count(OWNER)
        for batch_index, start in enumerate(range(0, total, BATCH_SIZE)):
            end = min(start + BATCH_SIZE - 1, total - 1)

            tx_params = {
                "chainId":      w3.eth.chain_id,
                "from":         OWNER,
                "nonce":        base_nonce + batch_index,
                "gas":          GAS_LIMIT,
                "gasPrice":     w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }

            fn = contract.functions.releaseHoldsBatch(
                campaign_id,
                seller_id,
                start,
                end
            )
            tx_hash = _build_and_send(fn, tx_params)
            tx_hashes.append(tx_hash)

        return tx_hashes

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def refund_all_holds_for_campaign_task(self, campaign_id, seller_id):
    """
    Break a big campaign’s holds into BATCH_SIZE chunks
    and call refundHoldsBatch(campaign, start, end) for each.
    """
    campaign_id = int(campaign_id)
    seller_id   = int(seller_id)

    try:
        # ─── Step 1: fetch the full buyer list ───────────────────────────────
        buyers = contract.functions.getCampaignBuyers(campaign_id).call({'from': OWNER})
        total  = len(buyers)
        if total == 0:
            return f"No holds to refund for campaign {campaign_id}"

        # ─── Step 2: loop over chunks ────────────────────────────────────────
        tx_hashes = []
        base_nonce = w3.eth.get_transaction_count(OWNER)
        for batch_index, start in enumerate(range(0, total, BATCH_SIZE)):
            end = min(start + BATCH_SIZE - 1, total - 1)

            tx_params = {
                "chainId":      w3.eth.chain_id,
                "from":         OWNER,
                "nonce":        base_nonce + batch_index,
                "gas":          GAS_LIMIT,
                "gasPrice":     w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }

            fn = contract.functions.refundHoldsBatch(
                campaign_id,
                start,
                end
            )
            tx_hash = _build_and_send(fn, tx_params)
            tx_hashes.append(tx_hash)

        return tx_hashes

    except Exception as exc:
        raise self.retry(exc=exc)
    
    
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def register_campaign_on_chain(self, campaign_id, seller_id):
    from campaign.models import EscrowRecord, Campaign
    from web3.exceptions import ContractLogicError, TimeExhausted

    # 1) Normalize inputs & fetch the campaign
    campaign_id = int(campaign_id)
    seller_id   = int(seller_id)
    campaign    = Campaign.objects.get(pk=campaign_id)

    # 2) Create your “pending” escrow record in one go
    rec = EscrowRecord.objects.create(
        user                = campaign.user,
        campaign            = campaign,
        onchain_campaign_id = str(campaign_id),
        tt_amount           = 0,
        credit_amount       = 0,
        gas_cost_credits    = 0,
        gas_cost_tt         = 0,
        status              = "held",          # or "pending" if you prefer
        tx_hash             = "",
        task_id             = self.request.id,
    )

    try:
        # 3) Build, sign & send the tx
        chain_id = w3.eth.chain_id
        nonce    = w3.eth.get_transaction_count(OWNER)
        tx_params = {
            "chainId":  chain_id,
            "from":     OWNER,
            "nonce":    nonce,
            "gas":      GAS_LIMIT,
            "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
        }
        fn     = contract.functions.registerCampaign(campaign_id, seller_id)
        raw_tx = _build_and_send(fn, tx_params)

        # 4) Wait for the receipt & assert success
        receipt = w3.eth.wait_for_transaction_receipt(raw_tx, timeout=120)
        if receipt.status != 1:
            raise ContractLogicError("On-chain tx reverted")

        # 5) Update your escrow record with the real tx hash & final status
        rec.tx_hash          = receipt.transactionHash.hex()
        rec.status           = "released"      # or "registered"
        rec.gas_cost_credits = int(tx_params["gasPrice"]) * receipt.gasUsed // (10**9)
        rec.gas_cost_tt      = receipt.gasUsed
        rec.save(update_fields=[
            "tx_hash", "status", "gas_cost_credits", "gas_cost_tt"
        ])

        return rec.tx_hash

    except (ContractLogicError, TimeExhausted) as exc:
        rec.status = "refunded"    # or “failed” if you prefer
        rec.save(update_fields=["status"])
        raise

    except Exception as exc:
        # any other crash → retry
        raise self.retry(exc=exc)
    
    
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def hold_for_campaign_on_chain(
    self,
    escrow_record_id: int,
    campaign_id: int,
    buyer_id: int,
    spent_tt_whole: int,
    cost_in_credits: int,
):
    from campaign.models import EscrowRecord, Campaign
    from web3.exceptions import ContractLogicError, TimeExhausted

    # 1) Fetch the escrow record & campaign
    rec      = EscrowRecord.objects.get(pk=escrow_record_id)
    campaign = Campaign.objects.get(pk=campaign_id)
    
    
    # Convert logical credits into Wei
    spent_credit_wei   = Web3.to_wei(str(cost_in_credits), "ether")  # e.g. 66 → 66e18
    # Pull the on‐chain conversionRate (uint256)
    conv_rate          = contract.functions.conversionRate().call()
    # Derive the exact TT‐Wei (including fractions!) by dividing credits‐Wei by conversionRate
    spent_tt_wei       = spent_credit_wei // conv_rate            # e.g. 66e18//10 = 6.6e18

    # log everything
    logger.error(f"[hold_for_campaign] escrow_id={escrow_record_id} campaign={campaign_id} buyer={buyer_id}")
    logger.error(f"  spent_tt_whole={spent_tt_whole}, cost_in_credits={cost_in_credits}")
    logger.error(f"  spent_tt_wei={spent_tt_wei}, spent_credit_wei={spent_credit_wei}")
    logger.error(f"  on-chain conversionRate={contract.functions.conversionRate().call()}")
    
    try:
        # 6) On‐chain balance check
        try:
            onchain_tt, onchain_credits = contract.functions.getUserBalances(buyer_id).call(
                {"from": OWNER}
            )
        except Exception:
            return Response({"error": "Could not read on‐chain balances"}, status=502)

        if onchain_credits < cost_in_credits:
            return Response({"error": "Insufficient on‐chain credits"}, status=400)

        if onchain_tt < spent_tt_whole:
            return Response({"error": "Insufficient on‐chain TT tokens"}, status=400)
        
        # 2) Build & sign the holdForCampaign tx
        fn = contract.functions.holdForCampaign(
            campaign_id,
            buyer_id,
            spent_tt_wei,
            spent_credit_wei,
        )
        latest   = w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        tip      = w3.to_wei(2, "gwei")
        tx       = fn.build_transaction({
            "chainId":           w3.eth.chain_id,
            "from":              OWNER,
            "nonce":             w3.eth.get_transaction_count(OWNER),
            "maxFeePerGas":      int(base_fee * 1.2) + tip,
            "maxPriorityFeePerGas": tip,
        })

        # 3) Estimate & set gas
        estimated = w3.eth.estimate_gas(tx)
        tx["gas"] = int(estimated * 1.2)

        # 4) Send
        signed = w3.eth.account.sign_transaction(tx, private_key=PK)
        raw    = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash = raw.hex()

        # 5) Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise ContractLogicError("holdForCampaign reverted")

        # 6) Compute gas costs
        gas_used        = receipt.gasUsed
        effective_price = getattr(receipt, "effectiveGasPrice", tx["maxFeePerGas"])
        gas_cost_wei    = gas_used * effective_price
        gas_cost_eth    = w3.from_wei(gas_cost_wei, "ether")
        # convert ETH→credits (whatever your formula is)
        gas_cost_credits = int(Decimal(str(gas_cost_eth)) * 1000)

        # 7) Update the EscrowRecord
        rec.tx_hash           = tx_hash
        rec.status            = "held"
        rec.gas_cost_credits  = gas_cost_credits
        rec.gas_cost_tt       = gas_used
        rec.save(update_fields=[
            "tx_hash", "status", "gas_cost_credits", "gas_cost_tt"
        ])

        return tx_hash

    except (ContractLogicError, TimeExhausted) as e:
        rec.status = "refunded"
        rec.save(update_fields=["status"])
        # you could retry on TimeExhausted if you like:
        # return self.retry(exc=e)
        raise

    except Exception as e:
        # unexpected failure → retry
        raise self.retry(exc=e)



@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def withdraw_for_user_task(self, user_id: int, credits_amount: int):
    """
    - credits_amount: the integer number of credits you got from the front end.
    - On chain: burn creditsWei = credits_amount * 1e18, then derive ttWei = creditsWei / conversionRate.
    - Then call withdraw(userId, ttWei).
    """
    try:
        # 1) turn credits→Wei (all balances are 18-decimal)
        credit_wei = Web3.to_wei(str(credits_amount), "ether")      # e.g. 100 → 100e18

        # 2) fetch conversionRate from contract (uint256)
        conv_rate = contract.functions.conversionRate().call()      # e.g. 10

        # 3) compute how many TT-Wei to withdraw
        tt_wei    = credit_wei // conv_rate                          # integer division

        # 4) build & send the tx
        chain_id = w3.eth.chain_id
        nonce    = w3.eth.get_transaction_count(OWNER)
        tx_params = {
            "chainId":  chain_id,
            "from":     OWNER,
            "nonce":    nonce,
            "gas":      GAS_LIMIT,
            "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
        }
        fn = contract.functions.withdraw(user_id, tt_wei)
        tx_hash = _build_and_send(fn, tx_params)
        return tx_hash

    except (ContractLogicError, TimeExhausted) as e:
        # you can retry if you want
        raise self.retry(exc=e)
    except Exception as e:
        raise self.retry(exc=e)
    
    
    

# ── STEP 1: GENERIC FETCHER ───────────────────────────────────────────────────
@shared_task(bind=True, max_retries=5, default_retry_delay=20)
def fetch_tx_details(self, model_name: str, record_id: int) -> str:
    """
    1) Waits for the tx to be mined.
    2) Calls both get_transaction_receipt and get_transaction.
    3) Populates status + full metadata.
    """
    model_map = {
        'Transaction': Transaction,
        'InfluencerTransaction': InfluencerTransaction,
        'OnChainAction': OnChainAction,
    }
    Model = model_map.get(model_name)
    if not Model:
        return f"Unknown model: {model_name}"

    obj = Model.objects.get(pk=record_id)
    if not obj.tx_hash:
        return f"{model_name}({record_id}) has no tx_hash"

    try:
        # built‑in: waits for the mined receipt or raises TransactionNotFound
        receipt = w3.eth.get_transaction_receipt(obj.tx_hash)
    except TransactionNotFound as exc:
        raise self.retry(exc=exc)

    # built‑in: fetch original tx data
    tx = w3.eth.get_transaction(obj.tx_hash)

    # Map chain status → our STATUS_CHOICES
    obj.status            = Model.COMPLETED if receipt.status == 1 else Model.FAILED
    obj.block_number      = receipt.blockNumber
    obj.transaction_index = receipt.transactionIndex
    obj.gas_used          = receipt.gasUsed
    # built‑in: EIP‑1559 includes .effectiveGasPrice
    obj.effective_gas_price = getattr(receipt, 'effectiveGasPrice', None)

    # From the original tx object:
    obj.from_address = tx['from']
    obj.to_address   = tx.to
    obj.value        = tx.value
    obj.input_data   = tx.input

    # If OnChainAction, also decode event args:
    if model_name == 'OnChainAction':
        decoded = {}
        for ev_name, ev_cls in w3.eth.contract.events._events.items():
            for ev in ev_cls().processReceipt(receipt):
                decoded.setdefault(ev.event, []).append(dict(ev.args))
        obj.args = decoded or None
        update_fields = [
            'status','block_number','transaction_index',
            'gas_used','effective_gas_price',
            'from_address','to_address','value','input_data',
            'args'
        ]
    else:
        update_fields = [
            'status','block_number','transaction_index',
            'gas_used','effective_gas_price',
            'from_address','to_address','value','input_data'
        ]

    # built‑in: Model.save(update_fields=…) only writes those cols back to DB
    obj.save(update_fields=update_fields)
    return f"{model_name}({record_id}) → {obj.status}"

# ── STEP 2: “SAVE & ENQUEUE” HELPERS ────────────────────────────────────────────

@shared_task(bind=True)
def save_transaction(
    self,
    user_id: int,
    campaign_id: Optional[int],
    tx_type: str,
    tt_amount: int,
    credits_delta: int,
    tx_hash: str
) -> int:
    tx = Transaction.objects.create(
        user_id=user_id,
        campaign_id=campaign_id,
        tx_type=tx_type,
        tt_amount=tt_amount,
        credits_delta=credits_delta,
        tx_hash=tx_hash,
    )
    fetch_tx_details.delay('Transaction', tx.id)
    return tx.id


@shared_task(bind=True)
def save_influencer_transaction(
    self,
    user_id: int,
    influencer_id: int,
    campaign_id: int,
    transaction_type: str,
    tt_amount: int,
    credits_delta: int,
    tx_hash: str
) -> int:
    itx = InfluencerTransaction.objects.create(
        user_id=user_id,
        influencer_id=influencer_id,
        campaign_id=campaign_id,
        transaction_type=transaction_type,
        tt_amount=tt_amount,
        credits_delta=credits_delta,
        tx_hash=tx_hash,
    )
    fetch_tx_details.delay('InfluencerTransaction', itx.id)
    return itx.id


@shared_task(bind=True)
def save_onchain_action(
    self,
    user_id: Optional[int],
    campaign_id: Optional[int],
    event_type: str,
    tx_hash: str
) -> int:
    act = OnChainAction.objects.create(
        user_id=user_id,
        campaign_id=campaign_id,
        event_type=event_type,
        tx_hash=tx_hash,
    )
    fetch_tx_details.delay('OnChainAction', act.id)
    return act.id