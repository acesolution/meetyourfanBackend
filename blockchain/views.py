# blockchain/views.py
import time
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from blockchain.utils import w3, contract
from rest_framework.permissions import IsAuthenticated
from uuid import uuid4
from blockchain.models import Transaction, BalanceSnapshot, InfluencerTransaction, TransactionIssueReport, IssueAttachment
from decimal import Decimal, InvalidOperation
import logging
from web3.exceptions import ContractCustomError
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from api.models import VerificationCode
from django.template.loader import render_to_string
from web3 import Web3
from django.http import ( JsonResponse, HttpResponseBadRequest, HttpResponseForbidden)
import hmac
import hashlib
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import os
import json
from blockchain.utils import get_current_rate_wei
from .serializers import TransactionSerializer, InfluencerTransactionSerializer, TransactionIssueReportSerializer
from rest_framework.pagination import PageNumberPagination
from rest_framework import status as drf_status
from django.utils.dateparse import parse_date
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction as db_transaction
from django.db.models import Sum, Case, When, F, DecimalField, Value, Max, Count
from django.db.models.functions import Coalesce, Abs
from celery import chain
import base64
from uuid import uuid4, UUID
from blockchain.tx_utils import build_and_send as _build_and_send
from blockchain.crypto_utils import b64u as _b64u, b64u_dec as _b64u_dec, sign as _sign
from blockchain.tasks import withdraw_for_user_task, save_transaction_info
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction
from blockchain.tasks import claim_guest_after_registration, _from_wei

logger = logging.getLogger(__name__)

OWNER        = settings.OWNER_ADDRESS
PK           = settings.PRIVATE_KEY
WERT_PK      = settings.WERT_SC_SIGNER_KEY
GAS_LIMIT    = 200_000
GAS_PRICE_GWEI = "50"
SC_ADDRESS = settings.CONTRACT_ADDRESS


MAX_BYTES = 5 * 1024 * 1024  # 5MB
# Load your webhook secret from env
WERT_WEBHOOK_SECRET = os.getenv('WERT_WEBHOOK_SECRET')
if not WERT_WEBHOOK_SECRET:
    raise RuntimeError("Missing WERT_WEBHOOK_SECRET in environment")


DAILY_LIMIT_USDT = Decimal("500")  # product requirement

def _sum_withdrawn_credits_for_date(user, day, include_pending=True) -> Decimal:
    """
    Sum *credits* withdrawn by `user` on date `day` (YYYY-MM-DD), as a positive Decimal.
    If include_pending=True we count both PENDING and COMPLETED.
    """
    status_filter = ["pending", "completed"] if include_pending else ["completed"]
    qs = (
        Transaction.objects
        .filter(
            user=user,
            tx_type=Transaction.WITHDRAW,
            timestamp__date=day,
            status__in=status_filter,
        )
        .annotate(abs_credits=Abs(F("credits_delta")))
        .aggregate(total=Coalesce(Sum("abs_credits", output_field=DecimalField()), Value(0, output_field=DecimalField())))
    )
    return qs["total"] or Decimal(0)


def decode_tx_input(tx_input: str):
    """
    Decode a contract call's input data into (function_name, args_dict).

    - contract.decode_function_input(...) is a web3.py helper that uses your ABI
      to turn the raw hex calldata (the 'input' field from the tx) into:
        * a ContractFunction object
        * a Python dict of named arguments

    - built-in getattr(): safely fetches an attribute from an object, returning
      a default if it's missing instead of raising AttributeError.
    """
    fn, args = contract.decode_function_input(tx_input)
    fn_name = getattr(fn, "fn_name", getattr(fn, "function_identifier", ""))
    return fn_name, args


