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
from blockchain.tasks import _build_and_send, withdraw_for_user_task, save_transaction_info
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
from django.db.models import Sum, Case, When, F, DecimalField, Value
from django.db.models.functions import Coalesce


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

        # 3) enqueue the on‐chain withdraw
        task = withdraw_for_user_task.delay(user_id, credits)

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
                "task_id": task.id
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
            html_msg = render_to_string("verify_email.html", {"verification_code": code})
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
        html = render_to_string("verify_email.html", {"verification_code": code})
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
    Class‑based view to handle Wert on‑chain webhooks.
    """

    # Built‑in: dispatch() routes to get()/post()/etc based on HTTP method.
    # By decorating dispatch() with csrf_exempt, all sub‑methods skip CSRF.
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # 1) Raw body for signature check
        raw_body = request.body

        # 2) Grab the HMAC header Wert sends
        signature = request.META.get('HTTP_X_WERT_SIGNATURE', '')
        if not signature:
            return HttpResponseForbidden("Missing signature")

        # 3) Compute our own HMAC‑SHA256 of the raw payload
        computed = hmac.new(
            key=WERT_WEBHOOK_SECRET.encode(),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()

        # 4) Compare in constant time
        if not hmac.compare_digest(computed, signature):
            return HttpResponseForbidden("Invalid signature")

        # 5) Parse JSON
        try:
            event = json.loads(raw_body)
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        # 6) Dispatch by event type
        evt = event.get('event')
        order_id = event.get('order_id')
        tx_id    = event.get('tx_id')     # only on confirmed
        amount   = event.get('amount')

        if evt == 'payment.pending':
            mark_deposit_pending(order_id, amount)

        elif evt == 'payment.confirmed':
            mark_deposit_confirmed(order_id, tx_id)

        elif evt == 'payment.failed':
            mark_deposit_failed(order_id)

        else:
            # Unrecognized event; you can log it here
            print("Unhandled Wert event:", evt)

        # 7) Always respond 200 OK to acknowledge receipt
        return JsonResponse({'ok': True})

    def get(self, request, *args, **kwargs):
        # Built‑in: if someone tries GET, we reject
        return HttpResponseBadRequest("Only POST allowed")


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
        tx_serialized = TransactionSerializer(tx_page, many=True).data

        response_payload = {
            "transactions": tx_serialized,
            "transactions_pagination": tx_meta,
        }

        if getattr(user, "user_type", None) == "influencer":
            # InfluencerTransactions are scoped by influencer field
            inf_qs = InfluencerTransaction.objects.filter(influencer=user).select_related("campaign")
            if status_filter:
                inf_qs = inf_qs.filter(status=status_filter)
            inf_qs = _apply_filters_to_qs(inf_qs, request.query_params)
            inf_qs = inf_qs.order_by("-timestamp")

            paginator_inf = StandardPagination()
            inf_page, inf_meta = _paginate_queryset(inf_qs, request, paginator_inf)
            inf_serialized = InfluencerTransactionSerializer(inf_page, many=True).data

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
            qs = InfluencerTransaction.objects.filter(influencer=user)
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