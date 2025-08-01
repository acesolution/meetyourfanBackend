# blockchain/tasks.py

from celery import shared_task
from django.conf import settings
from blockchain.utils import w3, contract, fetch_tx_details
from web3.exceptions import ContractLogicError, TimeExhausted
from rest_framework.response import Response
from decimal import Decimal, ROUND_DOWN
from web3 import Web3
import logging
from .models import Transaction, InfluencerTransaction, OnChainAction
from typing import Optional
from web3.exceptions import TransactionNotFound
from django.contrib.auth import get_user_model

User = get_user_model()

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

# ── Helper to turn an integer Wei value into a float with one decimal ──
def _wei_to_single_decimal(value_wei: int, decimals: int = 18) -> float:
    # built-in: Decimal lets us do exact decimal arithmetic
    quant = Decimal('0.1')  # one‐decimal precision
    d = Decimal(value_wei) / (Decimal(10) ** decimals)
    # ROUND_DOWN to avoid “0.1000000002” → “0.1”
    return float(d.quantize(quant, rounding=ROUND_DOWN))

@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def save_transaction_info(
    self,
    tx_hash: str,
    user_id: int,
    campaign_id: int,
    tx_type: str,
    tt_amount: int,
    credits_delta: int,
    email_verified: bool = False,
    phone_verified: bool = False,
):
    """
    Fetch on‑chain details for a user transaction and save Transaction model.
    """
    try:
        # May raise TransactionNotFound if not yet mined → triggers retry
        details = fetch_tx_details(tx_hash)
    except TransactionNotFound as exc:
        # Celery’s self.retry will re‑enqueue this task after default_retry_delay
        raise self.retry(exc=exc)

    # Django ORM .objects.create(): INSERT a new row with the given fields
    Transaction.objects.create(
        user_id=user_id,
        campaign_id=campaign_id,
        status=Transaction.COMPLETED,  # mark completed once details fetched
        tx_hash=tx_hash,
        **details,                     # unpack block_number, gas_used, etc.
        tx_type=tx_type,
        tt_amount=tt_amount,
        credits_delta=credits_delta,
        email_verified=email_verified,
        phone_verified=phone_verified,
    )

@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def save_influencer_transaction_info(
    self,
    tx_hash: str,
    user_id: int,
    campaign_id: int,
    influencer_id: int,
    transaction_type: str,
    tt_amount: int,
    credits_delta: int,
):
    """
    Fetch on‑chain details for an influencer payout/hold/refund and save InfluencerTransaction.
    """
    try:
        details = fetch_tx_details(tx_hash)
    except TransactionNotFound as exc:
        raise self.retry(exc=exc)

    InfluencerTransaction.objects.create(
        user_id=user_id,
        campaign_id=campaign_id,
        status=InfluencerTransaction.COMPLETED,
        tx_hash=tx_hash,
        **details,
        influencer_id=influencer_id,
        transaction_type=transaction_type,
        tt_amount=tt_amount,
        credits_delta=credits_delta,
    )