class DailyWithdrawUsageView(APIView):
    """
    GET /api/blockchain/withdraw/usage/?date=YYYY-MM-DD
    Returns how much the user withdrew today (or on the given date),
    plus remaining against the daily cap.

    Response:
    {
      "date": "2025-03-12",
      "limit": { "usdt": "500.00", "credits": "5000" },
      "used":  { "usdt": "123.45", "credits": "1234.50" },
      "remaining": { "usdt": "376.55", "credits": "3765.50" }
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # window date (defaults to *today* in server’s TZ)
        day = request.query_params.get("date")
        if day:
            try:
                day = timezone.datetime.fromisoformat(day).date()
            except ValueError:
                return Response({"detail": "Invalid date format. Use YYYY-MM-DD."}, status=400)
        else:
            day = timezone.localdate()

        # conversion rate (credits per 1 USDT, e.g. 10)
        conv_rate = Decimal(str(get_current_rate_wei()))

        # limits in both units
        limit_usdt    = DAILY_LIMIT_USDT
        limit_credits = (limit_usdt * conv_rate)

        # how much used today (sum of WITHDRAW credits)
        used_credits = _sum_withdrawn_credits_for_date(request.user, day, include_pending=True)
        used_usdt    = (used_credits / conv_rate).quantize(Decimal("0.01"))

        # remaining
        remaining_credits = (limit_credits - used_credits)
        if remaining_credits < 0:
            remaining_credits = Decimal(0)
        remaining_usdt = (remaining_credits / conv_rate).quantize(Decimal("0.01"))

        return Response({
            "date": str(day),
            "limit": {
                "usdt":    f"{limit_usdt:.2f}",
                "credits": str(limit_credits.normalize()),
            },
            "used": {
                "usdt":    f"{used_usdt:.2f}",
                "credits": str(used_credits.normalize()),
            },
            "remaining": {
                "usdt":    f"{remaining_usdt:.2f}",
                "credits": str(remaining_credits.normalize()),
            },
        })


class ConversionRateView(APIView):
    
    def get(self, request, *args, **kwargs):
        """
        GET /api/campaign/conversion-rate/
        Returns the latest on-chain rate (in Wei).
        """
        conversion_rate = get_current_rate_wei()             # your DB singleton lookup
        return Response({'conversion_rate': conversion_rate})

class RegisterUserView(APIView):
    """
    POST /api/blockchain/register/
    Body: { "user_id": "User123" }
    Only the OWNER may call this.
    """
    
    def post(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            chain_id = w3.eth.chain_id
            nonce    = w3.eth.get_transaction_count(OWNER)
            tx_params = {
                "chainId":  chain_id,
                "from":     OWNER,
                "nonce":    nonce,
                "gas":      GAS_LIMIT,
                "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }
            tx_hash = _build_and_send(contract.functions.registerUser(user_id), tx_params)
            return Response({"tx_hash": tx_hash})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DepositView(APIView):
    """
    POST /api/blockchain/deposit/
    Body: { "user_id": "User123", "amount": 12345 }
    Caller must approve the contract for `amount` TT first.
    """
    
    def post(self, request):
        user_id = request.data.get("user_id")
        try:
            amount = int(request.data.get("amount", 0))
        except (TypeError, ValueError):
            return Response({"error": "Invalid amount"}, status=status.HTTP_400_BAD_REQUEST)

        if not user_id or amount <= 0:
            return Response({"error": "user_id and positive amount required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            chain_id = w3.eth.chain_id
            nonce    = w3.eth.get_transaction_count(OWNER)
            tx_params = {
                "chainId":  chain_id,
                "from":     OWNER,
                "nonce":    nonce,
                "gas":      GAS_LIMIT,
                "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }
            tx_hash = _build_and_send(contract.functions.deposit(user_id, amount), tx_params)
            return Response({"tx_hash": tx_hash})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SetUserWalletView(APIView):
    """
    POST /api/blockchain/set-wallet/
    Body: { "user_id": "User123", "wallet": "0xFanWallet…" }
    Only the OWNER may call this.
    """
    
    def post(self, request):
        user_id = int(request.data["user_id"], 10)
        wallet  = request.data.get("wallet")
        if not user_id or not wallet:
            return Response({"error": "user_id and wallet are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            chain_id = w3.eth.chain_id
            nonce    = w3.eth.get_transaction_count(OWNER)
            tx_params = {
                "chainId":  chain_id,
                "from":     OWNER,
                "nonce":    nonce,
                "gas":      GAS_LIMIT,
                "gasPrice": w3.to_wei(GAS_PRICE_GWEI, "gwei"),
            }
            tx_hash = _build_and_send(contract.functions.setUserWallet(user_id, wallet), tx_params)
            return Response({"tx_hash": tx_hash})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MyBalancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = int(request.user.user_id)
        
        try:
            # Returns (tt_bal, credit_bal) in wei
            tt_bal, credit_bal = contract.functions.getUserBalances(user_id).call({
                "from": OWNER
            })
        except ContractCustomError:
            # If user not registered, treat as zero
            tt_bal, credit_bal = 0, 0

        # Record a snapshot in the database (still store raw wei)
        BalanceSnapshot.objects.create(
            user=request.user,
            tt_balance=tt_bal,
            credit_balance=credit_bal
        )

        # Return integer token/credit counts
        return Response({
            "tt_balance":     str(tt_bal),      # e.g. 2
            "credit_balance": str(credit_bal)   # e.g. 20
        })


class MyLatestSnapshotView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            snap = BalanceSnapshot.objects.filter(user=request.user).latest()
            return Response({
                "tt_balance":     snap.tt_balance,
                "credit_balance": snap.credit_balance,
                "taken_at":       snap.taken_at
            })
        except BalanceSnapshot.DoesNotExist:
            return Response({"error":"no snapshot yet"}, status=404)

class GetUserWalletView(APIView):
    """
    GET /api/blockchain/wallet/
    Returns the authenticated user’s registered withdrawal wallet address.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = int(request.user.user_id)
        try:
            wallet = contract.functions.getUserWallet(user_id).call({
                "from": OWNER  # your owner address from settings.OWNER_ADDRESS
            })
            return Response({"wallet": wallet})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WithdrawView(APIView):
    """
    POST /api/blockchain/withdraw/
    Body: { "amount": <credits>, "type": "email" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_id = int(user.user_id)

        # 1) parse & basic validation
        try:
            credits = int(request.data.get("amount", 0))
        except (TypeError, ValueError):
            return Response({"error": "Invalid amount"}, status=status.HTTP_400_BAD_REQUEST)
        if credits <= 0:
            return Response({"error": "amount must be > 0"}, status=status.HTTP_400_BAD_REQUEST)

        # 2) verify OTP
        verify_type = request.data.get("type")
        if verify_type not in ("email", "phone"):
            return Response(
                {"error": "type is required ('email' or 'phone')."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            vc = VerificationCode.objects.get(user=user)
        except VerificationCode.DoesNotExist:
            return Response({"error": "no verification in progress."},
                            status=status.HTTP_400_BAD_REQUEST)

        if verify_type == "email" and not vc.withdraw_email_verified:
            return Response({"error": "Email not verified."},
                            status=status.HTTP_400_BAD_REQUEST)
        if verify_type == "phone" and not vc.withdraw_phone_verified:
            return Response({"error": "Phone not verified."},
                            status=status.HTTP_400_BAD_REQUEST)
            
        conv_rate = Decimal(str(get_current_rate_wei()))       # e.g. 10 credits per 1 USDT
        limit_usdt = DAILY_LIMIT_USDT                          # 500.00
        limit_credits = (limit_usdt * conv_rate)               # e.g. 5000

        today = timezone.localdate()
        already_today = _sum_withdrawn_credits_for_date(user, today, include_pending=True)

        remaining_credits = limit_credits - already_today
        if remaining_credits < 0:
            remaining_credits = Decimal(0)

        if Decimal(credits) > remaining_credits:
            remaining_usdt = (remaining_credits / conv_rate).quantize(Decimal("0.01"))
            return Response(
                {
                    "error": "Daily withdraw limit exceeded.",
                    "limit": {
                        "usdt": f"{limit_usdt:.2f}",
                        "credits": str(limit_credits.normalize()),
                    },
                    "used_today": {
                        "usdt": f"{(already_today/conv_rate).quantize(Decimal('0.01')):.2f}",
                        "credits": str(already_today.normalize()),
                    },
                    "remaining_today": {
                        "usdt": f"{remaining_usdt:.2f}",
                        "credits": str(remaining_credits.normalize()),
                    },
                },
                status=status.HTTP_400_BAD_REQUEST
            )
            
        amount = credits // get_current_rate_wei()
        res = chain(
            withdraw_for_user_task.s(user_id, credits),
            save_transaction_info.s(
                request.user.id,        # user_id (pos 2)
                None,                   # campaign_id
                Transaction.WITHDRAW,   # tx_type
                int(amount),            # tt_amount (wei)
                -int(credits),       # credits_delta (burn is negative)
            ),
        ).apply_async()

        # 4) clear the one-time OTP flags so it can’t be reused
        vc.withdraw_email_verified = vc.withdraw_phone_verified = False
        vc.withdraw_expires_at     = None
        vc.save(update_fields=[
            "withdraw_email_verified",
            "withdraw_phone_verified",
            "withdraw_expires_at",
        ])

        # 5) record your own Transaction record if you want
        #    (optional, you can do that in the task’s callback instead)

        return Response(
            {
                "message": "Withdrawal enqueued, check on-chain soon",
                "task_id": res.id
            },
            status=status.HTTP_202_ACCEPTED
        )
        
class WithdrawVerifyRequestCodeView(APIView):
    """
    POST /api/blockchain/withdraw/request-code/
    Body: { "type": "email" } or { "type": "phone" }
    Sends a code to the user's email or phone.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        verify_type = request.data.get("type")
        if verify_type not in ("email", "phone"):
            return Response(
                {"error": "type must be 'email' or 'phone'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        verification, _ = VerificationCode.objects.get_or_create(user=request.user)
        code = verification.generate_code()

        # reset flags & set expiration
        verification.withdraw_expires_at = timezone.now() + timedelta(minutes=10)
        if verify_type == "email":
            verification.withdraw_email_code     = code
            verification.withdraw_email_verified = False
            verification.withdraw_email_sent_at  = timezone.now()
            verification.save()

            # send email
            html_msg = render_to_string(
                "confirm-withdrawal.html",
                {
                    "verification_code": code,
                    "title":  "Confirm Your Withdrawal",
                    "intro":  "Enter the 6-digit code below to confirm your withdrawal request.",
                    "footer": "If you didn’t request a withdrawal, please ignore this email.",
                    "expiry_minutes": 10,  # built-in int -> template filter default will accept it
                },
            )
            send_mail(
                subject="Your Withdrawal Verification Code",
                message=f"Your code is: {code}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.user.email],
                html_message=html_msg,
                fail_silently=False,
            )

        else:  # phone
    
            verification.withdraw_phone_code     = code
            verification.withdraw_phone_verified = False
            verification.withdraw_phone_sent_at  = timezone.now()
            verification.save()

            # TODO: integrate your SMS gateway here

        return Response({"message": "Verification code sent."}, status=status.HTTP_200_OK)
    
    
class WithdrawVerifyCodeView(APIView):
    """
    POST /api/blockchain/withdraw/verify-code/
    Body: { "type": "email"|"phone", "code": "123456" }
    Marks the user's withdraw_email_verified or withdraw_phone_verified.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        verify_type = request.data.get("type")
        code        = request.data.get("code")

        if verify_type not in ("email", "phone") or not code:
            return Response(
                {"error": "Both 'type' and 'code' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            vc = VerificationCode.objects.get(user=request.user)
        except VerificationCode.DoesNotExist:
            return Response({"error": "No verification in progress."},
                            status=status.HTTP_400_BAD_REQUEST)

        # check expiry
        if vc.withdraw_expires_at < timezone.now():
            return Response({"error": "Verification code expired."},
                            status=status.HTTP_400_BAD_REQUEST)

        if verify_type == "email" and vc.withdraw_email_code == code:
            vc.withdraw_email_verified = True
            vc.withdraw_email_code     = None
            vc.save(update_fields=['withdraw_email_verified','withdraw_email_code'])
            return Response({"message": "Email verified for withdrawal."})

        if verify_type == "phone" and vc.withdraw_phone_code == code:
            vc.withdraw_phone_verified = True
            vc.withdraw_phone_code     = None
            vc.save()
            return Response({"message": "Phone verified for withdrawal."})

        return Response({"error": "Invalid code."},
                        status=status.HTTP_400_BAD_REQUEST)


class WithdrawUpdateEmailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        new_email = request.data.get("new_email")
        if not new_email:
            return Response({"error":"new_email is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        # 1️⃣ Update the actual user email
        user = request.user
        user.email = new_email
        user.save()

        # 2️⃣ Now regenerate & store the withdrawal-OTP
        vc, _ = VerificationCode.objects.get_or_create(user=user)
        code = vc.generate_code()
        vc.withdraw_email_code     = code
        vc.withdraw_email_verified = False
        vc.withdraw_email_sent_at  = timezone.now()
        vc.withdraw_expires_at     = timezone.now() + timedelta(minutes=10)
        vc.save()

        # 3️⃣ Send it to the NEW address
        html = render_to_string("confirm-withdrawal.html", {"verification_code": code})
        send_mail(
            subject="Your Withdrawal Verification Code",
            message=f"Your code is: {code}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[new_email],
            html_message=html,
            fail_silently=False,
        )

        return Response({"message":"Email updated and withdrawal code sent."})


class ConfirmDepositView(APIView):
    permission_classes = [IsAuthenticated]  # built‑in: only allow logged‑in users

    def post(self, request, *args, **kwargs):
        # built‑in: DRF parses JSON body into request.data
        tx_hash = request.data.get('tx_hash')
        amount  = request.data.get('amount')
        conversion_rate = get_current_rate_wei()
        
        
        # basic validation
        if not tx_hash or amount is None:
            # built‑in: return JSON error + 400 Bad Request
            return Response(
                {'error': 'Both tx_hash and amount are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        credits = amount * conversion_rate 

        # built‑in: .delay() is Celery’s shortcut to enqueue an async task immediately
        save_transaction_info.delay(
            tx_hash,
            request.user.id,       # user_id FK
            None,                  # campaign_id
            Transaction.DEPOSIT,   # 'deposit'
            int(amount),           # tt_amount
            int(credits),           # credits_delta
        )

        # built‑in: return JSON + 201 Created
        return Response(
            {'message': 'Deposit recorded; awaiting on‑chain confirmation.'},
            status=status.HTTP_201_CREATED
        )
        
        
@method_decorator(csrf_exempt, name='dispatch')
class WertWebhookView(View):
    """
    Accept Wert webhooks (unsigned). If an X-WERT-SIGNATURE header ever appears
    and WERT_WEBHOOK_SECRET is set, verify it; otherwise just log and proceed.
    """

    def post(self, request, *args, **kwargs):
        raw_body = request.body
        logger.error("Wert webhook received: %s", raw_body[:MAX_BYTES])

        # Optional HMAC check (only enforce when BOTH are present)
        signature = request.META.get('HTTP_X_WERT_SIGNATURE')
        if WERT_WEBHOOK_SECRET and signature:
            computed = hmac.new(
                key=WERT_WEBHOOK_SECRET.encode(),
                msg=raw_body,
                digestmod=hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(computed, signature):
                logger.error("Wert webhook signature mismatch; ignoring HMAC and continuing")
        elif signature or WERT_WEBHOOK_SECRET:
            # Header or secret missing — just log for visibility, do not block
            logger.error("Wert webhook: no usable signature; proceeding unsigned")

        # Parse JSON
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.error("Wert webhook: invalid JSON")
            return HttpResponseBadRequest("Invalid JSON")

        evt_type = payload.get("type")  # e.g. test, payment_started, order_complete, order_failed, order_canceled, transfer_started, ...
        user_id  = (payload.get("user") or {}).get("user_id")
        click_id = payload.get("click_id")

        order     = payload.get("order") or {}
        order_id  = order.get("id")               # may be empty on test
        tx_id     = order.get("transaction_id")
        base      = order.get("base")             # asset (or sometimes fiat in their test)
        base_amt  = order.get("base_amount")
        quote     = order.get("quote")            # fiat/quote currency
        quote_amt = order.get("quote_amount")
        address   = order.get("address")

        # Map Wert event -> our WertOrder.status
        status_map = {
            "payment_started": "pending",
            "transfer_started": "pending",
            "order_complete": "confirmed",
            "order_failed": "failed",
            "order_canceled": "failed",
            "tx_smart_contract_failed": "failed",
            # "test" → leave as "created" so we can see it but not count it
        }
        new_status = status_map.get(evt_type)
        
        
        # Upsert WertOrder
        from blockchain.models import WertOrder  # lazy import to avoid cycles

        defaults = {
            "click_id":       click_id,
            "tx_id":          tx_id,
            "raw":            payload,
            "token_symbol":   base,
            "token_network":  None,  # fill if you pass it into widget and it returns back
            # Keep both fiat & asset numbers for reconciliation; guard Decimal conversions
            "fiat_currency":  quote,
            "fiat_amount":    Decimal(quote_amt) if quote_amt else None,
            # token_amount_wei: leave None unless you convert base_amt to a canonical integer
        }
        if new_status:
            defaults["status"] = new_status

        try:
            if order_id:
                obj, _ = WertOrder.objects.update_or_create(
                    order_id=order_id, defaults=defaults
                )
            else:
                # For “test” events with no order_id — use click_id as stable key
                obj, created = WertOrder.objects.get_or_create(
                    order_id=None, click_id=click_id, defaults=defaults
                )
                if not created:
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj.save(update_fields=list(defaults.keys()))

        except Exception as e:
            logger.exception("Failed to upsert WertOrder: %s", e)
            # Acknowledge anyway so Wert doesn't retry storm
            return JsonResponse({"ok": True, "stored": False})
        
        
        # >>> INSERT THIS BLOCK HERE ↓↓↓
        from blockchain.models import GuestOrder

        # 🔎 resolve GuestOrder first (FE is source of truth)
        go = None
        if click_id:
            try: go = GuestOrder.objects.get(click_id=UUID(str(click_id)))
            except (GuestOrder.DoesNotExist, ValueError):
                go = None

        # optional: some providers may echo back the ref
        payload_ref = payload.get("ref")
        if go is None and payload_ref:
            go = GuestOrder.objects.filter(ref__iexact=str(payload_ref)).first()

        # Build defaults and include ref if we know it
        defaults = {
            "click_id":      click_id,
            "tx_id":         tx_id,
            "raw":           payload,
            "token_symbol":  order.get("base"),
            "fiat_currency": order.get("quote"),
            "fiat_amount":   Decimal(order.get("quote_amount")) if order.get("quote_amount") else None,
            "ref":           (go.ref if go else None),  # ✅ keep ref in the order-id row
        }
        if new_status:
            defaults["status"] = new_status

        # 🧩 Merge with existing click_id row if present, else upsert by order_id
        obj = WertOrder.objects.filter(click_id=str(click_id)).order_by('-updated_at').first()
        if obj:
            # update fields in-place
            for k, v in defaults.items():
                setattr(obj, k, v)
            if order_id:
                obj.order_id = order_id
            # choose minimal set of fields to persist
            update_fields = list(defaults.keys()) + (["order_id"] if order_id else [])
            obj.save(update_fields=update_fields)
        else:
            obj, _ = WertOrder.objects.update_or_create(
                order_id=order_id or None,
                defaults=defaults
            )

        # 🔄 Reflect status into GuestOrder (if we found it)
        if go:
            guest_map = {
                "pending":   GuestOrder.Status.PENDING,
                "confirmed": GuestOrder.Status.CONFIRMED,
                "failed":    GuestOrder.Status.FAILED,
            }
            updates = []
            if new_status in guest_map:
                go.status = guest_map[new_status]; updates.append("status")
            if order_id and not go.order_id:
                go.order_id = order_id; updates.append("order_id")
            if tx_id and not go.tx_hash:
                go.tx_hash = tx_id; updates.append("tx_hash")
            if updates:
                go.save(update_fields=updates)

        # ✅ Enqueue ONCE, after both rows reflect "confirmed"
        if new_status == "confirmed" and go and go.email:
            from blockchain.tasks import notify_guest_claim_ready
            notify_guest_claim_ready.delay(str(go.click_id))

        return JsonResponse({"ok": True})

# Custom small wrapper to reuse DRF's page logic but expose metadata manually.
class StandardPagination(PageNumberPagination):
    page_size = 20  # default
    page_size_query_param = "page_size"  # allow override via ?page_size=
    max_page_size = 100

def _paginate_queryset(qs, request, paginator: StandardPagination):
    """
    Paginate the queryset and return (page_queryset, meta_dict)
    """
    page_qs = paginator.paginate_queryset(qs, request)
    # build metadata explicitly (so we can do two different paginations independently)
    page = getattr(paginator, "page", None)
    meta = {
        "page": paginator.page.number if page is not None else 1,
        "page_size": paginator.get_page_size(request),
        "total": qs.count(),
        "has_next": page.has_next() if page is not None else False,
        "has_previous": page.has_previous() if page is not None else False,
    }
    return page_qs or [], meta  # ensure list even if empty


def _safe_parse_decimal(val):
    try:
        return Decimal(val)
    except (TypeError, InvalidOperation):
        return None

def _apply_filters_to_qs(qs, params):
    """
    Apply the optional filters coming from query params to any on-chain queryset
    that has: timestamp, credits_delta, campaign (with title/slug), tx_type, status.
    """
    # date window (inclusive)
    start_date = params.get("start_date")
    if start_date:
        dt = parse_date(start_date)  # safe ISO date parsing (expects YYYY-MM-DD)
        if dt:
            # filter by date portion of timestamp
            qs = qs.filter(timestamp__date__gte=dt)

    end_date = params.get("end_date")
    if end_date:
        dt = parse_date(end_date)
        if dt:
            qs = qs.filter(timestamp__date__lte=dt)

    # campaign title/slug partial match
    campaign_title = params.get("campaign_title")
    if campaign_title:
        qs = qs.filter(
            Q(campaign__title__icontains=campaign_title)
            | Q(campaign__slug__icontains=campaign_title)
        )

    # tx_type filter (case insensitive)
    tx_type = params.get("tx_type")
    if tx_type:
        qs = qs.filter(tx_type__iexact=tx_type)

    # credits_delta range
    min_credit = params.get("min_credit")
    if min_credit is not None:
        parsed = _safe_parse_decimal(min_credit)
        if parsed is not None:
            qs = qs.filter(credits_delta__gte=parsed)

    max_credit = params.get("max_credit")
    if max_credit is not None:
        parsed = _safe_parse_decimal(max_credit)
        if parsed is not None:
            qs = qs.filter(credits_delta__lte=parsed)

    return qs


class UserTransactionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        """
        GET /api/user-transactions/?status=Completed|Pending|Failed|all
        & start_date=YYYY-MM-DD
        & end_date=YYYY-MM-DD
        & min_credit=...
        & max_credit=...
        & campaign_title=...
        & tx_type=...
        & page=...
        & page_size=...

        Fans: only their Transaction records.
        Influencers: both Transaction and InfluencerTransaction records.
        """
        user = request.user

        # Normalize status filter (frontend sends e.g. "Completed" or "all")
        raw_status = request.query_params.get("status", "all").lower()
        allowed = {"pending", "completed", "failed", "all"}
        if raw_status not in allowed:
            return Response(
                {"detail": "Invalid status filter."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        status_filter = None if raw_status == "all" else raw_status  # None means no filtering

        # Base Transaction queryset (always owned by user) with its filters
        tx_qs = Transaction.objects.filter(user=user).select_related("campaign")
        if status_filter:
            tx_qs = tx_qs.filter(status=status_filter)
        tx_qs = _apply_filters_to_qs(tx_qs, request.query_params)

        # Order before pagination (your existing ordering is also on model Meta, but explicit is safer here)
        tx_qs = tx_qs.order_by("-timestamp")

        # Paginate transactions
        paginator_tx = StandardPagination()
        tx_page, tx_meta = _paginate_queryset(tx_qs, request, paginator_tx)
        tx_serialized = TransactionSerializer(tx_page, many=True, context={"request": request}).data

        response_payload = {
            "transactions": tx_serialized,
            "transactions_pagination": tx_meta,
        }
        
        # ── NEW: participant view of release/refund (buyer-side) ───────────────
        # built-in filter(): DB WHERE user_id = request.user.id
        part_qs = (InfluencerTransaction.objects
                   .filter(user=user)                 # ← current user as participant/buyer
                   .select_related("campaign"))
        if status_filter:
            part_qs = part_qs.filter(status=status_filter)
        part_qs = _apply_filters_to_qs(part_qs, request.query_params)
        part_qs = part_qs.order_by("-timestamp")

        paginator_part = StandardPagination()
        part_page, part_meta = _paginate_queryset(part_qs, request, paginator_part)
        part_serialized = InfluencerTransactionSerializer(part_page, many=True, context={"request": request}).data

        response_payload["participant_transactions"] = part_serialized
        response_payload["participant_transactions_pagination"] = part_meta
        # ───────────────────────────────────────────────────────────────────────

        if getattr(user, "user_type", None) == "influencer":
            # InfluencerTransactions are scoped by influencer field
            inf_qs = InfluencerTransaction.objects.filter(influencer=user).select_related("campaign")
            if status_filter:
                inf_qs = inf_qs.filter(status=status_filter)
            inf_qs = _apply_filters_to_qs(inf_qs, request.query_params)
            inf_qs = inf_qs.order_by("-timestamp")

            paginator_inf = StandardPagination()
            inf_page, inf_meta = _paginate_queryset(inf_qs, request, paginator_inf)
            inf_serialized = InfluencerTransactionSerializer(inf_page, many=True, context={"request": request}).data

            response_payload["influencer_transactions"] = inf_serialized
            response_payload["influencer_transactions_pagination"] = inf_meta

        elif getattr(user, "user_type", None) == "fan":
            # nothing extra
            pass
        else:
            return Response(
                {"detail": "Unknown user type."}, status=drf_status.HTTP_400_BAD_REQUEST
            )

        return Response(response_payload, status=drf_status.HTTP_200_OK)
    
    
class ReportTransactionIssueView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _resolve_tx_obj(self, transaction_type: str, transaction_id: str, user):
        """
        Helper that tries to resolve either by numeric PK or tx_hash. Raises the appropriate
        DoesNotExist if nothing is found, or ValueError if transaction_type is invalid.
        """
        if transaction_type == "transaction":
            qs = Transaction.objects.filter(user=user)
        elif transaction_type == "influencer_transaction":
            # built-in Q(): OR condition so buyers OR owners can see their rows
            qs = InfluencerTransaction.objects.filter(Q(influencer=user) | Q(user=user))
        else:
            raise ValueError("Invalid transaction_type.")

        tx_obj = None

        # 1. Try interpreting as primary key (integer)
        try:
            pk = int(transaction_id)
            tx_obj = qs.filter(pk=pk).first()
        except (ValueError, TypeError):
            tx_obj = None  # not an integer, fallback to hash lookup

        # 2. If not found yet, try tx_hash (case-insensitive)
        if tx_obj is None:
            tx_obj = qs.filter(tx_hash__iexact=transaction_id).first()

        if not tx_obj:
            # propagate the correct DoesNotExist for caller to catch
            if transaction_type == "transaction":
                raise Transaction.DoesNotExist()
            else:
                raise InfluencerTransaction.DoesNotExist()

        return tx_obj

    def post(self, request):
        transaction_type = request.data.get("transaction_type")  # "transaction" or "influencer_transaction"
        transaction_id = request.data.get("transaction_id")
        description = (request.data.get("description") or "").strip()

        if not transaction_type or not transaction_id or not description:
            return Response(
                {"detail": "transaction_type, transaction_id and description are required."},
                status=400,
            )

        try:
            tx_obj = self._resolve_tx_obj(transaction_type, transaction_id, request.user)
        except ValueError:
            return Response({"detail": "Invalid transaction_type."}, status=400)
        except (Transaction.DoesNotExist, InfluencerTransaction.DoesNotExist):
            return Response({"detail": "Transaction not found."}, status=404)

        # Create report and attachments atomically
        with db_transaction.atomic():
            report = TransactionIssueReport.objects.create(
                user=request.user,
                transaction_hash=tx_obj.tx_hash or "",
                content_type=ContentType.objects.get_for_model(tx_obj),
                object_id=str(tx_obj.pk),
                description=description,
            )

            # attachments
            for f in request.FILES.getlist("attachments"):
                if f.size > 5 * 1024 * 1024:  # 5MB limit
                    return Response(
                        {"detail": f"File {f.name} too large. Max is 5MB."}, status=400
                    )
                IssueAttachment.objects.create(report=report, file=f)

        serialized = TransactionIssueReportSerializer(report, context={"request": request})
        return Response(serialized.data, status=201)
    
class InfluencerEarningsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        base_qs = InfluencerTransaction.objects.filter(
            influencer=user,
            status=InfluencerTransaction.COMPLETED,
        )

        # Sum of released TT
        release_agg = base_qs.aggregate(
            release_tt=Coalesce(
                Sum(
                    "tt_amount",
                    filter=Q(tx_type=InfluencerTransaction.RELEASE),
                    output_field=DecimalField(),
                ),
                Value(0, output_field=DecimalField()),
            ),
            refund_tt=Coalesce(
                Sum(
                    "tt_amount",
                    filter=Q(tx_type=InfluencerTransaction.REFUND),
                    output_field=DecimalField(),
                ),
                Value(0, output_field=DecimalField()),
            ),
        )
        actual_tt = (release_agg["release_tt"] or Decimal(0)) 

        # Pending (on_hold) TT (completed holds that are not yet released/refunded)
        pending_tt = InfluencerTransaction.objects.filter(
            influencer=user,
            status=InfluencerTransaction.COMPLETED,
            tx_type=InfluencerTransaction.ON_HOLD,
        ).aggregate(
            pending_tt=Coalesce(
                Sum("tt_amount", output_field=DecimalField()),
                Value(0, output_field=DecimalField()),
            )
        )["pending_tt"] or Decimal(0)

        # Net credits
        net_credits = base_qs.aggregate(
            net_credits=Coalesce(
                Sum("credits_delta", output_field=DecimalField()),
                Value(0, output_field=DecimalField()),
            )
        )["net_credits"] or Decimal(0)

        return Response({
            "actual_tt_earned": str(actual_tt),
            "pending_tt": str(pending_tt),
            "net_credits": str(net_credits),
        })
    
# ──────────────────────────────────────────────────────────────
# These are your ORM hooks – replace with real implementations
# ──────────────────────────────────────────────────────────────
def mark_deposit_pending(order_id: str, amount: float):
    # e.g.:
    # Deposit.objects.update_or_create(
    #    order_id=order_id,
    #    defaults={'status': 'pending', 'amount': amount}
    # )
    pass

def mark_deposit_confirmed(order_id: str, tx_id: str):
    # e.g.:
    # Deposit.objects.filter(order_id=order_id).update(
    #    status='confirmed',
    #    tx_id=tx_id
    # )
    pass

def mark_deposit_failed(order_id: str):
    # e.g.:
    # Deposit.objects.filter(order_id=order_id).update(status='failed')
    pass


class FanSpendingsView(APIView):
    """
    GET /api/blockchain/fan-spendings/
      Optional query params:
        - start_date=YYYY-MM-DD
        - end_date=YYYY-MM-DD
        - campaign_title=foo   (matches title or slug, case-insensitive partial)
        - breakdown=true       (include per-campaign totals)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # base: only this fan, only completed spends
        qs = Transaction.objects.filter(
            user=user,
            status=Transaction.COMPLETED,
            tx_type=Transaction.SPEND,
        ).select_related("campaign")

        # reuse your existing filter helper (dates, title, credit range, etc.)
        qs = _apply_filters_to_qs(qs, request.query_params)

        # totals (make spends positive by using Abs)
        totals = qs.aggregate(
            total_credits=Coalesce(
                Sum(Abs(F("credits_delta")), output_field=DecimalField()),
                Value(0, output_field=DecimalField()),
            ),
            total_tt=Coalesce(
                Sum(Abs(F("tt_amount")), output_field=DecimalField()),
                Value(0, output_field=DecimalField()),
            ),
            tx_count=Coalesce(Count("id"), 0),
            last_tx=Max("timestamp"),
        )

        payload = {
            "total_credits_spent": str(totals["total_credits"] or 0),
            "total_tt_spent":      str(totals["total_tt"] or 0),
            "transactions_count":  totals["tx_count"] or 0,
            "last_transaction_at": totals["last_tx"],
        }

        # optional per-campaign breakdown
        want_breakdown = str(request.query_params.get("breakdown", "")).lower() in {"1", "true", "yes"}
        if want_breakdown:
            rows = (
                qs.values("campaign_id", "campaign__title", "campaign__slug")
                  .annotate(
                      credits_spent=Coalesce(
                          Sum(Abs(F("credits_delta")), output_field=DecimalField()),
                          Value(0, output_field=DecimalField()),
                      ),
                      tt_spent=Coalesce(
                          Sum(Abs(F("tt_amount")), output_field=DecimalField()),
                          Value(0, output_field=DecimalField()),
                      ),
                      tx_count=Coalesce(Count("id"), 0),
                      last_tx=Max("timestamp"),
                  )
                  .order_by("-credits_spent", "-last_tx")
            )
            payload["breakdown"] = [
                {
                    "campaign_id": r["campaign_id"],
                    "title":       r["campaign__title"],
                    "slug":        r["campaign__slug"],
                    "credits_spent": str(r["credits_spent"]),
                    "tt_spent":      str(r["tt_spent"]),
                    "transactions_count": r["tx_count"],
                    "last_transaction_at": r["last_tx"],
                }
                for r in rows
            ]

        return Response(payload, status=200)



class GuestInitDepositView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        logger.error("GuestInitDepositView payload=%s", data)
        data        = request.data
        email       = (data.get("email") or "").strip() or None
        amount_raw  = data.get("amount")
        token_dec   = int(data.get("token_decimals") or 18)
        entries     = data.get("entries")
        campaign_id = data.get("campaign_id")

        if not amount_raw:
            return Response({"error": "amount is required"}, status=400)

        try:
            amount_wei = int(Decimal(str(amount_raw)) * (Decimal(10) ** token_dec))
        except Exception:
            return Response({"error": "invalid amount"}, status=400)

        # ✅ REQUIRE click_id from FE (no fallback)
        cid = data.get("click_id")
        if not cid:
            return Response({"error": "click_id is required"}, status=400)
        try:
            click_id = UUID(str(cid))
        except Exception:
            return Response({"error": "invalid click_id"}, status=400)

        # ✅ REQUIRE ref from FE (no fallback)
        ref_raw = data.get("ref")
        if not ref_raw:
            return Response({"error": "ref is required"}, status=400)
        ref_hex = str(ref_raw).lower()
        if not ref_hex.startswith("0x") or len(ref_hex) != 66:
            return Response({"error": "invalid ref"}, status=400)
        ref = ref_hex

        campaign = None
        if campaign_id:
            from campaign.models import Campaign
            campaign = Campaign.objects.filter(pk=campaign_id).first()

        from blockchain.models import GuestOrder, WertOrder

        defaults = {
            "ref":            ref,
            "email":          email,
            "amount":         amount_wei,
            "token_decimals": token_dec,
            "campaign":       campaign,
            "entries":        int(entries) if entries else None,
            "status":         GuestOrder.Status.CREATED,
        }

        obj, created = GuestOrder.objects.update_or_create(
            click_id=click_id, defaults=defaults
        )

        # mirror WertOrder shell (do NOT regenerate anything)
        WertOrder.objects.update_or_create(
            order_id=None,
            click_id=str(click_id),
            defaults={
                "ref":               ref,
                "status":            "created",
                "token_amount_wei":  amount_wei,
                "campaign":          campaign,
                "entries":           obj.entries,
            }
        )

        return Response(
            {"ok": True, "click_id": str(click_id), "ref": ref},
            status=201 if created else 200
        )
    

def _unique_username(desired: str, User):
    base = desired.strip() or "user"
    candidate = base
    i = 1
    while User.objects.filter(username__iexact=candidate).exists():
        i += 1
        candidate = f"{base}{i}"
    return candidate

class GuestClaimView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        token     = request.data.get("token")
        username  = (request.data.get("username") or "").strip()
        password  = request.data.get("password")
        

        if not token or "." not in token:
            return Response({"error":"invalid token"}, status=400)

        # --- verify token (same as your current code) ---
        try:
            payload_b64, sig = token.split(".", 1)
            payload = _b64u_dec(payload_b64).decode()
            click_id, email, exp_s = payload.split("|", 2)
            exp = int(exp_s)
        except Exception:
            return Response({"error":"bad token"}, status=400)
        if _sign(payload) != sig:
            return Response({"error":"bad signature"}, status=400)
        if time.time() > exp:
            return Response({"error":"token expired"}, status=410)

        from blockchain.models import GuestOrder
        try:
            go = GuestOrder.objects.select_related("campaign").get(click_id=click_id)
        except GuestOrder.DoesNotExist:
            return Response({"error":"not found"}, status=404)

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()

        # --- create or attach user ---
        created = False
        if not user:
            if not username:
                username = email.split("@", 1)[0]  # start from email prefix
            username = _unique_username(username, User)
            user = User(email=email, username=username)
            # allow setting password at creation
            if password:
                try:
                    validate_password(password, user)
                except Exception as e:
                    return Response({"error":"weak_password","detail":str(e)}, status=400)
                user.set_password(password)
            user.save()
            created = True
        else:
            # user exists; set username if empty and provided
            if not user.username and username:
                user.username = _unique_username(username, User)
            # only allow setting password if user has NO usable password yet
            if password and not user.has_usable_password():
                try:
                    validate_password(password, user)
                except Exception as e:
                    return Response({"error":"weak_password","detail":str(e)}, status=400)
                user.set_password(password)
            elif not created and user.has_usable_password() and password:
                # Email already belongs to an account with a password → ask to sign in
                return Response({"code":"account_exists"}, status=409)
            user.save()

        go.user = user
        go.save(update_fields=["user"])

        # 🚀 Kick the claim task after 30 seconds; it will retry until ready
        transaction.on_commit(lambda: claim_guest_after_registration.apply_async(
            kwargs={"click_id": str(go.click_id), "user_id": int(user.user_id)},
            countdown=30
        ))

        # ✅ Immediately issue auth back to FE; claim will complete async
        refresh = RefreshToken.for_user(user)

        campaign_payload = None
        if go.campaign_id:
            slug = getattr(go.campaign, "slug", None)
            campaign_payload = {"id": go.campaign_id, "slug": slug}

        payload = {
            "status": "ok",
            "already_claimed": (go.status == GuestOrder.Status.CLAIMED),
            "campaign": campaign_payload,                               # ✅ NEW
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "user_type": getattr(user, "user_type", "fan"),         # ✅ NEW
                "phone_number": getattr(user, "phone_number", None),
                "is_email_verified": True,                             # or your real flag
                "is_phone_verified": False,
                "profile": { "exists": True },                          # optional hint
            },
            "auth": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
        }
        return Response(payload, status=200)


class GuestClaimPreviewView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        token = request.query_params.get("token")
        if not token or "." not in token:
            return Response({"error": "invalid token"}, status=400)

        try:
            payload_b64, sig = token.split(".", 1)
            payload = _b64u_dec(payload_b64).decode()
            click_id, email, exp_s = payload.split("|", 2)
            exp = int(exp_s)
        except Exception:
            return Response({"error": "bad token"}, status=400)

        if _sign(payload) != sig:
            return Response({"error":"bad signature"}, status=400)
        if time.time() > exp:
            return Response({"error":"token expired"}, status=410)

        from blockchain.models import GuestOrder
        try:
            go = GuestOrder.objects.get(click_id=click_id)
        except GuestOrder.DoesNotExist:
            return Response({"error":"not found"}, status=404)

        already_claimed = (go.status == GuestOrder.Status.CLAIMED)
        masked = self._mask(email)
        return Response({
            "email_masked": masked,
            "expires_at": exp,
            "already_claimed": already_claimed
        })

    @staticmethod
    def _mask(email: str) -> str:
        try:
            name, dom = email.split("@", 1)
            name_mask = name[:2] + "***" if len(name) > 2 else name[0] + "***"
            return f"{name_mask}@{dom}"
        except Exception:
            return "***"
        
        
        
class WalletConfirmDepositView(APIView):
    """
    POST /api/blockchain/wallet/confirm-deposit/

    Body (JSON):
    {
      "tx_hash": "0x...",
      "amount":  "1230000000000000000"  # optional sanity check, in wei
    }

    This is for *user wallet* (MetaMask/WalletConnect) deposits:
      - user signs a tx that calls your wallet-deposit function
      - frontend sends tx_hash here
      - backend verifies it and enqueues save_transaction_info
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        tx_hash = request.data.get("tx_hash")
        raw_amount = request.data.get("amount")  # optional FE echo back; used for sanity only

        if not tx_hash:
            return Response(
                {"error": "tx_hash is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Ensure "0x" prefix
        if not tx_hash.startswith("0x"):
            # built-in string concatenation: adds "0x" prefix if it's missing
            tx_hash = "0x" + tx_hash

        # 1️⃣ Fetch original transaction from node
        try:
            tx = w3.eth.get_transaction(tx_hash)
            # web3.eth.get_transaction: JSON-RPC call, returns a Python dict with tx fields
        except Exception as e:
            logger.exception("wallet-confirm: get_transaction failed")
            return Response(
                {"error": f"Could not fetch transaction: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2️⃣ Check that tx was sent to *our* contract
        to_addr = (tx["to"] or "").lower()   # built-in dict access + str.lower()
        if not to_addr or to_addr != SC_ADDRESS.lower():
            return Response(
                {"error": "Transaction was not sent to the MYF contract"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3️⃣ Decode called function + args
        try:
            fn_name, args = decode_tx_input(tx["input"])
            # tx["input"] is the raw calldata hex string
        except Exception as e:
            logger.exception("wallet-confirm: decode_input failed")
            return Response(
                {"error": f"Could not decode transaction input: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 🔧 Accept your current wallet entrypoint: deposit(userId, amount)
        #    We keep the other names in case you introduce a dedicated wallet fn later.
        allowed_fns = {"walletDeposit", "depositFromWallet", "deposit"}  # built-in set(): unique names
        if fn_name not in allowed_fns:
            return Response(
                {
                    "error": (
                        f"Unexpected function '{fn_name}' for wallet deposit; "
                        f"expected one of {', '.join(sorted(allowed_fns))}"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4️⃣ Make sure calldata userId matches logged-in MYF user
        try:
            myf_user_id = int(user.user_id)  # built-in int(): parses string → integer
        except Exception:
            return Response(
                {"error": "User has no valid on-chain user_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        arg_user_id = None
        # built-in for-loop: iterate over possible arg names reported by web3 decode
        for key in ("userId", "user_id", "uid"):
            if key in args:                # built-in "in": membership test in dict keys
                arg_user_id = int(args[key])
                break

        if arg_user_id is not None and arg_user_id != myf_user_id:
            return Response(
                {"error": "Transaction userId does not match authenticated user"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 5️⃣ Extract amount in wei from calldata
        arg_amount_wei = None
        for key in ("amountWei", "amount", "valueWei"):
            if key in args:
                arg_amount_wei = int(args[key])
                break

        if arg_amount_wei is None:
            return Response(
                {"error": "Could not determine deposit amount from transaction"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional sanity: body "amount" must match decoded amount
        if raw_amount is not None:
            try:
                fe_amount = int(raw_amount)
            except (TypeError, ValueError):
                return Response(
                    {"error": "Invalid amount in request body"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if fe_amount != arg_amount_wei:
                return Response(
                    {"error": "Amount in request body does not match tx input"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 6️⃣ Validate sender wallet ↔ on-chain wallet mapping if present
        tx_from = (tx["from"] or "").lower()
        onchain_wallet = None
        try:
            onchain_wallet = contract.functions.getUserWallet(myf_user_id).call({"from": OWNER})
            # ContractFunction.call(): read-only eth_call, zero gas, returns Python types
        except Exception:
            # If getUserWallet reverts or isn't set yet, we just skip this check
            onchain_wallet = None

        if onchain_wallet and onchain_wallet.lower() != tx_from:
            return Response(
                {"error": "Transaction sender wallet does not match your registered wallet"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 7️⃣ Convert TT wei → TT units + credits, using your existing helpers
        tt_amount_wei = int(arg_amount_wei)
        conv_rate = int(get_current_rate_wei())   # built-in int(): ensures it's a plain integer
        credits_wei = tt_amount_wei * conv_rate   # built-in *: arbitrary-precision integer multiplication

        # _from_wei: your helper → Decimal with fixed decimal places
        tt_amount_dec = _from_wei(tt_amount_wei, token_decimals=18, places=2)
        credits_dec   = _from_wei(credits_wei,  token_decimals=18, places=2)

        # 8️⃣ Enqueue your existing indexer; it will fetch receipt and persist metadata
        save_transaction_info.delay(
            tx_hash,
            user.id,                  # Django FK, not on-chain id
            None,                     # campaign_id
            Transaction.DEPOSIT,      # tx_type
            str(tt_amount_dec),       # parsed TT amount (2dp)
            str(credits_dec),         # parsed credits change (2dp)
            tt_amount_wei=str(tt_amount_wei),     # raw on-chain integer
            credits_delta_wei=str(credits_wei),   # raw on-chain integer
        )

        return Response(
            {
                "message": "Wallet deposit recorded; awaiting on-chain confirmation.",
                "tt_amount": str(tt_amount_dec),
                "credits_delta": str(credits_dec),
            },
            status=status.HTTP_201_CREATED,
        )
