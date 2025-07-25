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
from blockchain.models import Transaction, BalanceSnapshot
from blockchain.tasks import _build_and_send, withdraw_for_user_task
import logging
from web3.exceptions import ContractCustomError
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from api.models import VerificationCode
from django.template.loader import render_to_string
from web3 import Web3

logger = logging.getLogger(__name__)


OWNER        = settings.OWNER_ADDRESS
PK           = settings.PRIVATE_KEY
WERT_PK      = settings.WERT_SC_SIGNER_KEY
GAS_LIMIT    = 200_000
GAS_PRICE_GWEI = "50"
SC_ADDRESS = settings.CONTRACT_ADDRESS


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
        logger.error("Fetching balances for user_id: %s", user_id)
        
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
            "tt_balance":     tt_bal,      # e.g. 2
            "credit_balance": credit_bal   # e.g. 20
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
        logger.info(f"Scheduled withdraw_for_user_task {task.id} for user {user_id}, credits={credits}")

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
            logger.info(f"SMS to {request.user.profile.phone_number}: code={code}")

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