@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def save_onchain_action_info(
    self,
    tx_hash: str,
    user_id: int,
    campaign_id: int,
    event_type: str,
    args: dict = None,
):
    """
    Fetch on‑chain details for a non‑monetary event (e.g. user_registered),
    and save OnChainAction.
    """
    try:
        details = fetch_tx_details(tx_hash)
    except TransactionNotFound as exc:
        raise self.retry(exc=exc)

    OnChainAction.objects.create(
        user_id=user_id,
        campaign_id=campaign_id,
        status=OnChainAction.COMPLETED,
        tx_hash=tx_hash,
        **details,
        tx_type=event_type,
        args=args or {},
    )
    
    
    
    
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
    campaign_id = int(campaign_id)
    seller_id   = int(seller_id)

    try:
        # 1) Fetch buyers on‑chain (eth_call, no gas)
        buyers = contract.functions.getCampaignBuyers(campaign_id).call({'from': OWNER})
        original_buyers = list(buyers)
        total  = len(buyers)
        if total == 0:
            return f"No holders to release for campaign {campaign_id}"

        base_nonce = w3.eth.get_transaction_count(OWNER)  # next nonce
        recorded   = []  # collect for return/debug

        for batch_index, start in enumerate(range(0, total, BATCH_SIZE)):
            end = min(start + BATCH_SIZE - 1, total - 1)

            tx_params = {
                "chainId":  w3.eth.chain_id,                  # current chain ID
                "from":     OWNER,                            # sender address
                "nonce":    base_nonce + batch_index,         # avoid collisions
                "gas":      GAS_LIMIT,
                "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),  # gwei→wei
            }

            # Prepare the batch release function call
            fn      = contract.functions.releaseHoldsBatch(campaign_id, seller_id, start, end)
            tx_hash = _build_and_send(fn, tx_params)  # sign & broadcast

            # Wait for the tx to be mined (blocks until mined)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            # Decode all HoldReleased events from receipt.logs
            events = contract.events.HoldReleased.process_receipt(receipt)
            

            for ev in events:
                sellerId = ev.args['sellerId']
                buyerId = ev.args['buyerId']
                wei_tt    = ev.args['ttAmountWei']
                wei_cr    = ev.args['creditAmountWei']

                # ── CONVERSION ──
                tt_amount = _wei_to_single_decimal(wei_tt)
                cr_amount = _wei_to_single_decimal(wei_cr)

                save_influencer_transaction_info.delay(
                    tx_hash=tx_hash,
                    user_id=User.objects.get(user_id=buyerId).id,
                    campaign_id=campaign_id,
                    influencer_id=User.objects.get(user_id=sellerId).id,
                    tx_type=InfluencerTransaction.RELEASE,
                    tt_amount=tt_amount,
                    credits_delta=cr_amount,
                )

                recorded.append({
                    'tx_hash':     tx_hash,
                    'buyerId':     buyerId,
                    'ttAmountWei': tt_amount,
                    'creditAmountWei': cr_amount,
                })



        return recorded

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def refund_all_holds_for_campaign_task(self, campaign_id, seller_id):
    campaign_id = int(campaign_id)
    seller_id   = int(seller_id)

    try:
        buyers = contract.functions.getCampaignBuyers(campaign_id).call({'from': OWNER})
        total  = len(buyers)
        if total == 0:
            return f"No holds to refund for campaign {campaign_id}"

        base_nonce = w3.eth.get_transaction_count(OWNER)
        recorded   = []

        for batch_index, start in enumerate(range(0, total, BATCH_SIZE)):
            end = min(start + BATCH_SIZE - 1, total - 1)

            tx_params = {
                "chainId":  w3.eth.chain_id,
                "from":     OWNER,
                "nonce":    base_nonce + batch_index,
                "gas":      GAS_LIMIT,
                "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }

            fn      = contract.functions.refundHoldsBatch(campaign_id, start, end)
            tx_hash = _build_and_send(fn, tx_params)

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            # Note: refund emits HoldRefunded events
            events = contract.events.HoldRefunded.process_receipt(receipt)

            for ev in events:
                buyerId = ev.args['buyerId']
                wei_tt    = ev.args['ttAmountWei']
                wei_cr    = ev.args['creditAmountWei']

                # ── CONVERSION ──
                tt_amount = _wei_to_single_decimal(wei_tt)
                cr_amount = _wei_to_single_decimal(wei_cr)

                save_influencer_transaction_info.delay(
                    tx_hash=tx_hash,
                    user_id=User.objects.get(user_id=buyerId).id,
                    campaign_id=campaign_id,
                    influencer_id=User.objects.get(user_id=seller_id).id,
                    tx_type=InfluencerTransaction.REFUND,
                    tt_amount=tt_amount,
                    credits_delta=cr_amount,
                )

                recorded.append({
                    'tx_hash':     tx_hash,
                    'buyerId':     buyerId,
                    'ttAmountWei': tt_amount,
                    'creditAmountWei': cr_amount,
                })

        return recorded

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
    
    
    

